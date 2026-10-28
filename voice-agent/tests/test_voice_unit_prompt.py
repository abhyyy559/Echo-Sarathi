"""Offline UNIT tests for app.prompting.render_system_prompt (Lane B).

Complements the Lane E contract suite in test_prompt_render.py with
implementation-level assertions. Renamed file avoids clobbering the
plan-shared filename while lanes land concurrently.
"""

from __future__ import annotations

from typing import Any, Dict

from app.prompting import (
    DISCLOSURE_HEADER,
    EXTRACTION_HEADER,
    PERSONA_HEADER,
    QUESTIONS_HEADER,
    render_system_prompt,
)

BASE_CONFIG: Dict[str, Any] = {
    "disclosure_script": (
        "Hello, I am calling from Acme Academy. I am an AI voice assistant. "
        "This call is recorded for quality and verification purposes."
    ),
    "system_prompt": (
        "You are an AI voice assistant representing Acme Academy. Your role is "
        "to contact parents or guardians of absent students."
    ),
    "company_context": {"company_name": "Acme Academy", "timezone": "Asia/Kolkata"},
    "question_flow": [
        {"step": 1, "question": "Could you share the reason for the absence?"},
        {"step": 2, "question": "Do you expect the student to return tomorrow?"},
        {"step": 3, "question": "Is the absence due to a medical reason?"},
    ],
    "extraction_schema": {
        "reason_for_absence": {
            "type": "string",
            "description": "Reason provided for the absence.",
            "validation": "required",
            "confidence_threshold": 0.8,
        },
        "is_sick_leave": {"type": "boolean", "description": "Illness-related.", "validation": "optional"},
    },
}


def test_disclosure_is_first_block() -> None:
    rendered = render_system_prompt(BASE_CONFIG)

    assert rendered.lstrip().startswith(DISCLOSURE_HEADER.split(" - ")[0])
    disclosure_text = BASE_CONFIG["disclosure_script"]
    assert rendered.index(disclosure_text) < rendered.index(PERSONA_HEADER)
    assert rendered.index(disclosure_text) < rendered.index(QUESTIONS_HEADER)
    assert rendered.index(disclosure_text) < rendered.index(EXTRACTION_HEADER)


def test_questions_are_numbered_in_order() -> None:
    rendered = render_system_prompt(BASE_CONFIG)

    questions_header_at = rendered.index(QUESTIONS_HEADER)
    extraction_at = rendered.index(EXTRACTION_HEADER)
    flow_block = rendered[questions_header_at:extraction_at]
    assert "1. Could you share the reason for the absence?" in flow_block
    assert "2. Do you expect the student to return tomorrow?" in flow_block
    assert "3. Is the absence due to a medical reason?" in flow_block
    # Order must be ascending.
    assert flow_block.index("1. ") < flow_block.index("2. ") < flow_block.index("3. ")
    # The provided step numbers are ignored; numbering is positional 1..n.
    assert "step" not in flow_block


def test_escalation_and_never_fabricate_text_present() -> None:
    rendered = render_system_prompt(BASE_CONFIG)
    lowered = rendered.lower()

    assert "never fabricate" in lowered
    assert "0.6" in rendered  # low-confidence escalation threshold
    assert "3 times" in lowered or "up to 3" in lowered  # max asks
    assert "flag" in lowered  # flagged wrap-up requirement


def test_ai_identity_rule_is_explicit_for_every_provider() -> None:
    """Recorded calls in India require an honest answer when asked whether
    this is a bot. The rule lives in the shared prompt, so it applies to
    Qwen, GPT-OSS, and Sarvam alike - not just the overflow provider."""
    rendered = render_system_prompt(BASE_CONFIG)
    lowered = rendered.lower()

    assert "ai identity" in lowered
    assert "answer honestly that you are an ai assistant" in lowered
    assert "never claim to be a human" in lowered


def test_opening_is_not_replayed_after_system_greeting() -> None:
    """The pipeline speaks build_opening_line() before the first LLM turn.
    Without this rule the model re-greets, repeats the recording disclosure,
    and re-asks the first question - the "Hello... Hello..." monologue."""
    rendered = render_system_prompt(BASE_CONFIG)
    lowered = rendered.lower()

    assert "opening already spoken" in lowered
    assert "do not re-greet" in lowered
    assert "repeat the disclosure" in lowered

    # No disclosure means the pipeline has no deterministic opening, so the
    # model must still greet on its own. The rule must not be emitted there.
    no_disclosure: Dict[str, Any] = dict(BASE_CONFIG)
    no_disclosure.pop("disclosure_script", None)
    no_disclosure.pop("mandatory_disclosure", None)
    assert "opening already spoken" not in render_system_prompt(no_disclosure).lower()


# ---------------------------------------------------------------------------
# Creator role definition (prompt-driven agents): the user's system_prompt is
# the authoritative ROLE & MISSION block, rendered verbatim - not a bullet.
# ---------------------------------------------------------------------------
LEAD_VERIFICATION_PROMPT = (
    "# ROLE\n"
    "You are a lead verification agent for EduPro Learning. You call people "
    "who filled the 'Free Demo Class' form on our website.\n"
    "# OBJECTIVE\n"
    "Confirm they are interested in the demo class, verify the details they "
    "submitted (name, city, preferred timing), and flag genuine interest for "
    "the sales team.\n"
    "# DO NOT\n"
    "- Never offer discounts or promise placements.\n"
    "- If they say they did not fill any form, apologise and end the call."
)


def test_creator_prompt_rendered_verbatim_as_own_block() -> None:
    config = dict(BASE_CONFIG)
    config["system_prompt"] = LEAD_VERIFICATION_PROMPT

    rendered = render_system_prompt(config)

    # Own block with its own header, not a "- Agent-specific role ..." bullet.
    assert "ROLE & MISSION - defined by the agent creator" in rendered
    assert "Agent-specific role from the creator" not in rendered
    # Verbatim, multi-line, including the section markers the author wrote.
    assert LEAD_VERIFICATION_PROMPT in rendered
    # Authoritative precedence is stated once for the model.
    assert "authoritative" in rendered.lower()


def test_creator_prompt_absent_means_no_role_block() -> None:
    config = dict(BASE_CONFIG)
    config["system_prompt"] = ""

    rendered = render_system_prompt(config)

    assert "ROLE & MISSION - defined by the agent creator" not in rendered


def test_required_fields_marked_in_schema_block() -> None:
    rendered = render_system_prompt(BASE_CONFIG)
    schema_block = rendered[rendered.index(EXTRACTION_HEADER):]

    assert "`reason_for_absence` [REQUIRED]" in schema_block
    assert "`is_sick_leave`" in schema_block
    assert "[REQUIRED]" not in schema_block.split("`is_sick_leave`")[1].split("\n")[0]


def test_derived_fields_are_never_asked_of_the_caller() -> None:
    """Call 96 asked the parent "May I know the outcome" because call_outcome
    rendered as a [REQUIRED] goal. Derived fields are decided by the agent at
    close, so the schema block must say so instead of demanding an answer."""
    config = dict(BASE_CONFIG)
    config["extraction_schema"] = {
        **BASE_CONFIG["extraction_schema"],
        "call_outcome": {
            "type": "string",
            "description": "What happened on the call.",
            "validation": "required",
        },
    }

    rendered = render_system_prompt(config)
    schema_block = rendered[rendered.index(EXTRACTION_HEADER):]
    outcome_line = schema_block.split("`call_outcome`")[1].split("\n")[0]

    assert "NEVER ask the caller" in outcome_line
    assert "[REQUIRED]" not in outcome_line


def test_derived_fields_are_not_required_from_the_caller() -> None:
    """Same defect from the collection side: the worker's required set drove
    the wrap-up and the "Unfilled required fields" flag on call 96."""
    from app.pipeline import _required_fields_from_schema

    required = _required_fields_from_schema(
        {
            "extraction_schema": {
                "reason_for_absence": {"validation": "required"},
                "call_outcome": {"validation": "required"},
                "is_sick_leave": {"validation": "optional"},
            }
        }
    )

    assert required == frozenset({"reason_for_absence"})


def test_legacy_mandatory_disclosure_key_supported() -> None:
    legacy: Dict[str, Any] = dict(BASE_CONFIG)
    del legacy["disclosure_script"]
    legacy["mandatory_disclosure"] = "Legacy disclosure sentence."

    rendered = render_system_prompt(legacy)

    assert rendered.lstrip().startswith(
        DISCLOSURE_HEADER.split(" - ")[0]
    ), "disclosure block must still come first"
    assert rendered.index("Legacy disclosure sentence.") < rendered.index(PERSONA_HEADER)


def test_empty_question_flow_renders_without_crash() -> None:
    minimal = {"disclosure_script": "Hi.", "question_flow": []}
    rendered = render_system_prompt(minimal)
    assert "Hi." in rendered
