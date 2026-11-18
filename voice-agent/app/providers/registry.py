"""Resolve a provider for a role and language from environment settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .base import LLMProvider, STTProvider, TelephonyProvider, TTSProvider  # noqa: F401


class ProviderRole(str, Enum):
    STT = "stt"
    TTS = "tts"
    LLM = "llm"
    TELEPHONY = "telephony"


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    role: ProviderRole
    languages: tuple[str, ...] = ()
    factory: str = ""
    description: str = ""


@dataclass(frozen=True)
class ProviderSelection:
    spec: ProviderSpec
    reason: str  # "global" | "language-override" | "default"


_SPECS: dict[tuple[str, str], ProviderSpec] = {}


def register_provider(spec: ProviderSpec) -> None:
    _SPECS[(spec.role.value, spec.name)] = spec


def _default_for(role: ProviderRole) -> str:
    return {
        ProviderRole.STT: "deepgram",
        ProviderRole.TTS: "cartesia",
        ProviderRole.LLM: "groq",
        ProviderRole.TELEPHONY: "fake",
    }[role]


def select_provider(role: ProviderRole, language: str, settings: Any) -> ProviderSelection:
    """Pick a registered provider.

    Precedence: per-language override (``TTS_PROVIDER_TE``) → global
    (``TTS_PROVIDER``) → role default. Existing env vars keep working.
    ``settings`` is accepted for forward compatibility with config-file
    selection; today resolution is purely env-driven.
    """
    env_name = f"{role.value.upper()}_PROVIDER"
    global_name = (os.getenv(env_name) or _default_for(role)).strip().lower()

    short = (language or "").split("-")[0].lower()
    override = os.getenv(f"{env_name}_{short.upper()}", "").strip().lower()
    if override and (role.value, override) in _SPECS:
        return ProviderSelection(_SPECS[(role.value, override)], "language-override")
    if global_name and (role.value, global_name) in _SPECS:
        return ProviderSelection(_SPECS[(role.value, global_name)], "global")
    return ProviderSelection(ProviderSpec(_default_for(role), role), "default")
