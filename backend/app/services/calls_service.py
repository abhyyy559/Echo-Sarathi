"""Call lifecycle helpers shared by the dialer, Twilio webhooks and internal API."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    IN_FLIGHT_CALL_STATUSES,
    Call,
    CallEvent,
    Campaign,
    Contact,
    ExtractedField,
    Transcript,
)
from app.timeutil import backoff_from, parse_iso, utcnow

logger = logging.getLogger(__name__)

# Twilio CallStatus -> internal call status
TWILIO_STATUS_MAP = {
    "initiated": "queued",
    "queued": "queued",
    "ringing": "ringing",
    "in-progress": "in_progress",
    "completed": "completed",
    "busy": "busy",
    "no-answer": "no_answer",
    "canceled": "canceled",
    "failed": "failed",
}

# Plivo uses the same CallStatus vocabulary as Twilio.
PLIVO_STATUS_MAP = {**TWILIO_STATUS_MAP}


def log_call_event(db: Session, call_id: int, event_type: str, payload: Optional[dict]) -> None:
    db.add(CallEvent(call_id=call_id, event_type=event_type, payload=payload))


def in_flight_call_count(db: Session) -> int:
    return int(
        db.scalar(select(func.count()).select_from(Call).where(Call.status.in_(IN_FLIGHT_CALL_STATUSES)))
        or 0
    )


def apply_contact_retry(contact: Contact, settings: Settings, now: Optional[Any] = None) -> None:
    """Retry bookkeeping after a no-answer/busy/dial-failure.

    Increments attempt_count; re-queues with backoff while under
    RETRY_MAX_ATTEMPTS, otherwise marks the contact failed.
    """
    now = now or utcnow()
    contact.attempt_count = (contact.attempt_count or 0) + 1
    if contact.attempt_count < settings.retry_max_attempts:
        contact.status = "queued"
        contact.next_attempt_at = backoff_from(now, settings.retry_backoff_minutes)
    else:
        contact.status = "failed"
        contact.next_attempt_at = None


def maybe_complete_campaign(db: Session, campaign_id: int) -> bool:
    """Complete a running campaign once no queued/calling contacts remain."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.status != "running":
        return False
    active = (
        db.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.campaign_id == campaign_id, Contact.status.in_(("queued", "calling")))
        )
        or 0
    )
    if active == 0:
        campaign.status = "completed"
        return True
    return False


def end_call(
    db: Session,
    call: Call,
    contact: Contact,
    status: str,
    settings: Settings,
    now: Optional[Any] = None,
    duration_seconds: Optional[float] = None,
) -> None:
    """Move a call to an end state and update the contact per retry policy."""
    now = now or utcnow()
    call.status = status
    call.ended_at = now
    if duration_seconds is None and call.started_at is not None:
        duration_seconds = (now - call.started_at).total_seconds()
    call.duration_seconds = duration_seconds

    if status in ("no_answer", "busy"):
        apply_contact_retry(contact, settings, now)
    elif status == "failed":
        contact.status = "failed"
        contact.next_attempt_at = None
    elif status == "completed":
        contact.status = "completed"
        contact.next_attempt_at = None
    elif status == "canceled":
        if contact.status == "calling":
            contact.status = "failed"
    maybe_complete_campaign(db, call.campaign_id)


# --- internal report handling -------------------------------------------------

def _require_dict(payload: Any, name: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError(f"'{name}' payload must be an object")
    return payload


def _apply_turn(db: Session, call: Call, payload: Any) -> None:
    p = _require_dict(payload, "turn")
    turn_index = p.get("turn_index")
    speaker = p.get("speaker")
    text = p.get("text")
    if not isinstance(turn_index, int) or isinstance(turn_index, bool):
        raise ValueError("'turn_index' must be an integer")
    if speaker not in ("agent", "caller"):
        raise ValueError("'speaker' must be 'agent' or 'caller'")
    if not isinstance(text, str):
        raise ValueError("'text' must be a string")
    timestamp = None
    if p.get("timestamp") is not None:
        if not isinstance(p["timestamp"], str):
            raise ValueError("'timestamp' must be an ISO-8601 string")
        timestamp = parse_iso(p["timestamp"])
    db.add(
        Transcript(
            call_id=call.id,
            turn_index=turn_index,
            speaker=speaker,
            text=text,
            timestamp=timestamp,
        )
    )


_PLACEHOLDER_FIELD_VALUES = {"unknown", "not provided", "n/a"}


def _normalize_field_row(item: dict) -> tuple[str, str | None] | None:
    """Normalize one extracted-field row.

    Voice-agent rows use ``field_name``/``field_value`` (preferred); legacy
    text-path rows use ``name``/``value``. Returns ``(field_name, value)`` or
    ``None`` when the voice-agent value is a placeholder to be skipped.
    """
    if "field_name" in item or "field_value" in item:
        name = item.get("field_name")
        if not isinstance(name, str) or not name:
            raise ValueError("field 'field_name' must be a non-empty string")
        raw_value = item.get("field_value")
        if raw_value is None:
            return None
        if not isinstance(raw_value, str):
            raise ValueError(f"field '{name}' 'field_value' must be a string")
        value = raw_value.strip()
        if not value or value.lower() in _PLACEHOLDER_FIELD_VALUES:
            return None
        return name, value
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("field 'name' must be a non-empty string")
    value = item.get("value")
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"field '{name}' value must be scalar or null")
    return name, None if value is None else str(value)


def _apply_fields(db: Session, call: Call, payload: Any) -> None:
    p = _require_dict(payload, "fields")
    fields = p.get("fields")
    if not isinstance(fields, list):
        raise ValueError("'fields' must be a list")
    for item in fields:
        if not isinstance(item, dict):
            raise ValueError("each field must be an object")
        normalized = _normalize_field_row(item)
        if normalized is None:
            continue
        name, value = normalized
        confidence = item.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            raise ValueError(f"field '{name}' confidence must be a number or null")
        if isinstance(confidence, float) and not 0.0 <= confidence <= 1.0:
            raise ValueError(f"field '{name}' confidence must be within 0..1")
        source_turn = item.get("source_turn_index")
        if source_turn is not None and (not isinstance(source_turn, int) or isinstance(source_turn, bool)):
            raise ValueError(f"field '{name}' source_turn_index must be an integer or null")
        # Upsert: replace any previous value for this field name.
        for existing in db.scalars(
            select(ExtractedField).where(
                ExtractedField.call_id == call.id, ExtractedField.field_name == name
            )
        ):
            db.delete(existing)
        db.add(
            ExtractedField(
                call_id=call.id,
                field_name=name,
                field_value=value,
                confidence=None if confidence is None else float(confidence),
                source_turn_index=source_turn,
            )
        )
    if p.get("complete") is not None:
        if not isinstance(p["complete"], bool):
            raise ValueError("'complete' must be a boolean")
        log_call_event(db, call.id, "fields_complete", {"complete": p["complete"]})


def _apply_summary(db: Session, call: Call, payload: Any) -> None:
    p = _require_dict(payload, "summary")
    if "summary" in p and p["summary"] is not None and not isinstance(p["summary"], str):
        raise ValueError("'summary' must be a string")
    if "outcome" in p and p["outcome"] is not None and not isinstance(p["outcome"], str):
        raise ValueError("'outcome' must be a string")
    if "flagged_for_human" in p and p["flagged_for_human"] is not None and not isinstance(
        p["flagged_for_human"], bool
    ):
        raise ValueError("'flagged_for_human' must be a boolean")
    call.summary = p.get("summary", call.summary)
    call.outcome = p.get("outcome", call.outcome)
    if p.get("flagged_for_human") is not None:
        call.flagged_for_human = p["flagged_for_human"]


def _apply_metrics(db: Session, call: Call, payload: Any) -> None:
    p = _require_dict(payload, "metrics")
    latency = p.get("latency_ms")
    cost = p.get("cost_usd")
    if latency is not None and not isinstance(latency, dict):
        raise ValueError("'latency_ms' must be an object")
    if cost is not None and not isinstance(cost, dict):
        raise ValueError("'cost_usd' must be an object")
    if latency is not None:
        call.latency = latency
    if cost is not None:
        call.cost = cost
    log_call_event(db, call.id, "metrics", {"latency_ms": latency, "cost_usd": cost})


def _apply_status(db: Session, call: Call, payload: Any) -> None:
    p = _require_dict(payload, "status")
    status = p.get("status")
    reason = p.get("reason")
    if status not in ("in_progress", "completed", "escalated", "failed"):
        raise ValueError("'status' must be one of in_progress|completed|escalated|failed")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("'reason' must be a string")
    now = utcnow()
    contact = db.get(Contact, call.contact_id)

    if status == "in_progress":
        call.status = "in_progress"
        if call.answered_at is None:
            call.answered_at = now
        if contact is not None:
            contact.status = "calling"
    elif status == "completed":
        call.status = "completed"
        if call.ended_at is None:
            call.ended_at = now
            if call.started_at is not None:
                call.duration_seconds = (now - call.started_at).total_seconds()
        if contact is not None:
            contact.status = "completed"
            contact.next_attempt_at = None
        maybe_complete_campaign(db, call.campaign_id)
    elif status == "escalated":
        call.status = "completed"
        call.flagged_for_human = True
        if call.outcome is None:
            call.outcome = "escalated"
        if call.ended_at is None:
            call.ended_at = now
            if call.started_at is not None:
                call.duration_seconds = (now - call.started_at).total_seconds()
        if contact is not None:
            contact.status = "completed"
            contact.next_attempt_at = None
        maybe_complete_campaign(db, call.campaign_id)
    elif status == "failed":
        call.status = "failed"
        if call.ended_at is None:
            call.ended_at = now
        if contact is not None:
            contact.status = "failed"
            contact.next_attempt_at = None
        maybe_complete_campaign(db, call.campaign_id)
    log_call_event(db, call.id, f"status:{status}", {"reason": reason})


_REPORT_HANDLERS = {
    "turn": _apply_turn,
    "fields": _apply_fields,
    "summary": _apply_summary,
    "metrics": _apply_metrics,
    "status": _apply_status,
}


def apply_report(db: Session, call: Call, report_type: str, payload: Any) -> None:
    """Apply a voice-agent report. Raises ValueError on invalid payloads."""
    handler = _REPORT_HANDLERS.get(report_type)
    if handler is None:
        raise ValueError("'type' must be one of turn|fields|summary|metrics|status")
    handler(db, call, payload)
