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
import datetime
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
from app.models import Agent, AgentVersion, Call, ExtractedField, Organization, Transcript, User
from app.timeutil import utcnow
from app.services.telemetry import recorder as telemetry
from app.services.token_substitution import (
    apply_token_substitution,
    build_token_map,
    filled_context,
    resolve_spoken_name,
)
from app.services.usage import record_response as record_provider_response

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
# Groq's INPUT tokens-per-minute bucket is organization-wide, and the system
# prompt is re-sent on every single turn, so prompt size IS the throughput
# ceiling. 6 rows is still enough working context for this flow (the last three
# exchanges) and measurably cheaper than the 14 it replaced.
_MAX_HISTORY_ROWS = 6
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


def _display_card(contact: dict[str, str]) -> dict[str, str]:
    """Contact card with human names properly cased.

    The model copies names verbatim from the card, so a card carrying
    "ram"/"abhi" made the agent address the parent as "ram" for the whole
    call. Only name-ish keys are touched; values like "10-B" are untouched.
    """
    name_keys = {
        "student_name",
        "patient_name",
        "parent_name",
        "parent",
        "guardian",
        "contact_person",
        "contact_name",
        "customer_name",
        "full_name",
        "lead_name",
        "candidate_name",
        "name",
    }
    return {
        key: (_proper_name(value) if key in name_keys and value else value)
        for key, value in (contact or {}).items()
    }


#: Periods that do NOT end a sentence. Without masking, "with Dr. Rao" was
#: split after "Dr." and the caller heard a reply truncated mid-name.
_ABBREVIATIONS = (
    "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "St.", "No.", "Rs.", "Sr.", "Jr.",
    "vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.",
)


def _mask_abbreviations(text: str) -> tuple[str, list[str]]:
    originals: list[str] = []
    masked = text
    for abbr in _ABBREVIATIONS:
        def _replace(match: re.Match[str]) -> str:
            originals.append(match.group(0))
            return f"\x00{len(originals) - 1}\x00"

        masked = re.sub(re.escape(abbr), _replace, masked, flags=re.IGNORECASE)
    return masked, originals


def _sentence_words(sentence: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", sentence.lower()) if len(w) > 2}


def _dedupe_sentences(sentences: list[str]) -> list[str]:
    """Drop a sentence that says the same thing as one already kept.

    Live probe: "When do you expect Ananya to return to college? When do you
    think Ananya will be back at college?" - the caller hears the same
    question twice in one breath.
    """
    kept: list[str] = []
    for sentence in sentences:
        words = _sentence_words(sentence)
        repeated = any(
            words
            and (prev_words := _sentence_words(prev))
            and len(words & prev_words) / min(len(words), len(prev_words)) >= 0.6
            for prev in kept
        )
        if repeated:
            logger.info("reply sentence dropped as a repeat: %r", sentence[:60])
            continue
        kept.append(sentence)
    return kept


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
    masked, originals = _mask_abbreviations(cleaned)
    sentences = [
        s.strip()
        for s in re.findall(r"[^.?!]*[.?!]+|[^.?!]+$", masked)
        if s.strip()
    ]
    sentence_count = len(sentences)
    sentences = _dedupe_sentences(sentences)
    if len(sentences) <= max_sentences:
        if len(sentences) == sentence_count:
            return cleaned
        joined = " ".join(sentences)
        return re.sub(r"\x00(\d+)\x00", lambda m: originals[int(m.group(1))], joined)
    kept = " ".join(sentences[:max_sentences]).strip()
    kept = re.sub(r"\x00(\d+)\x00", lambda m: originals[int(m.group(1))], kept)
    logger.warning("reply capped to %d sentences (was %d)", max_sentences, len(sentences))
    return kept


#: Words a spoken line cannot END on. A completion that stops right after one
#: of these was cut off by the provider ("Thank you for that. Could you").
_PARTIAL_TAIL_WORDS = frozenset(
    {
        "and", "but", "or", "so", "because", "the", "a", "an", "to", "for",
        "of", "with", "that", "this", "these", "those", "your", "my", "our",
        "their", "his", "her", "its", "i", "we", "you", "they", "he", "she",
        "it", "is", "are", "was", "were", "will", "would", "can", "could",
        "should", "may", "might", "must", "please", "if", "when", "while",
    }
)


def _trim_partial_tail(text: str) -> str:
    """Drop a cut-off trailing fragment, keeping the complete sentences.

    Providers sometimes stop mid-clause ("Thank you for that. Could you"),
    and speaking that aloud is worse than saying less.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned or cleaned[-1] in ".!?":
        return cleaned
    if not re.search(r"[^.?!]+[.?!]", cleaned):
        return cleaned  # no complete sentence to fall back to
    tail = re.split(r"[.?!]", cleaned)[-1].strip(" ,;:")
    if not tail:
        return cleaned
    if tail.split()[-1].lower().strip("'\"") not in _PARTIAL_TAIL_WORDS:
        return cleaned
    complete = re.findall(r"[^.?!]+[.?!]", cleaned)
    return " ".join(part.strip() for part in complete).strip()


#: A reply that stops on a bare contraction ("You're", "I'll") was cut off by
#: the provider - no speaker ends a turn on one of these.
_TRUNCATED_REPLY_RE = re.compile(r"\b\w+'(?:re|s|m|ll|ve|d)$", re.IGNORECASE)


def _is_unusable_reply(text: str) -> bool:
    """True for dead-air completions: punctuation only, or a cut-off stub.

    Live probes produced a literal "..." and a bare "You're" as whole turns.
    Both would be spoken to the caller as nothing. Terse real replies ("Hi",
    "Sure") stay usable on purpose - they are the model's choice to make.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return True
    if not re.search(r"[^\W\d_]", cleaned, re.UNICODE):
        return True
    if cleaned[-1] in ".!?\"'”’":
        return False
    return bool(_TRUNCATED_REPLY_RE.search(cleaned)) and len(cleaned.split()) <= 3


def _backfill_grounded_fields(
    db: Session,
    call: Call,
    version: Any,
    user_text: str,
    extracted_now: list[dict[str, Any]],
    turn_index: int,
) -> int:
    """Deterministic safety net for extraction (never fabricates).

    The model's tool calling is probabilistic. gpt-oss-20b was so eager it
    emitted tool calls into tools-less requests (Groq 400), and
    qwen/qwen3.8-27b is the opposite: it skips ``record_extracted_field``
    entirely on some turns, so a plainly stated "sick" was never recorded and
    the call reported no fields at all. Leaving that to sampling is not
    acceptable, so for every REQUIRED field still unfilled we look for a
    CALLER sentence that literally matches the field.

    This is a PER-FIELD check, not a per-turn one. Gating it on "the model
    recorded nothing this turn" looked reasonable and was wrong: the turn
    where the parent said "2nd oct" also carried another recorded field, so
    the guard suppressed the safety net and the return date was lost anyway.

    Safety properties, all deliberate:
    - only the caller's own words from THIS turn are candidates
    - a real word overlap with the field name/description is required, or the
      field is date-typed and the sentence is itself date-shaped
    - the normal grounding check still runs, so a paraphrase is refused first
      and the two-strike rule still applies
    - a field the model already recorded is never touched

    Mirrors the voice worker's heuristic pass, so text and voice behave the
    same way.
    """
    text = str(user_text or "").strip()
    if not text:
        return 0
    schema = getattr(version, "extraction_schema", None)
    if not isinstance(schema, dict) or not schema:
        return 0
    # The agent's last line is the question the caller is answering. When it
    # names a field ("what was the reason for that rating?"), the caller's
    # answer belongs to that field even if it shares none of its words -
    # "the technician was late" is a reason and was being thrown away.
    agent_prompt = str(
        db.scalar(
            select(Transcript.text)
            .where(
                Transcript.call_id == call.id,
                Transcript.speaker == "agent",
            )
            .order_by(Transcript.turn_index.desc())
            .limit(1)
        )
        or ""
    ).lower()
    prompt_words = set(re.findall(r"[a-z0-9']+", agent_prompt))
    already = {
        row.field_name
        for row in db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call.id)
        ).all()
    }
    # Fields the model just recorded are already handled; never overwrite them.
    already |= {
        str(item.get("field_name")) for item in extracted_now if item.get("field_name")
    }
    captured = 0
    for field_name, spec in schema.items():
        if field_name in already:
            continue
        # REQUIRED fields, date-typed fields, and optional free text. The net
        # exists so an answer the caller plainly gave is never lost; inferring
        # optional boolean/flag fields from a sentence match produces low-value
        # data ("He is sick" stored as a boolean). Dates are the exception: a
        # stated site-visit or reschedule date is exactly what the call was for,
        # and the model routinely spoke it ("Friday would be the 30th") without
        # recording it.
        if not isinstance(spec, dict):
            continue
        is_required = str(spec.get("validation") or "").lower() == "required"
        field_type = str(spec.get("type") or "").lower()
        # Optional FREE-TEXT answers are included too: an optional reason or
        # comment is still the point of the call, and contextual matching
        # below decides whether the sentence answers this question.
        contextual_ok = not is_required and field_type in ("", "string")
        # A required SCORE is answerable in words ("three out of five") and
        # the agent's own question names it ("rate the service out of five").
        number_typed = field_type in ("number", "integer", "float") or any(
            hint in field_name.lower() for hint in ("rating", "score")
        )
        if (
            not is_required
            and "date" not in field_type
            and not contextual_ok
            and not number_typed
        ):
            continue
        description = str(spec.get("description") or "")
        time_typed = "time" in field_name.lower() or (
            field_type in ("", "string") and "time" in description.lower()
        )
        # A date-typed field has to be recoverable from short answers like
        # "2 oct" or "on the 5th", which contain none of the field's words -
        # word overlap alone missed exactly these, and the caller was clearly
        # answering the date question.
        cue_words = {
            w.lower()
            for w in re.split(r"[^a-z0-9]+", f"{field_name} {description}")
            if len(w) > 3
        }
        if not cue_words and "date" not in field_type:
            continue
        asked_about_field = bool(prompt_words & cue_words)
        for sentence in re.split(r"(?<=[.!?])\s+|,\s+", text):
            sentence = sentence.strip(" .")
            if not sentence:
                continue
            words = set(re.findall(r"[a-z0-9']+", sentence.lower()))
            date_shaped = "date" in field_type and bool(_DATE_LIKE_RE.search(sentence))
            # A TIME field can only be answered with a time. "It's a follow-up
            # for my BP check" was stored as reschedule_time purely because
            # the agent's previous line contained "time".
            if time_typed and not _TIME_LIKE_RE.search(sentence):
                continue
            # Never record a QUESTION as an answer. "So tell me how can I help
            # you?" overlapped needs_human_help's description and was stored as
            # the value - a question is the opposite of captured information.
            # A date is exempt: "can we reschedule to Friday?" is a request
            # the caller means, and dropping it lost the reschedule.
            if sentence.rstrip().endswith("?") and not date_shaped:
                continue
            if date_shaped:
                pass  # a date-shaped answer to a date field is self-evident
            elif len(words & cue_words) < 2:
                # Synonym escape hatch: a plain-spoken answer ("sick") shares
                # no words with reason_for_absence's cues but IS the answer.
                # One synonym hit upgrades a 0/1-overlap sentence to evidence.
                name_stems = {
                    w.lower()
                    for w in re.split(r"[^a-z0-9]+", field_name)
                    if len(w) > 3
                }
                synonyms = set()
                for stem in name_stems:
                    synonyms |= _FIELD_SYNONYMS.get(stem, frozenset())
                if not (synonyms and (words & synonyms)):
                    # One generic word ("college", "today") is not evidence. The
                    # single-word rule stored explanations as flag values.
                    # Contextual escape hatch: when the agent's own last line
                    # named this field, the caller's sentence IS the answer even
                    # if it shares none of the field's words ("the technician
                    # was late" answers "what was the reason for that rating?").
                    contextual = (
                        (
                            contextual_ok
                            or (number_typed and bool(_coerce_number(sentence)))
                        )
                        and asked_about_field
                        and len(words) >= 3
                        and not words <= _ACK_ONLY_WORDS
                    )
                    if not contextual:
                        continue
            value = sentence
            if time_typed:
                # Store the time itself, not the sentence around it:
                # "Saturday 11 am works" -> "11 am".
                clock = _TIME_LIKE_RE.search(sentence)
                if not clock:
                    continue
                value = clock.group(0).strip()
            if number_typed:
                coerced = _coerce_number(sentence)
                if not coerced:
                    continue
                value = coerced
            if "date" in field_type:
                # A date-typed field needs an actual date. "so she stayed home
                # today" is date-shaped but says nothing about when she is
                # back, and it was recorded as the return date. Unresolvable
                # sentences are left to the model (which was asked the date
                # question) instead of being stored as a wrong date.
                normalized = _normalize_explicit_date(sentence, utcnow().date())
                if not normalized:
                    continue
                # An OPTIONAL date needs at least one word tying the sentence
                # to its field ("this Saturday" alone could be any date).
                if not is_required and not (words & cue_words):
                    continue
                value = normalized
            result_text, field_record, _done = _execute_text_tool(
                db,
                call,
                "record_extracted_field",
                {"field_name": field_name, "value": value, "confidence": 0.7},
                turn_index,
                text,
            )
            if field_record and "summary" not in field_record:
                extracted_now.append(field_record)
                captured += 1
                logger.info(
                    "grounded backfill call=%s field=%s value=%r",
                    call.id,
                    field_name,
                    sentence,
                )
            break
    if captured:
        telemetry.record(
            "extraction_backfill",
            level="warn",
            message=f"recovered {captured} required field(s) from the caller's "
            "own words that the model did not record",
            call_id=call.id,
            fields=[f.get("field_name") for f in extracted_now],
        )
    return captured


#: Turns before this many transcript rows get the FULL instruction set. The
#: opening, the verification and the first real answer are where the rules
#: matter most, so they are spent on in full.
_FULL_PROMPT_ROWS = 3

#: Telugu models default to the literary (granthik) register they were trained
#: on: a live call said "గైర్హాజరు", "వైద్య ధృవపత్రం", "విచారిస్తున్నాను" and even
#: "ఆఫీస్" for a college - the caller answered "ardham kaledhu andi" and heard the
#: same textbook sentence again. One GOOD/BAD pair plus a word-for-word swap
#: list is what moves the output; "speak casually" alone does nothing.
_SPOKEN_TELUGU_FULL = (
    "SPOKEN TELUGU (hard rule): speak the everyday Telugu people use on the "
    "phone in Hyderabad/Andhra - never bookish or newsreader Telugu.\n"
    "GOOD: \"అర్థమైంది — fever వల్ల కాలేజీకి రాలేదు కదా. రేపు వస్తాడా?\"\n"
    "BAD (never say): \"జ్వరము నిమిత్తము విద్యాలయమునకు విరామము కలదని "
    "వివరము నమోదు చేయుచున్నాను.\"\n"
    "Say: \"కాలేజీకి రాలేదు / leave\" not \"గైర్హాజరు\"; \"డాక్టర్ సర్టిఫికెట్\" not "
    "\"వైద్య ధృవపత్రం\"; \"అడగడానికి కాల్ చేశా\" not \"విచారిస్తున్నాను\"; "
    "\"థాంక్స్\" not \"ధన్యవాదాలు\"; \"హాయ్\" not \"నమస్కారం\" (unless the caller says "
    "it first); \"బై\" not \"సెలవు\". Never call a college \"ఆఫీస్\" - it is "
    "\"కాలేజీ\". Keep the caller's English words in English (college, fever, "
    "doctor, certificate, leave, exam, bus). If they say \"అర్థం కాలేదు\", do not "
    "repeat the same sentence: say it again shorter and simpler.\n"
    "Ask: \"ఈరోజు ఎందుకు రాలేదు?\" not \"గైర్హాజరుకు కారణం తెలియజేయండి\"; "
    "\"ఎప్పుడు తిరిగి వస్తారు?\" not \"ఎప్పుడు హాజరుకావాలని భావిస్తున్నారు?\". "
    "Never start a sentence with \"దయచేసి\".\n"
    "EMPATHY: if the student is sick, sound concerned (\"అయ్యో, ఏమైంది? ఇప్పుడు "
    "ఎలా ఉన్నాడు?\") - never say \"అది బాగుంది\" / \"good\" about an illness."
)

_SPOKEN_TELUGU_COMPACT = (
    "Speak everyday phone Telugu, never bookish Telugu: \"అర్థమైంది — fever వల్ల "
    "కాలేజీకి రాలేదు కదా. రేపు వస్తాడా?\" Say కాలేజీకి రాలేదు (not గైర్హాజరు), "
    "డాక్టర్ సర్టిఫికెట్ (not వైద్య ధృవపత్రం), కాల్ చేశా (not విచారిస్తున్నాను), "
    "ఎప్పుడు తిరిగి వస్తారు (not హాజరుకావాలని), థాంక్స్, బై; never \"ఆఫీస్\" for "
    "college and no \"దయచేసి\"; keep English words in English. If they say "
    "\"అర్థం కాలేదు\", rephrase shorter - do not repeat the same sentence. If the "
    "student is sick, sound concerned (\"అయ్యో, ఏమైంది?\"), never \"అది బాగుంది\".\n"
)



def _render_compact_system_prompt(
    captured: list[str],
    remaining: list[str],
    today: str,
    agent_name: str = "",
    language: str = "en",
    derived: list[str] | None = None,
) -> str:
    """Short continuation prompt for mid/late turns.

    THE binding constraint is arithmetic, not vibes: Groq's ITPM is 7000 for
    this organization and the full system prompt is ~1100 tokens, so a
    conversation dies at roughly 4-5 turns no matter how many API keys are
    added (they share one org bucket). Since the system prompt is re-sent on
    EVERY request, the only way through is to stop re-sending it.

    The conversation history already carries the persona, the names, the
    disclosure and what has already been said, so after the opening turns the
    model only needs: who it is, today's date, which fields are done, and the
    three rules that must never be forgotten. That is ~200 tokens instead of
    ~1100 - roughly 4x the turns per minute for the same quality of reply.
    """
    state = (
        f"Already recorded: {', '.join(captured)}" if captured else "Nothing recorded yet."
    )
    todo = f"Still needed: {', '.join(remaining)}." if remaining else ""
    goodbye_example = (
        "'సరే, థాంక్స్. బై.'" if language == "te" else "'Thanks, Ram. Goodbye.'"
    )
    close_rule = (
        f" Everything is recorded: say ONE short goodbye (e.g. {goodbye_example}), "
        "call end_call(summary) in the SAME reply, and say nothing "
        "else - no questions, no acknowledgments, no further turns."
        if not remaining
        else ""
    )
    language_rule = {
        "te": _SPOKEN_TELUGU_COMPACT,
        "hi": "Speak Hindi, using the caller's own English words as they do.\n",
    }.get(language, "")
    # A disposition the AGENT decides is never a question for the caller.
    # Listing it under "still needed" made a live Telugu agent ask the mother
    # "what is the outcome of the call?".
    derived = derived or []
    derived_rule = (
        f" You decide {', '.join(derived)} yourself when you close - record a "
        "short label with record_extracted_field; never ask the caller for it."
        if derived
        else ""
    )
    return (
        f"TODAY: {today}.\n"
        f"You are {agent_name or 'the outbound phone agent'}, the same agent from "
        "earlier in this call; the person is already verified.\n"
        f"{language_rule}"
        "Reply in 1-2 short spoken sentences, one thing per reply: if you still "
        "need an answer, ask it and STOP - never ask and thank/close in the same "
        "reply. Always speak a complete sentence - never answer with a single "
        "word, a fragment, or punctuation only. Acknowledge what they said, then "
        "move on. Never invent a value: only record what the caller actually "
        "said, and never ask for something they already answered.\n"
        "Do NOT repeat yourself: no restating a value or confirmation you have "
        "already given, no re-confirming a date, no 'anything else?'. If they "
        "confirmed, ask the next missing thing or close politely.\n"
        f"{state} {todo}{close_rule}{derived_rule}\n"
        f"Record with record_extracted_field(field_name, value, confidence); "
        f"finish with end_call(summary). Fields you may ask about: "
        f"{', '.join(remaining) or 'none'}."
        + (
            f" Fields you decide yourself, never ask about: {', '.join(derived)}."
            if derived
            else ""
        )
    )


_OPENING_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "greet": "Hi {name}.",
        "intro_with_name": "Hi {name}, {who} here.",
        "intro": "{who} here.",
        "verify": "Am I speaking with {name}?",
        "unknown": "May I know who I'm speaking with?",
    },
    "te": {
        "greet": "హాయ్ {name} గారు.",
        "intro_with_name": "హాయ్ {name} గారు, నేను {who}.",
        "intro": "నేను {who} మాట్లాడుతున్నా.",
        "verify": "{name} గారు మాట్లాడుతున్నారా?",
        "unknown": "హలో, మీరు ఎవరు మాట్లాడుతున్నారు?",
    },
    "hi": {
        "greet": "नमस्ते {name} जी।",
        "intro_with_name": "नमस्ते {name} जी, मैं {who} बोल रही हूँ।",
        "intro": "मैं {who} बोल रही हूँ।",
        "verify": "क्या मैं {name} जी से बात कर रही हूँ?",
        "unknown": "क्या आप बता सकते हैं कि मैं किससे बात कर रही हूँ?",
    },
}


#: Providers occasionally return an empty completion (content stripped by a
#: safety filter, or a tool-only round). An empty reply is the caller hearing
#: dead air, so every empty turn is replaced with a short line in the agent's
#: own language; a closed call gets a goodbye instead of a question it will
#: never hear answered.
_EMPTY_REPLY_LINES: dict[str, tuple[str, str]] = {
    "en": (
        "Sorry, I didn't catch that - could you say that again?",
        "Thank you for your time. Goodbye.",
    ),
    "te": (
        "సారీ, అర్థం కాలేదు - మళ్లీ చెప్పండి?",
        "సరే, థాంక్స్ అండి. బై.",
    ),
    "hi": (
        "क्षमा कीजिए, समझ नहीं आया - फिर से बता सकते हैं?",
        "आपके समय के लिए धन्यवाद। नमस्ते।",
    ),
}

#: Used instead of the retry line when the caller's answer WAS recorded but
#: the model produced no speech. Asking them to repeat an answer we already
#: have is the worst of both worlds.
_ACK_LINES = {
    "en": "Got it, thank you.",
    "te": "సరే, థాంక్స్.",
    "hi": "ठीक है, धन्यवाद।",
}


def _empty_reply_line(version: AgentVersion, done: bool) -> str:
    retry, goodbye = _EMPTY_REPLY_LINES[_agent_language(version)]
    return goodbye if done else retry


def _agent_language(version: AgentVersion) -> str:
    """Language of the voice this version ships with (drives opener phrasing)."""
    settings = getattr(version, "voice_settings", None) or {}
    if isinstance(settings, dict):
        lang = str(settings.get("language") or "en").lower()
        if lang in _OPENING_PHRASES:
            return lang
    return "en"


def _build_short_opening(
    version: AgentVersion,
    contact: dict[str, Any],
    institution: str,
    agent_name: str = "",
) -> str:
    """Deterministic 2-sentence opening, built without an LLM round trip.

    Asking the model to write its own greeting produced three sentences with
    a duplicated identity ("this is an AI assistant from CMR ... Hi Ram, this
    is Priya from the front office") — long TTS, high chance the caller hangs
    up, and a full provider round trip of latency before the first word. The
    voice worker already builds this deterministically; text mode now matches
    it: short disclosure + name + ONE question.

    Each name is spoken exactly once, and the opening asks ONE thing: is this
    the right person. The reason for the call is deliberately NOT in the
    opener - the caller answers "yes", and only then does the agent say who it
    is calling about and why. Opening with "could you tell me the reason"
    skipped verification entirely, which is the wrong order for a cold call to
    a stranger's parent.
    """
    tokens = build_token_map(
        contact,
        institution,
        agent_name=agent_name,
        company_context=getattr(version, "company_context", None),
    )
    disclosure = apply_token_substitution(
        str(getattr(version, "disclosure_script", "") or ""), tokens
    ).strip()
    if not disclosure:
        return ""
    card = contact or {}
    # [Student Name] aliases any known name, so it is only a student-flow
    # signal when the card actually carries student_name.
    student = (
        _proper_name(tokens.get("[Student Name]", ""))
        if str(card.get("student_name") or "").strip()
        else ""
    )
    parent = _proper_name(tokens.get("[Parent/Guardian Name]", ""))
    # Clinic, real-estate and service agents have no parent/student card:
    # their lead field is the person answering, so use it instead of
    # falling through to "May I know who I'm speaking with?".
    subject = parent or student or _proper_name(
        tokens.get("[Patient Name]", "")
        or tokens.get("[Contact Name]", "")
        or tokens.get("[Customer Name]", "")
    )
    who = _proper_name(tokens.get("[Agent Name]", "")) or "an AI assistant"
    phrases = _OPENING_PHRASES[_agent_language(version)]
    # The same name for greeting and verification: the caller hears it once
    # when greeted and once when asked to confirm it. No pronoun/relationship
    # guess ("Are you Abhi's parent?") - that was wrong for every vertical
    # where the lead is the person answering, not a guardian.
    address = subject
    parts = [disclosure]
    # Identity is only re-introduced when it is genuinely new information;
    # the disclosure usually already named the caller and the college.
    if who.lower() not in disclosure.lower():
        parts.append(
            phrases["intro_with_name"].format(name=address, who=who)
            if address
            else phrases["intro"].format(who=who)
        )
    elif address:
        parts.append(phrases["greet"].format(name=address))
    # Verification only, one short question, in the agent's own language.
    parts.append(
        phrases["verify"].format(name=address) if address else phrases["unknown"]
    )
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


@router.get("/diagnostics")
def playground_diagnostics(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Everything the operator needs to verify a test run, in one call.

    Answers the questions that were previously only answerable by scrolling
    docker logs: which providers are configured, which one actually served the
    last turn, which fell back and why, and what the last events were.

    Never returns keys - only whether a key is present and which provider it
    belongs to.
    """
    settings: Settings = request.app.state.settings
    chain = settings.llm_chain
    return {
        "components": {
            "stt": {
                "name": "Deepgram",
                "configured": bool(settings.deepgram_api_key),
                "required_for": "voice input transcription",
            },
            "tts": {
                "name": "Cartesia",
                "configured": bool(settings.cartesia_api_key),
                "required_for": "voice output",
            },
            "rooms": {
                "name": "LiveKit",
                "configured": bool(
                    settings.livekit_api_key and settings.livekit_api_secret
                ),
                "url": settings.livekit_url,
                "required_for": "browser + worker room join",
            },
            "llm": {
                "name": f"{len(chain)} provider(s) armed",
                "configured": bool(chain),
                "required_for": "every reply",
            },
            "telephony": {
                "name": "Vobiz",
                "configured": bool(
                    settings.vobiz_auth_id and settings.vobiz_auth_token
                ),
                "required_for": "phone calls only (not the playground)",
            },
        },
        "llm_chain": [
            {
                "position": index + 1,
                "provider": name,
                "model": model,
                "key_present": bool(api_key),
                "reasoning_model": _is_reasoning_model(model),
                "output_cap": _max_tokens_for(model),
                "healthy": _last_provider_health(name),
            }
            for index, (name, base_url, api_key, model) in enumerate(chain)
        ],
        "events": telemetry.since(limit=120),
        "latest_seq": telemetry.latest_seq(),
    }


@router.get("/events")
def playground_events(
    since: int = 0,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Live event feed for the Diagnostics panel (polled while a session runs)."""
    events = telemetry.since(seq=since, limit=200)
    return {"events": events, "latest_seq": telemetry.latest_seq()}


@router.delete("/events")
def clear_playground_events(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    telemetry.clear()
    return {"ok": True, "latest_seq": telemetry.latest_seq()}


def _last_provider_health(provider: str) -> dict[str, Any]:
    """Most recent attempt for a provider, so the panel can show its state."""
    for event in reversed(telemetry.since(limit=200)):
        if event.get("provider") == provider and event.get("kind") == "llm_attempt":
            return {
                "status": event.get("status"),
                "latency_ms": event.get("latency_ms"),
                "at": event.get("at"),
                "ok": event.get("status") == 200,
            }
    return {"status": None, "latency_ms": None, "at": None, "ok": None}


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
    # Per-turn serving providers for the latency table. See _run_agent_turn,
    # which appends one entry per agent turn as the turn is served.
    served_by_map: dict[int, dict[str, str]] = {}
    if isinstance(call.context, dict):
        for entry in call.context.get("llm_turn_providers") or []:
            if isinstance(entry, dict) and isinstance(entry.get("turn"), int):
                served_by_map[entry["turn"]] = {
                    "provider": str(entry.get("provider") or ""),
                    "model": str(entry.get("model") or ""),
                }

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
                **({"served_by": served_by_map.get(t.turn_index)} if t.turn_index in served_by_map else {}),
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


_GENERIC_SUBJECT_KEYS = (
    "patient_name",
    "customer_name",
    "full_name",
    "contact_name",
    "lead_name",
    "candidate_name",
    "name",
)
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
            "- Say names out loud and greet by name. Known: "
            f"{', '.join(names)}. Never say 'the parent of the student' when you "
            "have a real name."
        )
    lines.append(
        "- VERIFY before details: if the person who answered is NOT "
        f"{parent or 'the named contact'}, share nothing, ask when they will be "
        "available, thank them, and end the call."
    )
    return "\n".join(lines)


def _render_text_system_prompt(
    config: Any,
    contact: Optional[dict[str, str]] = None,
    institution: str = "",
    agent_name: str = "",
    agent_role: str = "",
) -> str:
    """Slim server-side twin of voice-agent/app/prompting.render_system_prompt.

    Same section order and discipline (disclosure verbatim first, TTS-safe
    style rules so text replies behave like the spoken ones), but compact
    enough to keep text-mode token cost low. ``contact`` (P0-2) appends the
    CALLER CONTEXT block so the agent personalizes and verifies the
    relationship before sharing any details.
    """
    sections: list[str] = []

    # 0. Today's date. Without it the model cannot resolve "after 2 days" or
    # "next week" into a real date, so it either guessed or refused the value -
    # the missing expected_return_date in live tests. Cheap, and it is what
    # makes relative-date capture work.
    sections.append(
        "TODAY: " + utcnow().strftime("%A %d %B %Y") + ". Resolve relative "
        "answers against it ('after 2 days' = 2 days from today)."
    )

    card = _display_card(contact or {})
    tokens = build_token_map(
        card,
        institution=institution,
        agent_name=agent_name,
        company_context=getattr(config, "company_context", None),
    )

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
    identity = ""
    if agent_name and agent_name.lower() not in ("ai", "ai assistant", "an ai assistant"):
        identity = f"- Your name is {agent_name}"
        if agent_role:
            identity += f", {agent_role}"
        identity += (
            ". Answer to it naturally when the caller uses it; you are still an "
            "AI assistant and must say so if asked.\n"
        )
    sections.append(
        "WHO YOU ARE:\n"
        + identity
        + "- You are a friendly outbound phone agent. Every reply "
        "you type is read aloud by a speech engine exactly as written."
    )
    # 2b. Creator's role definition - authoritative, verbatim (not a bullet).
    if persona:
        sections.append(
            "ROLE & MISSION - defined by the agent creator (AUTHORITATIVE for "
            "who you are and what this call is about; the speaking and "
            "recording rules below still apply):\n" + persona
        )

    # 3. Company context.
    company_context = filled_context(config.company_context or {})
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
        "- NEVER ask for something the caller just told you, even if you have "
        "not recorded it yet: confirm it briefly and move to the next thing "
        "still missing.\n"
        "- Be a person, not a form: acknowledge what they just said in a few "
        "words, then ask the next thing. Vary your wording; never read the "
        "goals out in order like a questionnaire; never stack two questions.\n"
        "- If they hesitate or ask why, give one short reason it helps them, "
        "then ask again in different words. When you need a time, offer two "
        "concrete options. A busy caller gets the point fast.\n"
        "- NEVER repeat yourself: do not restate a value or a confirmation you "
        "have already given ('we'll note that...', 'we'll update...', 'I've "
        "updated...'), and do not ask 'anything else?' or re-confirm a date. If "
        "they confirmed, move on to what is still missing, or close the call.\n"
        "- Answer what they ACTUALLY said first. If you did not catch it, say "
        "so plainly and move on after one retry. Stay polite even if upset.\n"
        "- Once they confirm who they are, say in one short line who you are "
        "calling about, then ask the first thing you still need.\n"
        "- Write only words a person says aloud. NEVER include stage "
        "directions, notes, or cues in brackets or parentheses such as "
        "'(Waiting for response)' or '*laughs*'.\n"
        "- Match the caller's language: start in the disclosure's language, "
        "and if they speak another one or mix languages, follow them rather "
        "than insisting on yours.\n"
        "- You can only talk and record answers. You cannot send messages, "
        "email anyone, book with a colleague, or transfer the call. Never say "
        "you did any of those; say what will happen next instead."
    )
    if _agent_language(config) == "te":
        sections.append(_SPOKEN_TELUGU_FULL)

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
        "- Record silently: never tell the caller you are recording a field, "
        "that something still needs to be recorded, or which field is next.",
        "- One answer can fill several fields (a reason and a date): record "
        "everything that answer covers before asking anything new.\n"
        "- A yes/no field is what they said: 'yes, I'll be there' is true, "
        "'I can't come' is false. Record it in the same turn.\n"
        "- For a NUMBER field record only the number (3, not 'three out of "
        "five'). For call_outcome use a short label such as visit_booked, "
        "not_interested, callback_requested, confirmed, rescheduled, "
        "feedback_captured or resolved - never a sentence.\n"
        "- Fields marked YOU DECIDE are your own conclusion: fill them "
        "yourself from what the caller said. NEVER ask the caller about them.",
        "- NEVER invent a value. A value the caller never said does not exist - "
        "no guessed date, not even a likely one. Silences, greetings and "
        "off-topic answers contain no answers. If unsure, ask instead.",
        "- If a tool reply says NOT RECORDED but the caller DID just tell you "
        "the value, call the tool AGAIN with what they said - do not ask them "
        "to repeat themselves. Never re-ask a question they already answered.",
        "- Say goodbye ONCE, only when nothing is left to ask. NEVER call "
        "`end_call` while a REQUIRED field is still unanswered unless the "
        "caller says they cannot or will not answer it, and never put a "
        "goodbye in the same reply as a question.\n"
        "- FINISH with `end_call(summary)` once everything is captured (or "
        "they want to stop), including any unfilled required fields.",
        "- needs_human_help means ONLY an explicit request: the caller asks for "
        "a callback, asks to speak to a human/teacher/principal, or raises a "
        "complaint. An explanation, a confirmation, or any other sentence is "
        "NEVER needs_human_help, no matter which words it shares.",
        "Fields:",
    ]
    schema = config.extraction_schema or {}
    if isinstance(schema, dict):
        ordered = sorted(
            schema.items(),
            key=lambda kv: 0
            if isinstance(kv[1], dict)
            and str(kv[1].get("validation") or "").lower() == "required"
            else 1,
        )
        for field_name, spec in ordered:
            if isinstance(spec, dict):
                # The description is what tells the model WHEN to record the
                # field; the type and validation words are recoverable from the
                # name and the [REQUIRED] tag.
                description = str(spec.get("description") or spec.get("type") or "").strip()
                if field_name in _AGENT_DERIVED_FIELDS:
                    required_marker = " [YOU DECIDE - never ask the caller]"
                elif str(spec.get("validation") or "").lower() == "required":
                    required_marker = " [REQUIRED]"
                else:
                    required_marker = ""
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


def _provider_handoff_block(
    previous: Optional[tuple[str, str]],
    current: tuple[str, str],
    captured: list[Mapping[str, Any]],
    recent_turns: list[str],
) -> Optional[str]:
    """Context bridge for when failover moves the call to another model.

    A model swap mid-call is a context trap: the new model has none of the
    previous model's knowledge and tends to re-introduce itself, re-ask
    answered questions, or contradict an earlier answer. It cannot be fixed by
    prompt alone because the new provider genuinely does not know.

    So the handoff states explicitly: who was speaking before, everything
    already captured with values, and the last few utterances. Cheap (a few
    dozen tokens), and it is what makes failover invisible to the caller
    instead of a conversation restarting from zero.
    """
    if not previous:
        return None
    prev_name, prev_model = previous
    cur_name, cur_model = current
    if prev_name == cur_name and prev_model == cur_model:
        return None
    lines = [
        "CONTINUITY (you took over this call mid-conversation):",
        f"- The conversation was already in progress and was being handled by "
        f"{prev_name} ({prev_model}). You are now {cur_name} ({cur_model}). "
        "Do NOT introduce yourself again, do NOT re-disclose, and do NOT "
        "re-ask anything the caller already answered.",
    ]
    if captured:
        facts = "; ".join(
            f"{item.get('field_name')}={item.get('field_value')}" for item in captured
        )
        lines.append(f"- Already captured (established, do not re-ask): {facts}")
    if recent_turns:
        lines.append(
            "- Recent exchanges: " + " | ".join(recent_turns[-4:])
        )
    lines.append(
        "- Continue naturally from here as if you had been on the call the whole time."
    )
    return "\n".join(lines)


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

#: When the whole chain is rate limited, wait this long and try the identical
#: request once. The org token bucket refills continuously, so this converts a
#: user-visible silence into a slightly slower reply instead of making the
#: caller repeat themselves.
_QUOTA_RETRY_WAIT_MS = 2500
_DEFAULT_MAX_TOKENS = 250
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


def _is_hard_quota_exhausted(text: str) -> bool:
    """True for a *quota* (plan/billing) rejection, not a rate limit.

    Gemini answers "You exceeded your current quota, please check your plan and
    billing details". Retrying that three times with backoff just burns three
    round trips (~1.5s of the caller's life) for a certainty. A per-minute rate
    limit is worth retrying; an exhausted plan is not. DeepSeek answers 402
    "Insufficient Balance" on an empty account - same shape, same treatment.
    """
    lowered = str(text or "").lower()
    return "current quota" in lowered or "check your plan" in lowered or "billing" in lowered or "insufficient balance" in lowered


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


def _short_error(text: str, limit: int = 220) -> str:
    """One-line provider error, trimmed to what is actually useful in a panel."""
    collapsed = " ".join(str(text or "").split())
    return collapsed[:limit]


_CLOSING_PHRASES = (
    "goodbye",
    "good bye",
    "have a good day",
    "have a great day",
    "have a great",
    "thank you for your time",
    "thanks for your time",
    "take care",
    "talk to you later",
)

#: Farewells in the other agent languages. Without these a Telugu goodbye
#: ("థాంక్స్, బై") never counted as one, so the call stayed open and the next
#: caller turn produced yet another goodbye - the mirror of the English bug
#: this list originally fixed. Word-bounded so "బైక్" (bike) never matches.
_TE_FAREWELL_RE = re.compile(r"(?<![\w])బై(?![\w])|సెలవు")
_HI_FAREWELL_RE = re.compile(r"अलविदा|फिर मिलेंगे")
_THANKS_WORDS = ("thank", "thanks", "థాంక్స్", "ధన్యవాదాలు", "धन्यवाद")


#: Dispositions the agent concludes from the conversation - never a question
#: it can ask the caller. Waiting for one to be "recorded" before a goodbye
#: left text sessions open forever: the model spoke its farewell, the caller
#: answered "yeah", and it replied with another micro-goodbye ("Great.
#: Thanks", "Thanks", "Is there", "I") because nothing marked the call done.
_AGENT_DERIVED_FIELDS = frozenset(
    {"call_outcome", "escalation_needed", "needs_human_help"}
)


def _is_closing_line(text: str) -> bool:
    """True when the reply is a farewell with no question or new content."""
    lowered = str(text or "").strip().lower()
    if not lowered or "?" in lowered:
        return False
    if any(phrase in lowered for phrase in _CLOSING_PHRASES):
        return True
    if _TE_FAREWELL_RE.search(lowered) or _HI_FAREWELL_RE.search(lowered):
        return True
    # A bare short thanks ("Thanks", "Thank you, Ram.", "థాంక్స్") is also a
    # farewell - the live transcript showed the call drifting through four
    # goodbye turns because "Thanks" alone was never recognized as the close.
    # Length-gated so a mid-call "Thanks, Ram. Abhi was absent..." can never
    # match.
    words = lowered.split()
    if len(words) <= 4 and any(w in lowered for w in _THANKS_WORDS):
        return True
    return False


def _is_explicit_farewell(text: str) -> bool:
    """A farewell the model clearly meant, not an acknowledgment.

    "Thanks" is ambiguous (it just recorded a field), so it may only close a
    call once the closing dispositions are recorded. "Goodbye", "bye" or
    "have a great day" are unambiguous and may close regardless.
    """
    lowered = str(text or "").strip().lower()
    if not lowered or "?" in lowered:
        return False
    if any(phrase in lowered for phrase in _CLOSING_PHRASES):
        return True
    if re.search(r"\bbye\b", lowered):
        return True
    return bool(_TE_FAREWELL_RE.search(lowered) or _HI_FAREWELL_RE.search(lowered))


#: The caller saying "nothing more" ends the call. Waiting for the model to
#: agree cost real turns: a mangled reply ("You're", "సర") never matched a
#: farewell, so the facts were collected and the session still hung open.
_CALLER_DONE_PHRASES = (
    "that's all",
    "thats all",
    "that is all",
    "that's it",
    "thats it",
    "nothing else",
    "no that's it",
    "no thanks",
    "no thank you",
    "we're good",
    "we are good",
    "don't need anything",
    "do not need anything",
    "not needed",
    "అంతే",
    "ఏమీ లేదు",
    "వేరే ఏమీ",
    "సరిపోతుంది",
    "कुछ नहीं",
    "बस इतना",
)


def _caller_is_finished(text: str) -> bool:
    """True when the caller has said there is nothing more to discuss."""
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(phrase in lowered for phrase in _CALLER_DONE_PHRASES)


def _caller_asked_question(text: str) -> bool:
    """The caller is waiting for an answer, so the call cannot close."""
    return "?" in str(text or "")


def _caller_is_acknowledging(text: str) -> bool:
    """A short yes/no/thanks - nothing left to "repeat back"."""
    lowered = str(text or "").strip().lower()
    words = re.findall(r"[a-z']+", lowered)
    if not words or len(words) > 10:
        return False
    if "thank" in lowered:
        return True
    return any(w in {"yes", "yeah", "yep", "no", "nope", "okay", "ok", "sure"} for w in words)


def _question_targets(
    text: str, schema: Mapping[str, Any], names: list[str]
) -> set[str]:
    """Which of ``names`` the question is about (one shared content word)."""
    words = set(re.findall(r"[a-z0-9']+", str(text or "").lower()))
    hits: set[str] = set()
    for name in names:
        spec = schema.get(name) if isinstance(schema.get(name), dict) else {}
        cues = {
            w
            for w in re.split(
                r"[^a-z0-9]+", f"{name} {spec.get('description') or ''}"
            )
            if len(w) > 3
        }
        if words & cues:
            hits.add(name)
    return hits


def _fields_known(
    db: Session, call: Call, required: list[str], extracted_now: list[dict[str, Any]]
) -> list[bool]:
    """Which required fields are known (DB plus this turn's records)."""
    known = {
        row.field_name
        for row in db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call.id)
        ).all()
    }
    known |= {str(item.get("field_name")) for item in extracted_now if item.get("field_name")}
    return [name in known for name in required]


def _refusal_text(reason: str, field_name: str) -> str:
    """Tool rejection the model will not turn into a story.

    The raw reason ("value ... was never stated by the caller") was read by the
    model as a confession and it told the parent "I'm sorry, I made a mistake
    earlier - I mentioned a return date you never gave me" after the caller HAD
    given one. That is a hallucination caused by our own tool text, so the
    message is now explicit that this is an internal bookkeeping rejection and
    must never be narrated to the caller.
    """
    return (
        f"NOT RECORDED: {reason} This is an internal note only. Do NOT tell the "
        f"caller you made a mistake and do NOT mention recording, extraction or "
        f"any date you have not just heard them say. If they already told you "
        f"'{field_name}', call this tool again with exactly what they said; "
        f"otherwise ask once more."
    )


def _message_or_raise(response: Any, served_by: Optional[tuple[str, str]] = None) -> dict[str, Any]:
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
    # Record which member actually served, so the NEXT turn can inject a
    # continuity brief if failover moves to a different provider/model. It must
    # land ON the message we return, not on the envelope.
    if served_by is not None:
        try:
            payload["__served_by__"] = {"provider": served_by[0], "model": served_by[1]}
        except TypeError:
            pass
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
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Unexpected response from the language model.",
        ) from exc
    served = payload.pop("__served_by__", None)
    if served:
        try:
            message["served_by"] = served
        except TypeError:
            pass
    return message


#: Providers proven plan/billing-exhausted, per call. _groq_chat is invoked
#: fresh every turn, so a function-local set cannot skip anything: a
#: zero-balance DeepSeek would 402 identically on every turn (~3s burned per
#: turn to re-learn it). Keyed by call_id with a TTL so ended calls stop
#: occupying memory; single-process backend, so module state is sufficient.
_EXHAUSTED_PROVIDERS: dict[int, tuple[float, set[str]]] = {}
_EXHAUSTED_TTL_S = 2 * 3600


def _record_llm_response(name: str, api_key: str, model: str, response: Any) -> None:
    """Persist rate-limit headers from one LLM attempt (never raises)."""
    provider = "groq" if str(name).startswith("groq") else str(name)
    try:
        record_provider_response(
            response,
            provider=provider,
            api_key=api_key,
            model=model,
        )
    except Exception:  # noqa: BLE001 - usage must never break a chat turn
        logger.debug("provider usage capture failed", exc_info=True)


def _session_exhausted(call_id: Optional[int]) -> set[str]:
    """Live set of providers to skip for this call (mutate to record more)."""
    if call_id is None:
        return set()
    now = time.monotonic()
    stale = [cid for cid, (stamp, _) in _EXHAUSTED_PROVIDERS.items() if now - stamp > _EXHAUSTED_TTL_S]
    for cid in stale:
        del _EXHAUSTED_PROVIDERS[cid]
    entry = _EXHAUSTED_PROVIDERS.get(call_id)
    if entry is None:
        entry = (now, set())
        _EXHAUSTED_PROVIDERS[call_id] = entry
    return entry[1]


async def _groq_chat(
    settings: Settings,
    messages: list[dict[str, Any]],
    include_tools: bool = True,
    call_id: Optional[int] = None,
    wait_before_retry_ms: int = _QUOTA_RETRY_WAIT_MS,
    previous_provider: Optional[tuple[str, str]] = None,
    captured: Optional[list[Mapping[str, Any]]] = None,
    recent_turns: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Chat-completions round trip over the configured provider chain.

    Members are tried in owner order (explicit LLM_FALLBACK_CHAIN entries,
    DeepSeek, Groq keys, then the remaining shorthands). Within a member, 429
    gets a short bounded backoff; a member that stays rate-limited or errors
    is abandoned and the identical request moves to the next provider. This is
    what stops the agent going silent after 4-6 turns on a single free-tier
    key — the caller only sees an error when the ENTIRE chain is exhausted.
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
    # Session-persistent: a provider proven billing-dead stays skipped for the
    # rest of THIS call, not just this turn (see _session_exhausted).
    exhausted_providers = _session_exhausted(call_id)
    # Operators watch this in the playground Diagnostics panel to see WHICH
    # provider served the turn and WHY it moved on, live.
    telemetry.record(
        "llm_chain_start",
        message=f"{len(members)} member(s) in chain: "
        + ", ".join(f"{n}:{m}" for n, _u, _k, m in members),
        call_id=call_id,
        include_tools=include_tools,
    )
    async with httpx.AsyncClient(timeout=45.0) as client:
        for member_index, (name, base_url, api_key, model) in enumerate(members):
            if name in exhausted_providers:
                telemetry.record(
                    "llm_skip",
                    level="warn",
                    provider=name,
                    model=model,
                    message="skipped: provider's shared token bucket is exhausted",
                    call_id=call_id,
                )
                continue
            member_body = _member_body(body, model)
            # If this is not the provider that served the previous turn, tell
            # the new model what it is taking over (see _provider_handoff_block).
            handoff = _provider_handoff_block(
                previous_provider, (name, model), captured or [], recent_turns or []
            )
            if handoff:
                member_body["messages"] = [
                    {"role": "system", "content": handoff},
                    *member_body["messages"],
                ]
                telemetry.record(
                    "llm_handoff",
                    level="warn",
                    provider=name,
                    model=model,
                    message=f"taking over mid-call from "
                    f"{previous_provider[0] if previous_provider else '?'}; "
                    "continuity brief injected",
                    call_id=call_id,
                )
            headers = {"Authorization": f"Bearer {api_key}"}
            if name == "openrouter":
                headers["HTTP-Referer"] = "https://echosarathi.local"
                headers["X-Title"] = "EchoSarathi"
            response = None
            for attempt in range(_GROQ_MAX_RETRIES + 1):
                attempt_started = time.monotonic()
                try:
                    response = await client.post(
                        f"{base_url.rstrip('/')}/chat/completions",
                        json=member_body,
                        headers=headers,
                    )
                    # Groq reports quota only in response headers; persist them
                    # so the dashboard can show which key dies first. Never
                    # raises, never blocks the turn.
                    _record_llm_response(name, api_key, model, response)
                    telemetry.record(
                        "llm_attempt",
                        level="info" if response.status_code == 200 else "warn",
                        provider=name,
                        model=model,
                        status=response.status_code,
                        latency_ms=round((time.monotonic() - attempt_started) * 1000),
                        message=(
                            "served the turn"
                            if response.status_code == 200
                            else _short_error(response.text)
                        ),
                        call_id=call_id,
                        attempt=attempt + 1,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    # Network-level failure: a different provider is the fix,
                    # not another retry of the same dead endpoint.
                    last_error_text = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "LLM provider %s transport failure: %s", name, last_error_text
                    )
                    telemetry.record(
                        "llm_attempt",
                        level="error",
                        provider=name,
                        model=model,
                        latency_ms=round((time.monotonic() - attempt_started) * 1000),
                        message=f"transport failure: {type(exc).__name__}",
                        call_id=call_id,
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
                    telemetry.record(
                        "llm_tool_conflict",
                        level="warn",
                        provider=name,
                        model=model,
                        status=response.status_code,
                        message="model emitted a tool call with tools disabled; "
                        "retrying once with tool history stripped",
                        call_id=call_id,
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
                    _record_llm_response(name, api_key, model, response)
                    if response.status_code == 200:
                        return _message_or_raise(response, served_by=(name, model))
                # Hard-quota FIRST, on ANY status: a DeepSeek 402 ("Insufficient
                # Balance") used to hit the `!= 429` break below and never reach
                # classification, so it was retried every turn. Gemini's quota
                # 429 also matches the shared markers ("requests per minute"),
                # so checking hard first fixes its misclassification too.
                if _is_hard_quota_exhausted(getattr(response, "text", "")):
                    # Plan/quota exhausted: retrying cannot help. Skip the whole
                    # provider for the rest of the SESSION, not just this turn:
                    # a zero-balance DeepSeek 402s identically on every turn,
                    # and paying ~3s per turn to re-learn that would wreck a
                    # call's latency for zero information.
                    exhausted_providers.add(name)
                    telemetry.record(
                        "llm_quota_exhausted",
                        level="error",
                        provider=name,
                        model=model,
                        status=response.status_code,
                        message="provider quota/plan exhausted; not retrying",
                        call_id=call_id,
                    )
                    break
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
                    telemetry.record(
                        "llm_quota_shared",
                        level="warn",
                        provider=name,
                        model=model,
                        status=429,
                        message="organization token bucket exhausted; this "
                        "provider's remaining keys are skipped (they share it)",
                        call_id=call_id,
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
                message = _message_or_raise(response, served_by=(name, model))
                content = str(message.get("content") or "")
                if message.get("tool_calls") or not _is_unusable_reply(content):
                    return message
                # A 200 carrying no usable words and no tool call is not a
                # reply: the caller would hear dead air. That covers an empty
                # body, a punctuation-only "..." and a one-word stub ("You're")
                # cut off by the provider, so the request moves to the next
                # member instead of being spoken.
                last_error_text = (
                    "empty completion (no content, no tool calls)"
                    if not content.strip()
                    else f"unusable completion: {content.strip()[:40]!r}"
                )
                logger.warning(
                    "LLM %s returned %s; trying the next member",
                    name,
                    last_error_text,
                )
                telemetry.record(
                    "llm_empty_completion",
                    level="warn",
                    provider=name,
                    model=model,
                    status=200,
                    message=f"{last_error_text}; moving to the next provider",
                    call_id=call_id,
                )
                continue
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
        # The org bucket refills continuously (7000 tokens/min). One short wait
        # and a single retry turns a hard "no response" into a slightly slower
        # reply, which is what the caller actually experiences: they speak once
        # and the agent answers. Without this they had to shout two or three
        # times to get past the rate limit.
        if wait_before_retry_ms > 0:
            telemetry.record(
                "llm_quota_wait",
                level="warn",
                message=f"every provider is rate limited; waiting "
                f"{wait_before_retry_ms}ms and retrying once",
                call_id=call_id,
            )
            logger.warning(
                "LLM chain rate limited; waiting %sms then retrying once",
                wait_before_retry_ms,
            )
            await asyncio.sleep(wait_before_retry_ms / 1000.0)
            # The continuity brief must survive the wait: without
            # previous_provider/captured/recent_turns the retry can restart
            # the conversation (re-introduce/re-ask) after failover moved it.
            return await _groq_chat(
                settings,
                messages,
                include_tools=include_tools,
                call_id=call_id,
                wait_before_retry_ms=0,
                previous_provider=previous_provider,
                captured=captured,
                recent_turns=recent_turns,
            )
        telemetry.record(
            "llm_chain_exhausted",
            level="error",
            message="every provider in the chain is rate limited (after one retry)",
            call_id=call_id,
            last_error=last_error_text[:200],
        )
        raise HTTPException(
            status_code=429,
            detail="The AI service rate limit was hit. Wait a few seconds and send again.",
        )
    logger.error("LLM chain exhausted. Last error: %s", last_error_text)
    telemetry.record(
        "llm_chain_exhausted",
        level="error",
        message="every provider in the chain failed; caller sees 502",
        call_id=call_id,
        last_error=last_error_text[:200],
    )
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
#: Field-name stems whose plain-spoken answers share NO words with the field
#: name or description. "Sick" answers reason_for_absence, but neither
#: "reason" nor "absence" appears in "he is feeling sick today", so the
#: 2-word overlap rule silently drops the exact case the backstop exists for.
#: A synonym hit counts as one overlap word (still needs the sentence to be
#: an answer, never a question - enforced at the call site).
_FIELD_SYNONYMS: dict[str, frozenset[str]] = {
    "reason": frozenset({"sick", "ill", "illness", "fever", "feverish", "unwell", "leave", "absent", "absence"}),
    "absence": frozenset({"sick", "ill", "illness", "fever", "feverish", "unwell", "leave", "absent", "absence"}),
    "absent": frozenset({"sick", "ill", "illness", "fever", "feverish", "unwell", "leave", "absent", "absence"}),
    "sick": frozenset({"sick", "ill", "illness", "fever", "feverish", "unwell", "leave", "absent", "absence"}),
    "leave": frozenset({"sick", "ill", "illness", "fever", "feverish", "unwell", "leave", "absent", "absence"}),
}
# "Yes please" after "what was the reason?" answers the question but carries
# no reason; only acknowledgements are refused as a contextual answer.
_ACK_ONLY_WORDS = frozenset(
    {
        "yes", "yeah", "yep", "no", "nope", "okay", "ok", "sure", "thanks",
        "thank", "you", "please", "fine", "good", "right", "correct", "alright",
    }
)
# A value counts as a resolved date (exempt from word-overlap grounding)
# when it names an actual day: digits ("30", "2026-09-30"), month names, or
# weekday/today/tomorrow tokens. Bare spans like "next week" or "one month"
# are NOT dates — that vagueness is exactly the fabrication shape.
_DATE_LIKE_RE = re.compile(
    r"\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|today|tomorrow|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"ఇవాళ|ఈరోజు|రేపు|సోమవారం|మంగళవారం|బుధవారం|గురువారం|శుక్రవారం|శనివారం|ఆదివారం",
    re.IGNORECASE,
)

#: A value that names a time of day, for time-typed fields.
_TIME_LIKE_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)\b|\b\d{1,2}\s*o'?clock\b|"
    r"morning|afternoon|evening|noon|midday|half past|quarter past|"
    r"ఉదయం|మధ్యాహ్నం|సాయంత్రం|రాత్రి",
    re.IGNORECASE,
)

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_ABBR = {
    abbr: number
    for name, number in _MONTHS.items()
    for abbr in {name[:3], name}
}
_EXPLICIT_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b",
    re.IGNORECASE,
)
_RELATIVE_DAYS_RE = re.compile(
    r"\b(?:after|in|within|next)\s+(\d{1,3})\s+days?\b|\b(\d{1,3})\s+days?\s+(?:later|from\s+now|hence)\b",
    re.IGNORECASE,
)
_TOMORROW_RE = re.compile(r"\btomorrow\b|\btmrw\b|రేపు", re.IGNORECASE)
_WEEKDAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|(సోమవారం|మంగళవారం|బుధవారం|గురువారం|శుక్రవారం|శనివారం|ఆదివారం)",
    re.IGNORECASE,
)
_WEEKDAY_NUMBERS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "సోమవారం": 0,
    "మంగళవారం": 1,
    "బుధవారం": 2,
    "గురువారం": 3,
    "శుక్రవారం": 4,
    "శనివారం": 5,
    "ఆదివారం": 6,
}
#: Date-shaped cue on the CALLER's side. Deliberately stricter than
#: _DATE_LIKE_RE (which matches any digit): caller_text spans the WHOLE call,
#: so a bare digit anywhere ("10-B", "class 5", a phone fragment) used to
#: exempt every later invented date. A cue must look like an actual date:
#: explicit day-month, day count, tomorrow/today, weekday, or ISO form.
_CALLER_DATE_CUE_RE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s*(?:of\s+)?(?:january|february|march|april|may|"
    r"june|july|august|september|october|november|december|jan|feb|mar|apr|jun|"
    r"jul|aug|sep|sept|oct|nov|dec)\b"
    r"|\b(?:after|in|within|next)\s+\d{1,3}\s+days?\b"
    r"|\b\d{1,3}\s+days?\s+(?:later|from\s+now|hence)\b"
    r"|\btomorrow\b|\btmrw\b|\btoday\b|రేపు|ఇవాళ|ఈరోజు"
    r"|\bmonday\b|\btuesday\b|\bwednesday\b|\bthursday\b|\bfriday\b|\bsaturday\b|\bsunday\b"
    r"|సోమవారం|మంగళవారం|బుధవారం|గురువారం|శుక్రవారం|శనివారం|ఆదివారం"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)


def _field_schema_type(db: Session, call: Call, field_name: str) -> str:
    try:
        version = (
            db.get(AgentVersion, call.agent_version_id)
            if call.agent_version_id
            else None
        )
        spec = (getattr(version, "extraction_schema", None) or {}).get(str(field_name))
        if isinstance(spec, dict):
            return str(spec.get("type") or "").lower()
    except Exception:  # noqa: BLE001 — normalization is best-effort
        pass
    return ""


def _field_is_date_typed(db: Session, call: Call, field_name: str) -> bool:
    """True when the field is date-typed by schema OR by name.

    Both writers (model tool calls and the deterministic backstop) must agree
    on what "date-typed" means, or the same field stores raw phrases from one
    path and ISO dates from the other. Schema type wins; the name fallback
    covers configs whose schema omits explicit types.
    """
    return _field_schema_type(db, call, field_name) == "date" or "date" in str(
        field_name
    ).lower()


def _field_is_number_typed(db: Session, call: Call, field_name: str) -> bool:
    return _field_schema_type(db, call, field_name) in ("number", "integer", "float")


_WORD_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "half": 0.5,
}


def _coerce_number(value: str) -> Optional[str]:
    """Store a number as a number: "three out of five" -> "3".

    The model was told to quote the caller's words, so a numeric field held
    "three out of five" and every export showed a sentence where a score was
    expected. The first number mentioned (digit or word) is the value.
    """
    text = str(value or "").strip().lower()
    if not text:
        return None
    digit = re.search(r"\d+(?:\.\d+)?", text)
    word_match: Optional[tuple[int, str]] = None
    for word in _WORD_NUMBERS:
        found = re.search(rf"\b{word}\b", text)
        if found and (word_match is None or found.start() < word_match[0]):
            word_match = (found.start(), word)
    if digit and (word_match is None or digit.start() < word_match[0]):
        return digit.group(0)
    if word_match is not None:
        number = _WORD_NUMBERS[word_match[1]]
        return str(int(number)) if float(number).is_integer() else str(number)
    return None


def _normalize_explicit_date(answer: str, today: "datetime.date") -> Optional[str]:
    """Turn a stated date into ISO form ("2nd oct" -> 2026-10-02).

    The agent was storing the raw phrase ("2nd oct", "after 2 days") while
    speaking a resolved date - the export and the speech disagreed. Two shapes
    are resolved deterministically against TODAY (which is known, not guessed):
    an explicit day+month (year = this year, or next year when passed), an
    explicit day count ("after/in N days", "tomorrow"), and a weekday name
    ("back on Monday" -> next Monday). Anything vaguer ("soon", "next week",
    "in a few days") is returned unchanged for the model, because picking a
    day from those IS guessing.
    """
    text = str(answer or "")
    match = _EXPLICIT_DAY_MONTH_RE.search(text)
    if match:
        day = int(match.group(1))
        month = _MONTH_ABBR[str(match.group(2)).lower()[:3] if len(str(match.group(2))) > 3 else str(match.group(2)).lower()]
        try:
            candidate = today.replace(year=today.year, month=month, day=day)
        except ValueError:
            return None  # "31st of feb" - leave it alone rather than invent one
        if candidate < today:
            try:
                candidate = candidate.replace(year=today.year + 1)
            except ValueError:
                return None
        return candidate.isoformat()
    relative = _RELATIVE_DAYS_RE.search(text)
    if relative:
        days = int(relative.group(1) or relative.group(2) or 0)
        if 1 <= days <= 60:
            return (today + datetime.timedelta(days=days)).isoformat()
        return None
    # "I can't come tomorrow, can we reschedule to Friday?" is a request for
    # FRIDAY; reading the negated "tomorrow" as the answer booked the wrong
    # day. A negated tomorrow is not a date the caller wants.
    negated_tomorrow = re.search(
        r"\b(?:can'?t|cannot|can not|won'?t|not)\b[^.]{0,25}\btomorrow\b",
        text,
        re.IGNORECASE,
    )
    if _TOMORROW_RE.search(text) and not negated_tomorrow:
        return (today + datetime.timedelta(days=1)).isoformat()
    weekday = _WEEKDAY_RE.search(text)
    if weekday:
        # "back on Monday" means the NEXT Monday; today's weekday maps to +7
        # so a bare weekday never resolves to the past.
        name = (weekday.group(1) or weekday.group(2) or "").lower()
        target = _WEEKDAY_NUMBERS[name]
        days_ahead = (target - today.weekday()) % 7 or 7
        return (today + datetime.timedelta(days=days_ahead)).isoformat()
    return None


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
        # invention, so the exemption requires a date-shaped cue on their
        # side - a bare digit ("10-B", "class 5") is NOT a date.
        if _CALLER_DATE_CUE_RE.search(caller_text):
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
                    _refusal_text(ground_reason, field_name),
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
        stored_value = None if value is None else str(value)
        # Normalize date-typed fields at write time so the export agrees with
        # what was spoken, no matter which path recorded it (model tool call
        # or deterministic backstop). Only resolvable shapes change. Keyed on
        # the SCHEMA type, not the field name: a date-typed field whose name
        # lacks "date" (e.g. expected_return) must normalize identically on
        # both writers, or the two paths store different shapes.
        if stored_value and _field_is_date_typed(db, call, field_name):
            normalized = _normalize_explicit_date(stored_value, utcnow().date())
            if normalized:
                stored_value = normalized
        elif stored_value and _field_is_number_typed(db, call, field_name):
            coerced = _coerce_number(stored_value)
            if coerced is not None:
                stored_value = coerced
        db.add(
            ExtractedField(
                call_id=call.id,
                field_name=field_name,
                field_value=stored_value,
                confidence=conf,
                source_turn_index=source_turn_index,
            )
        )
        # Mirror the DB write: the API response and the stored row must not
        # disagree about the value ("tomorrow" in JSON, an ISO date in the
        # export would be a real bug for anyone scripting the API).
        reported = None if value is None else str(value)
        if reported and _field_is_date_typed(db, call, field_name):
            normalized = _normalize_explicit_date(reported, utcnow().date())
            if normalized:
                reported = normalized
        elif reported and _field_is_number_typed(db, call, field_name):
            coerced = _coerce_number(reported)
            if coerced is not None:
                reported = coerced
        recorded = {
            "field_name": field_name,
            "field_value": reported,
            "confidence": conf,
        }
        return f"recorded {field_name}", recorded, False

    if name == "end_call":
        summary = str(arguments.get("summary") or "").strip() or None
        if not summary:
            # A call whose answers were all recorded still exported a blank
            # outcome because the model's end_call carried no summary. Build
            # one from what is actually stored.
            rows = db.scalars(
                select(ExtractedField).where(ExtractedField.call_id == call.id)
            ).all()
            if rows:
                summary = "; ".join(
                    f"{row.field_name}={row.field_value}" for row in rows
                )
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
# DeepSeek's own pseudo-call markup (<｜DSML｜function_calls> ...). It was read
# aloud as "less than DSML calls invoke name..." on a live turn. Whatever
# follows the marker is tool arguments, not speech - including the truncated
# case where the provider cut the tag mid-attribute, hence the "$" branch.
_DSML_BLOCK_RE = re.compile(
    r"</?[｜|]DSML[｜|].*?(?:</[｜|]DSML[｜|][^>]*>|$)", re.DOTALL | re.IGNORECASE
)
#: Reasoning wrappers that qwen/gpt-oss sometimes stream as CONTENT. A live
#: Telugu text call shipped the whole reply as "<think> The caller is saying
#: 'ardham kaledhu andi' ..." - the caller saw the model thinking, not an
#: answer. Well-formed blocks go first; an unclosed opener swallows the rest
#: because everything after it is reasoning, never speech.
_THINK_BLOCK_RE = re.compile(
    r"<think(?:ing)?>.*?</think(?:ing)?>|<think(?:ing)?>[^<]*$|</think(?:ing)?>",
    re.DOTALL | re.IGNORECASE,
)


#: Inline pseudo-calls written as prose instead of a function call: a live
#: turn shipped "record_extracted_field(expected_return_date, repu, high);
#: end_call(Call completed successfully)." straight into the spoken reply.
_PSEUDO_CALL_RE = re.compile(
    r"\b(?:record_extracted_field|end_call|escalate_to_human|transfer_call)"
    r"\s*\([^)]*\)\s*;?",
    re.IGNORECASE,
)

#: qwen also emits tool calls as XML-ish tags with a JSON body. A live Telugu
#: turn spoke "<record_extracted_field>{...}</record_extracted_field" to the
#: caller AND lost the return date. The closing tag may be truncated by the
#: provider, hence the optional ">".
_TOOL_XML_BLOCK_RE = re.compile(
    r"<record_extracted_field\b[^>]*>.*?(?:</record_extracted_field\s*>?|$)"
    r"|</record_extracted_field\b[^>]*>",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_XML_TAG_RE = re.compile(
    r"</?(?:end_call|escalate_to_human|transfer_call)\b[^>]*>", re.IGNORECASE
)
_XML_RECORD_RE = re.compile(
    r"<record_extracted_field\b[^>]*>\s*(.*?)\s*(?:</record_extracted_field\s*>?|$)",
    re.DOTALL | re.IGNORECASE,
)


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
    for body in _XML_RECORD_RE.findall(str(text or "")):
        try:
            data = json.loads(body)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        args = {
            key: data[key]
            for key in ("field_name", "value", "field_value", "confidence")
            if key in data
        }
        if "value" not in args and "field_value" in args:
            args["value"] = args.pop("field_value")
        found.append({"name": "record_extracted_field", "arguments": args})
    return found


_PUNCT_LEFTOVER_RE = re.compile(r"([.!?])\s*[.,;:)]+")

#: Stage directions qwen appended to spoken questions: a live Telugu turn said
#: "ఎప్పుడు తిరిగి వస్తారు? (Waiting for response)(Waiting for your reply)."
_META_CUE_RE = re.compile(
    r"\((?:waiting for (?:your )?(?:response|reply)|silent|pauses?)[^)]*\)",
    re.IGNORECASE,
)


def _scrub_tool_markup(text: str) -> str:
    """Remove tool-call markup so it never ships to the transcript/UI."""
    out = _THINK_BLOCK_RE.sub(" ", str(text or ""))
    out = _DSML_BLOCK_RE.sub(" ", out)
    out = _TOOL_CALL_BLOCK_RE.sub(" ", out)
    out = _TOOL_XML_BLOCK_RE.sub(" ", out)
    out = _TOOL_XML_TAG_RE.sub(" ", out)
    out = _PSEUDO_CALL_RE.sub(" ", out)
    out = _TAG_REMAINDER_RE.sub(" ", out)
    out = _META_CUE_RE.sub(" ", out)
    # A call cut out of the middle of a sentence leaves " ." behind.
    out = _PUNCT_LEFTOVER_RE.sub(r"\1", out)
    return " ".join(out.split())


#: The model writes Telugu in the literary register its training data is full
#: of, even when the prompt asks for everyday speech: a live call asked
#: "ఎప్పుడు తిరిగి హాజరుకావాలని భావిస్తున్నారు?" and closed with "మీ సమయానికి
#: ధన్యవాదాలు. సెలవు." These are grammar-safe substrings - they replace the
#: bookish noun/phrase inside whatever sentence the model built.
_TELUGU_SWAPS: tuple[tuple[str, str], ...] = (
    ("వైద్య ధృవపత్రం", "డాక్టర్ సర్టిఫికెట్"),
    ("ధృవపత్రం", "సర్టిఫికెట్"),
    ("గైర్హాజరు", "లీవ్"),
    ("హాజరుకావాలని", "రావాలని"),
    ("హాజరుకావడం", "రావడం"),
    ("హాజరుకాని", "రాని"),
    ("హాజరు", "రావడం"),
    ("విచారిస్తున్నాను", "అడుగుతున్నా"),
    ("విచారించడానికి", "అడగడానికి"),
    ("దయచేసి ", ""),
    ("మీ సమయానికి ", ""),
    ("ధన్యవాదాలు", "థాంక్స్"),
    ("సర్వే", "కాల్"),
)
_TELUGU_FAREWELL_RE = re.compile(r"\bసెలవు\s*[.!]?\s*$")


def _humanize_telugu(text: str) -> str:
    """Swap bookish Telugu for what people actually say on a phone call."""
    out = str(text or "")
    if not out:
        return out
    for bookish, everyday in _TELUGU_SWAPS:
        out = out.replace(bookish, everyday)
    return " ".join(_TELUGU_FAREWELL_RE.sub("బై.", out.strip()).split())


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

    Used by the HTTP turns endpoint for every text-mode playground session.
    """
    contact = (call.context or {}).get("contact") or {}
    org = db.get(Organization, call.org_id) if call.org_id else None
    agent = db.get(Agent, version.agent_id)
    agent_name = (agent.name or "") if agent else ""
    agent_role = (agent.description or "") if agent else ""
    institution = resolve_spoken_name(
        version.company_context, org.name if org and org.name else ""
    )
    history_rows = list(
        db.scalars(
            select(Transcript)
            .where(Transcript.call_id == call.id)
            .order_by(Transcript.turn_index, Transcript.id)
        ).all()
    )
    next_index = (history_rows[-1].turn_index + 1) if history_rows else 0

    # Full instructions only for the opening exchanges; after that a compact
    # continuation prompt (see _render_compact_system_prompt) so the org's
    # 7000 ITPM budget lasts a real conversation instead of ~4 turns.
    if len(history_rows) > _FULL_PROMPT_ROWS:
        schema_fields = getattr(version, "extraction_schema", None) or {}
        required = [
            name
            for name, spec in schema_fields.items()
            if isinstance(spec, dict)
            and str(spec.get("validation") or "").lower() == "required"
        ]
        already = [
            row.field_name
            for row in db.scalars(
                select(ExtractedField).where(ExtractedField.call_id == call.id)
            ).all()
        ]
        system_prompt = _render_compact_system_prompt(
            [f for f in already if f in schema_fields],
            [
                f
                for f in required
                if f not in already and f not in _AGENT_DERIVED_FIELDS
            ],
            utcnow().strftime("%A %d %B %Y"),
            agent_name=agent_name,
            language=_agent_language(version),
            derived=[
                f
                for f in required
                if f in _AGENT_DERIVED_FIELDS and f not in already
            ],
        )
    else:
        system_prompt = _render_text_system_prompt(
            version,
            contact=contact,
            institution=institution,
            agent_name=agent_name,
            agent_role=agent_role,
        )

    if start_event:
        # Deterministic opening: no provider round trip, no duplicated
        # identity, and the caller hears something within a few ms instead of
        # after a full LLM call.
        opening = _build_short_opening(version, contact, institution, agent_name)
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
        tokens = build_token_map(
            contact,
            institution,
            agent_name=agent_name,
            company_context=getattr(version, "company_context", None),
        )
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
    # Tool markup the model wrote as content. Kept even when the turn is
    # retried for real speech, so the field it tried to record still lands.
    markup_source = ""
    groq_call_ms: list[float] = []
    # Continuity state: who served the previous turn, what is already captured,
    # and the last utterances. If failover moves this turn to another model,
    # _groq_chat injects a brief so the new model does not restart the call.
    captured_before = [
        {"field_name": row.field_name, "field_value": row.field_value}
        for row in db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call.id)
        ).all()
    ]
    recent_turns = [
        f"{row.speaker}: {row.text}" for row in history_rows[-4:] if row.text
    ]
    previous_provider = (call.context or {}).get("llm_provider") if isinstance(call.context, dict) else None
    previous_provider = (
        (str(previous_provider.get("provider")), str(previous_provider.get("model")))
        if isinstance(previous_provider, dict)
        else None
    )

    for round_no in range(_MAX_TOOL_ROUNDS):
        call_started = time.monotonic()
        # Tools stay enabled on EVERY round. Disabling them on the last round
        # is what produced the Groq 400 "Tool choice is none, but model called
        # a tool": gpt-oss kept emitting tool calls (including hallucinated
        # ones like container.exec) and a request with tools absent makes any
        # tool call a server-side error. A legal tool call costs one round
        # trip; an illegal one costs a 400 plus a wasted key.
        try:
            message = await _groq_chat(
                settings,
                messages,
                include_tools=True,
                call_id=call.id,
                previous_provider=previous_provider,
                captured=captured_before,
                recent_turns=recent_turns,
            )
        except HTTPException as exc:
            if exc.status_code == 429:
                # The caller (or UI) should back off and try again; a 429 is
                # actionable and must not be masked by a spoken apology.
                raise
            # Every provider failed in a way retrying cannot fix (empty
            # completions, bad payloads, 5xx). Silence is worse than asking
            # the caller to repeat themselves, so the turn degrades to the
            # deterministic line - and extraction below still records what
            # the caller just said. A 502 here used to kill the whole turn.
            logger.warning(
                "text_turn call=%s: LLM chain failed (%s); speaking fallback line",
                call.id,
                exc.status_code,
            )
            telemetry.record(
                "llm_chain_failed",
                level="error",
                message=str(exc.detail)[:200],
                call_id=call.id,
            )
            break
        served = message.get("served_by")
        if isinstance(served, dict) and served.get("provider"):
            previous_provider = (str(served["provider"]), str(served.get("model") or ""))
        groq_call_ms.append((time.monotonic() - call_started) * 1000.0)
        tool_calls = message.get("tool_calls") or []
        content = str(message.get("content") or "").strip()
        if not tool_calls:
            # Judge usability on what would actually be SPOKEN. A content that
            # is nothing but tool markup scrubs to nothing and must not be
            # read aloud; ask for the real line instead.
            spoken = _scrub_tool_markup(content)
            if (
                not assistant_text
                and _is_unusable_reply(spoken)
                and round_no + 1 < _MAX_TOOL_ROUNDS
            ):
                # Empty or cut-off 200 (no words, no tool call) would be dead
                # air. Ask for the line once more before giving the turn up.
                markup_source += f"\n{content}"
                messages.append(
                    {
                        "role": "user",
                        "content": "[The caller is waiting. Say your next line "
                        "now in one short sentence.]",
                    }
                )
                telemetry.record(
                    "llm_empty_retry",
                    level="warn",
                    message="empty completion; asking the model for its line again",
                    call_id=call.id,
                )
                continue
            # Prefer speech that already rode along with an earlier tool call;
            # otherwise the follow-up round's short ack ("Thanks") replaces a
            # full reply the model already gave.
            if not assistant_text and not _is_unusable_reply(spoken):
                assistant_text = spoken
            break
        # Keep any spoken text that rode along with the tool calls. Dropping
        # it produced truncated replies ("When is Abhi expected to return to"
        # with the rest lost) whenever the model spoke AND recorded in one
        # turn; the follow-up round then added only a short ack.
        if content and not assistant_text and not _is_unusable_reply(content):
            assistant_text = content
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
                # A systems message appended after "tool" messages is not a
                # valid tail for every provider (DeepSeek answered it with an
                # empty completion, leaving the caller in silence). A user
                # turn is legal everywhere.
                messages
                + [
                    {
                        "role": "user",
                        "content": (
                            "[Say your next line to the caller now, in one "
                            "short sentence. Do not call any tool this turn.]"
                        ),
                    }
                ],
                include_tools=True,
                call_id=call.id,
                previous_provider=previous_provider,
                captured=captured_before,
                recent_turns=recent_turns,
            )
        except HTTPException:
            message = {}
        groq_call_ms.append((time.monotonic() - call_started) * 1000.0)
        # The tool loop may already have banked a real spoken reply (content
        # that rode along with tool calls). Never overwrite it with this
        # round's short ack - "Thanks - noted." replacing a substantive answer
        # is exactly the truncation this fallback was built to prevent.
        if not assistant_text:
            candidate = str(message.get("content") or "").strip()
            if _is_unusable_reply(candidate):
                # Tools stay on because a tools-less request can 400, but a
                # model that spent every round on tools still owes the caller
                # a line. De-prime the history and ask once in plain text.
                logger.warning(
                    "text_turn call=%s: no speech after tool rounds; asking "
                    "once in plain text",
                    call.id,
                )
                try:
                    plain = await _groq_chat(
                        settings,
                        _strip_tool_traffic(messages)
                        + [
                            {
                                "role": "user",
                                "content": "[Say your next line to the caller "
                                "now, in one short sentence.]",
                            }
                        ],
                        include_tools=False,
                        call_id=call.id,
                        previous_provider=previous_provider,
                        captured=captured_before,
                        recent_turns=recent_turns,
                    )
                    candidate = str(plain.get("content") or "").strip()
                except HTTPException:
                    candidate = ""
                if _is_unusable_reply(candidate):
                    candidate = "Thanks - noted."
                logger.warning(
                    "text_turn call=%s: plain-text round produced %r",
                    call.id,
                    candidate[:60],
                )
            assistant_text = candidate

    # Pseudo tool calls: the model sometimes emits <tool_call> XML as text
    # instead of a real function call (seen live: the field was lost and raw
    # markup was saved to the transcript). Execute record_* ones with identical
    # semantics, then scrub all markup so it never ships to the UI.
    for pseudo in _parse_pseudo_tool_calls(f"{assistant_text}\n{markup_source}"):
        if pseudo["name"] != "record_extracted_field":
            continue
        _result_text, field_record, _done_flag = _execute_text_tool(
            db, call, pseudo["name"], pseudo["arguments"], next_index, user_text
        )
        if field_record and "summary" not in field_record:
            extracted_now.append(field_record)
    assistant_text = _scrub_tool_markup(assistant_text)
    assistant_text = _cap_reply(_trim_partial_tail(assistant_text))
    fallback_used = False
    if _is_unusable_reply(assistant_text):
        assistant_text = _empty_reply_line(version, done)
        fallback_used = True
        logger.warning(
            "text_turn call=%s: model returned no usable speech; using fallback line",
            call.id,
        )

    caller_question = _caller_asked_question(user_text)
    if not done and caller_question and (
        _is_closing_line(assistant_text) or fallback_used
    ):
        # Live failure: the caller asked "can we do a site visit this Saturday?"
        # and the model answered "Thanks, Vikram. Goodbye." One plain-text
        # nudge gets the actual answer instead of hanging up on a question.
        try:
            answer = await _groq_chat(
                settings,
                _strip_tool_traffic(messages)
                + [
                    {
                        "role": "user",
                        "content": "[The caller just asked you something. Answer "
                        "it in one short sentence. Do not say goodbye and do "
                        "not end the call.]",
                    }
                ],
                include_tools=False,
                call_id=call.id,
                previous_provider=previous_provider,
                captured=captured_before,
                recent_turns=recent_turns,
            )
            candidate = _cap_reply(
                _trim_partial_tail(str(answer.get("content") or "").strip())
            )
            if not _is_unusable_reply(candidate) and not _is_explicit_farewell(
                candidate
            ):
                assistant_text = candidate
        except HTTPException:
            pass

    # Deterministic closing. The model regularly said a full goodbye
    # ("Thanks, have a good day") WITHOUT calling end_call, and if the caller
    # then said anything at all ("okay", "yup"), it said ANOTHER goodbye. The
    # live transcript showed four farewells before the call ended. The rule:
    # once every required field is filled, the FIRST closing line we speak is
    # the last one the caller hears - the turn is marked done and the session
    # completes server-side instead of asking the model for another reply it
    # will only use for another goodbye.
    required = [
        name
        for name, spec in (getattr(version, "extraction_schema", None) or {}).items()
        if isinstance(spec, dict) and str(spec.get("validation") or "").lower() == "required"
    ]
    # Only caller-answerable fields can hold the call open. A disposition the
    # agent derives at the end (call_outcome) is not something it can ask, so
    # waiting for it meant a farewell never closed the session. A bare
    # "Thanks" still needs those dispositions recorded - it is also what the
    # model says right after banking a field - but an explicit goodbye does not.
    all_known = _fields_known(db, call, required, extracted_now)
    blocking_known = [
        known
        for name, known in zip(required, all_known)
        if name not in _AGENT_DERIVED_FIELDS
    ]
    derived_pending = [
        name
        for name, known in zip(required, all_known)
        if name in _AGENT_DERIVED_FIELDS and not known
    ]
    caller_done = _caller_is_finished(user_text)
    closes = (
        all(blocking_known)
        and (not caller_question or caller_done)
        and (
            not derived_pending
            or _is_explicit_farewell(assistant_text)
            or caller_done
        )
    )
    if required and closes and (_is_closing_line(assistant_text) or caller_done) and not done:
        if not _is_closing_line(assistant_text):
            # The caller ended it, whatever the model said. Speak the
            # deterministic farewell in the agent's language and close.
            assistant_text = _empty_reply_line(version, True)
        # Summarize ALL known fields (DB + this turn), not just this turn's:
        # fields captured on earlier turns would otherwise leave an empty
        # summary on exactly the calls that closed cleanly.
        known_rows = {
            f.field_name: f.field_value
            for f in db.scalars(
                select(ExtractedField).where(ExtractedField.call_id == call.id)
            ).all()
        }
        for item in extracted_now:
            if item.get("field_name"):
                known_rows[str(item.get("field_name"))] = item.get("field_value")
        summary = "; ".join(
            f"{name}={known_rows.get(name)}" for name in required if name in known_rows
        )
        unfilled = [name for name in required if name not in known_rows]
        if unfilled:
            summary = (
                f"{summary} | Unfilled required fields (flagged, never "
                f"fabricated): {', '.join(unfilled)}"
            ).strip(" |")
        done = True
        # Finalize the row exactly like end_call: without this the session
        # stays in_progress forever and accepts more turns after goodbye.
        now = utcnow()
        call.summary = summary or None
        call.status = "completed"
        call.ended_at = now
        if call.started_at is not None:
            call.duration_seconds = (now - call.started_at).total_seconds()
        logger.info(
            "deterministic close call=%s fields=%s", call.id, [n for n in required]
        )
        telemetry.record(
            "deterministic_close",
            level="warn",
            message="all required fields filled and the reply was a farewell; "
            "ending server-side instead of requesting another model turn",
            call_id=call.id,
            fields=required,
        )

    # Deterministic extraction backstop. The model's tool calling is
    # probabilistic: with gpt-oss it was so eager it 400'd, and with
    # qwen3.8-27b it silently SKIPS the tool on some turns ("sick" was stated
    # plainly and reason_for_absence was never recorded). A coin flip must not
    # decide whether a captured field exists, so when the model recorded
    # nothing this turn we look for a caller sentence that literally overlaps
    # the field name/description.
    #
    # This cannot fabricate: it only ever records words the CALLER said in
    # THIS turn, it requires a real overlap with the field, and it runs
    # through the same grounding check as a model tool call. If the model did
    # record the field, we never touch it.
    _backfill_grounded_fields(
        db, call, version, user_text, extracted_now, next_index
    )

    # The model asked for something the caller had just given ("which date
    # would suit you better?" right after "reschedule to Friday"): the value
    # was captured by the backfill, so it was invisible to the model when it
    # wrote that line. One nudge with the fact stated gets the next line.
    schema_for_ask = getattr(version, "extraction_schema", None) or {}
    if not done and "?" in assistant_text and extracted_now and isinstance(
        schema_for_ask, dict
    ):
        just_recorded = [
            str(item.get("field_name"))
            for item in extracted_now
            if item.get("field_name")
        ]
        known_now = {
            row.field_name
            for row in db.scalars(
                select(ExtractedField).where(ExtractedField.call_id == call.id)
            ).all()
        } | set(just_recorded)
        still_missing = [
            name
            for name in schema_for_ask
            if name not in known_now and name not in _AGENT_DERIVED_FIELDS
        ]
        reasked = _question_targets(
            assistant_text, schema_for_ask, just_recorded
        ) - _question_targets(assistant_text, schema_for_ask, still_missing)
        if reasked:
            try:
                values = "; ".join(
                    f"{item.get('field_name')}={item.get('field_value')}"
                    for item in extracted_now
                    if item.get("field_name") in reasked
                )
                better = await _groq_chat(
                    settings,
                    _strip_tool_traffic(messages)
                    + [
                        {
                            "role": "user",
                            "content": (
                                f"[The caller already answered: {values}. Do not "
                                "ask about it again. Say your next line in one "
                                "short sentence.]"
                            ),
                        }
                    ],
                    include_tools=False,
                    call_id=call.id,
                    previous_provider=previous_provider,
                    captured=captured_before,
                    recent_turns=recent_turns,
                )
                candidate = _cap_reply(
                    _trim_partial_tail(str(better.get("content") or "").strip())
                )
                if (
                    not _is_unusable_reply(candidate)
                    and not (
                        _question_targets(candidate, schema_for_ask, reasked)
                        - _question_targets(candidate, schema_for_ask, still_missing)
                    )
                ):
                    assistant_text = candidate
                    logger.warning(
                        "text_turn call=%s: replaced a re-ask of %s",
                        call.id,
                        reasked,
                    )
            except HTTPException:
                pass

    if (
        fallback_used
        and not done
        and not caller_question
        and (extracted_now or _caller_is_acknowledging(user_text))
    ):
        # The caller's answer WAS captured (by the model or the backfill), or
        # their line was a plain acknowledgment, so a "could you say that
        # again?" would ask them to repeat something we already have.
        assistant_text = _ACK_LINES[_agent_language(version)]

    if _agent_language(version) == "te":
        assistant_text = _humanize_telugu(assistant_text)

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
    _persist_serving_provider(call, agent_index, previous_provider)
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
        # Which provider/model actually produced this reply. The playground
        # shows it per turn: a fast answer from an unknown model is not
        # verifiable otherwise, and failover is invisible without it.
        "served_by": (
            {"provider": previous_provider[0], "model": previous_provider[1]}
            if previous_provider and previous_provider[0]
            else None
        ),
        "llm_calls": len(groq_call_ms),
    }


def _persist_serving_provider(
    call: Call, agent_index: int, previous_provider: Optional[tuple[str, str]]
) -> None:
    """Persist who served this turn, so the completed-session view can show
    "served by" per row and the next turn knows which provider it inherits
    from for the continuity brief. Called AFTER agent_index exists."""
    if not (previous_provider and previous_provider[0]):
        return
    context = dict(call.context or {})
    context["llm_provider"] = {
        "provider": previous_provider[0],
        "model": previous_provider[1],
    }
    providers_seen = list(context.get("llm_turn_providers") or [])
    providers_seen.append(
        {
            "turn": agent_index,
            "provider": previous_provider[0],
            "model": previous_provider[1],
        }
    )
    context["llm_turn_providers"] = providers_seen
    call.context = context
