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
from typing import Any, Mapping, Optional

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
QUESTIONS_HEADER = "YOUR GOALS - information to collect during the call:"
EXTRACTION_HEADER = "RECORDING ANSWERS - extraction discipline:"
ESCALATION_HEADER = "WHEN TO WRAP UP:"

LANGUAGE_NAMES = {"en": "English", "te": "Telugu", "hi": "Hindi"}

_BRACKET_ARTIFACT_RE = re.compile(r"\[[^\]]*\]")
_DOUBLE_SPACE_RE = re.compile(r"\s{2,}")

_TOOL_BLOCK_RE = re.compile(
    r"<tool_call>.*?</tool_call>|<function=[^>]*>|<parameter=[^>]*>",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_CALLS_JSON_RE = re.compile(r'"[^"]*tool_calls[^"]*"\s*:\s*\[.*?\]', re.DOTALL)


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


def build_token_map(
    contact: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
    agent_name: str = "",
) -> dict[str, str]:
    """Resolve known placeholder tokens to real values for this call.

    ``contact`` is the contact card packed in room/token metadata; ``context``
    is the backend's call-context JSON (institution_name + optional contact).
    ``[Expected Return Date]`` has no data source, so it maps to "" (dropped).

    ``agent_name`` fills ``[Agent Name]``; empty falls back to
    "an AI assistant" so disclosures never dangle.
    """
    ctx = context if isinstance(context, Mapping) else {}
    ctx_contact = ctx.get("contact") if isinstance(ctx.get("contact"), Mapping) else {}
    institution = str(ctx.get("institution_name") or "").strip()
    name = _first_name(contact, ctx_contact)
    who = str(agent_name or "").strip() or "an AI assistant"
    return {
        "[Institution Name]": institution,
        "[Company Name]": institution,
        "[Student Name]": name,
        "[Lead Name]": name,
        "[Patient Name]": name,
        "[Parent/Guardian Name]": name,
        "[Agent Name]": who,
        "[Doctor Name]": _known_field(contact, ctx_contact,
                                      keys=("doctor_name", "doctor")),
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
    disclosure = apply_token_substitution(_disclosure_text(config), tok)
    if not disclosure:
        return ""
    card = contact if isinstance(contact, Mapping) else {}
    parent = _card_value(card, _CARD_PARENT_KEYS)
    subject = _card_value(card, _CARD_SUBJECT_KEYS)
    institution = tok.get("[Institution Name]", "") or tok.get("[Company Name]", "")
    # The disclosure script usually names the institution already — repeating
    # it in the greeting doubles ~15 words of TTS (~4s) for zero information.
    if institution and institution.lower() in disclosure.lower():
        institution = ""
    who = tok.get("[Agent Name]", "") or "an AI assistant"
    # Redundancy elimination: the disclosure usually already says who is
    # calling and from where — repeating either doubles TTS seconds for zero
    # information (callers experience it as the agent "taking forever").
    # The greeting carries only genuinely new information.
    if who not in disclosure:
        intro = f"This is {who} calling"
        if institution:
            intro += f" from {institution}"
        intro += "."
    elif institution:
        intro = f"Calling from {institution}."
    else:
        intro = ""
    # Short standalone sentences (not one long clause): the TTS engine
    # synthesizes sentence by sentence, so names get clean prosodic breaks
    # and are pronounced far more clearly than mid-sentence.
    if parent and subject and parent != subject:
        greet = f"Hello {parent}."
        if intro:
            greet += f" {intro}"
        greet += f" I'm calling about {subject}."
    elif subject:
        greet = f"Hello {subject}."
        if intro:
            greet += f" {intro}"
    elif intro:
        greet = f"Hello. {intro}"
    else:
        greet = "Hello."
    first_question = ""
    flow = config.get("question_flow") if isinstance(config, Mapping) else []
    if isinstance(flow, list):
        for item in flow:
            text_value = apply_token_substitution(_question_text(item), tok)
            if text_value:
                first_question = text_value
                break
    opening = f"{disclosure} {greet}"
    if first_question:
        opening += f" {first_question}"
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
                "available, thank them politely, say goodbye, and end the call."
            ),
        ]
    )
    return "\n".join(lines)


def render_system_prompt(
    config: Mapping[str, Any],
    contact: Optional[Mapping[str, Any]] = None,
    tokens: Optional[Mapping[str, str]] = None,
) -> str:
    """Render the full agent instructions from an agent-version config.

    ``contact`` (optional, P0-2) is the flat custom-field card packed into the
    room/token metadata; when present a CALLER CONTEXT section personalizes
    the prompt and adds the parent-verification rule.

    ``tokens`` (optional, C) is a resolved token map (``[Institution Name]`` ->
    value) applied to the disclosure, system_prompt, and question_flow text so
    literal ``[Institution Name]`` placeholders never ship. Empty values are
    removed.
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
    role_lines: list[str] = [
        "You are a human-sounding phone agent on one outbound SPOKEN call "
        "(your words are read aloud). Hold a natural short conversation and "
        "complete the goals below.",
    ]
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
            f"- The caller speaks {lang_name}. Respond entirely in {lang_name}.\n"
            "- If the caller code-switches (mixes languages mid-sentence), "
            f"follow their lead: reply in {lang_name} but accept words from any language.\n"
            "- Keep the same extraction field names in English when calling tools."
        )
    else:
        sections.append(
            f"{LANGUAGE_HEADER}\n- English first; follow the caller's lead otherwise."
        )

    # 4. Speaking style — this is what makes it sound human instead of IVR-like.
    # NOTE: every line below costs input tokens on EVERY turn (~2800 total
    # burns Groq's 8000 TPM in ~3 turns). Keep terse; cut examples first.
    sections.append(
        "HOW TO SPEAK (critical):\n"
        "- Every reply SHORT: 1-2 sentences, never more than 3. Plain words only: "
        "no markdown, lists, symbols, emoji, or newlines — this becomes speech.\n"
        "- Respond to what the caller ACTUALLY said first (brief warm reflection), "
        "ask ONE thing per turn, never repeat answered questions, never read like a script.\n"
        "- Volunteered info counts: skip that goal later. After silence, just 'Are you still there?' "
        "Stay polite even if the caller is upset."
    )

    # 4b. Guardrails. Same token warning as above: one line per rule.
    sections.append(
        "HARD RULES (non-negotiable):\n"
        "- ON TOPIC only (decline the rest, steer back). PRIVACY: discuss only "
        "this call's person. Verify who answers before sensitive details.\n"
        "- VERIFY-THEN-CONTINUE: identity confirmation STARTS the call — acknowledge "
        "BY NAME and move to the first unfilled goal in the same breath. Never a bare "
        "'thank you', never `end_call` right after verification.\n"
        "- END ONLY WHEN DONE: `end_call` when all REQUIRED goals are covered, caller "
        "says goodbye, or handoff/escalation triggers. Vague answers are NOT confirmation "
        "and NEVER a reason to end — ask a short clarifying question.\n"
        "- STOP SIGNALS (one closing line, then `end_call`, no further questions): not "
        "interested / call later / busy / remove number / stop calling / wants a human. "
        "If busy, offer the callback first.\n"
        "- TROUBLE LINES: can't hear — 'Sorry, the line is unclear — could you say that "
        "once more?'; technical problem — apologize, promise human follow-up, `end_call`."
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

    return "\n\n".join(sections)
