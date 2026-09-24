"""LiveKit 1.8.3 state-event activity publishing."""
from __future__ import annotations

import asyncio
import math
from typing import Any

from livekit.agents import AgentStateChangedEvent, UserStateChangedEvent

from app.backend_client import BackendClient
from app.pipeline import TurnTelemetry


class _FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def on(self, name: str):
        def register(handler: Any) -> Any:
            self.handlers[name] = handler
            return handler

        return register


def _user_state_event(old_state: str, new_state: str, created_at: float) -> Any:
    return UserStateChangedEvent(
        old_state=old_state,
        new_state=new_state,
        created_at=created_at,
    )


def _agent_state_event(old_state: str, new_state: str, created_at: float) -> Any:
    return AgentStateChangedEvent(
        old_state=old_state,
        new_state=new_state,
        created_at=created_at,
    )


async def _emit(session: _FakeSession, name: str, event: Any) -> None:
    session.handlers[name](event)
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_activity_sequence_uses_only_state_events(fake_backend) -> None:
    async def scenario() -> None:
        session = _FakeSession()
        telemetry = TurnTelemetry(
            session=session,  # type: ignore[arg-type]
            backend=fake_backend,
            call_id="call-1",
        )
        telemetry.attach()

        telemetry.queue_agent_connecting()
        await _emit(
            session,
            "user_state_changed",
            _user_state_event("listening", "speaking", 101.0),
        )
        await _emit(
            session,
            "user_state_changed",
            _user_state_event("speaking", "listening", 102.0),
        )
        await _emit(
            session,
            "agent_state_changed",
            _agent_state_event("listening", "thinking", 103.0),
        )
        await _emit(
            session,
            "agent_state_changed",
            _agent_state_event("thinking", "speaking", 104.0),
        )
        await _emit(
            session,
            "agent_state_changed",
            _agent_state_event("speaking", "listening", 105.0),
        )

        activity_count = len(fake_backend.activity_posts)
        session.handlers["user_input_transcribed"](
            type(
                "TranscriptEvent",
                (),
                {"transcript": "fever", "is_final": True},
            )()
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(fake_backend.activity_posts) == activity_count

    asyncio.run(scenario())

    posts = fake_backend.activity_posts
    assert [post["state"] for post in posts] == [
        "agent_connecting",
        "listening",
        "understanding",
        "understanding",
        "agent_speaking",
        "listening",
    ]
    assert [post["sequence"] for post in posts] == list(range(1, len(posts) + 1))
    assert [post["event_type"] for post in posts] == [
        "session_pre_start",
        "user_state_changed",
        "user_state_changed",
        "agent_state_changed",
        "agent_state_changed",
        "agent_state_changed",
    ]
    assert posts[0]["from_state"] == "initializing"
    assert posts[0]["to_state"] == "agent_connecting"
    assert all(post["source"] == "livekit-1.8.3" for post in posts)
    assert all(math.isfinite(post["occurred_at"]) for post in posts)


def test_replayed_state_event_is_posted_once(fake_backend) -> None:
    async def scenario() -> None:
        session = _FakeSession()
        telemetry = TurnTelemetry(
            session=session,  # type: ignore[arg-type]
            backend=fake_backend,
            call_id="call-2",
        )
        telemetry.attach()
        event = _user_state_event("listening", "speaking", 201.0)
        await _emit(session, "user_state_changed", event)
        await _emit(session, "user_state_changed", event)
        await _emit(session, "user_state_changed", event)

    asyncio.run(scenario())

    assert len(fake_backend.activity_posts) == 1
    assert fake_backend.activity_posts[0]["sequence"] == 1


def test_agent_thinking_after_speaking_maps_to_understanding(fake_backend) -> None:
    async def scenario() -> None:
        session = _FakeSession()
        telemetry = TurnTelemetry(
            session=session,  # type: ignore[arg-type]
            backend=fake_backend,
            call_id="call-3",
        )
        telemetry.attach()
        await _emit(
            session,
            "agent_state_changed",
            _agent_state_event("speaking", "thinking", 301.0),
        )

    asyncio.run(scenario())

    assert [post["state"] for post in fake_backend.activity_posts] == [
        "understanding"
    ]


class _Response:
    def raise_for_status(self) -> None:
        return None


class _HttpClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.posts: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, *, json: dict[str, Any]) -> _Response:
        self.posts.append((url, json))
        if self.fail:
            raise RuntimeError("backend unavailable")
        return _Response()


def test_backend_client_activity_payload_and_best_effort() -> None:
    client = _HttpClient()
    backend = BackendClient("http://base", "token", client=client)
    ok = asyncio.run(
        backend.post_activity(
            "call-4",
            "understanding",
            7,
            "agent_state_changed",
            401.0,
            "livekit-1.8.3",
            "listening",
            "thinking",
        )
    )

    assert ok is True
    assert client.posts[0][0].endswith("/internal/calls/call-4/activity")
    assert client.posts[0][1] == {
        "state": "understanding",
        "sequence": 7,
        "event_type": "agent_state_changed",
        "occurred_at": 401.0,
        "source": "livekit-1.8.3",
        "from_state": "listening",
        "to_state": "thinking",
    }

    failing_backend = BackendClient("http://base", "token", client=_HttpClient(fail=True))
    assert asyncio.run(
        failing_backend.post_activity(
            "call-5",
            "listening",
            0,
            "user_state_changed",
            402.0,
        )
    ) is False
