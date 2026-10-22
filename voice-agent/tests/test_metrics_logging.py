"""Per-stage metric logging (handoff Fix 4).

The backend latency table was blank for STT/LLM/TTS because only the
aggregated turn_latency line was emitted. These INFO lines make each stage
greppable in `docker compose logs voice-agent`; one line per stage per turn,
even though TTS emits one metric per sentence.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from app.pipeline import TurnTelemetry


def _telemetry() -> TurnTelemetry:
    return TurnTelemetry(
        session=SimpleNamespace(),
        backend=SimpleNamespace(),
        call_id="test-call",
    )


def test_per_stage_metrics_logged_once_per_turn(caplog: Any) -> None:
    telemetry = _telemetry()
    events = [
        SimpleNamespace(
            type="eou_metrics",
            end_of_utterance_delay=0.4,
            transcription_delay=0.1,
        ),
        SimpleNamespace(type="stt_metrics", duration=0.5, audio_duration=1.0),
        SimpleNamespace(
            type="llm_metrics",
            ttft=0.3,
            prompt_tokens=10,
            completion_tokens=5,
            metadata=SimpleNamespace(model_provider="groq", model_name="qwen"),
        ),
        SimpleNamespace(type="tts_metrics", ttfb=0.2, characters_count=20),
        # Second sentence in the same turn must not add a second TTS line.
        SimpleNamespace(type="tts_metrics", ttfb=0.25, characters_count=10),
    ]

    with caplog.at_level(logging.INFO, logger="voice_agent.pipeline"):
        for metric in events:
            telemetry._on_metrics_collected(SimpleNamespace(metrics=metric))

    text = caplog.text
    assert "EOU | end_of_utterance_delay=400ms transcription_delay=100ms" in text
    assert "STT | duration=500ms audio=1000ms" in text
    assert "LLM | ttft=300ms model=groq/qwen" in text
    assert "TTS | ttfb=200ms" in text
    assert text.count("TTS |") == 1
