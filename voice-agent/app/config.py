"""Environment-driven configuration for the voice agent runtime.

All credentials come from the environment (a ``.env`` file is loaded if
present); nothing is ever hardcoded. ``BACKEND_INTERNAL_URL`` points at the
FastAPI backend's *internal* (service-token protected) API.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

DEFAULT_BACKEND_INTERNAL_URL = "http://localhost:8000"
# Fast default for voice (gpt-oss-20b runs ~1000 tok/s on Groq dev tier).
# llama-3.1-8b-instant went Enterprise-only (404 for dev keys). Reasoning is
# disabled per-request in pipeline.py. Per-agent override: voice_settings.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _load_env_file() -> None:
    """Load the nearest ``.env`` walking up from this file, then the cwd."""
    if load_dotenv is None:  # pragma: no cover - dotenv is a declared dep
        return
    here = Path(__file__).resolve()
    candidates = [parent / ".env" for parent in reversed(here.parents)]
    candidates.append(Path.cwd() / ".env")
    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(candidate)
            return


def _get(key: str, default: Optional[str] = None) -> Optional[str]:
    value: Optional[str] = os.getenv(key, default)
    if value is not None and value.strip() == "":
        return default
    return value


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the process environment relevant to the worker."""

    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    deepgram_api_key: Optional[str]
    cartesia_api_key: Optional[str]
    groq_api_key: Optional[str]
    openai_api_key: Optional[str]
    openai_base_url: Optional[str]
    internal_api_token: str
    backend_internal_url: str
    groq_model: str
    openai_model: str
    log_level: str
    cartesia_pronunciation_dict_id: Optional[str] = None

    @staticmethod
    def from_env() -> "Settings":
        _load_env_file()
        return Settings(
            livekit_url=os.getenv("LIVEKIT_URL", "ws://localhost:7880"),
            livekit_api_key=os.getenv("LIVEKIT_API_KEY", "devkey"),
            livekit_api_secret=os.getenv("LIVEKIT_API_SECRET", "secret"),
            deepgram_api_key=_get("DEEPGRAM_API_KEY"),
            cartesia_api_key=_get("CARTESIA_API_KEY"),
            cartesia_pronunciation_dict_id=_get("CARTESIA_PRONUNCIATION_DICT_ID"),
            groq_api_key=_get("GROQ_API_KEY"),
            openai_api_key=_get("OPENAI_API_KEY"),
            openai_base_url=_get("OPENAI_BASE_URL"),
            internal_api_token=os.getenv("INTERNAL_API_TOKEN", ""),
            backend_internal_url=os.getenv(
                "BACKEND_INTERNAL_URL", DEFAULT_BACKEND_INTERNAL_URL
            ),
            groq_model=os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
            openai_model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            log_level=os.getenv("LOG_LEVEL", "info").lower(),
        )

    def missing_required(self) -> list[str]:
        """Names of required variables that are unset (worker cannot run)."""
        missing: list[str] = []
        if not self.livekit_url:
            missing.append("LIVEKIT_URL")
        if not self.livekit_api_key:
            missing.append("LIVEKIT_API_KEY")
        if not self.livekit_api_secret:
            missing.append("LIVEKIT_API_SECRET")
        if not self.internal_api_token:
            missing.append("INTERNAL_API_TOKEN")
        return missing

    def provider_problems(self) -> list[str]:
        """Human-readable list of missing *provider* keys (degradable)."""
        problems: list[str] = []
        if not self.deepgram_api_key:
            problems.append("DEEPGRAM_API_KEY missing - STT disabled")
        if not self.cartesia_api_key:
            problems.append("CARTESIA_API_KEY missing - TTS disabled")
        if not self.groq_api_key and not self.openai_api_key:
            problems.append(
                "GROQ_API_KEY and OPENAI_API_KEY both missing - LLM disabled"
            )
        return problems


_SETTINGS_CACHE: Optional[Settings] = None


def get_settings(refresh: bool = False) -> Settings:
    """Return cached :class:`Settings`, building them from the environment."""
    global _SETTINGS_CACHE
    if refresh or _SETTINGS_CACHE is None:
        _SETTINGS_CACHE = Settings.from_env()
    return _SETTINGS_CACHE


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests)."""
    global _SETTINGS_CACHE
    _SETTINGS_CACHE = None
