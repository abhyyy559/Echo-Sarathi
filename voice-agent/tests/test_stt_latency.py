"""P0-1 STT latency: Deepgram endpointing + EOU-vs-transcription split.

- build_providers must request 200 ms Deepgram endpointing (plugin spells it
  ``endpointing_ms``; introspected livekit-plugins-deepgram 1.7.0).
- TurnTelemetry keeps ``stt_final_ms`` = end_of_utterance_delay ONLY and logs
  ``transcription_delay_ms`` separately in the turn_latency line.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import app.pipeline as pipeline_module
from app.config import Settings
from app.pipeline import TurnTelemetry, build_providers
from conftest import FakeBackendClient


class _RecorderSTT:
    """Stands in for deepgram.STT, capturing constructor kwargs."""

    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_kwargs = kwargs


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "secret",
        "deepgram_api_key": "dg-key",
        "cartesia_api_key": "cartesia-key",
        "groq_api_key": "groq-key",
        "openai_api_key": None,
        "openai_base_url": "https://api.openai.com/v1",
        "backend_internal_url": "http://localhost:8000",
        "groq_model": "test-model",
        "openai_model": "gpt-4o-mini",
        "log_level": "info",
        "internal_api_token": "tok",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_deepgram_stt_gets_300ms_endpointing(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module.deepgram, "STT", _RecorderSTT)
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", lambda **kw: object())

    bundle = build_providers(_settings())

    assert bundle.complete
    # 300ms (raised from 200) so the agent's own looped-back TTS does not
    # hair-trigger a retrigger (False-interruption echo hardening).
    assert _RecorderSTT.last_kwargs["endpointing_ms"] == 300
    assert _RecorderSTT.last_kwargs["model"] == "nova-3"


class _FakeSession:
    """Collects event handlers the way AgentSession.on(...) does."""

    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def on(self, name: str):
        def _register(fn: Any) -> Any:
            self.handlers[name] = fn
            return fn

        return _register


class _FakeMetricsEvent:
    def __init__(self, metrics: Any) -> None:
        self.metrics = metrics


def test_stt_final_is_eou_only_and_transcription_delay_logged(
    fake_backend, caplog
) -> None:
    session = _FakeSession()
    telemetry = TurnTelemetry(
        session=session,  # type: ignore[arg-type]
        backend=fake_backend,
        call_id="c1",
        room=None,
    )
    telemetry.attach()

    # Caller finished a final transcript segment.
    session.handlers["user_input_transcribed"](
        type("Ev", (), {"transcript": "he had fever", "is_final": True})()
    )

    # LiveKit EOU metric: 400 ms end-of-utterance + 900 ms transcription delay.
    eou = type(
        "M", (), {
            "type": "eou_metrics",
            "end_of_utterance_delay": 0.4,
            "transcription_delay": 0.9,
        },
    )()
    session.handlers["metrics_collected"](_FakeMetricsEvent(eou))

    llm = type("M", (), {"type": "llm_metrics", "ttft": 0.25})()
    tts = type("M", (), {"type": "tts_metrics", "ttfb": 0.12})()

    with caplog.at_level(logging.INFO, logger="voice_agent.pipeline"):
        session.handlers["metrics_collected"](_FakeMetricsEvent(llm))
        session.handlers["metrics_collected"](_FakeMetricsEvent(tts))
        # Assistant reply completes the exchange.
        agent_item = type(
            "AgentItem", (), {"role": "assistant", "text_content": "Okay."}
        )()
        ev_agent = type("Ev", (), {"item": agent_item})()
        session.handlers["conversation_item_added"](ev_agent)
        import asyncio

        asyncio.run(telemetry.flush_pending())

    assert len(fake_backend.turn_posts) == 1
    _, turns = fake_backend.turn_posts[0]
    user_rows = [t for t in turns if t["speaker"] == "user"]
    assert user_rows and user_rows[0]["stt_final_ms"] == 400, (
        "stt_final_ms must be EOU delay only (not EOU+transcription)"
    )

    log_lines = [
        r.getMessage() for r in caplog.records if '"event": "turn_latency"' in r.getMessage()
    ]
    assert log_lines, "turn_latency log line missing"
    payload = json.loads(log_lines[-1])
    assert payload["transcription_delay_ms"] == 900
