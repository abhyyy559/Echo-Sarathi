"""Vobiz provider-status reconciliation.

Vobiz pushes no status webhooks for calls we create (we register no status
callback at Call-create), so without this our rows stick in
``ringing``/``in_progress`` forever and carrier outcomes (USER_BUSY,
NO_ANSWER, …) never surface. This module pulls the authoritative Call
resource (GET /api/v1/Account/{auth_id}/Call/{provider_id}/) and applies it
to our call + contact rows with the dialer's retry policy.

Shape verified against the live API (2026-09-28): the resource carries
``hangup_cause`` (e.g. USER_BUSY), ``bill_duration``/``billed_duration``,
``answer_time``, ``duration`` and ``end_time``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_TERMINAL = ("completed", "failed", "canceled", "no_answer", "busy")


def map_vobiz_outcome(body: Mapping[str, Any]) -> str:
    """Map a Vobiz Call resource onto our call status vocabulary.

    A billed call is a connected conversation (completed). An unbilled call
    is classified by hangup_cause; unknown/unfinished legs report ``ringing``
    (still in flight — never fabricate a terminal state).
    """
    cause = str(body.get("hangup_cause") or "").strip().upper()
    billed = _to_float(body.get("bill_duration", body.get("billed_duration")))
    answered = bool(body.get("answer_time")) or (billed is not None and billed > 0)
    if answered:
        return "completed"
    if not cause:
        return "ringing"
    if "BUSY" in cause:
        return "busy"
    if "NO_ANSWER" in cause or cause == "NOANSWER":
        return "no_answer"
    if cause in ("NORMAL_CLEARING", "ORIGINATOR_CANCEL", "NORMAL_UNSPECIFIED"):
        return "completed" if answered else "no_answer"
    if "CANCEL" in cause:
        return "canceled"
    return "failed"


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            from datetime import timezone

            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def fetch_vobiz_call(settings: Any, provider_call_id: str) -> Optional[dict[str, Any]]:
    """GET one Vobiz Call resource. None when unconfigured or on any failure."""
    auth_id = str(getattr(settings, "vobiz_auth_id", "") or "")
    auth_token = str(getattr(settings, "vobiz_auth_token", "") or "")
    if not auth_id or not auth_token or not provider_call_id:
        return None
    import httpx

    url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{provider_call_id}/"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(
                url,
                headers={"X-Auth-ID": auth_id, "X-Auth-Token": auth_token,
                         "Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning("vobiz reconcile GET %s -> %s", resp.status_code, resp.text[:200])
                return None
            body = resp.json()
            return dict(body) if isinstance(body, dict) else None
    except Exception:  # noqa: BLE001 — best effort only
        logger.warning("vobiz reconcile GET failed for %s", provider_call_id, exc_info=True)
        return None


def apply_provider_status(
    db: Session, call: Any, status: str, settings: Any, now: Any,
    detail: Optional[dict[str, Any]] = None,
) -> str:
    """Apply a reconciled terminal status to call + contact rows.

    Returns the applied status. Non-terminal outcomes leave rows untouched.
    Contact retry policy mirrors the dialer: no-answer/busy re-queue with
    backoff while attempts remain, else fail.
    """
    from app.models import Contact
    from app.services.calls_service import (
        apply_contact_retry,
        log_call_event,
        maybe_complete_campaign,
    )

    if status not in _TERMINAL:
        return str(call.status)
    if call.status in _TERMINAL:
        return str(call.status)  # never regress a final state
    call.status = status
    if call.ended_at is None:
        call.ended_at = now
    if detail:
        duration = _to_float(detail.get("duration", detail.get("bill_duration")))
        if duration is not None and duration >= 0:
            call.duration_seconds = duration
    contact = db.get(Contact, call.contact_id) if call.contact_id else None
    if contact is not None:
        if status == "completed":
            if contact.status == "calling":
                contact.status = "completed"
            contact.next_attempt_at = None
        elif status in ("no_answer", "busy"):
            apply_contact_retry(contact, settings, now)
        elif status in ("failed", "canceled"):
            contact.status = "failed"
    log_call_event(db, call.id, f"provider_reconciled:{status}", detail or {})
    if call.campaign_id is not None:
        maybe_complete_campaign(db, call.campaign_id)
    db.commit()
    return status


def reconcile_vobiz_call(db: Session, settings: Any, call: Any, now: Any) -> str:
    """Fetch + apply the provider outcome for one phone call (best-effort).

    Returns the resulting call status. Never raises; when the provider is
    unreachable the row is left exactly as it was.
    """
    if call.kind != "phone" or not call.provider_call_id:
        return str(call.status)
    if call.status in _TERMINAL:
        return str(call.status)
    body = fetch_vobiz_call(settings, str(call.provider_call_id))
    if not body:
        return str(call.status)
    return apply_provider_status(db, call, map_vobiz_outcome(body), settings, now, body)
