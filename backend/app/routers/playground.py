"""Web playground (frozen contract §4).

Browser mic joins a LiveKit room via a short-lived token issued here; the same
voice-agent worker that handles phone calls accepts the room job. Sessions are
recorded as ``calls(kind='playground')`` — zero telephony minutes burned.

Text mode: POST /sessions/{call_id}/turns drives the same conversational flow
(disclosure → question flow → extraction → end_call) with typed messages —
the backend talks to Groq directly, no LiveKit/telephony involved. The system
prompt below is a slim server-side twin of voice-agent/app/prompting.py; the
two services are deliberately decoupled.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.deps import get_current_user, get_org_or_404
from app.models import Agent, AgentVersion, Call, Campaign, Contact, ExtractedField, Organization, Transcript, User
from app.schemas import DryRunCreate
from app.timeutil import utcnow
from app.services.token_substitution import apply_token_substitution, build_token_map

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playground", tags=["playground"])

_TOKEN_TTL = timedelta(hours=1)
_LATENCY_METRICS = ("stt_final_ms", "llm_first_token_ms", "tts_first_audio_ms", "e2e_ms")

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Tool-call rounds per user turn before we force a plain-text reply.
_MAX_TOOL_ROUNDS = 3
_GROQ_MAX_RETRIES = 2
_GROQ_RETRY_DELAYS = (2.0, 5.0)


def _retry_delay(response: Any, attempt: int) -> float:
    """Backoff for a 429: honor Retry-After, else 2s then 5s."""
    try:
        header = response.headers.get("retry-after")
        if header is not None:
            return max(0.0, float(header))
    except (TypeError, ValueError, AttributeError):
        pass
    if 0 <= attempt < len(_GROQ_RETRY_DELAYS):
        return _GROQ_RETRY_DELAYS[attempt]
    return _GROQ_RETRY_DELAYS[-1]


class SessionCreate(BaseModel):
    agent_version_id: int = Field(gt=0)
    # P0-2 personalization: flat {field: scalar} contact card (e.g.
    # student_name / parent_name) rendered into the agent's system prompt.
    contact: Optional[dict[str, Any]] = None


def _clean_contact(raw: Optional[dict[str, Any]]) -> dict[str, str]:
    """Keep only flat, non-empty string fields from a caller-supplied card."""
    if not raw:
        return {}
    cleaned: dict[str, str] = {}
    for key, value in list(raw.items())[:50]:
        name = str(key).strip()[:100]
        if not name or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()[:500]
        if text:
            cleaned[name] = text
    return cleaned


def _call_context(contact: dict[str, str]) -> Optional[dict[str, Any]]:
    return {"contact": contact} if contact else None


def _call_metadata(
    version_id: int, call_id: int, context: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Room/token metadata contract consumed by the voice-agent worker."""
    metadata: dict[str, Any] = {"version_id": version_id, "call_id": call_id}
    if context and isinstance(context.get("contact"), dict):
        metadata["contact"] = context["contact"]
    return metadata


class TurnCreate(BaseModel):
    """One text-mode exchange. ``event='start'`` asks the agent for its
    opening utterance (disclosure + greeting + first question)."""

    text: str = Field(default="", max_length=2000)
    event: Optional[str] = None


def _issue_room_token(settings: Settings, room_name: str, identity: str, metadata: dict[str, Any]) -> str:
    """Sign a LiveKit room-join token (TTL 1h). Requires configured credentials."""
    if not (settings.livekit_api_key and settings.livekit_api_secret):
        raise HTTPException(
            status_code=503,
            detail="LiveKit credentials not configured (set LIVEKIT_API_KEY / LIVEKIT_API_SECRET)",
        )
    from livekit import api as livekit_api  # lazy: only needed on this endpoint

    token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_metadata(json.dumps(metadata))
        .with_grants(
            livekit_api.VideoGrants(room_join=True, room=room_name)
        )
        .with_ttl(_TOKEN_TTL)
    )
    return token.to_jwt()


def _get_own_playground_call(db: Session, call_id: int, user: User) -> Call:
    call = db.get(Call, call_id)
    if call is None or call.kind != "playground" or call.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="not found")
    return call


def _set_room_metadata_best_effort(
    settings: Settings, room_name: str, metadata: dict[str, Any]
) -> None:
    """Mirror token metadata onto the room so the worker sees it immediately.

    Best-effort: if the LiveKit server is unreachable the participant-token
    fallback still carries {version_id, call_id, contact}.
    """
    import asyncio

    try:
        from livekit import api as livekit_api

        async def _update() -> None:
            client = livekit_api.LiveKitAPI(
                settings.livekit_url,
                settings.livekit_api_key,
                settings.livekit_api_secret,
            )
            try:
                await client.room.update_room_metadata(
                    livekit_api.UpdateRoomMetadataRequest(
                        room=room_name,
                        metadata=json.dumps(metadata),
                    )
                )
            finally:
                await client.aclose()

        asyncio.run(_update())
    except Exception:
        logger.warning(
            "Could not set room metadata for %s (participant-token fallback applies)",
            room_name,
            exc_info=True,
        )


@router.post("/sessions")
def create_session(
    payload: SessionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    version = db.get(AgentVersion, payload.agent_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="not found")
    # Org check through the parent agent; foreign orgs get 404 (no leak).
    agent = get_org_or_404(db, Agent, version.agent_id, user.org_id)

    room_name = f"playground-{user.org_id}-{uuid.uuid4()}"
    context = _call_context(_clean_contact(payload.contact))
    call = Call(
        kind="playground",
        status="in_progress",
        org_id=user.org_id,
        agent_version_id=version.id,
        started_at=utcnow(),
        context=context,
    )
    db.add(call)
    db.flush()  # need call.id for the room metadata before signing

    metadata = _call_metadata(version.id, call.id, context)
    token = _issue_room_token(
        settings,
        room_name,
        identity=f"user-{user.id}",
        metadata=metadata,
    )
    _set_room_metadata_best_effort(settings, room_name, metadata)
    logger.info(
        "playground session created call_id=%s org=%s agent=%s version=%s room=%s",
        call.id,
        user.org_id,
        agent.name,
        version.version,
        room_name,
    )
    db.commit()

    return {
        "call_id": call.id,
        "room_name": room_name,
        "livekit_token": token,
        "livekit_url": settings.livekit_url,
    }


def _latency_summary(turns: list[Transcript]) -> dict[str, Any]:
    """Per-metric n/avg/p50/p95 over the turns that reported each metric."""
    summary: dict[str, Any] = {}
    for metric in _LATENCY_METRICS:
        values = sorted(
            value for turn in turns if (value := getattr(turn, metric)) is not None
        )
        if not values:
            continue
        count = len(values)

        def percentile(fraction: float, vals: list[float] = values) -> float:
            index = min(count - 1, round(fraction * (count - 1)))
            return round(vals[index], 1)

        summary[metric] = {
            "n": count,
            "avg": round(sum(values) / count, 1),
            "p50": percentile(0.5),
            "p95": percentile(0.95),
        }
    return summary


@router.post("/sessions/{call_id}/complete")
def complete_session(
    call_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Finalize a playground session and return transcript/fields/latency."""
    call = _get_own_playground_call(db, call_id, user)
    if call.status == "in_progress":
        now = utcnow()
        call.status = "completed"
        call.ended_at = now
        if call.started_at is not None:
            call.duration_seconds = (now - call.started_at).total_seconds()
    db.commit()

    turns = db.scalars(
        select(Transcript)
        .where(Transcript.call_id == call.id)
        .order_by(Transcript.turn_index)
    ).all()
    fields = db.scalars(
        select(ExtractedField)
        .where(ExtractedField.call_id == call.id)
        .order_by(ExtractedField.id)
    ).all()

    return {
        "call_id": call.id,
        "status": call.status,
        "summary": call.summary,
        "outcome": call.outcome,
        "flagged_for_human": call.flagged_for_human,
        "duration_seconds": call.duration_seconds,
        "transcript": [
            {
                "turn_index": t.turn_index,
                "speaker": t.speaker,
                "text": t.text,
                "timestamp": t.timestamp,
                **{m: getattr(t, m) for m in _LATENCY_METRICS},
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
        "latency": _latency_summary(list(turns)),
    }


# ---------------------------------------------------------------------------
# Text mode — same conversation flow, typed instead of spoken
# ---------------------------------------------------------------------------


def _question_text(item: Any) -> str:
    """Question text from either a plain string or a flow-step object."""
    if isinstance(item, dict):
        return str(item.get("question") or item.get("text") or "").strip()
    return str(item or "").strip()


_GENERIC_SUBJECT_KEYS = ("full_name", "contact_name", "lead_name", "candidate_name", "name")
_GENERIC_PARENT_KEYS = ("parent_name", "parent", "guardian", "contact_person")


def _render_caller_context(contact: dict[str, str], institution: str) -> str:
    """CALLER CONTEXT block that works for any domain, not just absent-student.

    Known keys get human phrasing; every other supplied key is passed through
    as a fact so domain-specific cards (city, budget, form_source, ...) still
    reach the agent. With no contact, emits a do-not-invent-names guard.
    """
    lines = ["CALLER CONTEXT - who this specific call is about:"]
    if institution:
        lines.append(f"- You are calling from {institution}.")
    if not contact:
        lines.append(
            "- You were NOT given the callee's name: NEVER invent or guess any name; "
            "ask who you are speaking with."
        )
        return "\n".join(lines)

    student = contact.get("student_name") or ""
    parent = ""
    for key in _GENERIC_PARENT_KEYS:
        if contact.get(key):
            parent = contact[key]
            break
    subject = ""
    for key in _GENERIC_SUBJECT_KEYS:
        if contact.get(key):
            subject = contact[key]
            break
    about: list[str] = []
    if student:
        about.append(f"the student {student}")
    if contact.get("class_section"):
        about.append(f"class {contact['class_section']}")
    if contact.get("absent_date"):
        about.append(f"absent on {contact['absent_date']}")
    if subject and subject != student:
        about.append(f"the person {subject}")
    if about:
        lines.append("- You are calling about " + ", ".join(about) + ".")
    else:
        lines.append("- Details: " + json.dumps(contact, ensure_ascii=False))
    woven = {"student_name", "class_section", "absent_date", *_GENERIC_SUBJECT_KEYS, *_GENERIC_PARENT_KEYS}
    extras = {k: v for k, v in contact.items() if k not in woven}
    if extras:
        lines.append(
            "- Other details you may use if relevant: "
            + json.dumps(extras, ensure_ascii=False, sort_keys=True)
        )
    if parent:
        lines.append(f"- Ask to speak with {parent} (the parent/guardian).")
    elif subject:
        lines.append(f"- Ask for {subject} when the call is answered.")

    names: list[str] = []
    for value in [parent, student, subject]:
        if value and value not in names:
            names.append(value)
    if names:
        lines.append(
            "- SAY THE NAMES OUT LOUD: greet the person using their name. "
            f"Known name(s) on this record: {', '.join(names)}."
        )
        lines.append(
            "- NEVER say 'the parent or guardian of the student' or 'the person "
            "we are calling about' when you have a real name on this record."
        )
    lines.extend(
        [
            "- VERIFY RELATIONSHIP BEFORE DETAILS: confirm you are speaking with the "
            "right person before discussing any details.",
            "- If the person who answered is NOT that person, do not share any details: "
            "ask when they will be available, thank them politely, and end the call.",
        ]
    )
    return "\n".join(lines)


def _render_text_system_prompt(
    config: Any,
    contact: Optional[dict[str, str]] = None,
    institution: str = "",
) -> str:
    """Slim server-side twin of voice-agent/app/prompting.render_system_prompt.

    Same section order and discipline (disclosure verbatim first, TTS-safe
    style rules so text replies behave like the spoken ones), but compact
    enough to keep text-mode token cost low. ``contact`` (P0-2) appends the
    CALLER CONTEXT block so the agent personalizes and verifies the
    relationship before sharing any details.
    """
    sections: list[str] = []

    card = contact or {}
    tokens = build_token_map(card, institution=institution)

    # 1. Mandatory disclosure FIRST and verbatim.
    disclosure = apply_token_substitution(str(config.disclosure_script or "").strip(), tokens)
    if disclosure:
        sections.append(
            f"MANDATORY DISCLOSURE - your VERY FIRST utterance, word-for-word:\n{disclosure}"
        )

    # 2. Persona / mission.
    role_lines = [
        "You are a friendly human-sounding outbound phone agent; this is a TEXT test of that call.",
        "Every reply you type is read aloud by a speech engine exactly as written.",
        "Have a short natural conversation and complete the goals below.",
    ]
    persona = apply_token_substitution(str(config.system_prompt or "").strip(), tokens)
    sections.append(
        "WHO YOU ARE:\n" + "\n".join(f"- {line}" for line in role_lines)
    )
    # 2b. Creator's role definition - authoritative, verbatim (not a bullet).
    if persona:
        sections.append(
            "ROLE & MISSION - defined by the agent creator (AUTHORITATIVE):\n"
            f"{persona}\n"
            "This role definition is authoritative for WHO you are and HOW you "
            "behave: where it differs from generic examples, follow the role "
            "definition."
        )

    # 3. Company context.
    company_context = config.company_context or {}
    if company_context:
        sections.append(
            "COMPANY KNOWLEDGE - facts you may use; never invent anything beyond this:\n"
            + json.dumps(company_context, ensure_ascii=False, default=str)
        )

    # 3b. CALLER CONTEXT (P0-2, generic) — who this specific call is about.
    sections.append(_render_caller_context(card, institution))

    # 4. TTS-safe speaking style (kept identical in spirit to the voice agent).
    sections.append(
        "HOW TO REPLY (critical):\n"
        "- Keep every reply SHORT: usually 1-2 sentences, never more than 3.\n"
        "- Plain conversational words only. This text is converted to speech:\n"
        "  NO markdown, NO asterisks, NO lists, NO numbering symbols, NO emoji,\n"
        "  NO newlines inside a reply. Sentences and punctuation only.\n"
        "- Respond to what the person ACTUALLY said before moving on; ask ONE thing per turn.\n"
        "- Never repeat a question they already answered. Stay polite even if they are upset."
    )

    # 5. Question flow as goals to weave in naturally.
    goals: list[str] = []
    number = 0
    for item in config.question_flow or []:
        text_value = apply_token_substitution(_question_text(item), tokens)
        if not text_value:
            continue
        number += 1
        goals.append(f"{number}. {text_value}")
    if not goals:
        goals.append("No fixed goals were configured; have a natural conversation about why you are calling.")
    sections.append(
        "YOUR GOALS - information to collect during the call:\n"
        + "\n".join(goals)
        + "\nCover ALL of these by the end, weaving each into the conversation naturally."
    )

    # 6. Extraction discipline with the exact field list.
    extraction_lines = [
        "RECORDING ANSWERS - extraction discipline:",
        "- The moment the caller states something that answers a goal above, IMMEDIATELY call "
        "`record_extracted_field(field_name, value, confidence)` in that same turn.",
        "- Use the EXACT field names below. Quote values exactly as the caller said them.",
        "- Give an honest confidence 0.0-1.0. NEVER fabricate or guess a value - "
        "if unsure, ask a short clarifying question instead of recording.",
        "- When everything is captured (or the caller wants to stop), call `end_call(summary)` "
        "with a factual summary including any unfilled required fields.",
        "Fields to capture:",
    ]
    schema = config.extraction_schema or {}
    if isinstance(schema, dict):
        for field_name, spec in schema.items():
            if isinstance(spec, dict):
                description = str(spec.get("description") or spec.get("type") or "").strip()
                required_marker = (
                    " [REQUIRED]" if str(spec.get("validation") or "").lower() == "required" else ""
                )
                extraction_lines.append(f"- `{field_name}`{required_marker}: {description}".rstrip(": "))
            else:
                extraction_lines.append(f"- `{field_name}`: {spec}")
    sections.append("\n".join(extraction_lines))

    return "\n\n".join(sections)


# OpenAI-compatible function tools (Groq chat completions accepts this schema).
_TEXT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "record_extracted_field",
            "description": (
                "Record a structured value the caller stated. Use the exact field name from "
                "the extraction schema. Never guess: if unsure, ask a clarifying question instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "field_name": {
                        "type": "string",
                        "description": "Exact field name from the extraction schema.",
                    },
                    "value": {
                        "type": "string",
                        "description": "The value exactly as the caller stated it.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Your honest confidence in the value (0.0 to 1.0).",
                    },
                },
                "required": ["field_name", "value", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": (
                "Politely finish the conversation. Call when all questions are handled, the "
                "caller wants to stop, or escalation rules say to wrap up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Factual wrap-up summary of captured and unfilled fields.",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


def _groq_request_body(settings: Settings, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Chat-completions payload mirroring the voice worker's LLM settings."""
    body: dict[str, Any] = {
        "model": settings.groq_model,
        "messages": messages,
        "tools": _TEXT_TOOLS,
        "tool_choice": "auto",
        "temperature": 0.6,
        "max_tokens": 300,
    }
    if "qwen" in settings.groq_model.lower():
        # Qwen is a hybrid reasoning model - thinking tokens add latency.
        body["reasoning_effort"] = "none"
    return body


async def _groq_chat(
    settings: Settings, messages: list[dict[str, Any]], include_tools: bool = True
) -> dict[str, Any]:
    """Groq chat-completions round trip with multi-key rotation.

    Each key gets up to ``_GROQ_MAX_RETRIES`` same-key backoff retries; a key
    that stays 429 is abandoned and the identical request is re-issued on
    the next key (GROQ_API_KEY first, then GROQ_API_KEYS). Single-key setups
    behave exactly as before. Only when every key is exhausted does the
    caller see a 429.
    """
    body = _groq_request_body(settings, messages)
    if not include_tools:
        body.pop("tools", None)
        body.pop("tool_choice", None)
    keys = settings.groq_api_key_list or [settings.groq_api_key]
    last_429_text = ""
    base_url = settings.groq_base_url or _GROQ_BASE_URL
    async with httpx.AsyncClient(base_url=base_url, timeout=45.0) as client:
        for key_index, key in enumerate(keys):
            headers = {"Authorization": f"Bearer {key}"}
            response = None
            for attempt in range(_GROQ_MAX_RETRIES + 1):
                response = await client.post("/chat/completions", json=body, headers=headers)
                if response.status_code != 429:
                    break
                if attempt >= _GROQ_MAX_RETRIES:
                    break
                logger.warning("Groq chat rate limited (429, key %d, attempt %s): backing off", key_index + 1, attempt + 1)
                await asyncio.sleep(_retry_delay(response, attempt))
            assert response is not None  # loop always runs at least once
            if response.status_code != 429:
                break  # success (or a non-429 error handled below)
            last_429_text = response.text[:300]
            if key_index < len(keys) - 1:
                logger.warning(
                    "Groq key %d/%d exhausted (persistent 429): rotating to next key",
                    key_index + 1, len(keys),
                )
                continue
    assert response is not None  # loop always runs at least once
    if response.status_code == 429:
        logger.warning("Groq chat rate limited on all %d key(s) (429): %s", len(keys), last_429_text)
        raise HTTPException(
            status_code=429,
            detail="The AI service rate limit was hit. Wait a few seconds and send again.",
        )
    if response.status_code != 200:
        logger.error("Groq chat failed (%s): %s", response.status_code, response.text[:500])
        raise HTTPException(status_code=502, detail="The language model did not respond. Try again shortly.")
    try:
        return response.json()["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Unexpected response from the language model.") from exc


def _execute_text_tool(
    db: Session, call: Call, name: str, arguments: dict[str, Any], source_turn_index: int
) -> tuple[str, Optional[dict[str, Any]], bool]:
    """Run one tool call against the DB.

    Returns ``(tool_result_text, extracted_field_or_None, done_flag)``.
    Field upsert semantics mirror the internal API (_apply_fields).
    """
    if name == "record_extracted_field":
        field_name = str(arguments.get("field_name") or "").strip()
        value = arguments.get("value")
        confidence = arguments.get("confidence")
        if not field_name:
            return "error: field_name is required", None, False
        try:
            conf = float(confidence)  # type: ignore[arg-type]
            if not 0.0 <= conf <= 1.0:
                conf = None
        except (TypeError, ValueError):
            conf = None
        for existing in db.scalars(
            select(ExtractedField).where(
                ExtractedField.call_id == call.id,
                ExtractedField.field_name == field_name,
            )
        ):
            db.delete(existing)
        db.add(
            ExtractedField(
                call_id=call.id,
                field_name=field_name,
                field_value=None if value is None else str(value),
                confidence=conf,
                source_turn_index=source_turn_index,
            )
        )
        recorded = {
            "field_name": field_name,
            "field_value": None if value is None else str(value),
            "confidence": conf,
        }
        return f"recorded {field_name}", recorded, False

    if name == "end_call":
        summary = str(arguments.get("summary") or "").strip() or None
        now = utcnow()
        call.summary = summary
        call.status = "completed"
        call.ended_at = now
        if call.started_at is not None:
            call.duration_seconds = (now - call.started_at).total_seconds()
        return "call ended", {"summary": summary}, True

    return f"error: unknown tool {name}", None, False


_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL | re.IGNORECASE)
_FUNCTION_RE = re.compile(r"<function\s*=\s*([^>\s]+)\s*>", re.IGNORECASE)
_PARAMETER_RE = re.compile(r"<parameter\s*=\s*([^>\s]+)\s*>\s*(.*?)\s*</parameter>", re.DOTALL | re.IGNORECASE)
_TAG_REMAINDER_RE = re.compile(r"</?(?:function|parameter)[^>]*>", re.IGNORECASE)


def _parse_pseudo_tool_calls(text: str) -> list[dict[str, Any]]:
    """Tool calls the model emitted as text instead of real function calls.

    Returns [{name, arguments}]. Only ``record_extracted_field`` is actionable;
    anything else is scrubbed but ignored (never terminate a call on echoed text).
    """
    found: list[dict[str, Any]] = []
    for block in _TOOL_CALL_BLOCK_RE.findall(str(text or "")):
        func = _FUNCTION_RE.search(block)
        if not func:
            continue
        args: dict[str, Any] = {}
        for key, value in _PARAMETER_RE.findall(block):
            args[key.strip()] = value.strip()
        found.append({"name": func.group(1).strip(), "arguments": args})
    return found


def _scrub_tool_markup(text: str) -> str:
    """Remove tool-call markup so it never ships to the transcript/UI."""
    out = _TOOL_CALL_BLOCK_RE.sub(" ", str(text or ""))
    out = _TAG_REMAINDER_RE.sub(" ", out)
    return " ".join(out.split())


@router.post("/sessions/{call_id}/turns")
async def create_turn(
    call_id: int,
    payload: TurnCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """One TEXT-mode conversational turn (or the opening line via event=start).

    Rebuilds history from persisted Transcript rows, calls Groq directly,
    executes any function tools, persists both sides of the exchange, and
    returns the agent reply plus extraction state.
    """
    settings: Settings = request.app.state.settings
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="Text mode needs GROQ_API_KEY configured on the backend.",
        )

    call = _get_own_playground_call(db, call_id, user)  # 404 unless own playground row
    if call.status != "in_progress":
        raise HTTPException(status_code=409, detail="This session has already ended.")
    version = db.get(AgentVersion, call.agent_version_id) if call.agent_version_id else None
    if version is None:
        raise HTTPException(status_code=409, detail="Session has no agent version configured.")

    start_event = payload.event == "start"
    user_text = "" if start_event else payload.text.strip()
    if not start_event and not user_text:
        raise HTTPException(status_code=422, detail="'text' must not be empty.")

    return await _run_agent_turn(
        db, settings, call, version, user_text=user_text, start_event=start_event
    )


async def _run_agent_turn(
    db: Session,
    settings: Settings,
    call: Call,
    version: AgentVersion,
    *,
    user_text: str,
    start_event: bool,
) -> dict[str, Any]:
    """One text-mode agent turn: build prompt, call Groq, run tools, persist.

    Shared by the HTTP turns endpoint and the campaign dry-run runner so
    simulated calls go through byte-identical conversation logic.
    """
    contact = (call.context or {}).get("contact") or {}
    org = db.get(Organization, call.org_id) if call.org_id else None
    institution = org.name if org and org.name else ""
    system_prompt = _render_text_system_prompt(version, contact=contact, institution=institution)
    history_rows = list(
        db.scalars(
            select(Transcript)
            .where(Transcript.call_id == call.id)
            .order_by(Transcript.turn_index, Transcript.id)
        ).all()
    )
    next_index = (history_rows[-1].turn_index + 1) if history_rows else 0

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    # Bounded history: full transcripts grow a turn per exchange, and by
    # turn ~10 the model re-reads the whole call before every reply (input
    # tokens balloon, TTFT climbs linearly, TPM 429s follow). The last 14
    # rows (~7 exchanges) carry all working context; the DB keeps the rest.
    for row in history_rows[-14:]:
        messages.append(
            {"role": "assistant" if row.speaker == "agent" else "user", "content": row.text}
        )
    if start_event:
        # NOTE: must be role "user" - some Groq models reject tool-bound
        # requests whose messages do not end with a user query.
        kickoff = (
            "[Call just connected; the callee has not spoken yet] "
            "Produce ONLY your opening utterance now: the mandatory disclosure "
            "followed by a warm one-line greeting and your first question."
        )
        contact = (call.context or {}).get("contact") or {}
        tokens = build_token_map(contact, institution)
        student = tokens["[Student Name]"]
        parent = tokens["[Parent/Guardian Name]"]
        if student:
            kickoff += (
                f" You are calling about {student}"
                + (f"; ask to speak with {parent}." if parent else ".")
            )
        messages.append({"role": "user", "content": kickoff})
    else:
        messages.append({"role": "user", "content": user_text})

    extracted_now: list[dict[str, Any]] = []
    done = False
    started_mono = time.monotonic()
    assistant_text = ""
    groq_call_ms: list[float] = []

    for round_no in range(_MAX_TOOL_ROUNDS):
        call_started = time.monotonic()
        message = await _groq_chat(settings, messages, include_tools=round_no < _MAX_TOOL_ROUNDS - 1)
        groq_call_ms.append((time.monotonic() - call_started) * 1000.0)
        tool_calls = message.get("tool_calls") or []
        content = str(message.get("content") or "").strip()
        if not tool_calls:
            assistant_text = content
            break
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    arguments = {}
            except json.JSONDecodeError:
                arguments = {}
            result_text, field_record, done_flag = _execute_text_tool(
                db, call, str(function.get("name") or ""), arguments, next_index
            )
            if field_record and "summary" not in field_record:
                extracted_now.append(field_record)
            done = done or done_flag
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tool_call.get("id") or ""),
                    "content": result_text,
                }
            )
    else:
        # Tool loop exhausted without plain text - force one final text reply.
        call_started = time.monotonic()
        message = await _groq_chat(
            settings,
            messages + [{"role": "system", "content": "Reply now in plain words only."}],
            include_tools=False,
        )
        groq_call_ms.append((time.monotonic() - call_started) * 1000.0)
        assistant_text = str(message.get("content") or "").strip()

    # Pseudo tool calls: the model sometimes emits <tool_call> XML as text
    # instead of a real function call (seen live: the field was lost and raw
    # markup was saved to the transcript). Execute record_* ones with identical
    # semantics, then scrub all markup so it never ships to the UI.
    for pseudo in _parse_pseudo_tool_calls(assistant_text):
        if pseudo["name"] != "record_extracted_field":
            continue
        _result_text, field_record, _done_flag = _execute_text_tool(
            db, call, pseudo["name"], pseudo["arguments"], next_index
        )
        if field_record and "summary" not in field_record:
            extracted_now.append(field_record)
    assistant_text = _scrub_tool_markup(assistant_text)

    elapsed_ms = round((time.monotonic() - started_mono) * 1000.0)

    # Persist both sides of the exchange (caller turn only when not start).
    user_index: Optional[int] = None
    if user_text:
        user_index = next_index
        db.add(
            Transcript(
                call_id=call.id,
                turn_index=next_index,
                speaker="caller",
                text=user_text,
                timestamp=utcnow(),
            )
        )
    agent_index = next_index + 1 if user_text else next_index
    if assistant_text:
        db.add(
            Transcript(
                call_id=call.id,
                turn_index=agent_index,
                speaker="agent",
                text=assistant_text,
                timestamp=utcnow(),
                # First Groq round-trip time as the LLM leg proxy (text mode
                # has no STT/TTS legs, so e2e ≈ LLM + tool overhead).
                llm_first_token_ms=round(groq_call_ms[0], 1) if groq_call_ms else None,
                e2e_ms=float(elapsed_ms),  # text-mode wall clock (no STT/TTS legs)
            )
        )
    db.commit()

    logger.info(
        "text_turn call=%s org=%s turn=%s start=%s done=%s llm_ms=%s fields=%s",
        call.id,
        call.org_id,
        agent_index,
        start_event,
        done,
        elapsed_ms,
        len(extracted_now),
    )

    return {
        "reply_text": assistant_text,
        "done": done,
        "extracted_fields": extracted_now,
        "turn_index": agent_index if assistant_text else next_index,
    }


@router.post("/campaigns/{campaign_id}/dry-run")
async def dry_run_campaign(
    campaign_id: int,
    payload: DryRunCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """SIMULATION ONLY: run campaign contacts through text-mode turns.

    No telephony, no dialer. Each contact gets a scripted caller persona and
    a persisted ``Call(kind="dry-run")`` for inspection via call detail.
    """
    from app.services.dry_run import PERSONA_ORDER, run_campaign_dry_run, validate_persona

    settings: Settings = request.app.state.settings
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="Text mode needs GROQ_API_KEY configured on the backend.",
        )
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="not found")
    version = None
    if campaign.agent_version_id:
        version = db.get(AgentVersion, campaign.agent_version_id)
    if version is None:
        version = db.scalar(
            select(AgentVersion)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(Agent.org_id == user.org_id)
            .order_by(AgentVersion.id.desc())
        )
    if version is None:
        raise HTTPException(status_code=422, detail="no agent versions in org")
    if payload.persona is not None:
        try:
            persona_names = [validate_persona(payload.persona)]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        persona_names = list(PERSONA_ORDER)
    contacts = list(
        db.scalars(
            select(Contact)
            .where(
                Contact.campaign_id == campaign.id,
                Contact.status.in_(["queued", "pending_review"]),
            )
            .order_by(Contact.id)
            .limit(payload.contact_limit)
        ).all()
    )
    report = await run_campaign_dry_run(
        db, settings, _run_agent_turn,
        campaign=campaign, version=version,
        contacts=contacts, persona_names=persona_names,
    )
    return {
        "campaign_id": campaign.id,
        "persona": payload.persona,
        "contacts_total": len(contacts),
        "contacts_run": len(report["results"]),
        "results": report["results"],
    }
