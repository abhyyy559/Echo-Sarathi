"""Pure system-prompt rendering for the cascaded voice pipeline.

This module is deliberately free of I/O and third-party imports so it can be
unit tested offline (it imports only the threshold constants from
``app.extraction_tools``, which are themselves stdlib-only).

The rendered prompt is structured, in order:

1. Mandatory disclosure script — VERBATIM, always the very first utterance.
2. Role & mission (who the agent is, what this call achieves).
3. Persona / company context.
4. Speaking style — TTS-safe, human, brief.
5. Conversation flow — question flow as a checklist, not a script.
6. Extraction discipline (never-fabricate + immediate tool recording).
7. Escalation policy (low confidence / exhausted asks -> wrap-up + flag).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from app.extraction_tools import LOW_CONFIDENCE_THRESHOLD, MAX_ASKS_PER_FIELD

logger = logging.getLogger("voice_agent.prompting")

DISCLOSURE_HEADER = (
    "MANDATORY DISCLOSURE - your VERY FIRST utterance, spoken word-for-word:"
)
PERSONA_HEADER = "WHO YOU ARE - role and mission:"
ROLE_MISSION_HEADER = (
    "ROLE & MISSION - defined by the agent creator (AUTHORITATIVE):"
)
CONTEXT_HEADER = "COMPANY KNOWLEDGE - facts you may use; never invent anything beyond this:"
CALLER_CONTEXT_HEADER = "CALLER CONTEXT - who this specific call is about:"
GREETING_HEADER = "GREETING RULE (hard) - state only what you know:"
LANGUAGE_HEADER = "LANGUAGE INSTRUCTION:"
TODAY_HEADER = "TODAY'S DATE (Asia/Kolkata) - resolve every relative date against this:"
QUESTIONS_HEADER = "YOUR GOALS - information to collect during the call:"
EXTRACTION_HEADER = "RECORDING ANSWERS - extraction discipline:"
ESCALATION_HEADER = "WHEN TO WRAP UP:"
CALL_BUDGET_HEADER = "CALL BUDGET - finish fast, calls cost money:"

LANGUAGE_NAMES = {"en": "English", "te": "Telugu", "hi": "Hindi"}

#: Spoken-register examples. A model told only "respond in Telugu" writes the
#: literary (granthik) register from its training data: on a live call the
#: agent said "కాలేయ పునాహక్రష్ వల్లే రాలేకపోయాడనే వివరం నమోదు చేస్తున్నా"
#: and the caller heard a newsreader from a textbook, not a college office.
#: One GOOD/BAD pair per language is what actually moves the output.
_SPOKEN_STYLE: dict[str, str] = {
    "te": (
        "- Telugu script for the Telugu, English words IN ENGLISH inside the "
        "same sentence, the way Hyderabad speaks on the phone.\n"
        "  GOOD: \"అర్థమైంది — fever వల్ల కాలేజ్‌కి రాలేదు కదా. రేపు వస్తాడా?\"\n"
        "  BAD (bookish, never say this): \"జ్వరము నిమిత్తము విద్యాలయమునకు "
        "విరామము కలదని వివరము నమోదు చేయుచున్నాను.\"\n"
        "- When the caller used an English word (fever, college, attendance, "
        "tomorrow, fee), give it back to them in English. Never hunt for a "
        "Sanskrit or classical synonym for a word they already said.\n"
    ),
    "hi": (
        "- Devanagari for the Hindi, English words IN ENGLISH inside the same "
        "sentence, the way Delhi/Hyderabad speaks on the phone: \"बुखार से "
        "college नहीं आ पाया, कल आ जाएगा ना?\" — not शब्दों की रचना.\n"
    ),
}

_BRACKET_ARTIFACT_RE = re.compile(r"\[[^\]]*\]")
_DOUBLE_SPACE_RE = re.compile(r"\s{2,}")

_TOOL_BLOCK_RE = re.compile(
    r"<tool_call>.*?</tool_call>|<function=[^>]*>|<parameter=[^>]*>",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_CALLS_JSON_RE = re.compile(r'"[^"]*tool_calls[^"]*"\s*:\s*\[.*?\]', re.DOTALL)


#: Phone TTS (Sarvam Bulbul) rejects any segment with no letter it recognises:
#: "400: Text must contain at least one character from the allowed languages".
#: A qwen reply that is bare punctuation, or that leaks a Han character into a
#: Telugu sentence, therefore fails to synthesize and the framework re-sends the
#: whole segment several times - seconds of dead air mid-call.
_SPEAKABLE_LETTER_RANGES = (
    (0x0041, 0x005A),
    (0x0061, 0x007A),
    (0x00C0, 0x017F),
    (0x0900, 0x097F),  # Devanagari (hi)
    (0x0C00, 0x0C7F),  # Telugu (te)
)
_SPEAKABLE_ALNUM_RE = re.compile(r"[0-9A-Za-z\u0900-\u097F\u0C00-\u0C7F]")


def speakable_text(text: str) -> str:
    """Keep only characters a phone voice can pronounce, preserving spacing.

    Letters outside Latin/Devanagari/Telugu are dropped; a chunk left with no
    letter or digit at all becomes "" so nothing is sent to synthesis.
    """
    kept: list[str] = []
    for ch in str(text or ""):
        cp = ord(ch)
        if ch.isalpha() and not any(lo <= cp <= hi for lo, hi in _SPEAKABLE_LETTER_RANGES):
            continue
        kept.append(ch)
    out = "".join(kept)
    return out if _SPEAKABLE_ALNUM_RE.search(out) else ""


def scrub_speech_text(text: str) -> str:
    """Remove LLM tool-call markup from text that will be spoken/saved.

    Handles LiveKit-style inline markup (``<tool_call>...``, ``<function=...>``,
    ``<parameter=...>``) and OpenAI-style ``\"tool_calls\": [...]`` JSON that a
    model may emit as inline assistant text. Returns cleaned, stripped text.
    """
    original = str(text or "")
    out = _TOOL_BLOCK_RE.sub(" ", original)
    out = _TOOL_CALLS_JSON_RE.sub(" ", out)
    out = _DOUBLE_SPACE_RE.sub(" ", out).strip()
    if out != original.strip():
        logger.debug("Scrubbed tool-call markup from agent text")
    return out


def apply_token_substitution(
    text: str, tokens: Optional[Mapping[str, str]] = None
) -> str:
    """Replace known bracket tokens with real values; empty -> removed.

    After substitution, any remaining ``[...]`` placeholder is stripped so a
    bare bracket never ships. Returns cleaned text.
    """
    if not text:
        return text
    out = str(text)
    for token, value in (tokens or {}).items():
        out = out.replace(str(token), str(value) if value is not None else "")
    # Safety net: strip any remaining placeholder tokens.
    out = _BRACKET_ARTIFACT_RE.sub("", out)
    return _DOUBLE_SPACE_RE.sub(" ", out).strip()


def _first_name(*candidates: Optional[Mapping[str, Any]]) -> str:
    """First known name found across contact cards (any domain's name key)."""
    for card in candidates:
        if not isinstance(card, Mapping):
            continue
        for key in ("student_name", "patient_name", "name", "contact_name",
                    "full_name", "lead_name", "candidate_name"):
            value = str(card.get(key) or "").strip()
            if value:
                return value
    return ""


def _known_field(*candidates: Optional[Mapping[str, Any]], keys: tuple[str, ...]) -> str:
    """First non-empty value for any of ``keys`` across contact cards."""
    for card in candidates:
        if not isinstance(card, Mapping):
            continue
        for key in keys:
            value = str(card.get(key) or "").strip()
            if value:
                return value
    return ""


def today_line(timezone_name: str = "Asia/Kolkata", now: Optional[datetime] = None) -> str:
    """Render today's date for the prompt so relative dates resolve.

    ``now`` is injectable (tests); otherwise the current time in
    ``timezone_name`` (falls back to UTC on unknown zones). Format is
    weekday-explicit so 'Monday'/'this Friday' map unambiguously.
    """
    try:
        zone = ZoneInfo(str(timezone_name or "Asia/Kolkata"))
    except Exception:  # noqa: BLE001 — bad zone name must never break prompts
        zone = timezone.utc
    current = now.astimezone(zone) if now is not None else datetime.now(zone)
    return current.strftime("%A, %d %B %Y")


def _unfilled(value: Any) -> bool:
    """True for a preset token like "[Clinic Name]" that no one filled in."""
    text = str(value or "").strip()
    return text.startswith("[") and text.endswith("]") and len(text) > 2


def _context_value(company_context: Any, *keys: str) -> str:
    if not isinstance(company_context, Mapping):
        return ""
    for key in keys:
        value = company_context.get(key)
        if isinstance(value, str) and value.strip() and not _unfilled(value):
            return value.strip()
    return ""


def build_token_map(
    contact: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
    agent_name: str = "",
    company_context: Any = None,
) -> dict[str, str]:
    """Resolve known placeholder tokens to real values for this call.

    ``contact`` is the contact card packed in room/token metadata; ``context``
    is the backend's call-context JSON (institution_name + optional contact).
    ``company_context`` is the agent version's per-vertical context, which is
    where a clinic or realtor fills in clinic_name / property_name / locality.
    ``[Expected Return Date]`` has no data source, so it maps to "" (dropped).

    ``agent_name`` fills ``[Agent Name]``; empty falls back to
    ``AI_ASSISTANT_FALLBACK`` so disclosures never dangle.
    """
    ctx = context if isinstance(context, Mapping) else {}
    ctx_contact = ctx.get("contact") if isinstance(ctx.get("contact"), Mapping) else {}
    institution = str(ctx.get("institution_name") or "").strip()
    name = _first_name(contact, ctx_contact)
    parent = _known_field(
        contact,
        ctx_contact,
        keys=("parent_name", "parent", "guardian", "contact_person"),
    )
    who = str(agent_name or "").strip() or AI_ASSISTANT_FALLBACK
    return {
        "[Institution Name]": institution,
        "[Company Name]": _context_value(company_context, "company_name") or institution,
        "[Clinic Name]": _context_value(company_context, "clinic_name") or institution,
        "[Property Name]": _context_value(company_context, "property_name"),
        "[Locality]": _context_value(company_context, "locality"),
        "[Service Type]": _context_value(company_context, "service_type"),
        "[Service Date]": _context_value(company_context, "service_date"),
        "[Student Name]": name,
        "[Lead Name]": name,
        "[Contact Name]": name,
        "[Customer Name]": name,
        "[Patient Name]": name,
        "[Parent/Guardian Name]": parent,
        "[Agent Name]": who,
        "[Source]": _context_value(company_context, "source", "lead_source"),
        "[Doctor Name]": _context_value(company_context, "doctor_name")
        or _known_field(contact, ctx_contact, keys=("doctor_name", "doctor")),
        "[Appointment Date]": _known_field(contact, ctx_contact,
                                           keys=("appointment_date", "date")),
        "[Appointment Time]": _known_field(contact, ctx_contact,
                                           keys=("appointment_time", "time")),
        "[Expected Return Date]": "",
    }


_CARD_PARENT_KEYS = ("parent_name", "parent", "guardian", "contact_person")
_CARD_SUBJECT_KEYS = ("student_name", "patient_name", "full_name", "contact_name",
                      "lead_name", "candidate_name", "name")


def _card_value(card: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(card.get(key) or "").strip()
        if value:
            return value
    return ""


def _norm_institution(text: str) -> str:
    """Normalize institution names for duplicate detection.

    Token maps carry 'A & B' while disclosures write 'A and B' (or differ
    in case/punctuation) — a raw substring check then misses the duplicate
    and the opening repeats the college name twice (~8 wasted seconds).
    """
    out = str(text or "").lower()
    out = out.replace("&", "and")
    out = re.sub(r"[^a-z0-9 ]+", " ", out)
    return _DOUBLE_SPACE_RE.sub(" ", out).strip()


#: Spoken ``who`` when a version has no ``[Agent Name]`` value. A module
#: constant (not an inline string) so ``build_opening_line`` can tell "nothing
#: authored" apart from a real name and use the LOCALIZED phrasing instead: a
#: Telugu disclosure followed by the English words "an AI assistant" is the
#: exact English sandwich localization is meant to avoid.
AI_ASSISTANT_FALLBACK = "an AI assistant"

#: Word-boundary (not substring) match on the Latin "AI": disclosures that
#: introduce the assistant themselves ("... నుండి AI అసిస్టెంట్", "...this is an AI
#: assistant calling from X") already said what the generated intro would
#: repeat. \b keeps "said"/"email"/"may" from matching.
_AI_MENTION_RE = re.compile(r"\bai\b", re.IGNORECASE)

#: Greeting words across the supported languages. Most authored disclosure
#: scripts open with one ("నమస్కారం, నేను [Institution Name] నుండి AI అసిస్టెంట్..."),
#: and the generated greeting prefixes another, so every call started with two
#: welcomes back to back — callers read that as a stuttering agent. Latin
#: greetings match on word boundaries so "hi" cannot fire inside "this".
_GREETING_WORDS: tuple[str, ...] = (
    "hello", "hi", "namaste", "namaskar", "namaskaram", "vanakkam",
    "నమస్కారం", "నమస్తే", "హలో",
    "नमस्ते", "नमस्कार", "हैलो", "हेलो",
)
_GREETING_RE = re.compile(
    "|".join(
        rf"\b{re.escape(word)}\b" if word.isascii() else re.escape(word)
        for word in _GREETING_WORDS
    ),
    re.IGNORECASE,
)

#: First flow questions that verify the callee's identity. When one of these
#: already names the person, it is the whole greeting: a separate "Hello, Riya."
#: would only repeat the name the caller is being asked about.
_VERIFY_OPENER_RE = re.compile(
    r"^\s*(?:hi|hello|hey\b[,\s]*)?(?:am i (?:speaking|talking)|is (?:this|that)|are you)\b",
    re.IGNORECASE,
)


#: Connective phrases the platform generates around the AUTHORED disclosure and
#: first flow question. Only these few fragments need localizing — everything
#: else in the opening is authored by the agent creator in the target language.
#: Proper nouns (institution, names) stay verbatim inside the local sentence,
#: which is exactly how Indian code-switched speech sounds ("Demo School నుండి
#: కాల్ చేస్తున్నాను").
_OPENING_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "hello": "Hello",
        "ai_assistant": "an AI assistant",
        "self_intro": "This is {who} calling",
        "name_only": "I'm {who}.",
        "from_suffix": " from {institution}",
        "from_standalone": "Calling from {institution}.",
        "about": " I'm calling about {subject}.",
        "ask_who": "May I know who I'm speaking with?",
    },
    "te": {
        "hello": "నమస్కారం",
        "ai_assistant": "ఒక AI అసిస్టెంట్",
        "self_intro": "నేను {who} మాట్లాడుతున్నాను",
        "name_only": "నేను {who}.",
        "from_suffix": " {institution} నుండి",
        "from_standalone": "{institution} నుండి కాల్ చేస్తున్నాను.",
        "about": " {subject} గురించి కాల్ చేస్తున్నాను.",
        "ask_who": "మీ పేరు ఏంటి?",
        # Bare "Ram." is how a form letter addresses someone; on a Telugu phone
        # call the caller is "Ram గారూ". Without it the name also runs into the
        # next sentence and sounds like one long name ("Ram Demo Student").
        "address": "{parent} గారూ",
    },
    "hi": {
        "hello": "नमस्ते",
        "ai_assistant": "एक AI असिस्टेंट",
        "self_intro": "मैं {who} बोल रहा हूँ",
        "name_only": "मैं {who} हूँ।",
        "from_suffix": " {institution} से",
        "from_standalone": "{institution} से कॉल कर रहा हूँ।",
        "about": " {subject} के बारे में कॉल कर रहा हूँ।",
        "ask_who": "क्या मैं जान सकता हूँ कि आप कौन हैं?",
        "address": "{parent} जी",
    },
}


def _opening_language(config: Mapping[str, Any]) -> str:
    """Agent language code from ``voice_settings`` (defaults to English)."""
    voice_settings = config.get("voice_settings") if isinstance(config, Mapping) else {}
    if isinstance(voice_settings, Mapping):
        return str(voice_settings.get("language") or "en").strip().lower() or "en"
    return "en"


def _opening_phrases(config: Mapping[str, Any]) -> dict[str, str]:
    """Localized connective phrases for the generated part of the opening."""
    return _OPENING_PHRASES.get(_opening_language(config), _OPENING_PHRASES["en"])


#: Sentence starters that can follow an English vocative comma without the
#: capital: "Suresh Kumar, could you ...?". Anything else (a proper noun at
#: the start, e.g. "Aarav was absent ...") keeps its own sentence.
_VOCATIVE_QUESTION_STARTERS = frozenset({
    "could", "would", "can", "may", "might", "will", "shall", "should",
    "do", "does", "did", "is", "are", "was", "were", "have", "has", "had",
    "why", "what", "when", "where", "who", "how", "please", "tell", "kindly",
})


def _vocative_continuation(question: str) -> Optional[str]:
    """Lowercased question for a vocative comma, or None to keep it a sentence."""
    text = str(question or "").strip()
    if not text or not text[0].isascii():
        return None
    first = text.split(maxsplit=1)[0].lower().strip(".,:;!?")
    if first not in _VOCATIVE_QUESTION_STARTERS:
        return None
    return text[0].lower() + text[1:]


def build_opening_line(
    config: Mapping[str, Any],
    tokens: Optional[Mapping[str, str]] = None,
    contact: Optional[Mapping[str, Any]] = None,
) -> str:
    """Deterministic opening: disclosure + greeting + first question.

    Everything is token-substituted, so no ``[...]`` placeholder can ship.
    Returns "" when there is no disclosure script — the caller then falls
    back to the prompt-driven auto-turn.
    """
    tok = dict(tokens or {})
    phrases = _opening_phrases(config)
    disclosure = apply_token_substitution(_disclosure_text(config), tok)
    if not disclosure:
        return ""
    card = contact if isinstance(contact, Mapping) else {}
    parent = _card_value(card, _CARD_PARENT_KEYS)
    subject = _card_value(card, _CARD_SUBJECT_KEYS)
    institution = tok.get("[Institution Name]", "") or tok.get("[Company Name]", "")
    # The disclosure script usually names the institution already — repeating
    # it in the greeting doubles ~15 words of TTS (~4s) for zero information.
    # Compare normalized (see _norm_institution): '&' vs 'and' must not hide
    # the duplicate.
    if institution and _norm_institution(institution) in _norm_institution(disclosure):
        institution = ""
    # A disclosure that already says "calling from X" has introduced the
    # caller's origin. When the contact card / call context carries a DIFFERENT
    # institution name than the authored script, the opening used to name both
    # ("...calling from CMR College... Hello Ravi. Calling from Demo
    # University.") - confusing for the callee and ~1s of extra TTS at the most
    # latency-sensitive moment. The authored name wins; drop the token one.
    if institution and "calling from" in _norm_institution(disclosure):
        institution = ""
    who = tok.get("[Agent Name]", "").strip()
    if not who or who == AI_ASSISTANT_FALLBACK:
        # No [Agent Name] was authored: speak the LOCALIZED assistant phrase
        # ("ఒక AI అసిస్టెంట్"), never the English token default.
        who = phrases["ai_assistant"]
    # Redundancy elimination: the disclosure usually already says who is
    # calling and from where — repeating either doubles TTS seconds for zero
    # information (callers experience it as the agent "taking forever").
    # The greeting carries only genuinely new information.
    stated_assistant = bool(_AI_MENTION_RE.search(disclosure))
    if not who:
        intro = phrases["from_standalone"].format(institution=institution) if institution else ""
    elif who == phrases["ai_assistant"]:
        # The token default is the generic identity. A bare disclosure has not
        # introduced anyone, so state it; only an authored "AI assistant" makes
        # the line redundant.
        if stated_assistant:
            intro = ""
        else:
            intro = phrases["self_intro"].format(who=who)
            if institution:
                intro += phrases["from_suffix"].format(institution=institution)
            intro += "."
    elif who not in disclosure:
        if stated_assistant:
            # The disclosure already said "AI assistant"; the caller still
            # needs a name to attach the voice to, so introduce it on its own.
            intro = phrases["name_only"].format(who=who)
        else:
            intro = phrases["self_intro"].format(who=who)
            if institution:
                intro += phrases["from_suffix"].format(institution=institution)
            intro += "."
    elif institution:
        intro = phrases["from_standalone"].format(institution=institution)
    else:
        intro = ""
    # Short standalone sentences (not one long clause): the TTS engine
    # synthesizes sentence by sentence, so names get clean prosodic breaks
    # and are pronounced far more clearly than mid-sentence.
    # The greeting is dropped when the authored disclosure already opens with
    # one, otherwise the caller hears "నమస్కారం, ... నమస్కారం ..." (two welcomes).
    first_question = ""
    flow = config.get("question_flow") if isinstance(config, Mapping) else []
    if isinstance(flow, list):
        for item in flow:
            text_value = apply_token_substitution(_question_text(item), tok)
            if text_value:
                first_question = text_value
                break
    hello = "" if _GREETING_RE.search(disclosure) else phrases["hello"]
    # The flow question normally names the student too ("...the reason for
    # Demo Student's absence today?"). Saying "I'm calling about Demo Student."
    # immediately before it repeats the same name for zero information, at the
    # exact moment the caller is waiting for their turn to speak. Keep one
    # mention and drop the other; the question is the one that must survive.
    named_in_question = bool(
        subject
        and first_question
        and subject.casefold() in first_question.casefold()
    )
    about = "" if named_in_question else phrases["about"].format(subject=subject)
    bare_address = ""
    if parent and subject and parent != subject:
        address = phrases.get("address", "{parent}").format(parent=parent)
        greet = f"{hello} {address}.".strip()
        if intro:
            greet += f" {intro}"
        greet += about
        if not hello and not intro and not about:
            bare_address = address
    elif subject:
        greet = f"{hello} {subject}.".strip()
        if intro:
            greet += f" {intro}"
    elif intro:
        greet = f"{hello}. {intro}" if hello else intro
    else:
        greet = f"{hello}." if hello else ""
    if not parent and not subject:
        # No names anywhere on this record: every name-bearing flow question
        # would speak dangling grammar ("Am I speaking with , parent of ,").
        # Ask plainly instead of shipping a broken sentence.
        return scrub_speech_text(
            f"{disclosure} {greet} {phrases['ask_who']}"
        )
    # Verify-style openers address the parent BY NAME ("Am I speaking with
    # Suresh, parent of Aarav...?"): prepending the standard greeting would
    # repeat the same name twice and push the opening past ~20 seconds of
    # speech. Disclosure + question is the whole opening then. (Subject-only
    # questions keep the greeting — the parent hasn't been addressed yet.)
    if first_question:
        asked = first_question.lower()
        if parent and parent.lower() in asked:
            opening = f"{disclosure} {first_question}"
            leftovers = _BRACKET_ARTIFACT_RE.findall(opening)
            if leftovers:
                logger.warning(
                    "opening line has unsubstituted tokens (missing contact data): %s",
                    sorted(set(leftovers)),
                )
            return scrub_speech_text(opening)
        # Lead-style presets open by verifying the callee ("Am I speaking with
        # Riya?"). Prepending the subject greeting then says the name twice.
        if subject and subject.lower() in asked and _VERIFY_OPENER_RE.search(first_question):
            opening = f"{disclosure} {first_question}"
            leftovers = _BRACKET_ARTIFACT_RE.findall(opening)
            if leftovers:
                logger.warning(
                    "opening line has unsubstituted tokens (missing contact data): %s",
                    sorted(set(leftovers)),
                )
            return scrub_speech_text(opening)
    spoken_question = first_question
    if bare_address and first_question:
        # The disclosure already greeted; "Suresh Kumar." on its own sounds
        # like a roll-call reading. Make it a vocative that flows into the
        # question: "Suresh Kumar, could you please share ...?"
        continued = _vocative_continuation(first_question)
        if continued is not None:
            greet = f"{bare_address},"
            spoken_question = continued
    opening = f"{disclosure} {greet}"
    if spoken_question:
        opening += f" {spoken_question}"
    # Loud failure over silent failure: an unsubstituted [Token] means the
    # contact card lacked the data — speaking "appointment with on at" is
    # worse than a hallucination because the caller cannot catch it. Log
    # which tokens failed; the scrubbed output still ships so the call runs.
    leftovers = _BRACKET_ARTIFACT_RE.findall(opening)
    if leftovers:
        logger.warning(
            "opening line has unsubstituted tokens (missing contact data): %s",
            sorted(set(leftovers)),
        )
    return scrub_speech_text(opening)


def _disclosure_text(config: Mapping[str, Any]) -> str:
    """Disclosure script, accepting both the platform key and the legacy one."""
    raw = config.get("disclosure_script")
    if not raw:
        raw = config.get("mandatory_disclosure")
    return str(raw or "").strip()


def _question_text(item: Any) -> str:
    """Question text from either a plain string or a flow-step object."""
    if isinstance(item, Mapping):
        text = item.get("question") or item.get("text") or ""
        return str(text).strip()
    return str(item or "").strip()


def render_caller_context(
    contact: Mapping[str, Any],
    known_keys: Optional[object] = None,
) -> str:
    """CALLER CONTEXT block (P0-2) from the contact card packed in room/token
    metadata. Names the person the call is about, tells the agent who to ask
    for, and enforces verify-relationship-before-details.

    ``known_keys`` (optional, from the domain config's ``known_context_keys``)
    is the known-vs-discovered separation: only these fields are facts the
    agent may state. Target/extraction fields (reason, slots, preferences)
    must NEVER reach the prompt, or the agent asserts undiscovered facts
    ("calling about Abhi's fever"). When None, all scalar fields render
    (legacy behavior).
    """
    allow: Optional[set[str]] = None
    if isinstance(known_keys, (list, tuple, set)):
        allow = {str(k).strip() for k in known_keys if str(k).strip()}
    fields: dict[str, str] = {}
    if isinstance(contact, Mapping):
        for key, value in contact.items():
            name = str(key).strip()
            if not name or isinstance(value, (dict, list)):
                continue
            if allow is not None and name not in allow:
                continue
            text = str(value).strip()
            if text:
                fields[name] = text

    lines = [CALLER_CONTEXT_HEADER]
    about: list[str] = []
    student = fields.get("student_name") or ""
    parent = fields.get("parent_name") or ""
    # Domain-generic subject keys: whichever of these is present marks the
    # person the call is about (lead verification, surveys, appointments, ...).
    subject = (
        fields.get("full_name")
        or fields.get("contact_name")
        or fields.get("lead_name")
        or fields.get("candidate_name")
        or fields.get("name")
        or ""
    )
    if student:
        about.append(f"the student {student}")
    if fields.get("class_section"):
        about.append(f"class {fields['class_section']}")
    if fields.get("absent_date"):
        about.append(f"absent on {fields['absent_date']}")
    if subject:
        about.append(f"the person {subject}")
    if about:
        lines.append("- You are calling about " + ", ".join(about) + ".")
    else:
        lines.append(
            "- Details of the person this call is about: "
            + json.dumps(fields, ensure_ascii=False, sort_keys=True)
        )

    # Any other custom fields still get through - the creator's contact card
    # may carry domain-specific facts (city, form_source, account_id, ...) the
    # agent should be able to use without the platform knowing their meaning.
    woven = {
        "student_name",
        "class_section",
        "absent_date",
        "full_name",
        "contact_name",
        "lead_name",
        "candidate_name",
        "name",
        "parent_name",
        "contact_person",
    }
    extras = {k: v for k, v in fields.items() if k not in woven}
    if extras and about:
        lines.append(
            "- Other details you may use if relevant: "
            + json.dumps(extras, ensure_ascii=False, sort_keys=True)
        )

    # Who to ask for: an explicit parent (school flows) or contact person wins;
    # otherwise the subject themself (e.g. a lead answering their own phone).
    verify_target = (
        parent
        or fields.get("contact_person")
        or (subject and f"{subject} (the person you are calling)")
        or "the person you are calling"
    )
    if parent:
        lines.append(f"- Ask to speak with {parent} (the parent/guardian).")
    elif subject:
        lines.append(f"- Ask for {subject} when the call is answered.")

    # Say the names out loud. The #1 complaint from real test calls is a generic
    # opening ("may I speak with the parent or guardian...") when the caller's
    # name is sitting right there in the contact card. Collect every name we
    # know and instruct the agent to use them in the greeting. Prefer the plain
    # name over the label so the greeting sounds natural ("Suresh", not
    # "Suresh (the parent/guardian)").
    known_names: list[str] = []
    for key in ("parent_name", "student_name", "full_name", "lead_name",
                "contact_name", "candidate_name", "name", "contact_person"):
        val = str(fields.get(key) or "").strip()
        if val and val not in known_names:
            known_names.append(val)
    if known_names:
        examples = []
        if parent and student:
            examples.append(f"Good morning, am I speaking with {parent}, parent or guardian of {student}?")
        elif parent:
            examples.append(f"Good morning, am I speaking with {parent}?")
        elif subject:
            examples.append(f"Good morning, am I speaking with {subject}?")
        named = ", ".join(known_names)
        lines.append(
            "- SAY THE NAMES OUT LOUD: greet the person using their name. "
            f"Known name(s) on this record: {named}."
        )
        if examples:
            lines.append(
                "- Example openings to model: "
                + " | ".join(examples)
            )
        if parent or student:
            lines.append(
                "- NEVER say 'the person we are calling about' or 'the parent or "
                "guardian of the student' when you have a real name on this record. "
                "Names make the call feel human; vagueness is how callers sense a bot."
            )
        else:
            lines.append(
                "- NEVER say 'the person we are calling about' when you have a real "
                "name on this record. Names make the call feel human; vagueness is "
                "how callers sense a bot."
            )
    lines.extend(
        [
            (
                "- VERIFY RELATIONSHIP BEFORE DETAILS: confirm you are speaking with "
                f"{verify_target} before discussing any details about the person "
                "this call is about."
            ),
            (
                "- If the person who answered is NOT "
                f"{verify_target}, do NOT share any details: ask when they will be "
                "available, thank them politely, say goodbye, and end the call by "
                "calling the `end_call` tool with a short summary so the line "
                "actually closes."
            ),
        ]
    )
    return "\n".join(lines)


def render_compact_instructions(
    captured: list[str],
    remaining: list[str],
    today: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    """Short continuation instructions for mid/late voice turns.

    Mirrors the backend's _render_compact_system_prompt: the full 8k-char
    instructions are re-sent on EVERY LLM call, and Groq's input-token bucket
    is organization-wide (7000/min). A voice call dies at ~3 turns on the full
    prompt. After the opening exchanges the conversation history already
    carries the persona, names and disclosure, so the model only needs today's
    date, which fields are done, and the rules that must not be forgotten.

    ``language`` must be passed: from turn two on this block REPLACES the full
    instructions, so anything that lives only in the full prompt (the spoken
    register, mirroring the caller) is silently dropped for the rest of the
    call.
    """
    lang_code = str(language or "").strip().lower()
    language_line = ""
    if lang_code and lang_code != "en":
        lang_name = LANGUAGE_NAMES.get(lang_code, lang_code)
        language_line = (
            f"Answer in {lang_name} when the caller writes "
            f"{lang_name}: everyday spoken {lang_name}, mixed with English "
            "words exactly as the caller mixes them, in this register: "
            + _SPOKEN_STYLE.get(lang_code, "short spoken sentences, not bookish.")
            + "If the caller answers the whole turn in English, reply in English "
            "for that turn and go back afterwards.\n"
        )
    state = (
        f"Already recorded: {', '.join(captured)}" if captured else "Nothing recorded yet."
    )
    todo = f"Still needed: {', '.join(remaining)}." if remaining else ""
    return (
        f"TODAY: {today or ''}.\n"
        "You are the same outbound phone agent from earlier in this call; the "
        "person is already verified. Reply in 1-2 short spoken sentences, one "
        "thing per reply: if you still need an answer, ask it and STOP - never "
        "ask and thank/close in the same reply. Acknowledge what they said, then "
        "move on. Never invent a value: only record what the caller actually "
        "said, and never ask them to repeat an answer they already gave.\n"
        "Do NOT repeat yourself: no restating a value or confirmation you have "
        "already given, no re-confirming a date, no 'anything else?'. If they "
        "confirmed, ask the next missing thing or close politely.\n"
        "A tool result is bookkeeping, not the caller speaking: after one, add "
        "nothing to what you already said. Never read the caller's words back "
        "verbatim - the phone transcript is often misspelled, so say what you "
        "understood in your own words. Keep their language; code-switch only "
        "as they do.\n"
        "The caller does not know your checklist: never ask what the purpose, "
        "outcome or 'details' of this call are, never say you are recording, "
        "updating or noting a field. Ask about the person, not about the call. "
        "When they give a value - including 'after 2 days' or 'this Monday', "
        "which you resolve against TODAY - record it in this same turn, then "
        "ask the one thing still missing or close.\n"
        + language_line
        + f"{state} {todo}\n"
        f"Record with record_extracted_field(field_name, value, confidence); "
        f"finish with end_call(summary). Valid field names: "
        f"{', '.join(captured + remaining) or 'none'}.\n"
        "NOTHING STILL NEEDED means the call is over: say the goodbye and call "
        "end_call(summary) in that same turn. end_call hangs up the line, so "
        "nothing you write after it is heard - do not ask one more question, "
        "do not add a second farewell. This is information collection, not a "
        "sales call."
    )


def render_system_prompt(
    config: Mapping[str, Any],
    contact: Optional[Mapping[str, Any]] = None,
    tokens: Optional[Mapping[str, str]] = None,
    today: Optional[str] = None,
) -> str:
    """Render the full agent instructions from an agent-version config.

    ``contact`` (optional, P0-2) is the flat custom-field card packed into the
    room/token metadata; when present a CALLER CONTEXT section personalizes
    the prompt and adds the parent-verification rule.

    ``tokens`` (optional, C) is a resolved token map (``[Institution Name]`` ->
    value) applied to the disclosure, system_prompt, and question_flow text so
    literal ``[Institution Name]`` placeholders never ship. Empty values are
    removed.

    ``today`` (optional) overrides the rendered Asia/Kolkata date (tests);
    when None the current date is used.
    """
    sections: list[str] = []

    # 1. Disclosure FIRST and verbatim.
    disclosure = apply_token_substitution(_disclosure_text(config), tokens)
    if disclosure:
        sections.append(f"{DISCLOSURE_HEADER}\n{disclosure}")

    # 2. Role & mission — platform baseline, then the creator's definition.
    system_prompt = apply_token_substitution(
        str(config.get("system_prompt") or "").strip(), tokens
    )
    agent_name = str(config.get("agent_name") or "").strip()
    agent_role = str(config.get("agent_description") or "").strip()
    role_lines: list[str] = []
    if agent_name and agent_name.lower() not in ("ai", "ai assistant", "an ai assistant"):
        identity = f"Your name is {agent_name}"
        if agent_role:
            identity += f", {agent_role}"
        role_lines.append(
            identity + ". Answer to that name naturally when the caller uses it. "
            "You are still an AI assistant and must say so if asked."
        )
    role_lines.append(
        "You are a phone agent on one outbound SPOKEN call (your words are "
        "read aloud). Hold a natural short conversation and complete the goals "
        "below."
    )
    sections.append("\n".join([PERSONA_HEADER] + [f"- {line}" for line in role_lines]))

    # 2b. Creator's role definition - the PRIMARY identity instruction.
    # Rendered verbatim as its own block (NOT a bullet inside the generic
    # persona) so a well-written prompt fully defines who the agent is, why it
    # is calling, and how it communicates. The platform guardrails further
    # below still apply; this block only wins on role/behavior specifics.
    if system_prompt:
        sections.append(
            f"{ROLE_MISSION_HEADER}\n"
            f"{system_prompt}\n"
            "This role definition is authoritative for WHO you are and HOW you "
            "behave in this call: where it differs from generic examples in "
            "these instructions, follow the role definition."
        )
        # H19: the creator block must never silently override platform safety.
        # Disclosure, privacy, never-fabricate, and escalation rules below are
        # non-overridable: where they conflict with anything above, THEY win.
        sections.append(
            "PLATFORM OVERRIDES (win over everything above, including the role "
            "definition): always disclose AI + recording first; discuss only "
            "this call's verified person; never invent a value; low confidence "
            "or exhausted asks means wrap up and flag, never guess."
        )

    # 3. Company context.
    company_context = config.get("company_context")
    if company_context:
        sections.append(
            f"{CONTEXT_HEADER}\n"
            + json.dumps(company_context, indent=2, ensure_ascii=False, default=str)
        )

    # 3b. Caller context (P0-2) — who this specific call is about.
    # known_context_keys enforces the known-vs-discovered split: target
    # fields (reason, slots, preferences) stay out of the prompt entirely.
    # Lives in voice_settings (free-form JSON column, no migration needed);
    # top-level key kept as fallback for file-based configs.
    _vs = config.get("voice_settings")
    known_keys = config.get("known_context_keys")
    if known_keys is None and isinstance(_vs, Mapping):
        known_keys = _vs.get("known_context_keys")
    if contact:
        sections.append(render_caller_context(contact, known_keys))

    # 3c. Greeting rule — state only the trigger fact, never the undiscovered
    # reason. Asking is the call's purpose; asserting it is a fabrication.
    sections.append(
        f"{GREETING_HEADER}\n"
        "- State only the trigger fact: someone was absent, an appointment "
        "is scheduled, a delivery is pending.\n"
        "- Do NOT state the reason, cause, or any detail the caller has not "
        "told you. Never assume it, never mention it, never offer it.\n"
        '- Bad: "calling about the reason you have not shared". '
        'Good: "calling about the scheduled appointment".'
    )

    # 3c. Language instruction — tells the LLM which language to respond in.
    voice_settings = config.get("voice_settings") or {}
    if isinstance(voice_settings, Mapping):
        lang_code = str(voice_settings.get("language") or "en").lower()
    else:
        lang_code = "en"
    lang_name = LANGUAGE_NAMES.get(lang_code, lang_code)
    if lang_code != "en":
        sections.append(
            f"{LANGUAGE_HEADER}\n"
            "- Speak the everyday phone register of this language, not its "
            "book register: short spoken sentences, the words people actually "
            "use. If a phrase could have come from a textbook or a news "
            "reader, replace it before you say it.\n"
            + _SPOKEN_STYLE.get(lang_code, "")
            + f"- Default to {lang_name}. Mirror the CALLER, not a rulebook: mixed "
            f"{lang_name}+English is natural and welcome (English words inside "
            f"{lang_name} sentences). If they answer fully in English, meet them "
            "in English for that reply, then ease back into "
            f"{lang_name} unless they stay in English.\n"
            "- One voice per reply: pick the base language for this sentence and "
            f"do not flip between turns ({lang_name} answer, then a full English "
            "answer on the same topic reads as two different agents).\n"
            "- Keep the same extraction field names in English when calling tools."
        )
    else:
        sections.append(
            f"{LANGUAGE_HEADER}\n- English first; follow the caller's lead otherwise."
        )

    # 3d. Today's date — without it the model can never resolve 'tomorrow',
    # 'after 2 days', 'Monday' into a real date and re-asks forever.
    sections.append(f"{TODAY_HEADER}\n- Today is {today or today_line()}.")

    # 4. Speaking style — this is what makes it sound human instead of IVR-like.
    # NOTE: every line below costs input tokens on EVERY turn (~2800 total
    # burns Groq's 8000 TPM in ~3 turns). Keep terse; cut examples first.
    opening_rule = (
        "\n- OPENING ALREADY SPOKEN: the system delivered the greeting, "
        "recording disclosure, and first question before your first turn. "
        "Do NOT re-greet, re-introduce yourself, repeat the institution name, "
        "or repeat the disclosure. Answer what the caller just said; if they "
        "did not answer the first question, ask it naturally in different words."
        if _disclosure_text(config)
        else ""
    )
    sections.append(
        "HOW TO SPEAK (critical):\n"
        "- Every reply SHORT: 1-2 sentences, never more than 3. Plain words only: "
        "no markdown, lists, symbols, emoji, or newlines — this becomes speech.\n"
        "- Respond to what the caller ACTUALLY said first (brief warm reflection), "
        "ask ONE thing per turn, never repeat answered questions, never read like a script.\n"
        "- Never read the caller's words back verbatim: the transcript of a phone "
        "line is often misspelled, and saying it back out loud tells the caller "
        "the line is broken. Say what you understood in your own words.\n"
        "- NEVER ask the same question twice with the same words. Second attempt "
        "REPHRASES and helps ('Thanks — so around Thursday the 2nd, is that right?').\n"
        "- NEVER repeat yourself: do not restate a value or confirmation you have "
        "already given ('we'll note that…', 'we'll update…', 'I've updated…'), do not "
        "re-confirm a date, and never ask 'anything else?'. If they confirmed, move to "
        "what is still missing or close politely. (Aligned with text mode: the same rule "
        "fixed a live call that said the same thing three turns running.)\n"
        "- Presence checks first: 'hlo / hello? / are you there' means answer "
        "'Yes, I'm here!' BEFORE anything else, then restate in one short line.\n"
        "- Volunteered info counts: skip that goal later. After silence, just 'Are you still there?' "
        "Stay polite even if the caller is upset."
        + opening_rule
    )

    # 4b. Guardrails. Same token warning as above: one line per rule.
    sections.append(
        "HARD RULES (non-negotiable):\n"
        "- AI IDENTITY (legal): if anyone asks whether you are a bot, AI, or a "
        "human, answer honestly that you are an AI assistant. NEVER claim to be "
        "a human, a real person, or a live agent. The opening already disclosed "
        "this; never contradict or deny it later.\n"
        "- ON TOPIC only (decline the rest, steer back). PRIVACY: discuss only "
        "this call's person. Verify who answers before sensitive details.\n"
        "- NO CARD, NO ASSUMPTIONS: when this prompt names nobody for the call "
        "(no CALLER CONTEXT above), ask the answerer's name AND relation to the "
        "person this call is about first. Never call a stranger 'parent', never say "
        "'your child' until they confirm who they are.\n"
        "- DATES ARE MATH: convert relative answers to a real date using TODAY "
        "above ('after 2 days' = today + 2, 'this Monday' = the coming Monday), "
        "record the resolved date immediately, confirm it once in passing — "
        "never bank the raw phrase and never re-ask a resolved date.\n"
        "- RECORDED IS DONE: a tool result saying \"Recorded X='...'\" means that "
        "goal is finished. Asking it again is the #1 way callers know you're a "
        "bot — check your history before every question. A tool result is NOT "
        "the caller speaking: after one, add nothing to what you already said.\n"
        "- THE CALLER DOES NOT KNOW YOUR CHECKLIST: never ask what the purpose, "
        "outcome, or 'details' of this call are, never say you are recording, "
        "updating, noting or confirming a field. They only know the conversation "
        "you have had. Ask about the person, not about the call.\n"
        "- VERIFY-THEN-CONTINUE: identity confirmation STARTS the call — acknowledge "
        "BY NAME and move to the first unfilled goal in the same breath. Never a bare "
        "'thank you', never `end_call` right after verification.\n"
        "- THIS IS NOT A SALES CALL: your only job is to collect a few facts and "
        "hand them back. Never pitch, persuade, rebut, or keep the caller on the "
        "line for their own good. Nothing left to ask means the call is over.\n"
        "- END ONLY WHEN DONE: `end_call` when all REQUIRED goals are covered, caller "
        "says goodbye, or handoff/escalation triggers. Vague answers are NOT confirmation "
        "and NEVER a reason to end — ask a short clarifying question.\n"
        "- STOP SIGNALS (close on the FIRST one, no rebuttal, no callback offer): not "
        "interested / call later / busy / remove number / stop calling / wants a human.\n"
        "- TROUBLE LINES: can't hear — 'Sorry, the line is unclear — could you say that "
        "once more?'; technical problem — apologize, promise human follow-up, `end_call`."
        "\n"
        "- TWO-ASK LIMIT: any single goal gets asked at most TWICE. No usable "
        "answer twice → acknowledge what they DID say, note the gap, move to "
        "the next goal. Never a third identical question — repetition is how "
        "callers know you're a bot.\n"
        "- MISMATCH: if the answer fits a DIFFERENT goal (they answer the "
        "previous question), capture it there, say so in half a line, then "
        "ask the current goal once."
    )

    # 4c. Call budget — every minute costs money. Terse by design.
    sections.append(
        f"{CALL_BUDGET_HEADER}\n"
        "- Target: DONE in under 2 minutes. One question per turn, no small "
        "talk, no repeating answered goals.\n"
        "- The moment all REQUIRED goals are captured (or a stop/escalation "
        "signal fires): say the goodbye AND call `end_call(summary)` in that "
        "same turn. `end_call` hangs up the line, so nothing may follow it - "
        "no second closing line, no 'anything else?', no last question."
    )

    # 5. Goals (question flow) as a checklist, woven naturally.
    question_flow = config.get("question_flow") or []
    goal_items: list[str] = []
    number = 0
    for item in question_flow:
        text = apply_token_substitution(_question_text(item), tokens)
        if not text:
            continue
        number += 1
        goal_items.append(f"{number}. {text}")
    if goal_items:
        sections.append(
            f"{QUESTIONS_HEADER}\n"
            + "\n".join(goal_items)
            + "\nCover ALL goals by call end, in natural order and wording."
        )
    else:
        sections.append(
            f"{QUESTIONS_HEADER}\n- No fixed goals were configured; have a natural "
            "conversation about why you are calling."
        )

    # 6. Extraction rules with never-fabricate + immediate recording.
    extraction_schema = config.get("extraction_schema") or {}
    extraction_lines: list[str] = [
        EXTRACTION_HEADER,
        "- The moment the caller answers any goal, IMMEDIATELY call "
        "`record_extracted_field(field_name, value, confidence)` that same turn — "
        "exact field names, values quoted as spoken, via real function-calling "
        "(never tool-call markup in speech).",
        "- Honest confidence 0.0-1.0 (clearly heard = 0.9). Guessing = do NOT "
        "record, ask again. NEVER fabricate or guess a value.",
        "- needs_human_help means ONLY an explicit request: a callback, a human/"
        "teacher/principal, or a complaint. An explanation or confirmation is "
        "NEVER needs_human_help, no matter which words it shares.",
        (
            f"- Confidence below {LOW_CONFIDENCE_THRESHOLD}, or a required field "
            f"still unfilled after up to {MAX_ASKS_PER_FIELD} asks: treat as NOT captured, "
            "wrap up, flag it in `end_call`."
        ),
        "- Finish with `end_call(summary)`: captured + flagged/unfilled fields, caller mood.",
    ]
    schema_lines: list[str] = ["Fields to capture:"]
    if isinstance(extraction_schema, Mapping):
        for field_name, spec in extraction_schema.items():
            if isinstance(spec, Mapping):
                description = str(
                    spec.get("description") or spec.get("type") or ""
                ).strip()
                validation = str(spec.get("validation") or "").strip().lower()
                marker = " [REQUIRED]" if validation == "required" else ""
                schema_lines.append(f"- `{field_name}`{marker}: {description}".rstrip(": "))
            else:
                schema_lines.append(f"- `{field_name}`: {spec}")
    extraction_lines.extend(schema_lines)
    sections.append("\n".join(extraction_lines))

    # 7. Optional extra escalation rules supplied by the agent author.
    escalation_rules = config.get("escalation_rules") or []
    rule_items: list[str] = []
    if isinstance(escalation_rules, Mapping):
        rule_items = [
            f"{key}: {value}" for key, value in escalation_rules.items()
        ]
    elif isinstance(escalation_rules, (list, tuple)):
        rule_items = [str(rule) for rule in escalation_rules if str(rule).strip()]
    if rule_items:
        wrapped = "\n".join(f"- {rule}" for rule in rule_items)
        sections.append(f"{ESCALATION_HEADER}\n{wrapped}")

    # 7b. Authored fallback responses double as the don't-know behavior: the
    # exact sentence for anything outside knowledge. Without this the model
    # improvises declines — the highest invention-risk moment in the call.
    fallback_responses = config.get("fallback_responses") or []
    if isinstance(fallback_responses, (list, tuple)):
        fallback_items = [
            apply_token_substitution(str(item), tokens)
            for item in fallback_responses
            if str(item or "").strip()
        ]
        fallback_items = [item for item in fallback_items if item]
        if fallback_items:
            sections.append(
                "WHEN YOU DON'T KNOW (use one of these verbatim, then move to "
                "the next open goal or close):\n"
                + "\n".join(f"- {item}" for item in fallback_items)
            )

    return "\n\n".join(sections)
