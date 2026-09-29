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
# Any OpenAI-compatible endpoint works here (Groq default; Cerebras
# https://api.cerebras.ai/v1 is the fastest swap — same keys list applies).
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


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


_PLACEHOLDER_KEY_HINTS = ("your_", "change_me", "example", "test-test", "xxx", "placeholder")


def _looks_like_placeholder(value: str) -> bool:
    """Detect unfilled template keys (e.g. your_openai_key) without logging values."""
    lowered = str(value or "").strip().lower()
    return any(hint in lowered for hint in _PLACEHOLDER_KEY_HINTS)


def _parse_key_list(*values: Optional[str]) -> tuple[str, ...]:
    """Combine comma-separated key env vars into a de-duplicated key tuple.

    ``GROQ_API_KEY`` (single) comes first for backward compatibility, then
    every key in ``GROQ_API_KEYS`` (comma-separated) that is not a duplicate.
    Empty entries are dropped, so unset vars simply contribute nothing.
    """
    keys: list[str] = []
    for value in values:
        for part in str(value or "").split(","):
            key = part.strip()
            if key and key not in keys:
                keys.append(key)
    return tuple(keys)


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
    # Multi-key rotation (GROQ_API_KEY first, then GROQ_API_KEYS). Defaulted
    # last so positional construction in older tests keeps working.
    groq_api_keys: tuple[str, ...] = ()
    groq_base_url: str = DEFAULT_GROQ_BASE_URL
    # Extra OpenAI-compatible providers, shared with the backend so one .env
    # line arms the fallback for BOTH text and voice mode. Parsed into
    # (name, base_url, api_key, model) tuples by ``llm_fallback_chain``.
    llm_fallback_chain_raw: str = ""
    cerebras_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None

    @property
    def llm_fallback_chain(self) -> tuple[tuple[str, str, str, str], ...]:
        """``(name, base_url, api_key, model)`` members after the Groq keys.

        Same format the backend reads, so a key pasted once covers text and
        voice. Entries are ``name|base_url|key|model``; a legacy
        ``name:base_url:key:model`` is still accepted, but ``|`` is preferred
        because OpenRouter model ids carry a colon suffix (``:free``) that the
        colon form cannot represent. Malformed entries are skipped rather than
        crashing the worker at boot.
        """
        members: list[tuple[str, str, str, str]] = []
        for entry in (self.llm_fallback_chain_raw or "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            fields = [f.strip() for f in entry.split("|")]
            if len(fields) != 4:
                # Legacy colon form: base_url contains "://" so the fields are
                # peeled from both ends.
                name, _, rest = entry.partition(":")
                head, _, model = rest.rpartition(":")
                base_url, _, api_key = head.rpartition(":")
                fields = [name, base_url, api_key, model]
            name, base_url, api_key, model = (f.strip() for f in fields)
            if not all((name, base_url, api_key, model)):
                continue
            if not base_url.startswith("http"):
                continue
            # A template value left in .env must never occupy a chain slot: it
            # would 401 on every turn and mask the real failure.
            if _looks_like_placeholder(api_key):
                continue
            if name == "groq" and api_key in self.groq_api_keys:
                continue  # already armed from GROQ_API_KEY(S)
            members.append((name, base_url, api_key, model))
        if self.openai_api_key and not any(m[0] == "openai" for m in members):
            if self.openai_base_url and not _looks_like_placeholder(self.openai_api_key):
                members.append(
                    (
                        "openai",
                        self.openai_base_url,
                        self.openai_api_key,
                        self.openai_model,
                    )
                )
        if self.cerebras_api_key:
            members.append(
                (
                    "cerebras",
                    "https://api.cerebras.ai/v1",
                    self.cerebras_api_key,
                    "llama-3.3-70b",
                )
            )
        if self.openrouter_api_key:
            members.append(
                (
                    "openrouter",
                    "https://openrouter.ai/api/v1",
                    self.openrouter_api_key,
                    "meta-llama/llama-3.3-70b-instruct:free",
                )
            )
        return tuple(members)

    @staticmethod
    def from_env() -> "Settings":
        _load_env_file()
        single_groq_key = _get("GROQ_API_KEY")
        return Settings(
            # Inside the compose network the room server is reachable by
            # service name; LIVEKIT_URL is the browser-facing host address and
            # resolves to the worker's own loopback otherwise. Same trick the
            # backend bridges use.
            livekit_url=os.getenv("LIVEKIT_URL_INTERNAL")
            or os.getenv("LIVEKIT_URL", "ws://localhost:7880"),
            livekit_api_key=os.getenv("LIVEKIT_API_KEY", "devkey"),
            livekit_api_secret=os.getenv("LIVEKIT_API_SECRET", "secret"),
            deepgram_api_key=_get("DEEPGRAM_API_KEY"),
            cartesia_api_key=_get("CARTESIA_API_KEY"),
            cartesia_pronunciation_dict_id=_get("CARTESIA_PRONUNCIATION_DICT_ID"),
            groq_api_key=single_groq_key,
            # Multi-key rotation: GROQ_API_KEY first, then GROQ_API_KEYS.
            # Extra keys are only useful once pasted in .env (see .env.example).
            groq_api_keys=_parse_key_list(single_groq_key, _get("GROQ_API_KEYS")),
            openai_api_key=_get("OPENAI_API_KEY"),
            openai_base_url=_get("OPENAI_BASE_URL"),
            internal_api_token=os.getenv("INTERNAL_API_TOKEN", ""),
            backend_internal_url=os.getenv(
                "BACKEND_INTERNAL_URL", DEFAULT_BACKEND_INTERNAL_URL
            ),
            groq_model=os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
            groq_base_url=os.getenv("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL),
            openai_model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            llm_fallback_chain_raw=_get("LLM_FALLBACK_CHAIN") or "",
            cerebras_api_key=_get("CEREBRAS_API_KEY"),
            openrouter_api_key=_get("OPENROUTER_API_KEY"),
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
        if not self.groq_api_keys and not self.openai_api_key:
            problems.append(
                "GROQ_API_KEY/GROQ_API_KEYS and OPENAI_API_KEY all missing - LLM disabled"
            )
        for label, key in (
            ("OPENAI_API_KEY", self.openai_api_key),
            ("GROQ_API_KEY", self.groq_api_key),
        ):
            if key and _looks_like_placeholder(key):
                problems.append(
                    f"{label} looks like an unfilled template value - "
                    f"failover to it will 401; paste a real key"
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
