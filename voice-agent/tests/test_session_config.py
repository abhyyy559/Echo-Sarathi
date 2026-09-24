from __future__ import annotations

import asyncio
from typing import Any

from app import pipeline as pipeline_module


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
    assert captured["turn_handling"] == {
        "turn_detection": "vad",
        "endpointing": {
            "mode": "fixed",
            "min_delay": 0.35,
            "max_delay": 1.5,
        },
        "interruption": {
            "enabled": True,
            "mode": "vad",
            "discard_audio_if_uninterruptible": True,
            "min_duration": 0.5,
            "false_interruption_timeout": 2.0,
            "resume_false_interruption": False,
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
