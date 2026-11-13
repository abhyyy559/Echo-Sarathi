"""Spoken register: the Telugu agent must sound like a caller, not a textbook.

The user's verdict on the live Telugu call was that the agent spoke
"ancient Telugu which even I don't know" while the English call was good. The
LLM writes the reply itself - there is no translation stage - and a model told
only "respond in Telugu" picks the literary (granthik) register its training
data is written in. The register therefore needs a positive example, a named
counter-example, and it must survive the mid-call switch to compact
instructions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.prompting import (
    build_opening_line,
    build_token_map,
    render_compact_instructions,
    render_system_prompt,
)


def _config(language: str) -> dict[str, Any]:
    return {
        "disclosure_script": "ఈ కాల్ రికార్డ్ అవుతుంది." if language == "te" else "This call is recorded.",
        "system_prompt": "You are a college office assistant following up on an absence.",
        "question_flow": ["Why was the student absent today?"],
        "extraction_schema": {
            "reason_for_absence": {
                "type": "string",
                "required": True,
                "description": "Reason given for the absence.",
            }
        },
        "voice_settings": {"language": language},
    }


def test_telugu_prompt_names_the_book_register_as_wrong() -> None:
    prompt = render_system_prompt(_config("te"))
    assert "book register" in prompt
    assert "Never hunt for a Sanskrit or classical synonym" in prompt
    # A model steers on the example, not the adjective.
    assert "అర్థమైంది — fever వల్ల కాలేజ్‌కి రాలేదు కదా" in prompt


def test_english_prompt_gets_no_indic_register_block() -> None:
    prompt = render_system_prompt(_config("en"))
    assert "book register" not in prompt


def test_telugu_replies_default_to_tenglish_before_the_caller_mixes() -> None:
    prompt = render_system_prompt(_config("te"))
    assert "Default to natural Tenglish" in prompt
    assert "even when the caller uses only Telugu" in prompt
    assert "Telugu script" in prompt
    assert "English words in English" in prompt
    assert "Stay in English while they continue in English" in prompt
    assert "Default to Telugu." not in prompt
    assert "caller used an English word" not in prompt
    assert "site visit" in prompt
    assert "Examples show style, not facts about this call" in prompt


def test_compact_instructions_carry_the_register_mid_call() -> None:
    compact = render_compact_instructions(
        ["reason_for_absence"], [], "Monday 22 December 2026", "te"
    )
    assert "everyday spoken Telugu" in compact
    assert "fever" in compact

    english = render_compact_instructions(
        [], ["reason_for_absence"], "Monday 22 December 2026", "en"
    )
    assert "everyday spoken" not in english


def test_tenglish_default_survives_prompt_compaction_without_mirroring_conflicts() -> None:
    compact = render_compact_instructions(
        ["reason_for_absence"], ["expected_return_date"], language="te"
    )
    assert "Default to natural Tenglish" in compact
    assert "even when the caller uses only Telugu" in compact
    assert "Stay in English while they continue in English" in compact
    assert "code-switch only as they do" not in compact
    assert "words exactly as the caller mixes them" not in compact
    assert "go back afterwards" not in compact
    assert "Already recorded: reason_for_absence" in compact
    assert "Still needed: expected_return_date" in compact


def test_absence_preset_uses_tenglish_and_one_question_per_step() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "domain-configs/presets/absent-student-followup-telugu.json"
    )
    config = json.loads(path.read_text(encoding="utf-8"))["version_payload"]
    contact = {"student_name": "Aarav", "parent_name": "Lakshmi"}
    tokens = build_token_map(
        contact=contact, context={"institution_name": "Demo College"}, agent_name="Sahithi"
    )
    opening = build_opening_line(config, tokens, contact)
    assert opening.startswith(
        "హాయ్, నేను Sahithi, Demo College నుండి AI అసిస్టెంట్. ఈ కాల్ రికార్డ్ అవుతుంది."
    )
    assert "Aarav ఈరోజు college‌కి ఎందుకు రాలేదు?" in opening
    assert opening.count("హాయ్") == 1
    assert "Hi " not in opening
    assert opening.count("?") == 1
    assert all(step["question"].count("?") == 1 for step in config["question_flow"])
    assert config["question_flow"][2]["question"] == "Doctor certificate submit చేశారా?"
    prompt = render_system_prompt(config, contact=contact, tokens=tokens)
    assert "Default to natural Tenglish" in prompt
    assert "తెలుగు అంటే తెలుగు" not in prompt
    assert "కాలర్ వాడే English words" not in prompt


def test_tenglish_closes_without_promising_unavailable_actions() -> None:
    full = render_system_prompt(_config("te"))
    compact = render_compact_instructions(["reason_for_absence"], [], language="te")
    for prompt in (full, compact):
        assert "Never promise or claim a message, update or follow-up" in prompt
        assert "Answer the caller's question from known facts" in prompt
        assert "సరే అండి, Thanks. బై." in prompt
        assert "end_call(summary)" in prompt
        assert "I'll make sure the right person follows up" not in prompt
        assert "promise human follow-up" not in prompt
        assert "one half-line on what happens next" not in prompt
