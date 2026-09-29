"""Multi-key LLM rotation: GROQ_API_KEY + GROQ_API_KEYS combine, and the
FallbackLLM chain cools down only the failed key while turns keep flowing.
"""
from __future__ import annotations

import asyncio
from typing import Any

from livekit.agents import llm
from livekit.agents.llm.llm import APIConnectOptions

import app.pipeline as pipeline_module
from app.config import Settings, _parse_key_list
from app.pipeline import FallbackLLM, _FallbackStream, build_providers


def test_parse_key_list_single_first_deduped() -> None:
    assert _parse_key_list("k1", "k2, k3") == ("k1", "k2", "k3")
    assert _parse_key_list("k1", "k1, k2") == ("k1", "k2")
    assert _parse_key_list(None, "  , ") == ()
    assert _parse_key_list("", None) == ()


def test_settings_from_env_combines_groq_keys(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "k1")
    monkeypatch.setenv("GROQ_API_KEYS", "k2, k1, k3")
    settings = Settings.from_env()
    assert settings.groq_api_key == "k1"
    assert settings.groq_api_keys == ("k1", "k2", "k3")


def test_settings_from_env_extra_keys_only(monkeypatch) -> None:    # Blank (not delete): from_env() loads the repo .env, which may carry a
    # real GROQ_API_KEY — load_dotenv never overrides an existing var, so an
    # explicit blank wins and _get() treats "" as unset.
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEYS", "k9")
    settings = Settings.from_env()
    assert settings.groq_api_key is None
    assert settings.groq_api_keys == ("k9",)
    assert not any("LLM disabled" in p for p in settings.provider_problems())


class _PrimaryStream:
    def __init__(self, chat_ctx: llm.ChatContext) -> None:
        self.chat_ctx = chat_ctx
        self.tools: list[Any] = []
        self.closed = False

    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class _RateLimitedError(Exception):
    def __init__(self) -> None:
        super().__init__("rate_limited")
        self.status_code = 429


class _FailingStream(_PrimaryStream):
    async def __anext__(self) -> Any:
        raise _RateLimitedError()


class _RecordingLLM(llm.LLM):
    fail: bool = False

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
        if self.fail:
            return _FailingStream(chat_ctx)
        return _PrimaryStream(chat_ctx)


def test_chain_serves_next_member_after_retryable_failure() -> None:
    async def scenario() -> None:
        bad = _RecordingLLM()
        bad.fail = True
        good = _RecordingLLM()
        third = _RecordingLLM()
        owner = FallbackLLM([bad, good, third])
        assert owner.chain_size == 3

        first = owner.chat(chat_ctx=llm.ChatContext.empty(), tools=[])
        assert isinstance(first, _FallbackStream)
        assert first._member_index == 0
        try:
            await first.__anext__()
            raise AssertionError("expected the 429 to propagate")
        except _RateLimitedError:
            pass

        second = owner.chat(chat_ctx=llm.ChatContext.empty(), tools=[])
        assert isinstance(second, _FallbackStream)
        assert second._member_index == 1  # failed key skipped via cooldown

        # Non-final members fail fast (one attempt); the final member keeps
        # the session's own retry policy.
        assert bad.connect_options[0].max_retry == 1
        assert good.connect_options[0].max_retry == 1
        assert third.connect_options == []

        await llm.LLMStream.aclose(first)
        await llm.LLMStream.aclose(second)

    asyncio.run(scenario())


def test_build_providers_builds_one_groq_client_per_key(monkeypatch) -> None:
    made: list[dict[str, Any]] = []

    class _FakeGroqLLM:
        def __init__(self, **kwargs: Any) -> None:
            made.append(kwargs)

    monkeypatch.setattr(pipeline_module.deepgram, "STT", lambda **kw: object())
    monkeypatch.setattr(pipeline_module.cartesia, "TTS", lambda **kw: object())
    monkeypatch.setattr(pipeline_module.openai, "LLM", _FakeGroqLLM)

    settings = Settings(
        livekit_url="ws://localhost:7880",
        livekit_api_key="devkey",
        livekit_api_secret="secret",
        deepgram_api_key="dg-key",
        cartesia_api_key="cartesia-key",
        groq_api_key="k1",
        groq_api_keys=("k1", "k2"),
        openai_api_key="ok",
        openai_base_url="https://api.openai.com/v1",
        backend_internal_url="http://localhost:8000",
        groq_model="test-model",
        openai_model="gpt-4o-mini",
        log_level="info",
        internal_api_token="tok",
    )
    bundle = build_providers(settings)
    assert bundle.complete
    assert isinstance(bundle.llm, FallbackLLM)
    assert bundle.llm.chain_size == 3  # k1, k2, then OpenAI
    assert [m["api_key"] for m in made] == ["k1", "k2", "ok"]


def test_placeholder_keys_raise_startup_warning(monkeypatch) -> None:
    from app.config import _looks_like_placeholder, get_settings, reset_settings_cache

    assert _looks_like_placeholder("your_openai_key_here") is True
    assert _looks_like_placeholder("gsk_real_looking_key") is False
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_key")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    reset_settings_cache()
    try:
        problems = get_settings(refresh=True).provider_problems()
    finally:
        reset_settings_cache()
    assert any("OPENAI_API_KEY" in p and "template" in p for p in problems)


def test_norm_institution_ignores_ampersand_variant() -> None:
    from app.prompting import _norm_institution, apply_token_substitution, build_opening_line

    assert _norm_institution("CMR College of Engineering & Technology") == _norm_institution(
        "CMR College of Engineering and Technology"
    )
    # End to end: disclosure names the college with "and", token uses "&".
    config = {
        "mandatory_disclosure": (
            "Hello, this is an AI assistant calling from CMR College of "
            "Engineering and Technology. This call is being recorded."
        ),
        "question_flow": [{"step": 1, "question": "Why was the student absent?"}],
    }
    tokens = {"[Institution Name]": "CMR College of Engineering & Technology"}
    opening = build_opening_line(config, tokens, {})
    assert opening.count("CMR College") == 1, f"college repeated: {opening}"
