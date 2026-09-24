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
        assert options.max_retry == 1
        assert options.retry_interval == 0.5
        assert options.timeout == 15.0

        await llm.LLMStream.aclose(stream)
        await stream._active.aclose()

    asyncio.run(scenario())
