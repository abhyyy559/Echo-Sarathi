"""Conversation-repair rules: today's date, no-reask, rephrase, presence-first."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app import pipeline as pipeline_module
from app.prompting import build_opening_line, render_system_prompt, today_line

BASE_CONFIG: dict[str, Any] = {
    "system_prompt": "You call parents about absence.",
    "disclosure_script": "Hello, this is an AI assistant. This call is recorded.",
    "question_flow": [{"step": 1, "question": "Why was the student absent?"}],
    "extraction_schema": {
        "reason_for_absence": {
            "type": "string",
            "description": "Reason.",
            "validation": "required",
            "confidence_threshold": 0.8,
        }
    },
    "escalation_rules": ["Caller is angry."],
}


def test_today_line_renders_weekday_explicit() -> None:
    now = datetime(2026, 9, 28, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert today_line(now=now) == "Monday, 28 September 2026"


def test_today_line_bad_zone_falls_back_to_utc() -> None:
    now = datetime(2026, 9, 28, 10, 30, tzinfo=ZoneInfo("UTC"))
    assert today_line(timezone_name="Not/AZone", now=now) == "Monday, 28 September 2026"


def test_prompt_carries_date_and_repair_rules() -> None:
    prompt = render_system_prompt(BASE_CONFIG, today="Monday, 28 September 2026")
    assert "Today is Monday, 28 September 2026." in prompt
    assert "RECORDED IS DONE" in prompt
    assert "DATES ARE MATH" in prompt
    assert "Yes, I'm here!'" in prompt
    assert "NO CARD, NO ASSUMPTIONS" in prompt
    assert "NEVER ask the same question twice with the same words" in prompt


def test_opts_drops_unknown_fields_for_other_versions() -> None:
    class _Newer:
        __annotations__ = {"a": int}

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    built = pipeline_module._opts(_Newer, a=1, min_words=2)
    assert built.kwargs == {"a": 1}


def test_opts_falls_back_to_defaults_on_type_error() -> None:
    class _Picky:
        __annotations__ = {"a": int}

        def __init__(self, **kwargs: Any) -> None:
            if kwargs:
                raise TypeError("nope")
            self.kwargs = kwargs

    built = pipeline_module._opts(_Picky, a=1)
    assert built.kwargs == {}


def test_verify_opener_skips_redundant_greeting() -> None:
    """Parent-named Q1 (v3 flow): opening is disclosure + question only."""
    config = dict(BASE_CONFIG)
    config["question_flow"] = [
        {
            "step": 1,
            "question": "Am I speaking with [Parent/Guardian Name], parent of [Student Name]?",
        }
    ]
    tokens = {
        "[Institution Name]": "CMR College",
        "[Parent/Guardian Name]": "Suresh",
        "[Student Name]": "Aarav",
    }
    contact = {"parent_name": "Suresh", "student_name": "Aarav"}
    opening = build_opening_line(config, tokens, contact)
    assert opening.count("Suresh") == 1, f"name must not repeat: {opening}"
    assert "Am I speaking with Suresh" in opening
    assert len(opening.split()) <= 45, "opening must stay under ~20s of speech"
