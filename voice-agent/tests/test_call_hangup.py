"""Closing the leg: end_call must hang the phone up.

Our answer XML streams audio with ``keepCallAlive``, so a call whose
conversation has finished stays connected until the caller hangs up. These
tests pin the two things that end it: waiting for the farewell before cutting,
and asking the provider by a leg id that actually exists.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from app import pipeline


class _FakeSession:
    """A session that is busy for ``busy_for`` seconds, then silent."""

    def __init__(self, busy_for: float = 0.0, speech_at_end: bool = False) -> None:
        self._busy_until = time.monotonic() + busy_for
        self.current_speech: Any = object() if speech_at_end else None
        self.closed = False

    @property
    def agent_state(self) -> str:
        return "AgentState.SPEAKING" if time.monotonic() < self._busy_until else "AgentState.LISTENING"

    async def aclose(self) -> None:
        self.closed = True


class _FakeBackend:
    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[str, Optional[str]]] = []
        self.ok = ok

    async def post_hangup(self, call_id: str, room: Optional[str] = None) -> bool:
        self.calls.append((call_id, room))
        return self.ok


def _shrink_grace(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "_GOODBYE_START_SECONDS", 0.3)
    monkeypatch.setattr(pipeline, "_GOODBYE_QUIET_SECONDS", 0.05)
    monkeypatch.setattr(pipeline, "_HANGUP_DEADLINE_SECONDS", 2.0)
    monkeypatch.setattr(pipeline, "_GOODBYE_POLL_SECONDS", 0.02)


def test_agent_busy_reads_speech_handle_and_state() -> None:
    speaking = _FakeSession(busy_for=30.0)
    idle = _FakeSession()
    assert pipeline._agent_is_busy(speaking) is True
    assert pipeline._agent_is_busy(idle) is False
    # A queued speech handle means busy even when the state enum lagged behind.
    assert pipeline._agent_is_busy(_FakeSession(speech_at_end=True)) is True


def test_hangup_waits_for_the_farewell_then_closes(monkeypatch) -> None:
    """The goodbye is still being spoken when end_call returns: don't cut it."""
    _shrink_grace(monkeypatch)
    session = _FakeSession(busy_for=0.4)
    backend = _FakeBackend()

    async def _run() -> float:
        began = time.monotonic()
        await pipeline.close_call_after_goodbye(session, backend, "17", "phone-17")
        return time.monotonic() - began

    waited = asyncio.run(_run())
    assert waited >= 0.4, "hangup fired while the agent was still talking"
    assert backend.calls == [("17", "phone-17")]
    assert session.closed is True


def test_session_closes_even_when_the_backend_hangup_fails(monkeypatch) -> None:
    """A dead backend must not pin the job (and its concurrency slot) open."""
    _shrink_grace(monkeypatch)
    session = _FakeSession()
    backend = _FakeBackend(ok=False)

    async def _run() -> None:
        await pipeline.close_call_after_goodbye(session, backend, "17", "phone-17")

    asyncio.run(_run())
    assert backend.calls == [("17", "phone-17")]
    assert session.closed is True
