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

from typing import Any

from app.prompting import render_compact_instructions, render_system_prompt


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
