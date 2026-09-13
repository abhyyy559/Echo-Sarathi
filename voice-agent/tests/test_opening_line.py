"""Deterministic protected opening line: disclosure + greeting + first question."""
import asyncio

from app import pipeline as pipeline_module
from app.prompting import build_opening_line, build_token_map

CONFIG = {
    "disclosure_script": "Hi, this is [Agent Name] calling from [Company Name].",
    "question_flow": [{"question": "Why was [Student Name] absent?"}],
}


def _tokens(contact, institution="Demo School"):
    return build_token_map(contact=contact, context={"institution_name": institution})


def test_opening_line_school_card() -> None:
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(CONFIG, _tokens(contact), contact)
    assert out.startswith("Hi, this is an AI assistant calling from Demo School.")
    assert "Suresh Kumar" in out
    assert "Aarav Kumar" in out
    assert "Why was Aarav Kumar absent?" in out
    assert "[" not in out and "]" not in out


def test_opening_line_lead_card() -> None:
    contact = {"lead_name": "Riya"}
    out = build_opening_line(CONFIG, _tokens(contact, "Acme Realty"), contact)
    assert "Riya" in out and "Acme Realty" in out
    assert "[" not in out and "]" not in out


def test_opening_line_no_names_no_invention() -> None:
    out = build_opening_line(CONFIG, _tokens({}), {})
    assert "Hello" in out
    assert "[" not in out and "]" not in out


def test_opening_line_empty_without_disclosure() -> None:
    assert build_opening_line({"question_flow": []}, {}, {}) == ""


def test_opening_line_uses_short_sentences_for_tts_clarity() -> None:
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(CONFIG, _tokens(contact), contact)
    assert "Hello Suresh Kumar." in out
    # Disclosure already says who/where — the greeting must not repeat it.
    assert "This is an AI assistant calling from Demo School." not in out
    assert "I'm calling about Aarav Kumar." in out


def test_opening_line_repeats_intro_when_disclosure_is_bare() -> None:
    config = {
        "disclosure_script": "This call is recorded.",
        "question_flow": [{"question": "Why?"}],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact), contact)
    assert "This is an AI assistant calling from Demo School." in out


class _FakeSession:
    def __init__(self) -> None:
        self.said: list[tuple[str, bool]] = []

    async def say(self, text: str, allow_interruptions: bool = True) -> None:
        self.said.append((text, allow_interruptions))


def test_speak_opening_protected_and_first() -> None:
    session = _FakeSession()
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    tokens = build_token_map(contact=contact, context={"institution_name": "Demo School"})
    spoken = asyncio.run(pipeline_module._speak_opening(session, CONFIG, tokens, contact))
    assert spoken is True
    assert len(session.said) == 1
    text, allow_interruptions = session.said[0]
    assert allow_interruptions is False
    assert text.startswith("Hi, this is an AI assistant calling from Demo School.")
    assert "Suresh Kumar" in text and "Aarav Kumar" in text
    assert "[" not in text and "]" not in text


def test_speak_opening_skips_without_disclosure() -> None:
    session = _FakeSession()
    spoken = asyncio.run(pipeline_module._speak_opening(session, {"question_flow": []}, {}, {}))
    assert spoken is False
    assert session.said == []
