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
    assert "May I know who I'm speaking with?" in out
    assert "[" not in out and "]" not in out


def test_opening_line_empty_without_disclosure() -> None:
    assert build_opening_line({"question_flow": []}, {}, {}) == ""


def test_opening_line_uses_short_sentences_for_tts_clarity() -> None:
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(CONFIG, _tokens(contact), contact)
    # CONFIG's disclosure already says "Hi", so the greeting contributes only
    # the name: short standalone sentences, clean prosody for the TTS engine.
    assert "Suresh Kumar." in out
    assert "Hello Suresh Kumar." not in out
    # Disclosure already says who/where — the greeting must not repeat it.
    assert "This is an AI assistant calling from Demo School." not in out
    # CONFIG's question already names the student, so "I'm calling about
    # Aarav Kumar." would be a second mention of the same name right before the
    # question. The question is the mention that survives.
    assert "I'm calling about Aarav Kumar." not in out
    assert "Why was Aarav Kumar absent?" in out


def test_opening_line_keeps_the_about_clause_when_the_question_is_generic() -> None:
    """A question that does not name the student leaves the purpose unstated —
    then the "calling about X" clause is the only thing that says why we rang,
    so it must stay."""
    config = {
        "disclosure_script": "Hi, this is [Agent Name] calling from [Company Name].",
        "question_flow": [{"question": "Why were you absent today?"}],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact), contact)

    assert "I'm calling about Aarav Kumar." in out
    assert out.count("Aarav Kumar") == 1


def test_opening_line_drops_the_greeting_the_disclosure_already_spoke() -> None:
    """The authored disclosure opens with a greeting; the generated one must go.

    Regression (call 15): the Telugu disclosure starts "నమస్కారం, నేను [Institution
    Name] నుండి AI అసిస్టెంట్..." and the greeting prefixed another "నమస్కారం", so
    every call opened with two welcomes back to back — callers read it as a
    stuttering, broken agent.
    """
    config = {
        "voice_settings": {"language": "te"},
        "disclosure_script": (
            "నమస్కారం, నేను [Institution Name] నుండి AI అసిస్టెంట్. "
            "ఈ కాల్ రికార్డ్ అవుతుంది."
        ),
        "question_flow": [{"question": "[Student Name] ఎందుకు గైర్హాజరయ్యారు?"}],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact), contact)

    assert out.count("నమస్కారం") == 1, out
    assert "Suresh Kumar." in out
    # The question names the student, so the "calling about X" clause is dropped
    # rather than naming the same child twice in a row.
    assert "గురించి కాల్ చేస్తున్నాను" not in out
    assert "ఎందుకు గైర్హాజరయ్యారు?" in out
    assert out.count("Aarav Kumar") == 1, out


def test_opening_line_drops_latin_greeting_duplicate() -> None:
    """Latin greetings match on word boundaries: "Hi," in the disclosure counts,
    but the "hi" inside "this" must not suppress the real greeting."""
    config = {
        "disclosure_script": "Hi, this is an AI assistant calling.",
        "question_flow": [{"question": "Why was [Student Name] absent?"}],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact), contact)
    assert "Hello" not in out
    assert "Suresh Kumar." in out

    bare = {
        "disclosure_script": "This is an AI assistant calling.",
        "question_flow": [{"question": "Why was [Student Name] absent?"}],
    }
    out = build_opening_line(bare, _tokens(contact), contact)
    assert "Hello Suresh Kumar." in out


def test_opening_line_repeats_intro_when_disclosure_is_bare() -> None:
    config = {
        "disclosure_script": "This call is recorded.",
        "question_flow": [{"question": "Why?"}],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact), contact)
    assert "This is an AI assistant calling from Demo School." in out


def test_opening_line_never_names_two_institutions() -> None:
    """A disclosure that already says "calling from X" must not then add the
    token institution Y.

    Regression: the seeded disclosure names the college verbatim while the call
    context supplied a different institution, so the greeting named BOTH
    ("...calling from Acme College... Hello Suresh Kumar. Calling from Demo
    School."). Confusing for the callee and ~1s of extra TTS at the most
    latency-sensitive moment.
    """
    config = {
        "disclosure_script": "Hi, this is an AI assistant calling from Acme College.",
        "question_flow": [{"question": "Why was [Student Name] absent?"}],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact, "Demo School"), contact)
    assert "Demo School" not in out
    assert "Acme College" in out


def test_opening_line_telugu_agent_speaks_no_english_sentences() -> None:
    """A Telugu agent's generated greeting must be Telugu too.

    Regression: the greeting fragments were hardcoded English, so a Telugu
    call opened the authored Telugu disclosure with "Hello Suresh Kumar. This
    is an AI assistant calling from Demo School. I'm calling about Aarav
    Kumar." — an English sandwich around Telugu speech.
    """
    config = {
        "voice_settings": {"language": "te"},
        "disclosure_script": "[Institution Name] నుండి AI అసిస్టెంట్ మాట్లాడుతున్నాను.",
        "question_flow": [{"question": "[Student Name] ఎందుకు గైర్హాజరయ్యారు?"}],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact), contact)

    assert "నమస్కారం" in out
    assert "Suresh Kumar" in out and "Aarav Kumar" in out
    # The Telugu connective phrases are Telugu, and no English "calling about"
    # syntax leaks in when the redundant clause is dropped.
    assert "I'm calling about" not in out
    # The Telugu question survives; no English greeting syntax leaks in.
    assert "ఎందుకు గైర్హాజరయ్యారు?" in out
    assert "Hello" not in out
    assert "I'm calling about" not in out
    assert "[" not in out and "]" not in out


def test_opening_line_telugu_without_names_asks_in_telugu() -> None:
    config = {
        "voice_settings": {"language": "te"},
        "disclosure_script": "[Institution Name] నుండి AI అసిస్టెంట్.",
        "question_flow": [],
    }
    out = build_opening_line(config, _tokens({}), {})
    assert "మీరు ఎవరో తెలుసుకోవచ్చా?" in out


def test_opening_line_telugu_disclosure_that_names_the_ai_drops_the_intro() -> None:
    """A Telugu disclosure that already introduces the assistant must not be
    followed by a generated English intro.

    Regression: ``[Agent Name]`` falls back to the English default "an AI
    assistant", which was spoken verbatim inside Telugu speech
    ("...నేను an AI assistant మాట్లాడుతున్నాను.") — an English sandwich, and
    redundant with the authored disclosure.
    """
    config = {
        "voice_settings": {"language": "te"},
        "disclosure_script": "[Institution Name] నుండి AI అసిస్టెంట్ మాట్లాడుతున్నాను.",
        "question_flow": [{"question": "[Student Name] ఎందుకు గైర్హాజరయ్యారు?"}],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact), contact)

    assert "an AI assistant" not in out
    assert "This is" not in out
    assert "నేను ఒక AI అసిస్టెంట్ మాట్లాడుతున్నాను" not in out
    # The authored disclosure and the localized greeting/question still stand.
    assert "AI అసిస్టెంట్ మాట్లాడుతున్నాను" in out
    assert "నమస్కారం Suresh Kumar." in out
    assert "[" not in out and "]" not in out


def test_opening_line_telugu_unwritten_agent_name_uses_localized_phrase() -> None:
    """Without an authored ``[Agent Name]`` the Telugu opening must introduce the
    caller with the Telugu phrase, not the English token default."""
    config = {
        "voice_settings": {"language": "te"},
        # Says nothing about who is calling, so the generated intro must appear.
        "disclosure_script": "ఈ కాల్ రికార్డ్ అవుతుంది.",
        "question_flow": [],
    }
    contact = {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"}
    out = build_opening_line(config, _tokens(contact, "CMR College"), contact)

    assert "ఒక AI అసిస్టెంట్" in out
    assert "నేను ఒక AI అసిస్టెంట్ మాట్లాడుతున్నాను" in out
    assert "an AI assistant" not in out
    assert "CMR College నుండి" in out
    assert "[" not in out and "]" not in out


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
    assert allow_interruptions is True
    assert text.startswith("Hi, this is an AI assistant calling from Demo School.")
    assert "Suresh Kumar" in text and "Aarav Kumar" in text
    assert "[" not in text and "]" not in text


def test_speak_opening_skips_without_disclosure() -> None:
    session = _FakeSession()
    spoken = asyncio.run(pipeline_module._speak_opening(session, {"question_flow": []}, {}, {}))
    assert spoken is False
    assert session.said == []


def test_degrade_apology_remains_protected(monkeypatch, fake_backend) -> None:
    sessions: list[object] = []

    class _ApologySession:
        def __init__(self, **_kwargs) -> None:
            self.said: list[tuple[str, bool]] = []
            sessions.append(self)

        async def start(self, **_kwargs) -> None:
            return None

        async def say(self, text: str, allow_interruptions: bool = True) -> None:
            self.said.append((text, allow_interruptions))

    async def _connected(_ctx) -> bool:
        return True

    monkeypatch.setattr(pipeline_module, "AgentSession", _ApologySession)
    monkeypatch.setattr(pipeline_module, "Agent", lambda **_kwargs: object())
    monkeypatch.setattr(pipeline_module, "_is_connected", _connected)
    monkeypatch.setattr(
        pipeline_module,
        "build_providers",
        lambda _settings: pipeline_module.ProviderBundle(
            stt=object(), llm=object(), tts=object()
        ),
    )

    ctx = type("Context", (), {"room": object()})()
    asyncio.run(
        pipeline_module._degrade(
            ctx, fake_backend, "call-degrade", object(), "provider failure"
        )
    )

    assert len(sessions) == 1
    assert sessions[0].said == [(pipeline_module.APOLOGY_TEXT, False)]
