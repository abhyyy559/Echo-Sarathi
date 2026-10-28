"""Generic caller context + token substitution in the text-mode prompt."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.routers.playground import (
    _build_short_opening,
    _empty_reply_line,
    _render_caller_context,
    _render_text_system_prompt,
)
from app.services.token_substitution import resolve_spoken_name


def _config(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "disclosure_script": "Hi, this is [Agent Name] calling from [Institution Name].",
        "system_prompt": "You call about [Student Name].",
        "company_context": {},
        "question_flow": [{"step": 1, "question": "Why was [Student Name] absent?"}],
        "extraction_schema": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_absent_student_card_names_and_institution() -> None:
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar", "class_section": "10-A"}
    prompt = _render_text_system_prompt(_config(), contact=contact, institution="Demo School")
    assert "Aarav Kumar" in prompt
    assert "Suresh Kumar" in prompt
    assert "Demo School" in prompt
    assert "[Student Name]" not in prompt
    assert "[Institution Name]" not in prompt
    assert "Why was Aarav Kumar absent?" in prompt


def test_lead_style_card_generic_phrasing() -> None:
    contact = {"lead_name": "Riya", "city": "Hyderabad"}
    block = _render_caller_context(contact, "Acme Realty")
    assert "Riya" in block
    assert "Hyderabad" in block
    assert "the person Riya" in block
    assert "absent" not in block.lower()
    assert "class_section" not in block


def test_empty_contact_guards_against_invented_names() -> None:
    block = _render_caller_context({}, "")
    assert "NEVER invent or guess any name" in block
    prompt = _render_text_system_prompt(_config(), contact=None, institution="")
    assert "CALLER CONTEXT" in prompt
    assert "NEVER invent or guess any name" in prompt


def test_empty_institution_drops_cleanly() -> None:
    prompt = _render_text_system_prompt(_config(), contact={"student_name": "Aarav"}, institution="")
    assert "Aarav" in prompt
    assert "[Institution Name]" not in prompt
    # Scoped: the static HOW-TO-REPLY block intentionally uses two-space
    # indentation, so the no-gap check applies to substituted text only.
    disclosure_line = next(l for l in prompt.splitlines() if "AI assistant calling from" in l)
    assert "  " not in disclosure_line


def test_clinic_card_names_the_patient_and_appointment() -> None:
    config = _config(
        disclosure_script="Hello, this is [Agent Name] from [Clinic Name].",
        system_prompt="You confirm appointments with [Doctor Name].",
        company_context={"clinic_name": "Sunrise Dental", "doctor_name": "Dr Rao"},
        question_flow=[
            {
                "step": 1,
                "question": "Is [Patient Name] coming on [Appointment Date] at [Appointment Time]?",
            }
        ],
    )
    contact = {
        "patient_name": "Ananya Rao",
        "appointment_date": "2026-11-03",
        "appointment_time": "10:30 AM",
    }
    prompt = _render_text_system_prompt(config, contact=contact, institution="")
    assert "Ananya Rao" in prompt
    assert "Dr Rao" in prompt
    assert "2026-11-03" in prompt
    assert "10:30 AM" in prompt
    assert "[" not in prompt
    block = _render_caller_context(contact, "Sunrise Dental")
    assert "the person Ananya Rao" in block
    assert "Ask for Ananya Rao" in block
    assert "absent" not in block.lower()


def test_clinic_opening_greets_the_patient_from_the_lead_card() -> None:
    config = _config(disclosure_script="Hello, this is [Agent Name] from [Clinic Name]. This call is being recorded.")
    opening = _build_short_opening(
        config,
        {"patient_name": "Ananya Rao"},
        institution="Sunrise Dental",
        agent_name="Meera",
    )
    assert "Ananya Rao" in opening
    assert "Am I speaking with Ananya Rao?" in opening
    assert "May I know who I'm speaking with" not in opening


def test_real_estate_opening_greets_the_lead() -> None:
    config = _config(disclosure_script="Hello, this is [Agent Name] from [Company Name]. This call is being recorded.")
    opening = _build_short_opening(
        config,
        {"contact_name": "Kiran"},
        institution="Skyline Estates",
        agent_name="Arjun",
    )
    assert "Am I speaking with Kiran?" in opening
    assert "May I know who I'm speaking with" not in opening


def test_student_opening_still_asks_for_the_parent() -> None:
    config = _config(disclosure_script="Hello, this is [Agent Name] from [Institution Name].")
    opening = _build_short_opening(
        config,
        {"student_name": "Abhi", "parent_name": "Ram"},
        institution="CMR College",
        agent_name="Priya",
    )
    assert "With Ram" in opening or "with Ram" in opening
    assert "Are you Abhi's parent?" not in opening


def test_empty_contact_opening_asks_who_is_speaking() -> None:
    config = _config(disclosure_script="Hello, this is [Agent Name].")
    opening = _build_short_opening(config, {}, institution="", agent_name="Priya")
    assert "May I know who I'm speaking with?" in opening


def test_telugu_version_opening_stays_in_telugu() -> None:
    """A Telugu disclosure followed by English is what callers actually heard."""
    config = _config(
        disclosure_script="నమస్కారం, ఇది [Institution Name] నుండి ఆటోమేటెడ్ కాల్.",
        voice_settings={"language": "te"},
    )
    opening = _build_short_opening(
        config,
        {"student_name": "Aarav", "parent_name": "Lakshmi"},
        institution="CMR College",
        agent_name="Sahithi",
    )
    assert "Hi " not in opening
    assert "Am I speaking with" not in opening
    assert "Lakshmi" in opening
    assert opening.count("Lakshmi") == 2
    assert "Aarav" not in opening


def test_empty_reply_line_matches_language_and_end_state() -> None:
    """Silence is never a spoken reply; a closed call gets a goodbye."""
    english = _config(voice_settings={"language": "en"})
    telugu = _config(voice_settings={"language": "te"})
    assert "say that again" in _empty_reply_line(english, done=False)
    assert "Goodbye" in _empty_reply_line(english, done=True)
    assert "మళ్లీ" in _empty_reply_line(telugu, done=False)


_PRESETS = Path(__file__).resolve().parents[2] / "domain-configs" / "presets"


def _preset(filename: str) -> Any:
    data = json.loads((_PRESETS / filename).read_text(encoding="utf-8"))
    return SimpleNamespace(**data["version_payload"])


def test_persona_openings_speak_their_own_brand_not_the_tenant() -> None:
    """Bunty and Anu belong to their own brands; a demo tenant's college name
    must not appear in their first sentence."""
    for filename, agent_name, brand in (
        ("prankster.json", "Bunty", "The Prank Line"),
        ("sweet-checkin.json", "Anu", "Little Lantern"),
    ):
        opening = _build_short_opening(
            _preset(filename),
            {"contact_name": "Kiran"},
            institution="CMR College",
            agent_name=agent_name,
        )
        assert brand in opening
        assert "Am I speaking with Kiran?" in opening
        assert "CMR" not in opening
        assert "[" not in opening


def test_persona_text_prompts_drop_the_tenant_and_fill_every_token() -> None:
    for filename, brand in (
        ("prankster.json", "The Prank Line"),
        ("sweet-checkin.json", "Little Lantern"),
    ):
        payload = _preset(filename)
        institution = resolve_spoken_name(payload.company_context, "CMR College")
        assert institution == brand
        prompt = _render_text_system_prompt(
            payload, contact={"contact_name": "Kiran"}, institution=institution
        )
        assert brand in prompt
        assert "CMR" not in prompt
        assert "[Contact Name]" not in prompt
        assert "[Company Name]" not in prompt
        assert "[Agent Name]" not in prompt
        assert "Kiran" in prompt
