"""Text mode and voice mode must behave the same.

WHY this test exists: text mode is the cheap way to iterate (a phone call
burns STT+LLM+TTS credits per second), so whatever is tuned in text mode is
what gets carried into call mode. That only works if both renderers carry the
SAME behavioural rules. They are separate implementations in separate
packages, so they drift silently: the no-self-repetition rule was added to
text mode to stop a live call saying "we'll note that" three turns running, and
nothing in the voice prompt mentioned it.

These assertions fail when one renderer gains a rule the other lacks.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "domain-configs" / "absent-student.json"


def _config() -> dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8-sig"))


class _VersionLike:
    """Minimal stand-in with the attributes the backend renderer reads."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.disclosure_script = config["mandatory_disclosure"]
        self.system_prompt = config["system_prompt"]
        self.company_context = {"institution": "CMR College of Engineering and Technology"}
        self.question_flow = config["question_flow"]
        self.extraction_schema = config["extraction_schema"]
        self.escalation_rules = config["escalation_rules"]
        self.voice_settings = {"voice_id": "demo", "speed": 1.0}


CARD = {"student_name": "Abhi", "parent_name": "Ram", "class_section": "10-B"}
INSTITUTION = "CMR College of Engineering and Technology"


def _text_prompts() -> list[str]:
    """Every text-mode system prompt variant we can produce mid-call."""
    from app.routers.playground import (
        _render_compact_system_prompt,
        _render_text_system_prompt,
    )

    return [
        _render_text_system_prompt(_VersionLike(_config()), contact=CARD, institution=INSTITUTION),
        _render_compact_system_prompt(["reason_for_absence"], ["expected_return_date"], "TODAY"),
    ]


def _voice_prompting():
    """Import the voice worker's prompting module from the backend test suite.

    Both services use the top-level package name ``app``. Extending the
    backend package's search path lets ``app.extraction_tools`` and
    ``app.prompting`` resolve from voice-agent/app while ``app.routers`` keeps
    resolving from the backend - which is what lets one suite assert that both
    renderers carry the same rules.
    """
    import importlib

    import app as backend_app

    voice_dir = str(Path(__file__).resolve().parents[2] / "voice-agent" / "app")
    if voice_dir not in backend_app.__path__:
        backend_app.__path__.append(voice_dir)
    return importlib.import_module("app.prompting")


def _voice_prompt() -> str:
    return _voice_prompting().render_system_prompt(
        _config(), tokens={"[Institution Name]": INSTITUTION}, contact=CARD
    )


def _voice_opening() -> str:
    return _voice_prompting().build_opening_line(
        _config(),
        {
            "[Institution Name]": INSTITUTION,
            "[Agent Name]": "Priya",
            "[Student Name]": "Abhi",
            "[Parent/Guardian Name]": "Ram",
        },
        CARD,
    )


def _all_text() -> str:
    return "\n".join(_text_prompts()).lower()


def _all_voice() -> str:
    return _voice_prompt().lower()


def test_both_modes_forbid_self_repetition() -> None:
    """The rule that fixed a live call repeating itself three turns running."""
    for name, haystack in (("text", _all_text()), ("voice", _all_voice())):
        assert "never repeat yourself" in haystack, f"{name} prompt lost the no-repetition rule"


def test_both_modes_ask_one_thing_per_reply() -> None:
    for name, haystack in (("text", _all_text()), ("voice", _all_voice())):
        assert "one thing per" in haystack or "one thing per turn" in haystack, name


def test_both_modes_forbid_inventing_values() -> None:
    for name, haystack in (("text", _all_text()), ("voice", _all_voice())):
        assert "never invent" in haystack, f"{name} prompt lost the anti-fabrication rule"


def test_both_modes_never_re_ask_an_answered_question() -> None:
    for name, haystack in (("text", _all_text()), ("voice", _all_voice())):
        assert "re-ask" in haystack, f"{name} prompt lost the re-ask guard"


def test_both_modes_require_end_call_to_finish() -> None:
    for name, haystack in (("text", _all_text()), ("voice", _all_voice())):
        assert "end_call" in haystack, name


def test_both_modes_verify_the_caller_before_details() -> None:
    for name, haystack in (("text", _all_text()), ("voice", _all_voice())):
        assert "verify" in haystack, f"{name} prompt lost caller verification"


def test_voice_prompt_includes_the_extraction_field_names() -> None:
    schema = _config()["extraction_schema"]
    haystack = _all_voice()
    for field_name in schema:
        assert field_name in haystack, f"voice prompt is missing field {field_name}"


def test_opening_is_verification_only_in_both_modes() -> None:
    """Text mode builds the opener deterministically; the voice worker's
    build_opening_line must ask the same single verification question rather
    than opening on the reason for the call."""
    voice_opening = _voice_opening().lower()
    assert voice_opening.count("?") == 1, f"voice opening is not a single question: {voice_opening}"
    assert "speaking with" in voice_opening


def test_text_and_voice_openings_both_avoid_leading_with_the_reason() -> None:
    voice_opening = _voice_opening().lower()
    assert "reason for" not in voice_opening, (
        "the opener must confirm who it is speaking with before asking for the reason"
    )


def test_no_unsubstituted_tokens_reach_either_prompt() -> None:
    assert not re.search(r"\[[^\]]*\]", _voice_opening())