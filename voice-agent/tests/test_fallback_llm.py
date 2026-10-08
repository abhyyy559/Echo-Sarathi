from __future__ import annotations

import asyncio
from typing import Any

from livekit.agents import llm
from livekit.agents.llm.llm import APIConnectOptions

from app.pipeline import FallbackLLM, _FallbackStream


class _PrimaryStream:
    def __init__(self, chat_ctx: llm.ChatContext) -> None:
        self.chat_ctx = chat_ctx
        self.tools: list[Any] = []
        self.closed = False

    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class _RecordingLLM(llm.LLM):
    def __init__(self) -> None:
        super().__init__()
        self.connect_options: list[APIConnectOptions] = []

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[Any] | None = None,
        conn_options: APIConnectOptions,
        **_kwargs: Any,
    ) -> _PrimaryStream:
        self.connect_options.append(conn_options)
        return _PrimaryStream(chat_ctx)


def test_fallback_stream_uses_real_api_connect_options() -> None:
    async def scenario() -> None:
        primary = _RecordingLLM()
        fallback = _RecordingLLM()
        owner = FallbackLLM(primary, fallback)
        stream = owner.chat(chat_ctx=llm.ChatContext.empty(), tools=[])

        assert isinstance(stream, _FallbackStream)
        assert len(primary.connect_options) == 1
        options = primary.connect_options[0]
        assert isinstance(options, APIConnectOptions)
        # Every member fails fast (one quick attempt): the session retry,
        # not the SDK loop, advances the chain — a dead final key costs ~1s,
        # not ~13s of dead air.
        assert options.max_retry == 1
        assert options.retry_interval == 0.5
        # 8s: a hung provider must surface before the 4s stall watchdog's
        # filler, so the chain moves on instead of stacking silence.
        assert options.timeout == 8.0

        await llm.LLMStream.aclose(stream)
        await stream._active.aclose()

    asyncio.run(scenario())


def test_final_member_also_fails_fast() -> None:
    async def scenario() -> None:
        first = _RecordingLLM()
        last = _RecordingLLM()
        owner = FallbackLLM([first, last])
        owner._mark_down(0)  # force serving the final member
        stream = owner.chat(chat_ctx=llm.ChatContext.empty(), tools=[])
        assert isinstance(stream, _FallbackStream)
        assert stream._member_index == 1
        assert last.connect_options[0].max_retry == 1
        await llm.LLMStream.aclose(stream)

    asyncio.run(scenario())


class _FailingStream(_PrimaryStream):
    def __init__(self, chat_ctx: llm.ChatContext, status: int) -> None:
        super().__init__(chat_ctx)
        self._status = status

    async def __anext__(self) -> Any:
        exc = RuntimeError("boom")
        exc.status_code = self._status  # type: ignore[attr-defined]
        raise exc


def test_402_marks_member_down_instead_of_killing_the_turn() -> None:
    """Live gap: a zero-balance DeepSeek answers 402, which was not in the
    retryable set, so voice raised it raw - the turn died in silence with a
    working pool behind it. Now 402 cools the member down and the session's
    retry serves the next member."""
    import time

    async def scenario() -> None:
        first = _RecordingLLM()
        last = _RecordingLLM()
        owner = FallbackLLM([first, last])
        failing = _FailingStream(llm.ChatContext.empty(), 402)
        stream = _FallbackStream(owner, failing, 0)
        try:
            await stream.__anext__()
            raise AssertionError("expected the 402 to propagate after cooldown")
        except RuntimeError:
            pass
        assert owner._down_until[0] > time.monotonic()
        # The session retry now lands on the next member, not the dead one.
        retry = owner.chat(chat_ctx=llm.ChatContext.empty(), tools=[])
        assert isinstance(retry, _FallbackStream)
        assert retry._member_index == 1
        await llm.LLMStream.aclose(retry)

    asyncio.run(scenario())
