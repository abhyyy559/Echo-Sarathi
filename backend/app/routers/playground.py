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
# One tool round is enough for a spoken turn: record the field, then speak. A
# third round plus the forced-final-reply fallback is what pushed late turns to
# 8s of end-to-end latency (three sequential provider round trips before the
# caller hears anything).
_MAX_TOOL_ROUNDS = 2

# Groq's on_demand TPM is ORGANIZATION-wide (all keys in one org share the
# pool), so prompt tokens are the scarce resource, not key count. 14 history
# rows plus a long system prompt put a single turn near the ceiling, which is
# why 3 keys did not triple throughput. 8 rows is enough working context for
# the flow and roughly halves the per-turn prompt cost.
_MAX_HISTORY_ROWS = 8
_GROQ_MAX_RETRIES = 2
_GROQ_RETRY_DELAYS = (2.0, 5.0)


# Never sleep past this on a 429: Groq sometimes answers Retry-After: 60+,
# but our HTTP client times out at 45s — honoring it blindly converts a
# backoff into a hung request that surfaces as a failure in the browser.
_GROQ_MAX_RETRY_AFTER_SECONDS = 10.0


def _retry_delay(response: Any, attempt: int) -> float:
    """Backoff for a 429: honor Retry-After (capped), else 2s then 5s."""
    try:
        header = response.headers.get("retry-after")
        if header is not None:
            return max(0.0, min(float(header), _GROQ_MAX_RETRY_AFTER_SECONDS))
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


def _proper_name(value: str) -> str:
    """Title-case a name the caller/contact typed in lower case.

    Contact CSVs and dictated test input often carry "dhanu"/"abhi"; TTS reads
    an all-lowercase name flatly and the transcript looks like data noise.
    """
    parts = [p for p in str(value or "").split() if p]
    return " ".join(p[0].upper() + p[1:] if p else p for p in parts)


def _cap_reply(text: str, max_sentences: int = 2) -> str:
    """Keep the reply to its first N sentences.

    The model regularly packed a question, a thank-you, a callback offer and a
    goodbye into ONE reply ("By which date...?Thank you. Would you like...?
    Sure, I can note that. Have a good day."). Spoken aloud that is a
    monologue the caller never answers, and it is the run-on shape callers
    report as "the agent talks over me". A hard server-side cap makes the
    one-question-one-turn rule true regardless of model compliance.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return ""
    # Split on sentence punctuation, tolerating the missing space that models
    # emit ("college?Thank you.") - a whitespace-anchored pattern silently
    # drops the run-on clause it was supposed to keep.
    sentences = [
        s.strip()
        for s in re.findall(r"[^.?!]*[.?!]+|[^.?!]+$", cleaned)
        if s.strip()
    ]
    if len(sentences) <= max_sentences:
        return cleaned
    kept = " ".join(sentences[:max_sentences]).strip()
    logger.warning("reply capped to %d sentences (was %d)", max_sentences, len(sentences))
    return kept


def _build_short_opening(
    version: AgentVersion, contact: dict[str, Any], institution: str
) -> str:
    """Deterministic 2-sentence opening, built without an LLM round trip.

    Asking the model to write its own greeting produced three sentences with
    a duplicated identity ("this is an AI assistant from CMR ... Hi Ram, this
    is Priya from the front office") — long TTS, high chance the caller hangs
    up, and a full provider round trip of latency before the first word. The
    voice worker already builds this deterministically; text mode now matches
    it: short disclosure + name + ONE question.

    Each name is spoken exactly once. Announcing the reason ("quick check on
    abhi's absence") and then asking a question that repeats both names is
    what produced the 4-clause opener seen on the second test call.
    """
    tokens = build_token_map(contact, institution)
    disclosure = apply_token_substitution(
        str(getattr(version, "disclosure_script", "") or ""), tokens
    ).strip()
    if not disclosure:
        return ""
    student = _proper_name(tokens.get("[Student Name]", ""))
    parent = _proper_name(tokens.get("[Parent/Guardian Name]", ""))
    who = _proper_name(tokens.get("[Agent Name]", "")) or "an AI assistant"
    parts = [disclosure]
    # Identity is only re-introduced when it is genuinely new information;
    # the disclosure usually already named the caller and the college.
    if who.lower() not in disclosure.lower():
        parts.append(f"Hi {parent}, {who} here." if parent else f"{who} here.")
    elif parent:
        parts.append(f"Hi {parent}.")
    # One question, one mention of the student. The flow question is only used
    # when it does not also re-ask for the name we just greeted.
    flow = getattr(version, "question_flow", None) or []
    first_question = ""
    if isinstance(flow, list) and student:
        for item in flow:
            text_value = apply_token_substitution(
                str((item or {}).get("question") or ""), tokens
            )
            if not text_value or ", ," in text_value:
                continue
            if parent and parent.lower() in text_value.lower():
                continue  # would say the parent's name twice in one breath
            if student.lower() in text_value.lower():
                first_question = text_value
                break
    if not first_question and student:
        first_question = f"Am I speaking with {student}'s parent?"
    parts.append(first_question or "Am I speaking with the parent?")
    opening = " ".join(p for p in parts if p)
    # No unsubstituted [...] may ever be spoken; apply_token_substitution
    # already stripped them, this is belt-and-braces for merged text.
    return re.sub(r"\[[^\]]*\]", "", opening).strip()
    opening = " ".join(p for p in parts if p)
    # No unsubstituted [...] may ever be spoken; apply_token_substitution
    # already stripped them, this is belt-and-braces for merged text.
    return re.sub(r"\[[^\]]*\]", "", opening).strip()


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

    # 2. Persona / mission. Kept to two lines: the creator's role definition
    # below already carries the character, and repeating generic framing in
    # three places only spent TPM.
    persona = apply_token_substitution(str(config.system_prompt or "").strip(), tokens)
    sections.append(
        "WHO YOU ARE:\n"
        "- You are a friendly human-sounding outbound phone agent. Every reply "
        "you type is read aloud by a speech engine exactly as written."
    )
    # 2b. Creator's role definition - authoritative, verbatim (not a bullet).
    if persona:
        sections.append(
            "ROLE & MISSION - defined by the agent creator (AUTHORITATIVE, and it "
            "wins any conflict with the rules below):\n" + persona
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
    # Prompt tokens are the scarce resource (Groq's TPM is org-wide), so the
    # rules are stated once, tightly. A previous version carried two
    # overlapping style blocks plus a six-bulets persona block and cost ~1.8k
    # prompt tokens per turn - the single largest TPM cost in the system.
    sections.append(
        "HOW TO REPLY (critical):\n"
        "- 1-2 short sentences, never more than 3. Plain spoken words only: NO "
        "markdown, NO lists, NO emoji, NO newlines inside a reply.\n"
        "- ONE thing per reply: if you still need an answer, ask it and STOP. "
        "Never ask a question and also thank, offer a callback, or say goodbye "
        "in the same reply - the person has not answered yet.\n"
        "- Be a person, not a form: acknowledge what they just said in a few "
        "words, then ask the next thing. Vary your wording; never read the "
        "goals out in order like a questionnaire; never stack two questions.\n"
        "- Answer what they ACTUALLY said first. If you did not catch it, say "
        "so plainly and move on after one retry. Stay polite even if upset."
    )

    # 5. Question flow as goals to weave in naturally.
    goals: list[str] = []
    for item in config.question_flow or []:
        text_value = apply_token_substitution(_question_text(item), tokens)
        if text_value:
            goals.append(f"- {text_value}")
    if not goals:
        goals.append("- Have a natural conversation about why you are calling.")
    sections.append(
        "YOUR GOALS (weave in naturally, in no fixed order):\n" + "\n".join(goals)
    )

    # 6. Extraction discipline with the exact field list.
    extraction_lines = [
        "RECORDING ANSWERS:",
        "- The moment the caller states something that answers a goal, call "
        "`record_extracted_field(field_name, value, confidence)` in that same turn.",
        "- Use the EXACT field names below; quote values as the caller said them.",
        "- NEVER invent a value. A value the caller never said does not exist - "
        "no guessed date, not even a likely one. Silences, greetings and "
        "off-topic answers contain no answers. If unsure, ask instead.",
        "- When everything is captured (or they want to stop), call "
        "`end_call(summary)` including any unfilled required fields.",
        "Fields:",
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
        # One short spoken reply, not an essay. Capping tokens is the single
        # biggest text-mode latency lever: reasoning plus a long passage is
        # what pushed turn 8+ to 12s before the caller gave up.
        "max_tokens": 160,
    }
    if "gpt-oss" in settings.groq_model.lower():
        # Parity with the voice worker: gpt-oss burns thinking tokens against
        # the output budget (truncated/empty replies that trigger more tool
        # rounds, more tokens, more 429s - the doom loop). NOTE: no qwen branch
        # any more. "reasoning_effort=none" is not a valid value on Groq at all
        # ("must be one of low, medium, high"), and qwen3.8-27b does not think
        # out loud anyway, so the parameter is simply omitted for it.
        body["reasoning_effort"] = "low"
    return body


#: Groq accepts only these values; anything else is a hard 400.
_VALID_REASONING_EFFORT = ("low", "medium", "high")

#: A REASONING model (gpt-oss) spends its output budget on thinking before it
#: emits anything. Measured with the real system prompt and a tool schema:
#:   gpt-oss-20b  max_tokens=160 -> completion 160, content "", no tool call
#:   gpt-oss-20b  max_tokens=500 -> completion 83, correct tool call
#:   qwen3.8-27b  max_tokens=160 -> completion 60,  correct tool call (686ms)
#: So a single 160-token cap is the direct cause of "the agent goes silent",
#: and reasoning models cost ~3-4x the output tokens for the same reply.
#: Per-model caps fix the silence AND cut TPM for the non-reasoning tier.
#: Deliberately NOT including qwen3: qwen/qwen3.8-27b is a plain instruct
#: model (measured: 60 output tokens, 686ms, correct tool call) and must keep
#: the small cap. Only true reasoning models need the larger budget.
_REASONING_MODEL_MARKERS = ("gpt-oss", "deepseek-r1", "reasoner", "o1-", "o3-")
_DEFAULT_MAX_TOKENS = 160
_REASONING_MAX_TOKENS = 500


def _is_reasoning_model(model: str) -> bool:
    lowered = str(model or "").lower()
    return any(marker in lowered for marker in _REASONING_MODEL_MARKERS)


def _max_tokens_for(model: str, default: int = _DEFAULT_MAX_TOKENS) -> int:
    """Output cap that leaves a reasoning model room to actually answer."""
    return _REASONING_MAX_TOKENS if _is_reasoning_model(model) else default


def _is_shared_quota_exhausted(text: str) -> bool:
    """True when the rejection is an ORGANIZATION/PROJECT token bucket.

    Groq's TPM limit is per org/project, not per key: every key in
    ``org_...`` draws on one pool. When that pool is empty, retrying the
    remaining keys of the same provider cannot succeed - it just spends six
    more requests to reach the same wall. Detect it and move to a different
    provider instead.
    """
    lowered = text.lower()
    return (
        "tokens per minute" in lowered
        or "requests per minute" in lowered
        or "on organization" in lowered
        or "on project" in lowered
    )


def _member_body(base: dict[str, Any], model: str) -> dict[str, Any]:
    """Per-provider payload: only send knobs the target model understands.

    ``reasoning_effort`` is a Groq/gpt-oss parameter. Forwarding it to another
    provider in the chain (Gemini) returns 400, and an invalid value returns
    400 even on Groq ("none"). The output cap is raised for reasoning models so
    they are not truncated into silence. Dropping reasoning_effort is always
    safe: it only caps thinking tokens.
    """
    member = {**base, "model": model}
    effort = member.get("reasoning_effort")
    if effort is not None and (
        effort not in _VALID_REASONING_EFFORT or "gpt-oss" not in model.lower()
    ):
        member.pop("reasoning_effort", None)
    member["max_tokens"] = _max_tokens_for(model, int(member.get("max_tokens", _DEFAULT_MAX_TOKENS)))
    return member


def _strip_tool_traffic(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop assistant tool_calls and their tool results from the history.

    THE CAUSE OF THE 400s: the final round of a turn is sent WITHOUT tools
    (the loop is over), but the history still contains the previous
    assistant/tool exchange. gpt-oss reads that pattern, emits another
    tool call, and Groq rejects the generation with 400
    ``tool_use_failed: Tool choice is none, but model called a tool``.
    Resending the identical payload (the previous recovery) reproduced the
    same 400, then burned a rate-limited key. Removing the tool traffic
    de-primes the model so the retry is actually a plain-text turn.
    """
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "tool":
            continue
        if message.get("role") == "assistant" and message.get("tool_calls"):
            kept = {k: v for k, v in message.items() if k != "tool_calls"}
            if kept.get("content"):
                cleaned.append(kept)
            continue
        cleaned.append(message)
    return cleaned


def _is_tool_choice_conflict(status_code: int, text: str) -> bool:
    """True when the provider rejected the payload because the model called a
    tool while tool use was disabled (``tool_use_failed``).

    Recovery is to strip the tool traffic from the history and retry as a
    plain-text turn - resending the identical payload just reproduced the
    same 400 while spending a rate-limited key.
    """
    if status_code != 400:
        return False
    return "tool_use_failed" in text or "Tool choice is none" in text


def _message_or_raise(response: Any) -> dict[str, Any]:
    """Extract ``choices[0].message`` or fail loudly with the provider body.

    The body used to be dropped, which made every provider 4xx/5xx look
    identical in the logs ("LLM provider X failed (400)") and cost real
    debugging time.
    """
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Unexpected response from the language model.",
        ) from exc
    try:
        usage = payload.get("usage") or {}
        logger.info(
            "llm_tokens provider=%s prompt=%s completion=%s total=%s",
            payload.get("model", "?"),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
    except AttributeError:
        pass
    try:
        return payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Unexpected response from the language model.",
        ) from exc


async def _groq_chat(
    settings: Settings, messages: list[dict[str, Any]], include_tools: bool = True
) -> dict[str, Any]:
    """Chat-completions round trip over the configured provider chain.

    Members are tried in order (Groq keys first, then LLM_FALLBACK_CHAIN,
    OpenAI, Cerebras, OpenRouter). Within a member, 429 gets a short bounded
    backoff; a member that stays rate-limited or errors is abandoned and the
    identical request moves to the next provider. This is what stops the agent
    going silent after 4-6 turns on a single free-tier key — the caller only
    sees an error when the ENTIRE chain is exhausted.
    """
    body = _groq_request_body(settings, messages)
    if not include_tools:
        body.pop("tools", None)
        body.pop("tool_choice", None)
    members = settings.llm_chain
    if not members:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured (set GROQ_API_KEY).",
        )
    last_error_text = ""
    rate_limited = False
    exhausted_providers: set[str] = set()
    async with httpx.AsyncClient(timeout=45.0) as client:
        for member_index, (name, base_url, api_key, model) in enumerate(members):
            if name in exhausted_providers:
                continue
            member_body = _member_body(body, model)
            headers = {"Authorization": f"Bearer {api_key}"}
            if name == "openrouter":
                headers["HTTP-Referer"] = "https://echosarathi.local"
                headers["X-Title"] = "EchoSarathi"
            response = None
            for attempt in range(_GROQ_MAX_RETRIES + 1):
                try:
                    response = await client.post(
                        f"{base_url.rstrip('/')}/chat/completions",
                        json=member_body,
                        headers=headers,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    # Network-level failure: a different provider is the fix,
                    # not another retry of the same dead endpoint.
                    last_error_text = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "LLM provider %s transport failure: %s", name, last_error_text
                    )
                    response = None
                    break
                if _is_tool_choice_conflict(
                    response.status_code, getattr(response, "text", "")
                ):
                    # The model called a tool while tool use was disabled.
                    # De-prime the history (see _strip_tool_traffic) and retry
                    # ONCE as a genuine plain-text turn. Resending the same
                    # payload reproduced the same 400 while spending a key
                    # that is often already rate-limited.
                    logger.warning(
                        "LLM tool-choice conflict on %s; retrying with tool "
                        "traffic stripped from history",
                        name,
                    )
                    member_body = {
                        **member_body,
                        "messages": _strip_tool_traffic(member_body["messages"]),
                    }
                    member_body.pop("tools", None)
                    member_body.pop("tool_choice", None)
                    response = await client.post(
                        f"{base_url.rstrip('/')}/chat/completions",
                        json=member_body,
                        headers=headers,
                    )
                    if response.status_code == 200:
                        return _message_or_raise(response)
                if response.status_code != 429:
                    break
                if _is_shared_quota_exhausted(getattr(response, "text", "")):
                    # Org/project bucket is empty: the other keys of THIS
                    # provider draw on the same pool, so stop burning them.
                    logger.warning(
                        "LLM %s hit a shared TPM/RPM bucket; skipping its "
                        "remaining keys",
                        name,
                    )
                    break
                if attempt >= _GROQ_MAX_RETRIES:
                    break
                logger.warning(
                    "LLM rate limited (429, %s, attempt %s): backing off",
                    name,
                    attempt + 1,
                )
                await asyncio.sleep(_retry_delay(response, attempt))
            if response is None:
                continue
            if response.status_code == 200:
                return _message_or_raise(response)
            last_error_text = response.text[:300]
            rate_limited = rate_limited or response.status_code == 429
            logger.warning(
                "LLM provider %s failed (%s); %d member(s) left: %s",
                name,
                response.status_code,
                len(members) - member_index - 1,
                last_error_text[:180],
            )
            if _is_shared_quota_exhausted(last_error_text):
                # Every remaining member of this provider draws on the same
                # exhausted bucket. Skip straight to the next PROVIDER.
                remaining_same = [
                    m
                    for m in members[member_index + 1 :]
                    if m[0] == name
                ]
                if remaining_same:
                    logger.warning(
                        "skipping %d further %s member(s) on the exhausted bucket",
                        len(remaining_same),
                        name,
                    )
                    exhausted_providers.add(name)
    if rate_limited:
        raise HTTPException(
            status_code=429,
            detail="The AI service rate limit was hit. Wait a few seconds and send again.",
        )
    logger.error("LLM chain exhausted. Last error: %s", last_error_text)
    raise HTTPException(
        status_code=502, detail="The language model did not respond. Try again shortly."
    )


_GROUNDING_STOPWORDS = frozenset(
    "the a an is was are be been being has have had will would shall should "
    "he she it they him her them his hers theirs you we i me my mine our ours "
    "for of to in on at from with by and or not no yes so as if then than that "
    "this these those there here what when where which who whom whose how why "
    "do does did done am s t ve re ll m d don doesn isn wasn aren".split()
)
# A value counts as a resolved date (exempt from word-overlap grounding)
# when it names an actual day: digits ("30", "2026-09-30"), month names, or
# weekday/today/tomorrow tokens. Bare spans like "next week" or "one month"
# are NOT dates — that vagueness is exactly the fabrication shape.
_DATE_LIKE_RE = re.compile(
    r"\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|today|tomorrow|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday",
    re.IGNORECASE,
)


def _value_grounded_in_transcript(
    db: Session,
    call_id: int,
    field_name: str,
    value: str,
    current_user_text: str = "",
) -> tuple[bool, str]:
    """FR-12 grounding check: the value must echo the caller's own words.

    The model sometimes records plausible-but-invented values at high
    confidence (seen live: ``expected_return_date="next week"`` when the
    caller never mentioned any date). At least one content word of the value
    must appear in the caller's transcript turns, otherwise the value is
    refused and the model is told to re-ask.

    Agent-resolved dates are exempt: the prompt instructs the model to convert
    relative answers ("after 2 days") into real dates, which legitimately
    share no words with what was said.
    """
    text = str(value or "").strip()
    if not text:
        return False, f"empty value for '{field_name}' is not a captured answer."
    caller_text = " ".join(
        db.scalars(
            select(Transcript.text).where(
                Transcript.call_id == call_id, Transcript.speaker == "caller"
            )
        ).all()
    )
    # The current turn persists AFTER the tool loop — include its live text,
    # or every first-turn recording would fail grounding.
    caller_text = f"{caller_text} {current_user_text or ''}".lower()
    if not caller_text.strip():
        # No caller speech to check against (scripted dry-run persona, or a
        # turn that started with a tool call). Grounding can only reject a
        # value that contradicts speech; with no speech the scripted value
        # stands.
        return True, ""
    if _DATE_LIKE_RE.search(text):
        # Resolved dates are only exempt when the caller actually gave a date
        # to resolve. "tomorrow at 8am" recorded against "hlooo" is pure
        # invention, so the exemption requires a date-ish cue on their side.
        if _DATE_LIKE_RE.search(caller_text):
            return True, ""
        return (
            False,
            f"date '{text}' for '{field_name}' was never stated by the caller.",
        )
    words = {
        w for w in re.findall(r"[a-z0-9']+", text.lower())
        if len(w) > 2 and w not in _GROUNDING_STOPWORDS
    }
    if not words:
        return True, ""  # nothing checkable (e.g. "yes"): let confidence decide
    caller_words = set(re.findall(r"[a-z0-9']+", caller_text))
    if words & caller_words:
        return True, ""
    return (
        False,
        f"value '{text}' for '{field_name}' was never stated by the caller.",
    )


def _execute_text_tool(
    db: Session,
    call: Call,
    name: str,
    arguments: dict[str, Any],
    source_turn_index: int,
    current_user_text: str = "",
) -> tuple[str, Optional[dict[str, Any]], bool]:
    """Run one tool call against the DB.

    Returns ``(tool_result_text, extracted_field_or_None, done_flag)``.
    Field upsert semantics mirror the internal API (_apply_fields).
    ``current_user_text`` feeds the grounding check (see above).
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
        value_text = "" if value is None else str(value)
        grounded, ground_reason = _value_grounded_in_transcript(
            db, call.id, field_name, value_text, current_user_text
        )
        if not grounded and call.kind == "dry-run":
            # Simulated persona, not a real caller: the scripted conversation
            # is the ground truth, so transcript grounding does not apply.
            grounded, ground_reason = True, ""
        if not grounded:
            # FR-12 with a paraphrase escape hatch: the FIRST ungrounded value
            # is refused with a re-ask, but if the model insists on the same
            # value after being told, it is accepted. Strict grounding alone
            # rejects legitimate paraphrases ("high temperature" -> "fever")
            # and any scripted dry-run persona; insisting twice is the signal
            # that separates a real answer from an invention.
            nudge_key = f"{field_name}={value_text.strip().lower()}"
            nudges = list((call.context or {}).get("grounding_nudges") or [])
            if nudge_key not in nudges:
                call.context = {
                    **(call.context or {}),
                    "grounding_nudges": [*nudges, nudge_key],
                }
                return (
                    f"NOT RECORDED: {ground_reason} Re-ask specifically, or record "
                    f"it once the caller actually states it.",
                    None,
                    False,
                )
            logger.info(
                "grounding: accepting %s for call=%s after re-ask", nudge_key, call.id
            )
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
    if not settings.groq_api_key_list:
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

    if start_event:
        # Deterministic opening: no provider round trip, no duplicated
        # identity, and the caller hears something within a few ms instead of
        # after a full LLM call.
        opening = _build_short_opening(version, contact, institution)
        if opening:
            db.add(
                Transcript(
                    call_id=call.id,
                    turn_index=next_index,
                    speaker="agent",
                    text=opening,
                    timestamp=utcnow(),
                    e2e_ms=0.0,
                )
            )
            db.commit()
            logger.info(
                "text_turn call=%s start opening (deterministic)", call.id
            )
            return {
                "reply_text": opening,
                "done": False,
                "extracted_fields": [],
                "turn_index": next_index,
            }

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    # Bounded history: full transcripts grow a turn per exchange, and by
    # turn ~10 the model re-reads the whole call before every reply (input
    # tokens balloon, TTFT climbs linearly, TPM 429s follow). The last 14
    # rows (~7 exchanges) carry all working context; the DB keeps the rest.
    for row in history_rows[-_MAX_HISTORY_ROWS:]:
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
        # Tools stay enabled on EVERY round. Disabling them on the last round
        # is what produced the Groq 400 "Tool choice is none, but model called
        # a tool": gpt-oss kept emitting tool calls (including hallucinated
        # ones like container.exec) and a request with tools absent makes any
        # tool call a server-side error. A legal tool call costs one round
        # trip; an illegal one costs a 400 plus a wasted key.
        message = await _groq_chat(settings, messages, include_tools=True)
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
                db, call, str(function.get("name") or ""), arguments, next_index,
                user_text,
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
        # The model spent its tool rounds and still owes the caller words.
        # One more request WITH tools enabled (a tools-less request is what
        # 400s). If it replies with more tool calls instead of speech, we do
        # not error and we do not speak markup: we fall through to a
        # deterministic line so the caller always hears something.
        call_started = time.monotonic()
        try:
            message = await _groq_chat(
                settings,
                messages
                + [
                    {
                        "role": "system",
                        "content": (
                            "Speak to the caller now in one short sentence. "
                            "Do not call any tool this turn."
                        ),
                    }
                ],
                include_tools=True,
            )
        except HTTPException:
            message = {}
        groq_call_ms.append((time.monotonic() - call_started) * 1000.0)
        assistant_text = str(message.get("content") or "").strip()
        if not assistant_text:
            assistant_text = "Thanks - noted."
            logger.warning(
                "text_turn call=%s: no speech after tool rounds; using fallback line",
                call.id,
            )

    # Pseudo tool calls: the model sometimes emits <tool_call> XML as text
    # instead of a real function call (seen live: the field was lost and raw
    # markup was saved to the transcript). Execute record_* ones with identical
    # semantics, then scrub all markup so it never ships to the UI.
    for pseudo in _parse_pseudo_tool_calls(assistant_text):
        if pseudo["name"] != "record_extracted_field":
            continue
        _result_text, field_record, _done_flag = _execute_text_tool(
            db, call, pseudo["name"], pseudo["arguments"], next_index, user_text
        )
        if field_record and "summary" not in field_record:
            extracted_now.append(field_record)
    assistant_text = _scrub_tool_markup(assistant_text)
    assistant_text = _cap_reply(assistant_text)

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
    if not settings.groq_api_key_list:
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
