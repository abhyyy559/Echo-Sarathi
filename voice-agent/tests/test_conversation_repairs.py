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


def test_vad_singleton_loads_once(monkeypatch) -> None:
    import app.pipeline as pipeline_module

    loads: list[int] = []

    class _Vad:
        @staticmethod
        def load() -> object:
            loads.append(1)
            return object()

    monkeypatch.setattr(pipeline_module.silero, "VAD", _Vad)
    first = pipeline_module._get_vad()
    second = pipeline_module._get_vad()
    assert first is second
    assert len(loads) == 1


def test_preemptive_off_for_phone_rooms(monkeypatch) -> None:
    import app.pipeline as pipeline_module

    captured: dict[str, Any] = {}

    class _CapturingSession:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class _Vad:
        @staticmethod
        def load() -> object:
            return object()

    monkeypatch.setattr(pipeline_module, "AgentSession", _CapturingSession)
    monkeypatch.setattr(pipeline_module.silero, "VAD", _Vad)
    bundle = pipeline_module.ProviderBundle(stt=object(), llm=object(), tts=object())

    pipeline_module._build_agent_session(bundle, preemptive_generation=False)
    turn_handling = captured["turn_handling"]
    # Explicitly disabled: omitting the key fills the SDK default, which is
    # enabled=True (speculative generation on PSTN rooms). The mapping form
    # is required - a plain bool raises TypeError on 1.8+.
    preemptive = turn_handling.get("preemptive_generation")
    assert isinstance(preemptive, dict), preemptive
    assert preemptive.get("enabled") is False, preemptive
    pipeline_module._build_agent_session(bundle)
    # Must match the helper output after the installed SDK's own filtering:
    # 1.8+ carries the options mapping, 1.7 drops the unknown key entirely.
    turn_handling = captured["turn_handling"]
    annotations = getattr(pipeline_module.TurnHandlingOptions, "__annotations__", {}) or {}
    if "preemptive_generation" in annotations:
        assert turn_handling.get("preemptive_generation") == pipeline_module._preemptive_kwargs(
            True
        ).get("preemptive_generation")
    else:
        assert "preemptive_generation" not in turn_handling


def test_barge_in_published_when_user_speaks_over_agent() -> None:
    import asyncio
    from types import SimpleNamespace

    import app.pipeline as pipeline_module
    from conftest import FakeBackendClient

    published: list[bytes] = []

    class _Participant:
        async def publish_data(self, payload: bytes) -> None:
            published.append(bytes(payload))

    room = SimpleNamespace(local_participant=_Participant())

    class _Session:
        def on(self, name: str):
            def register(handler: Any) -> Any:
                return handler

            return register

    async def scenario() -> None:
        telemetry = pipeline_module.TurnTelemetry(
            session=_Session(),  # type: ignore[arg-type]
            backend=FakeBackendClient(),  # type: ignore[arg-type]
            call_id="call-barge",
            room=room,
        )
        telemetry._on_agent_state_changed(
            SimpleNamespace(old_state="listening", new_state="speaking")
        )
        assert telemetry._agent_speaking is True
        telemetry._on_user_state_changed(
            SimpleNamespace(old_state="listening", new_state="speaking")
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(scenario())
    import json

    assert len(published) == 1
    assert json.loads(published[0])["type"] == "barge_in"


def test_no_barge_in_when_agent_silent() -> None:
    import asyncio
    from types import SimpleNamespace

    import app.pipeline as pipeline_module
    from conftest import FakeBackendClient

    published: list[bytes] = []

    class _Participant:
        async def publish_data(self, payload: bytes) -> None:
            published.append(bytes(payload))

    room = SimpleNamespace(local_participant=_Participant())

    class _Session:
        def on(self, name: str):
            def register(handler: Any) -> Any:
                return handler

            return register

    async def scenario() -> None:
        telemetry = pipeline_module.TurnTelemetry(
            session=_Session(),  # type: ignore[arg-type]
            backend=FakeBackendClient(),  # type: ignore[arg-type]
            call_id="call-quiet",
            room=room,
        )
        telemetry._on_user_state_changed(
            SimpleNamespace(old_state="listening", new_state="speaking")
        )
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert published == []


def test_backchannel_controller_timing() -> None:
    import asyncio

    from app.pipeline import BackchannelController

    spoken: list[str] = []
    now = [0.0]

    async def say(text: str) -> None:
        spoken.append(text)

    async def scenario() -> None:
        ctl = BackchannelController(say, clock=lambda: now[0])
        ctl.on_user_speaking(True)
        now[0] = 1.0
        assert await ctl.tick() is False  # under 2.5s threshold
        now[0] = 3.0
        assert await ctl.tick() is True  # first cue earned
        assert spoken == ["mm-hmm"]
        now[0] = 4.0
        assert await ctl.tick() is False  # 6s cooldown
        now[0] = 10.0
        assert await ctl.tick() is True
        assert spoken == ["mm-hmm", "right"]
        ctl.on_user_speaking(False)
        now[0] = 20.0
        assert await ctl.tick() is False  # floor yielded, stays silent

    asyncio.run(scenario())


def test_smart_turn_preferred_with_fallback(monkeypatch) -> None:
    import app.pipeline as pipeline_module

    assert pipeline_module._turn_detection() is not None
    # Forced failure inside the detector factory falls back, never raises.
    monkeypatch.setattr(pipeline_module, "_get_smart_turn", lambda: (_ for _ in ()).throw(RuntimeError("no weights")))
    detector = pipeline_module._turn_detection()
    assert detector is not None


def test_room_options_none_without_hush() -> None:
    import sys

    import app.pipeline as pipeline_module

    assert "livekit.plugins.hush" not in sys.modules
    # Local test venvs don't install hush: plain start, no crash.
    assert pipeline_module._room_options() is None
