"""Language-aware TTS routing (handoff Fix 10).

A Telugu/Hindi agent must use Sarvam Bulbul even when the platform default is
Cartesia; an English agent keeps Cartesia. The LLM prompt language and the TTS
voice must agree, otherwise the agent speaks English words with an Indian
language engine (or vice versa).
"""

from __future__ import annotations

from typing import Any

import pytest
from livekit.plugins import sarvam

import app.pipeline as pipeline_module
from app.config import Settings
from app.pipeline import build_providers


def _settings() -> Settings:
    return Settings(
        livekit_url="ws://localhost:7880",
        livekit_api_key="devkey",
        livekit_api_secret="secret",
        deepgram_api_key="dg-key",
        cartesia_api_key="cartesia-key",
        groq_api_key="groq-key",
        openai_api_key=None,
        openai_base_url=None,
        internal_api_token="tok",
        backend_internal_url="http://localhost:8000",
        groq_model="qwen/qwen3.8-27b",
        openai_model="gpt-4o-mini",
        log_level="info",
    )


@pytest.fixture(autouse=True)
def _isolate_tts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setenv("TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("SARVAM_TTS_API", "sarvam-key")
    monkeypatch.delenv("TTS_LANGUAGE_ROUTING", raising=False)
    monkeypatch.delenv("SARVAM_TTS_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("SARVAM_TTS_LANG", raising=False)
    monkeypatch.setattr(pipeline_module.deepgram, "STT", lambda **kw: object())


def test_telugu_agent_gets_sarvam_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    sarvam_calls: list[dict[str, Any]] = []
    cartesia_calls: list[dict[str, Any]] = []

    class _SarvamRecorder:
        def __init__(self, **kwargs: Any) -> None:
            sarvam_calls.append(kwargs)

    class _CartesiaRecorder:
        def __init__(self, **kwargs: Any) -> None:
            cartesia_calls.append(kwargs)

    monkeypatch.setattr(sarvam, "TTS", _SarvamRecorder)
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", _CartesiaRecorder)

    bundle = build_providers(_settings(), {"language": "te", "speaking_rate": 0.9})

    assert bundle.tts_provider == "sarvam"
    assert cartesia_calls == []
    assert sarvam_calls
    kwargs = sarvam_calls[0]
    assert kwargs["target_language_code"] == "te-IN"
    assert kwargs["speech_sample_rate"] == 8000
    assert kwargs["pace"] == 0.9
    assert kwargs["speaker"] == "priya"


def test_english_agent_keeps_cartesia(monkeypatch: pytest.MonkeyPatch) -> None:
    sarvam_calls: list[dict[str, Any]] = []
    cartesia_calls: list[dict[str, Any]] = []

    class _SarvamRecorder:
        def __init__(self, **kwargs: Any) -> None:
            sarvam_calls.append(kwargs)

    class _CartesiaRecorder:
        def __init__(self, **kwargs: Any) -> None:
            cartesia_calls.append(kwargs)

    monkeypatch.setattr(sarvam, "TTS", _SarvamRecorder)
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", _CartesiaRecorder)

    bundle = build_providers(_settings(), {"language": "en"})

    assert bundle.tts_provider == "cartesia"
    assert cartesia_calls
    assert sarvam_calls == []


def test_language_routing_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTS_LANGUAGE_ROUTING", "off")
    cartesia_calls: list[dict[str, Any]] = []

    class _CartesiaRecorder:
        def __init__(self, **kwargs: Any) -> None:
            cartesia_calls.append(kwargs)

    monkeypatch.setattr(pipeline_module.cartesia, "TTS", _CartesiaRecorder)
    monkeypatch.setattr(sarvam, "TTS", lambda **kw: object())

    bundle = build_providers(_settings(), {"language": "te"})

    assert bundle.tts_provider == "cartesia"
    assert cartesia_calls


def _record_sarvam(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class _SarvamRecorder:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(sarvam, "TTS", _SarvamRecorder)
    return calls


def test_phone_leg_asks_bulbul_for_mulaw(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PSTN leg IS 8 kHz G.711, so the call path carries no mp3 layer.

    mp3 at 8 kHz is an MPEG-2.5 mode with audible grain, and it costs an
    encoder round trip plus a decoder per chunk (latency) on every call.
    """
    calls = _record_sarvam(monkeypatch)
    build_providers(_settings(), {"language": "te"}, is_phone=True)

    assert calls[0]["output_audio_codec"] == "mulaw"
    assert calls[0]["speech_sample_rate"] == 8000


def test_browser_room_keeps_mp3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Narrowband G.711 would sound muffled in a browser room."""
    calls = _record_sarvam(monkeypatch)
    build_providers(_settings(), {"language": "te"})

    assert calls[0]["output_audio_codec"] == "mp3"


def test_tts_codec_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SARVAM_TTS_CODEC", "linear16")
    calls = _record_sarvam(monkeypatch)
    build_providers(_settings(), {"language": "te"}, is_phone=True)

    assert calls[0]["output_audio_codec"] == "linear16"
    assert calls[0]["speech_sample_rate"] == 8000
