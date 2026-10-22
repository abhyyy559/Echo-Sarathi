from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import pipeline as pipeline_module


@pytest.fixture(autouse=True)
def _pin_turn_detector(monkeypatch) -> None:
    """_turn_detection reads TURN_DETECTOR from the environment, and the repo
    .env (loaded into os.environ by Settings.from_env in other tests) may
    carry a debugging override. Pin the default so session-config assertions
    test the code, not the ambient environment."""
    monkeypatch.setenv("TURN_DETECTOR", "smart")


class _SessionWithHandlers:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.started = False

    def on(self, name: str):
        def register(handler: Any) -> Any:
            self.handlers[name] = handler
            return handler

        return register

    async def start(self, **_kwargs: Any) -> None:
        self.started = True


class _BlockingBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.posts: list[dict[str, Any]] = []

    async def post_activity(
        self,
        call_id: str,
        state: str,
        sequence: int,
        event_type: str,
        occurred_at: float,
        source: str,
        from_state: str | None,
        to_state: str | None,
    ) -> bool:
        self.started.set()
        await self.release.wait()
        self.posts.append(
            {
                "call_id": call_id,
                "state": state,
                "sequence": sequence,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "source": source,
                "from_state": from_state,
                "to_state": to_state,
            }
        )
        return True


def test_normal_session_uses_local_vad_turn_handling(monkeypatch) -> None:
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
    pipeline_module._build_agent_session(bundle)

    assert captured["aec_warmup_duration"] == 0.0
    # Model-based turn detection pinned to the local mini model (no doomed
    # cloud attempt from self-hosted workers); plain "vad" on old SDKs.
    turn_detection = captured["turn_handling"].pop("turn_detection")
    if turn_detection == "vad":
        assert pipeline_module._inference is None
    else:
        assert type(turn_detection).__name__ == "TurnDetector"
    # Preemptive shape is version-dependent (mapping on 1.8+, bool on older):
    # resolve it through the same helper the pipeline uses.
    expected_preemptive = pipeline_module._preemptive_kwargs(True)[
        "preemptive_generation"
    ]
    assert captured["turn_handling"] == {
        "preemptive_generation": expected_preemptive,
        "endpointing": {
            "mode": "fixed",
            # 0.3s (lowered from 0.4): the floor is dead time on EVERY turn,
            # and the semantic detector still catches mid-sentence pauses.
            "min_delay": 0.3,
            "max_delay": 2.5,
        },
        "interruption": {
            "enabled": True,
            "mode": "vad",
            "discard_audio_if_uninterruptible": True,
            "min_duration": 0.35,
            "min_words": 1,
            "false_interruption_timeout": 2.0,
            "resume_false_interruption": True,
        },
    }
    deprecated_kwargs = {
        "turn_detection",
        "min_endpointing_delay",
        "max_endpointing_delay",
        "min_interruption_duration",
        "false_interruption_timeout",
        "resume_false_interruption",
        "discard_audio_if_uninterruptible",
        "allow_interruptions",
    }
    assert deprecated_kwargs.isdisjoint(captured)


def test_agent_connecting_does_not_delay_session_start() -> None:
    async def scenario() -> list[dict[str, Any]]:
        backend = _BlockingBackend()
        session = _SessionWithHandlers()
        telemetry = pipeline_module.TurnTelemetry(
            session=session,  # type: ignore[arg-type]
            backend=backend,  # type: ignore[arg-type]
            call_id="call-startup",
        )
        telemetry.attach()

        telemetry.queue_agent_connecting()
        assert telemetry._activity_sequence == 2

        start_task = asyncio.create_task(
            pipeline_module._start_agent_session(session, telemetry, object(), object())
        )
        await backend.started.wait()
        await asyncio.wait_for(start_task, timeout=1.0)
        assert session.started

        backend.release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return backend.posts

    posts = asyncio.run(scenario())

    assert len(posts) == 1
    assert posts[0]["state"] == "agent_connecting"
    assert posts[0]["sequence"] == 1
    assert posts[0]["event_type"] == "session_pre_start"
    assert posts[0]["source"] == "livekit-1.8.3"


class _FakeEmitter:
    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}

    def on(self, event: str):
        def register(handler: Any) -> Any:
            self.handlers.setdefault(event, []).append(handler)
            return handler

        return register

    def off(self, event: str, handler: Any) -> None:
        self.handlers.get(event, []).remove(handler)

    def emit(self, event: str, *args: Any) -> None:
        for handler in list(self.handlers.get(event, [])):
            handler(*args)


class _FakeRoom(_FakeEmitter):
    def __init__(self, participants: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.remote_participants = participants if participants is not None else {}


class _FakeJobCtx:
    def __init__(self, room: _FakeRoom) -> None:
        self.room = room


def _watcher(room: _FakeRoom, session: _FakeEmitter):
    return pipeline_module._CallEndWatcher(
        _FakeJobCtx(room), session, "phone-1"  # type: ignore[arg-type]
    )


def test_call_end_watcher_holds_the_call_until_the_caller_leaves() -> None:
    """Regression: run_session used to return (and close the provider pools)
    right after the opening, so every later turn died with "Cannot send a
    request, as the client has been closed." while the caller was still on
    the line (live calls phone-7..phone-10)."""

    async def scenario() -> tuple[str, bool]:
        room = _FakeRoom({"caller": object()})
        session = _FakeEmitter()
        waiter = asyncio.create_task(_watcher(room, session).wait())

        # Someone else leaves (an observer, a second leg): not the end of the call.
        await asyncio.sleep(0.01)
        room.emit("participant_disconnected", object())
        await asyncio.sleep(0.01)
        still_waiting = not waiter.done()

        room.remote_participants.clear()
        room.emit("participant_disconnected", object())
        return await asyncio.wait_for(waiter, timeout=1.0), still_waiting

    reason, still_waiting = asyncio.run(scenario())

    assert reason == "caller left the room"
    assert still_waiting, "the call ended while the caller was still connected"


def test_call_end_watcher_ends_on_room_or_session_close_and_unsubscribes() -> None:
    async def _end_with(event: str) -> str:
        room = _FakeRoom({"caller": object()})
        session = _FakeEmitter()
        watcher = _watcher(room, session)
        waiter = asyncio.create_task(watcher.wait())
        await asyncio.sleep(0.01)
        (room if event == "disconnected" else session).emit(event, object())
        reason = await asyncio.wait_for(waiter, timeout=1.0)
        # Listeners must not outlive the wait: the next job builds fresh objects,
        # but a stale handler would keep firing on this room until it is dropped.
        assert all(not handlers for handlers in room.handlers.values())
        assert all(not handlers for handlers in session.handlers.values())
        return reason

    assert asyncio.run(_end_with("disconnected")) == "room disconnected"
    assert asyncio.run(_end_with("close")) == "agent session closed"


def test_call_end_watcher_gives_up_at_the_hard_cap(monkeypatch) -> None:
    """A tab left open must not pin a job (and its pools) forever."""
    monkeypatch.setattr(pipeline_module, "_MAX_CALL_SECONDS", 0.05)

    async def scenario() -> str:
        return await asyncio.wait_for(_watcher(_FakeRoom({"caller": object()}), _FakeEmitter()).wait(), timeout=1.0)

    assert asyncio.run(scenario()) == "max call duration reached (0s)"
