"""Internal API consumed by the voice-agent service (service-token protected).

Auth: every request must carry ``X-Internal-Token`` matching
``settings.internal_api_token``. An empty token setting disables the whole
router (503) so a misconfigured deployment never exposes it.

- GET  /internal/calls/{call_id}/context — everything the agent needs to run
  a phone call (contact, campaign, legacy domain config JSON).
- GET  /internal/agent-config?version_id= — full AgentVersion config (playground
  + campaign runtime).
- POST /internal/calls/{call_id}/transcript-turns — append turns with optional
  per-turn latency metrics (stt_final_ms / llm_first_token_ms /
  tts_first_audio_ms / e2e_ms), logged per turn from day one.
- POST /internal/calls/{call_id}/extracted-fields — upsert extracted fields.
- POST /internal/calls/{call_id}/latency-metrics — call-level latency/cost.
- POST /internal/calls/{call_id}/complete — finalize call state + summary.
- POST /internal/calls/{call_id}/report  — legacy combined report endpoint.

Invalid payloads get a 400/422; these endpoints never 500 for bad input.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Agent, AgentVersion, Call, Campaign, Contact, DomainConfig, Organization
from app.services.calls_service import (
    apply_report,
    log_call_event,
    maybe_complete_campaign,
)
from app.timeutil import parse_iso, utcnow

logger = logging.getLogger(__name__)

_LATENCY_FIELDS = ("stt_final_ms", "llm_first_token_ms", "tts_first_audio_ms", "e2e_ms")


def require_internal_token(request: Request) -> None:
    """Shared service-token guard for all /internal/* endpoints."""
    expected = request.app.state.settings.internal_api_token
    if not expected:
        raise HTTPException(
            status_code=503, detail="internal API token not configured"
        )
    provided = request.headers.get("X-Internal-Token", "")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid internal token")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/calls/{call_id}/context")
def call_context(call_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="call not found")
    contact = db.get(Contact, call.contact_id) if call.contact_id else None
    campaign = db.get(Campaign, call.campaign_id) if call.campaign_id else None
    domain_config = (
        db.get(DomainConfig, campaign.domain_config_id)
        if campaign and campaign.domain_config_id
        else None
    )
    org_id = call.org_id
    if org_id is None and campaign is not None:
        org_id = campaign.org_id
    institution_name = ""
    if org_id is not None:
        org = db.get(Organization, org_id)
        if org is not None and org.name:
            institution_name = org.name
    if not institution_name and campaign is not None:
        institution_name = campaign.name or ""
    return {
        "call": {
            "id": call.id,
            "status": call.status,
            "kind": call.kind,
            "agent_version_id": call.agent_version_id,
        },
        "contact": {
            "name": contact.name if contact else None,
            "phone": contact.phone if contact else None,
            "external_id": contact.external_id if contact else None,
            "custom_fields": (contact.custom_fields or {}) if contact else {},
        },
        "campaign": {"name": campaign.name if campaign else None},
        "domain_config": domain_config.config if domain_config else None,
        "institution_name": institution_name,
    }


@router.get("/agent-config")
def agent_config(
    version_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Full immutable agent-version config for the voice-agent runtime."""
    version = db.get(AgentVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    agent = db.get(Agent, version.agent_id)
    return {
        "version_id": version.id,
        "version_number": version.version,
        "agent_id": version.agent_id,
        "agent_name": agent.name if agent else None,
        "system_prompt": version.system_prompt,
        "company_context": version.company_context or {},
        "question_flow": version.question_flow or [],
        "extraction_schema": version.extraction_schema or {},
        "disclosure_script": version.disclosure_script,
        "escalation_rules": version.escalation_rules or [],
        "voice_settings": version.voice_settings or {},
    }


def _get_call_or_404(db: Session, call_id: int) -> Call:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="call not found")
    return call


def _validated_turn(item: Any) -> dict[str, Any]:
    """Validate one transcript turn payload; raises ValueError on bad input."""
    if not isinstance(item, dict):
        raise ValueError("each turn must be an object")
    turn_index = item.get("turn_index")
    speaker = item.get("speaker")
    text_value = item.get("text")
    if not isinstance(turn_index, int) or isinstance(turn_index, bool):
        raise ValueError("'turn_index' must be an integer")
    if speaker not in ("agent", "caller", "user"):
        raise ValueError("'speaker' must be 'agent', 'caller' or 'user'")
    speaker = "caller" if speaker == "user" else speaker
    if not isinstance(text_value, str):
        raise ValueError("'text' must be a string")

    turn: dict[str, Any] = {
        "turn_index": turn_index,
        "speaker": speaker,
        "text": text_value,
        "timestamp": None,
    }
    if item.get("timestamp") is not None:
        if not isinstance(item["timestamp"], str):
            raise ValueError("'timestamp' must be an ISO-8601 string")
        turn["timestamp"] = parse_iso(item["timestamp"])
    for field in _LATENCY_FIELDS:
        value = item.get(field)
        if value is None:
            turn[field] = None
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"'{field}' must be a non-negative number")
        turn[field] = float(value)
    return turn


@router.post("/calls/{call_id}/transcript-turns")
def post_transcript_turns(
    call_id: int,
    body: Any = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Append one or many turns. Body: {"turns":[...]} or a bare [...] list."""
    call = _get_call_or_404(db, call_id)
    raw_turns = body.get("turns") if isinstance(body, dict) else body
    if not isinstance(raw_turns, list) or not raw_turns:
        raise HTTPException(status_code=400, detail="body must contain a non-empty 'turns' list")
    try:
        turns = [_validated_turn(item) for item in raw_turns]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.models import Transcript

    for turn in turns:
        db.add(Transcript(call_id=call.id, **turn))
        # Per-turn latency log line (NFR-1 instrumentation from day one).
        logger.info(
            "turn_latency call=%s kind=%s turn=%s speaker=%s stt_final_ms=%s "
            "llm_first_token_ms=%s tts_first_audio_ms=%s e2e_ms=%s",
            call.id,
            call.kind,
            turn["turn_index"],
            turn["speaker"],
            turn["stt_final_ms"],
            turn["llm_first_token_ms"],
            turn["tts_first_audio_ms"],
            turn["e2e_ms"],
        )
    db.commit()
    return {"ok": True, "added": len(turns)}


@router.post("/calls/{call_id}/extracted-fields")
def post_extracted_fields(
    call_id: int,
    body: Any = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Upsert extracted fields. Body: {"fields":[{name,value,confidence,...}]}."""
    call = _get_call_or_404(db, call_id)
    try:
        apply_report(db, call, "fields", body)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/calls/{call_id}/latency-metrics")
def post_latency_metrics(
    call_id: int,
    body: Any = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Call-level latency/cost merge. Accepts flat {stt_final_ms,...} and/or
    {"latency_ms": {...}, "cost_usd": {...}}."""
    call = _get_call_or_404(db, call_id)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be an object")

    merged = dict(call.latency or {})
    flat = {k: v for k, v in body.items() if k in _LATENCY_FIELDS}
    for key, value in flat.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"'{key}' must be a number")
        merged[key] = value
    if body.get("latency_ms") is not None:
        if not isinstance(body["latency_ms"], dict):
            raise HTTPException(status_code=400, detail="'latency_ms' must be an object")
        merged.update(body["latency_ms"])
    call.latency = merged

    cost = body.get("cost_usd")
    if cost is not None:
        if not isinstance(cost, dict):
            raise HTTPException(status_code=400, detail="'cost_usd' must be an object")
        call.cost = cost

    logger.info("call_latency call=%s kind=%s %s", call.id, call.kind, merged)
    log_call_event(db, call.id, "latency_metrics", {"latency_ms": merged, "cost_usd": cost})
    db.commit()
    return {"ok": True, "latency": merged}


@router.post("/calls/{call_id}/complete")
def post_complete(
    call_id: int,
    body: Any = Body(default={}),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Finalize a call: status completed + summary/outcome flags."""
    call = _get_call_or_404(db, call_id)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be an object")
    for key in ("summary", "outcome"):
        if body.get(key) is not None and not isinstance(body[key], str):
            raise HTTPException(status_code=400, detail=f"'{key}' must be a string")
    if body.get("flagged_for_human") is not None and not isinstance(
        body["flagged_for_human"], bool
    ):
        raise HTTPException(status_code=400, detail="'flagged_for_human' must be a boolean")
    duration = body.get("duration_seconds")
    if duration is not None and (not isinstance(duration, (int, float)) or duration < 0):
        raise HTTPException(status_code=400, detail="'duration_seconds' must be >= 0")

    now = utcnow()
    call.status = "completed"
    call.ended_at = now
    if call.started_at is not None:
        call.duration_seconds = duration or (now - call.started_at).total_seconds()
    elif duration is not None:
        call.duration_seconds = duration
    if body.get("summary") is not None:
        call.summary = body["summary"]
    if body.get("outcome") is not None:
        call.outcome = body["outcome"]
    if body.get("flagged_for_human") is not None:
        call.flagged_for_human = body["flagged_for_human"]

    contact = db.get(Contact, call.contact_id) if call.contact_id else None
    if contact is not None and contact.status == "calling":
        contact.status = "completed"
        contact.next_attempt_at = None
    if call.campaign_id is not None:
        maybe_complete_campaign(db, call.campaign_id)

    log_call_event(
        db,
        call.id,
        "completed",
        {"source": "internal_complete", "outcome": call.outcome},
    )
    db.commit()
    return {
        "ok": True,
        "call_id": call.id,
        "status": call.status,
        "duration_seconds": call.duration_seconds,
    }


@router.post("/calls/{call_id}/report")
def call_report(
    call_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Legacy combined report endpoint (turn|fields|summary|metrics|status)."""
    call = _get_call_or_404(db, call_id)
    if not isinstance(body, dict) or "type" not in body:
        raise HTTPException(status_code=400, detail="body must be {type, payload}")
    try:
        apply_report(db, call, body["type"], body.get("payload"))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
