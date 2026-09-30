"""Scripted caller personas for the text-mode campaign dry-run.

Personas are positional scripts: reply N answers the agent's Nth utterance.
They deliberately do NOT track conversation state — the point is stressing
the agent's confirmation loop, extraction precision, and wind-down behavior,
not passing a Turing test. ``None`` means the persona has nothing left to
say (runner stops the simulation for that lead).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import select

from app.timeutil import utcnow

logger = logging.getLogger(__name__)

#: A dry run fires ~10 LLM calls per contact back-to-back, straight into the
#: org's 7000 input-tokens/minute bucket. Without pacing, the second contact
#: always 429s and the whole request fails. On a 429 we wait for the bucket to
#: refill and resume instead of failing; a few extra seconds beats re-running
#: the entire dry run by hand.
_DRY_RUN_429_WAIT_S = 20.0
_DRY_RUN_429_MAX_WAITS = 4
_DRY_RUN_PACING_S = 2.0


async def _run_turn_patiently(run_turn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call run_turn, waiting out rate limits instead of failing the dry run."""
    waits = 0
    while True:
        try:
            reply = await run_turn(*args, **kwargs)
            await asyncio.sleep(_DRY_RUN_PACING_S)
            return reply
        except HTTPException as exc:
            if exc.status_code != 429 or waits >= _DRY_RUN_429_MAX_WAITS:
                raise
            waits += 1
            logger.warning(
                "dry-run rate limited; waiting %ss (%d/%d) then resuming",
                _DRY_RUN_429_WAIT_S,
                waits,
                _DRY_RUN_429_MAX_WAITS,
            )
            await asyncio.sleep(_DRY_RUN_429_WAIT_S)

PERSONA_ORDER: tuple[str, ...] = ("cooperative", "terse", "distracted", "refuses", "clueless")

_PERSONA_SCRIPTS: dict[str, list[str]] = {
    "cooperative": [
        "Yes, speaking.",
        "He has had fever since yesterday.",
        "He should be back on Monday.",
        "Yes, I can submit the medical certificate tomorrow.",
        "Thank you, goodbye.",
    ],
    "terse": ["Yes.", "Fever.", "Monday.", "Yes.", "Bye."],
    "distracted": [
        "Yes, speaking — sorry, the TV is loud, one second.",
        "Fever since yesterday. Ask my wife if you need the exact time, she tracks all that.",
        "Monday, I think. Unless the doctor says rest longer, then Tuesday maybe.",
        "Yes, certificate tomorrow. Anyway the traffic today was terrible.",
        "Okay bye now.",
    ],
    "refuses": [
        "I do not want to talk about this, please do not call again.",
        "Please remove our number. Goodbye.",
    ],
    "clueless": [
        "I don't know.",
        "Not sure, you'd have to ask someone else.",
        "I really couldn't say.",
        "No idea. Is there anything else?",
    ],
}


def validate_persona(name: str) -> str:
    """Return the persona name or raise ValueError for unknown names."""
    if name not in _PERSONA_SCRIPTS:
        raise ValueError(f"unknown dry-run persona: {name!r}")
    return name


def persona_reply(
    persona_name: str,
    agent_text: str,
    turn_no: int,
    contact: Mapping[str, Any],
) -> Optional[str]:
    """Next scripted caller line, or None when the persona is done."""
    script = _PERSONA_SCRIPTS[validate_persona(persona_name)]
    if turn_no < 0 or turn_no >= len(script):
        return None
    return script[turn_no]


_MAX_DRY_RUN_TURNS = 6


def _mask_phone(phone: str) -> str:
    text = str(phone or "")
    if len(text) <= 4:
        return "****"
    return f"{text[:4]}****{text[-2:]}"


def _contact_card(contact: Any) -> dict[str, str]:
    card: dict[str, str] = {}
    for key, value in ((contact.custom_fields or {}) if contact else {}).items():
        name = str(key).strip()
        if not name or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            card[name] = text
    return card


async def run_campaign_dry_run(
    db: Any,
    settings: Any,
    run_turn: Any,
    *,
    campaign: Any,
    version: Any,
    contacts: list[Any],
    persona_names: list[str],
) -> dict[str, Any]:
    """Simulate one text-mode call per contact against scripted personas.

    Persists each simulation as a ``Call(kind="dry-run")`` so transcripts and
    fields stay inspectable through the existing call-detail path. ``run_turn``
    is ``_run_agent_turn`` injected for testability.
    """
    from app.models import Call, ExtractedField, Transcript  # local: avoids import cycles

    results: list[dict[str, Any]] = []
    for index, contact in enumerate(contacts):
        persona = persona_names[index % len(persona_names)]
        card = _contact_card(contact)
        call = Call(
            kind="dry-run",
            status="in_progress",
            org_id=campaign.org_id,
            campaign_id=campaign.id,
            contact_id=contact.id,
            agent_version_id=version.id,
            started_at=utcnow(),
            context={"contact": card} if card else None,
        )
        db.add(call)
        db.flush()

        turns_used = 0
        reply = await _run_turn_patiently(run_turn, db, settings, call, version, user_text="", start_event=True)
        turns_used += 1
        while not reply.get("done") and turns_used < _MAX_DRY_RUN_TURNS:
            caller_line = persona_reply(persona, reply.get("reply_text") or "", turns_used - 1, card)
            if not (caller_line or "").strip():
                break
            reply = await _run_turn_patiently(run_turn, db, settings, call, version, user_text=caller_line, start_event=False)
            turns_used += 1
        if call.status == "in_progress":
            call.status = "completed"
            call.ended_at = utcnow()
        db.commit()

        rows = db.scalars(
            select(Transcript).where(Transcript.call_id == call.id).order_by(Transcript.turn_index)
        ).all()
        fields = db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call.id).order_by(ExtractedField.id)
        ).all()
        results.append(
            {
                "contact_id": contact.id,
                "name": contact.name,
                "phone": _mask_phone(contact.phone),
                "persona": persona,
                "transcript": [
                    {"role": ("agent" if r.speaker == "agent" else "caller"), "text": r.text}
                    for r in rows
                ],
                "extracted_fields": [
                    {"field_name": f.field_name, "field_value": f.field_value, "confidence": f.confidence}
                    for f in fields
                ],
                "status": call.status,
                "outcome": call.outcome,
                "turns": turns_used,
            }
        )
    return {"results": results}
