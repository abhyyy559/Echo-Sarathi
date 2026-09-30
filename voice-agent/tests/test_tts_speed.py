"""Cartesia speed wiring: platform speaking_rate must reach the TTS provider.

Previously VoiceSettingsForm collected speaking_rate but build_providers
never passed it, so 0.9-for-clarity did nothing. Cartesia speed is valid
0.6-1.5 (default 1.0); the platform range 0.5-2.0 is clamped onto it.
"""
from __future__ import annotations

from typing import Any

import pytest

import app.pipeline as pipeline_module
from app.pipeline import _cartesia_speed, build_providers


@pytest.fixture(autouse=True)
def _pin_cartesia_provider(monkeypatch) -> None:
    """These tests assert Cartesia wiring. The repo .env may carry
    TTS_PROVIDER=deepgram (loaded into os.environ by Settings.from_env), which
    would route build_providers away from Cartesia."""
    monkeypatch.setenv("TTS_PROVIDER", "cartesia")


def _settings(**overrides: Any):  # type: ignore[no-untyped-def]
    from app.config import Settings

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


def test_cartesia_speed_mapping() -> None:
    assert _cartesia_speed(1.0) is None
    assert _cartesia_speed(0.9) == 0.9
    assert _cartesia_speed(0.5) == 0.6  # clamped to Cartesia minimum
    assert _cartesia_speed(2.0) == 1.5  # clamped to Cartesia maximum
    assert _cartesia_speed(None) is None
    assert _cartesia_speed("slow") is None


class _RecorderTTS:
    """Stands in for cartesia.TTS, capturing constructor kwargs."""

    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_kwargs = kwargs


def test_build_providers_passes_speaking_rate(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module.deepgram, "STT", lambda **kw: object())
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", _RecorderTTS)

    build_providers(_settings(), {"speaking_rate": 0.9})
    assert _RecorderTTS.last_kwargs["speed"] == 0.9


def test_build_providers_omits_speed_at_normal_rate(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module.deepgram, "STT", lambda **kw: object())
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", _RecorderTTS)

    build_providers(_settings(), {})
    assert "speed" not in _RecorderTTS.last_kwargs


def test_build_providers_env_pronunciation_dict(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module.deepgram, "STT", lambda **kw: object())
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", _RecorderTTS)

    build_providers(
        _settings(cartesia_pronunciation_dict_id="pdict_env123"), {}
    )
    assert _RecorderTTS.last_kwargs["pronunciation_dict_id"] == "pdict_env123"


def test_build_providers_agent_dict_overrides_env(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module.deepgram, "STT", lambda **kw: object())
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", _RecorderTTS)

    build_providers(
        _settings(cartesia_pronunciation_dict_id="pdict_env123"),
        {"pronunciation_dict_id": "pdict_agent456"},
    )
    assert _RecorderTTS.last_kwargs["pronunciation_dict_id"] == "pdict_agent456"


def test_build_providers_omits_dict_when_unset(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module.deepgram, "STT", lambda **kw: object())
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", _RecorderTTS)

    build_providers(_settings(), {})
    assert "pronunciation_dict_id" not in _RecorderTTS.last_kwargs
