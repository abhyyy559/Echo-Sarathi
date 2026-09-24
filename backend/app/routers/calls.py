"""Call list + detail endpoints (org-scoped per contract §4).

``GET /api/calls`` is the cross-campaign call history feed (Overview page and
the Call History table both read it); ``GET /api/calls/{call_id}`` is the
per-call detail payload used by the transcript view.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    Agent,
    AgentVersion,
    Call,
    CallEvent,
    Campaign,
    Contact,
    ExtractedField,
    Transcript,
    User,
)
from app.schemas import CallActivityOut, CampaignCallOut, CallDetailOut, CallListItemOut
from app.services.export_service import (
    CSV_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    export_call_csv,
    export_call_xlsx,
)

router = APIRouter(prefix="/api", tags=["calls"])


def _call_org_id(db: Session, call: Call) -> Any:
    """Effective org of a call: denormalized column, else campaign lineage."""
    if call.org_id is not None:
        return call.org_id
    campaign = db.get(Campaign, call.campaign_id) if call.campaign_id else None
    return campaign.org_id if campaign else None


def _org_call_filter(org_id: int):
    """SQL predicate matching calls whose effective org is ``org_id``."""
    return or_(Call.org_id == org_id, Campaign.org_id == org_id)


_ACTIVITY_STATES = {"agent_connecting", "listening", "understanding", "agent_speaking"}


def _activity_payload(event: CallEvent) -> dict[str, Any]:
    return event.payload if isinstance(event.payload, dict) else {}


def _activity_sequence(event: CallEvent) -> float | None:
    value = _activity_payload(event).get("sequence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    sequence = float(value)
    if not math.isfinite(sequence) or sequence <= 0 or not sequence.is_integer():
        return None
    return int(sequence)


def _activity_occurred_at(event: CallEvent) -> datetime | None:
    value = _activity_payload(event).get("occurred_at")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _activity_state(event: CallEvent) -> str | None:
    payload = _activity_payload(event)
    value = payload.get("state")
    if value in _ACTIVITY_STATES:
        return value
    legacy_value = payload.get("event_type")
    return legacy_value if legacy_value in _ACTIVITY_STATES else None


def _activity_out(event: CallEvent) -> CallActivityOut | None:
    payload = _activity_payload(event)
    sequence = _activity_sequence(event)
    state = _activity_state(event)
    occurred_at = payload.get("occurred_at")
    source = payload.get("source")
    event_type = payload.get("event_type")
    if (
        sequence is None
        or state is None
        or isinstance(occurred_at, bool)
        or not isinstance(occurred_at, (int, float))
        or not math.isfinite(float(occurred_at))
        or not isinstance(source, str)
        or not source.strip()
        or not isinstance(event_type, str)
        or not event_type.strip()
    ):
        return None
    from_state = payload.get("from_state")
    to_state = payload.get("to_state")
    if from_state is not None and not isinstance(from_state, str):
        return None
    if to_state is not None and not isinstance(to_state, str):
        return None
    return CallActivityOut(
        state=state,
        event_type=event_type,
        sequence=sequence,
        occurred_at=float(occurred_at),
        source=source,
        from_state=from_state,
        to_state=to_state,
        created_at=event.created_at,
        updated_at=event.created_at,
    )


def _ordered_activity_events(db: Session, call_id: int) -> list[CallEvent]:
    events = db.scalars(
        select(CallEvent)
        .where(CallEvent.call_id == call_id, CallEvent.event_type == "voice_activity")
        .order_by(CallEvent.id)
    ).all()
    valid_events = [event for event in events if _activity_out(event) is not None]
    return sorted(valid_events, key=lambda event: (_activity_sequence(event), event.id))


def _is_agent_state_transition(event: CallEvent) -> bool:
    payload = _activity_payload(event)
    from_state = payload.get("from_state")
    to_state = payload.get("to_state")
    if from_state != "speaking" or not isinstance(to_state, str) or not to_state:
        return False
    if to_state == "speaking":
        return False
    source = str(payload.get("source") or "").lower()
    event_type = str(payload.get("event_type") or "").lower()
    if "user" in source or "transcript" in source:
        return False
    return event_type == "agent_state_changed"


def _activity_timing(
    call: Call, events: list[CallEvent]
) -> tuple[float | None, float | None]:
    first_speaking_index = next(
        (
            index
            for index, event in enumerate(events)
            if _activity_state(event) == "agent_speaking"
        ),
        None,
    )
    if first_speaking_index is None:
        return None, None

    first_speaking = events[first_speaking_index]
    first_speaking_at = _activity_occurred_at(first_speaking)
    pickup_seconds = None
    answered_at = call.answered_at
    if answered_at is not None and answered_at.tzinfo is not None:
        answered_at = answered_at.astimezone(timezone.utc).replace(tzinfo=None)
    if answered_at is not None and first_speaking_at is not None:
        pickup_seconds = (first_speaking_at - answered_at).total_seconds()

    opening_seconds = None
    if first_speaking_at is not None:
        for event in events[first_speaking_index + 1 :]:
            if not _is_agent_state_transition(event):
                continue
            transition_at = _activity_occurred_at(event)
            if transition_at is None:
                continue
            opening_seconds = (transition_at - first_speaking_at).total_seconds()
            break
    return pickup_seconds, opening_seconds


# Avg end-to-end latency per call (single grouped scan, joined in below).
_avg_e2e_subq = (
    select(Transcript.call_id, func.avg(Transcript.e2e_ms).label("avg_e2e_ms"))
    .where(Transcript.e2e_ms.isnot(None))
    .group_by(Transcript.call_id)
    .subquery()
)


@router.get("/calls", response_model=list[CallListItemOut])
def list_calls(
    limit: int = 500,
    agent_version_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Most recent org-scoped calls across every campaign + playground."""
    capped_limit = max(1, min(limit, 1000))
    stmt = (
        select(
            Call,
            Contact.name,
            Contact.phone,
            Agent.name,
            _avg_e2e_subq.c.avg_e2e_ms,
        )
        .outerjoin(Contact, Contact.id == Call.contact_id)
        .outerjoin(Campaign, Campaign.id == Call.campaign_id)
        .outerjoin(AgentVersion, AgentVersion.id == Call.agent_version_id)
        .outerjoin(Agent, Agent.id == AgentVersion.agent_id)
        .outerjoin(_avg_e2e_subq, _avg_e2e_subq.c.call_id == Call.id)
        .where(_org_call_filter(user.org_id))
    )
    if agent_version_id is not None:
        stmt = stmt.where(Call.agent_version_id == agent_version_id)
    rows = db.execute(stmt.order_by(Call.id.desc()).limit(capped_limit)).all()
    return [
        {
            "id": call.id,
            "status": call.status,
            "kind": call.kind or "phone",
            "duration_seconds": call.duration_seconds,
            "started_at": call.started_at,
            "created_at": call.created_at,
            "agent_version_id": call.agent_version_id,
            "agent_name": agent_name,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "avg_e2e_ms": round(float(avg_e2e), 1) if avg_e2e is not None else None,
            "flagged_for_human": call.flagged_for_human,
        }
        for call, contact_name, contact_phone, agent_name, avg_e2e in rows
    ]


@router.get("/campaigns/{campaign_id}/calls", response_model=list[CampaignCallOut])
def list_campaign_calls(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="campaign not found")
    rows = db.execute(
        select(Call, Contact.name, Contact.phone)
        .join(Contact, Contact.id == Call.contact_id)
        .where(Call.campaign_id == campaign_id)
        .order_by(Call.id.desc())
    ).all()
    return [
        {
            "id": call.id,
            "campaign_id": call.campaign_id,
            "contact_id": call.contact_id,
            "provider_call_id": call.provider_call_id,
            "status": call.status,
            "started_at": call.started_at,
            "answered_at": call.answered_at,
            "ended_at": call.ended_at,
            "duration_seconds": call.duration_seconds,
            "recording_url": call.recording_url,
            "summary": call.summary,
            "outcome": call.outcome,
            "flagged_for_human": call.flagged_for_human,
            "cost": call.cost,
            "latency": call.latency,
            "created_at": call.created_at,
            "contact_name": name,
            "contact_phone": phone,
        }
        for call, name, phone in rows
    ]


@router.get("/calls/{call_id}", response_model=CallDetailOut)
def get_call(
    call_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    call = db.get(Call, call_id)
    if call is None or _call_org_id(db, call) != user.org_id:
        raise HTTPException(status_code=404, detail="call not found")
    contact = db.get(Contact, call.contact_id)
    turns = db.scalars(
        select(Transcript).where(Transcript.call_id == call.id).order_by(Transcript.turn_index)
    ).all()
    fields = db.scalars(
        select(ExtractedField).where(ExtractedField.call_id == call.id).order_by(ExtractedField.id)
    ).all()
    activity_events = _ordered_activity_events(db, call.id)
    activity = [_activity_out(event) for event in activity_events]
    activity = [item for item in activity if item is not None]
    activity_history = [item.model_dump(mode="json") for item in activity[-200:]]
    latest_activity = activity_history[-1] if activity_history else None
    pickup_to_first_audio_seconds, opening_duration_seconds = _activity_timing(
        call, activity_events
    )
    return {
        "id": call.id,
        "campaign_id": call.campaign_id,
        "contact_id": call.contact_id,
        "provider_call_id": call.provider_call_id,
        "status": call.status,
        "started_at": call.started_at,
        "answered_at": call.answered_at,
        "ended_at": call.ended_at,
        "duration_seconds": call.duration_seconds,
        "recording_url": call.recording_url,
        "summary": call.summary,
        "outcome": call.outcome,
        "flagged_for_human": call.flagged_for_human,
        "cost": call.cost,
        "latency": call.latency,
        "created_at": call.created_at,
        "contact_name": contact.name if contact else None,
        "contact_phone": contact.phone if contact else None,
        "transcript": [
            {
                "turn_index": t.turn_index,
                "speaker": t.speaker,
                "text": t.text,
                "timestamp": t.timestamp,
            }
            for t in turns
        ],
        "extracted_fields": [
            {
                "field_name": f.field_name,
                "field_value": f.field_value,
                "source_turn_index": f.source_turn_index,
                "confidence": f.confidence,
            }
            for f in fields
        ],
        "activity": latest_activity,
        "activity_history": activity_history,
        "pickup_to_first_audio_seconds": pickup_to_first_audio_seconds,
        "opening_duration_seconds": opening_duration_seconds,
    }


@router.get("/calls/{call_id}/export")
def export_call(
    call_id: int,
    format: str = "csv",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export ONE call row (campaign or contact-less playground call) as CSV/XLSX."""
    call = db.get(Call, call_id)
    if call is None or _call_org_id(db, call) != user.org_id:
        raise HTTPException(status_code=404, detail="call not found")
    if format == "csv":
        return Response(
            content=export_call_csv(db, call),
            media_type=CSV_MEDIA_TYPE,
            headers={"Content-Disposition": f'attachment; filename="call-{call.id}.csv"'},
        )
    if format == "xlsx":
        return Response(
            content=export_call_xlsx(db, call),
            media_type=XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": f'attachment; filename="call-{call.id}.xlsx"'},
        )
    raise HTTPException(status_code=422, detail="format must be csv or xlsx")
