"""Structural contracts for swappable voice providers."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class STTProvider(Protocol):
    name: str

    def build(self) -> Any: ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    # One voice id that speaks every language this agent uses. When present,
    # a Tenglish switch must not swap the voice (Outpero's "no pipeline swap").
    multilingual_voice_id: str | None

    def build(self) -> Any: ...


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def build(self) -> Any: ...


@runtime_checkable
class TelephonyProvider(Protocol):
    name: str

    def build(self) -> Any: ...
