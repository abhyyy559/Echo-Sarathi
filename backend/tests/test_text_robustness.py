"""Text-path robustness: pseudo tool-call markup + Groq 429 retry."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.routers.playground as playground_module
from conftest import auth_headers, register
from test_playground_text import chat, create_groq_app, groq_client, script, start_session  # noqa: F401  (pytest fixture import)


def _iso_in(days: int) -> str:
    """ISO date `days` from the app's "today" (same clock the router uses)."""
    from datetime import timedelta

    from app.routers.playground import utcnow

    return (utcnow() + timedelta(days=days)).date().isoformat()


def _iso_oct2() -> str:
    """This year's Oct 2, or next year's once it has passed (same rule as the
    router's day-month resolver, so the test never goes stale)."""
    from app.routers.playground import utcnow

    today = utcnow().date()
    year = today.year if today <= today.replace(month=10, day=2) else today.year + 1
    return f"{year}-10-02"


def test_parse_and_scrub_pseudo_tool_call() -> None:
    from app.routers.playground import _parse_pseudo_tool_calls, _scrub_tool_markup

    text = (
        "ok <tool_call>\n<function=record_extracted_field>\n<parameter=confidence>\n0.95\n</parameter>\n"
        "<parameter=field_name>\nis_sick_leave\n</parameter>\n<parameter=value>\nyes\n</parameter>\n"
        "</function>\n</tool_call> done"
    )
    calls = _parse_pseudo_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "record_extracted_field"
    assert calls[0]["arguments"] == {"confidence": "0.95", "field_name": "is_sick_leave", "value": "yes"}
    assert _scrub_tool_markup(text) == "ok done"


def test_pseudo_tool_call_recorded_and_scrubbed(groq_client, session_factory):
    from sqlalchemy import select

    from app.models import ExtractedField, Transcript

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    pseudo = (
        "<tool_call>\n<function=record_extracted_field>\n<parameter=confidence>\n0.95\n</parameter>\n"
        "<parameter=field_name>\nis_sick_leave\n</parameter>\n<parameter=value>\nyes\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    script(chat(pseudo))
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "He is sick."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["extracted_fields"] == [
        {"field_name": "is_sick_leave", "field_value": "yes", "confidence": 0.95}
    ]
    assert "<tool_call>" not in body["reply_text"]
    with session_factory() as db:
        fields = db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call_id)
        ).all()
        assert [(f.field_name, f.field_value) for f in fields] == [("is_sick_leave", "yes")]
        texts = [
            t.text
            for t in db.scalars(
                select(Transcript).where(Transcript.call_id == call_id).order_by(Transcript.turn_index)
            ).all()
        ]
        assert all("<tool_call>" not in t for t in texts)


def test_pseudo_tool_call_mixed_text_kept(groq_client):
    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    pseudo = (
        "Noted. <tool_call>\n<function=record_extracted_field>\n<parameter=confidence>\n0.9\n</parameter>\n"
        "<parameter=field_name>\nreason_for_absence\n</parameter>\n<parameter=value>\nfever\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    script(chat(pseudo))
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "He has fever."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reply_text"] == "Noted."
    assert resp.json()["extracted_fields"][0]["field_name"] == "reason_for_absence"


class _FlakyResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        # Mirror httpx: the real response body is what error classification
        # reads, so the fake must expose it too (a fake without .text made a
        # provider 400 indistinguishable from a 429).
        self.text = json.dumps(self._payload) if self._payload else "rate limited"

    def json(self) -> dict[str, Any]:
        return self._payload


class _FlakyAsyncClient:
    planned: list[_FlakyResponse] = []
    requests: list[dict[str, Any]] = []

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FlakyAsyncClient":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def post(self, url: str | None = None, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> _FlakyResponse:
        _FlakyAsyncClient.requests.append({"url": url, "json": json, "headers": headers})
        assert _FlakyAsyncClient.planned, "no planned response left"
        return _FlakyAsyncClient.planned.pop(0)


@pytest.fixture()
def flaky_client(session_factory, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(playground_module.httpx, "AsyncClient", _FlakyAsyncClient)
    _FlakyAsyncClient.planned = []
    _FlakyAsyncClient.requests = []
    fresh = create_groq_app(session_factory)
    with TestClient(fresh) as test_client:
        yield test_client
    _FlakyAsyncClient.planned = []
    _FlakyAsyncClient.requests = []


def test_groq_429_retries_then_succeeds(flaky_client):
    from test_playground_text import start_session as _start

    client = flaky_client
    token, _ = register(client)
    call_id = _start(client, token)
    _FlakyAsyncClient.planned = [
        _FlakyResponse(429, headers={"retry-after": "0"}),
        _FlakyResponse(200, {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}),
    ]
    _FlakyAsyncClient.requests = []
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "hi"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reply_text"] == "hi"
    assert len(_FlakyAsyncClient.requests) == 2


def test_groq_persistent_429_raises_after_retries(flaky_client):
    from app.routers.playground import _groq_chat

    async def scenario() -> None:
        from app.config import Settings as _S

        client = flaky_client
        token, _ = register(client)
        call_id = start_session(client, token)
        _FlakyAsyncClient.planned = [_FlakyResponse(429, headers={"retry-after": "0"})] * 3
        _FlakyAsyncClient.requests = []
        settings = _S(groq_api_key="k1", database_url="sqlite://", _env_file=None)
        # wait_before_retry_ms=0 disables the give-up-and-retry pass so this
        # test can assert the per-member retry budget on its own.
        with pytest.raises(HTTPException) as excinfo:
            await _groq_chat(
                settings, [{"role": "user", "content": "hi"}], wait_before_retry_ms=0
            )
        assert excinfo.value.status_code == 429
        assert len(_FlakyAsyncClient.requests) == 3

    asyncio.run(scenario())


def test_rate_limited_chain_waits_once_and_recovers(flaky_client):
    """The complaint being fixed: the caller spoke once and got silence, then
    had to repeat themselves. One short wait and a single retry must turn that
    into a (slower) answer."""
    from app.config import Settings as _S
    from app.routers.playground import _groq_chat

    async def scenario() -> None:
        client = flaky_client
        token, _ = register(client)
        start_session(client, token)
        _FlakyAsyncClient.planned = [
            _FlakyResponse(429, headers={"retry-after": "0"})] * 3 + [
            _FlakyResponse(200, {"choices": [{"message": {"role": "assistant", "content": "sorry, one moment - yes, noted"}}]}),
        ]
        _FlakyAsyncClient.requests = []
        settings = _S(groq_api_key="k1", database_url="sqlite://", _env_file=None)
        original_sleep = playground_module.asyncio.sleep

        async def instant(_seconds: object) -> None:
            return None

        playground_module.asyncio.sleep = instant  # type: ignore[assignment]
        try:
            result = await _groq_chat(
                settings, [{"role": "user", "content": "hi"}], wait_before_retry_ms=10
            )
        finally:
            playground_module.asyncio.sleep = original_sleep  # type: ignore[assignment]
        assert result["content"] == "sorry, one moment - yes, noted"
        assert len(_FlakyAsyncClient.requests) == 4

    asyncio.run(scenario())


def test_hard_quota_exhaustion_is_not_retried(flaky_client):
    """A Gemini-style plan/quota rejection must not burn three retries."""
    from app.config import Settings as _S
    from app.routers.playground import _groq_chat

    async def scenario() -> None:
        client = flaky_client
        token, _ = register(client)
        start_session(client, token)
        gemini_quota = {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota, please check your plan "
                "and billing details.",
            }
        }
        _FlakyAsyncClient.planned = [_FlakyResponse(429, gemini_quota)]
        _FlakyAsyncClient.requests = []
        settings = _S(
            groq_api_key="",
            llm_fallback_chain="gemini|https://x/v1|gk|gemini-flash-latest",
            database_url="sqlite://",
            _env_file=None,
        )
        original_sleep = playground_module.asyncio.sleep

        async def instant(_seconds: object) -> None:
            return None

        playground_module.asyncio.sleep = instant  # type: ignore[assignment]
        try:
            with pytest.raises(HTTPException) as excinfo:
                await _groq_chat(
                    settings, [{"role": "user", "content": "hi"}], wait_before_retry_ms=0
                )
        finally:
            playground_module.asyncio.sleep = original_sleep  # type: ignore[assignment]
        assert excinfo.value.status_code == 429
        # One attempt only, not three.
        assert len(_FlakyAsyncClient.requests) == 1

    asyncio.run(scenario())


def test_invented_value_refused_despite_high_confidence(groq_client, session_factory):
    """Regression: expected_return_date='next week' the caller never said."""
    from sqlalchemy import select

    from app.models import ExtractedField
    from test_playground_text import chat, script, start_session, tool_call

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(
        tool_call(
            "record_extracted_field",
            {"field_name": "expected_return_date", "value": "next week", "confidence": 0.9},
        ),
        chat("When will he be back?"),
    )
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "He is sick."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["extracted_fields"] == []
    with session_factory() as db:
        rows = db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call_id)
        ).all()
        assert [f.field_name for f in rows] == []


def test_run_on_reply_is_capped_to_two_sentences(groq_client, session_factory):
    """Regression: the agent packed a question, a thank-you, a callback offer
    and a goodbye into one reply, so the caller never got to answer."""
    from sqlalchemy import select

    from app.models import Transcript
    from test_playground_text import chat, script, start_session

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(
        chat(
            "By which date will he be back in college?Thank you. "
            "Would you like someone from the college to call you back about "
            "anything?Sure, I can note that. If you need anything else, just "
            "let me know. Have a good day."
        )
    )
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "He has a fever."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    reply = resp.json()["reply_text"]
    assert reply == "By which date will he be back in college? Thank you."
    with session_factory() as db:
        stored = [
            t.text
            for t in db.scalars(
                select(Transcript).where(Transcript.call_id == call_id, Transcript.speaker == "agent")
            ).all()
        ]
        assert stored == [reply]


def test_cap_reply_keeps_short_replies_intact() -> None:
    from app.routers.playground import _cap_reply

    assert _cap_reply("Hi, happy to help.") == "Hi, happy to help."
    assert _cap_reply("A? B? C? D?") == "A? B?"
    assert _cap_reply("   ") == ""


def test_tool_choice_conflict_strips_history_instead_of_resending() -> None:
    """The 400 loop, reproduced: the model calls a tool while tools are
    disabled. The recovery used to resend the IDENTICAL payload, reproducing
    the same 400 while spending a rate-limited key."""
    from app.routers.playground import _strip_tool_traffic

    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "he had fever"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "function": {}}]},
        {"role": "tool", "tool_call_id": "1", "content": "Recorded reason_for_absence='fever'"},
        {"role": "assistant", "content": "Noted. When is he back?", "tool_calls": [{"id": "2"}]},
        {"role": "tool", "tool_call_id": "2", "content": "NOT RECORDED: never stated"},
    ]
    cleaned = _strip_tool_traffic(history)
    assert [m["role"] for m in cleaned] == ["system", "user", "assistant"]
    # The tool-call-only assistant turn is dropped entirely (no empty content),
    # the assistant turn that also spoke survives without its tool_calls.
    assert cleaned[2]["content"] == "Noted. When is he back?"
    assert not any("tool_calls" in m for m in cleaned)
    assert not any(m["role"] == "tool" for m in cleaned)


def test_member_body_drops_unsupported_reasoning_effort() -> None:
    """Gemini 400s on reasoning_effort, and Groq rejects the value 'none'."""
    from app.routers.playground import _member_body

    base = {"messages": [], "max_tokens": 160, "reasoning_effort": "low"}
    groq = _member_body(base, "openai/gpt-oss-20b")
    assert groq["reasoning_effort"] == "low"
    # Not a gpt-oss model: the Groq-only knob must not be forwarded.
    assert "reasoning_effort" not in _member_body(base, "gemini-flash-latest")
    # Invalid value for Groq: drop it rather than 400.
    assert "reasoning_effort" not in _member_body(
        {**base, "reasoning_effort": "none"}, "openai/gpt-oss-20b"
    )
    # No-op when absent.
    assert "reasoning_effort" not in _member_body({"messages": []}, "gemini-flash-latest")


def test_tool_choice_conflict_retries_with_clean_history(flaky_client, monkeypatch):
    """End to end through _groq_chat: 400 tool_use_failed, then 200 - and the
    second request must not carry the tool traffic that caused it."""
    from app.routers.playground import _message_or_raise  # noqa: F401 - import guard

    client = flaky_client
    _FlakyAsyncClient.planned = [
        _FlakyResponse(400, {"error": {"code": "tool_use_failed", "message": "Tool choice is none, but model called a tool"}}),
        _FlakyResponse(200, {"choices": [{"message": {"role": "assistant", "content": "sure, noted"}}]}),
    ]
    _FlakyAsyncClient.requests = []
    import asyncio as _asyncio

    from app.config import Settings as _S

    settings = _S(groq_api_key="k1", database_url="sqlite://", _env_file=None)
    settings.livekit_url = "ws://x"  # unused here
    result = _asyncio.run(
        __import__("app.routers.playground", fromlist=["_groq_chat"])._groq_chat(
            settings,
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "he had fever"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
                {"role": "tool", "tool_call_id": "1", "content": "ok"},
            ],
            include_tools=False,
        )
    )
    assert result["content"] == "sure, noted"
    assert len(_FlakyAsyncClient.requests) == 2
    retry_messages = _FlakyAsyncClient.requests[1]["json"]["messages"]
    assert [m["role"] for m in retry_messages] == ["system", "user"]
    assert "tools" not in _FlakyAsyncClient.requests[1]["json"]


def test_reasoning_models_get_a_larger_output_cap() -> None:
    """Measured: gpt-oss-20b at max_tokens=160 returned completion=160 with
    EMPTY content and no tool call - the agent's silence. qwen3.8-27b answers
    in 60 tokens at the same cap."""
    from app.routers.playground import (
        _DEFAULT_MAX_TOKENS,
        _REASONING_MAX_TOKENS,
        _max_tokens_for,
        _member_body,
    )

    assert _max_tokens_for("qwen/qwen3.8-27b") == _DEFAULT_MAX_TOKENS
    assert _max_tokens_for("openai/gpt-oss-20b") == _REASONING_MAX_TOKENS
    assert _REASONING_MAX_TOKENS > _DEFAULT_MAX_TOKENS
    assert _member_body({"max_tokens": 160}, "openai/gpt-oss-20b")["max_tokens"] == _REASONING_MAX_TOKENS
    assert _member_body({"max_tokens": 160}, "qwen/qwen3.8-27b")["max_tokens"] == 160


def test_shared_quota_error_is_detected() -> None:
    """Groq's TPM bucket is per organization, so remaining keys of the same
    provider cannot help and must be skipped."""
    from app.routers.playground import _is_shared_quota_exhausted

    org_tpm = (
        '{"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in '
        'organization `org_01ky4xmtzjfe3aqq78hh4jw7sd` service tier `on_demand` '
        'on tokens per minute (TPM): Limit 8000, Requested 9210"}}'
    )
    assert _is_shared_quota_exhausted(org_tpm) is True
    assert _is_shared_quota_exhausted("rate_limited") is False
    assert _is_shared_quota_exhausted("model_decommissioned") is False


def test_shared_quota_skips_the_rest_of_that_provider(flaky_client, monkeypatch):
    """Two Groq keys, one other provider: an org-level TPM rejection must move
    to the other provider instead of re-trying the second key."""
    import asyncio as _asyncio

    from app.config import Settings as _S
    from app.routers.playground import _groq_chat

    _FlakyAsyncClient.planned = [
        _FlakyResponse(429, {"error": {"message": "Rate limit reached ... on tokens per minute (TPM): Limit 8000"}}),
        _FlakyResponse(200, {"choices": [{"message": {"role": "assistant", "content": "served by fallback"}}]}),
    ]
    _FlakyAsyncClient.requests = []
    settings = _S(
        groq_api_key="k1",
        groq_api_keys="k1,k2",
        llm_fallback_chain="cerebras|https://api.cerebras.ai/v1|ck1|llama-3.3-70b",
        database_url="sqlite://",
        _env_file=None,
    )
    result = _asyncio.run(_groq_chat(settings, [{"role": "user", "content": "hi"}]))
    assert result["content"] == "served by fallback"
    bearers = [r["headers"]["Authorization"] for r in _FlakyAsyncClient.requests]
    # key 1 fails on the shared bucket -> key 2 is skipped -> cerebras answers.
    assert bearers == ["Bearer k1", "Bearer ck1"]


def test_provider_handoff_brief_is_only_injected_on_a_real_switch() -> None:
    from app.routers.playground import _provider_handoff_block

    captured = [{"field_name": "reason_for_absence", "field_value": "fever"}]
    turns = ["caller: yes", "agent: noted, when is he back?"]
    # Same provider serving the next turn: nothing to bridge.
    assert _provider_handoff_block(("groq", "qwen"), ("groq", "qwen"), captured, turns) is None
    # First turn of a call: no predecessor.
    assert _provider_handoff_block(None, ("groq", "qwen"), captured, turns) is None
    block = _provider_handoff_block(("groq", "qwen"), ("gemini", "flash"), captured, turns)
    assert block is not None
    lowered = block.lower()
    assert "do not introduce yourself again" in lowered
    assert "reason_for_absence=fever" in block
    assert "caller: yes" in block
    assert "groq" in block and "gemini" in block


def test_chain_fails_over_and_hands_over_context(flaky_client):
    """Groq is rate limited, the fallback serves the turn, and the fallback
    request carries a continuity brief naming what was already captured."""
    from app.config import Settings as _S
    from app.routers.playground import _groq_chat

    async def scenario() -> None:
        client = flaky_client
        token, _ = register(client)
        start_session(client, token)
        _FlakyAsyncClient.planned = [
            _FlakyResponse(429, {"error": {"message": "Rate limit reached ... on tokens per minute (TPM): Limit 8000"}}),
            _FlakyResponse(200, {"choices": [{"message": {"role": "assistant", "content": "noted"}}]}),
        ]
        _FlakyAsyncClient.requests = []
        settings = _S(
            groq_api_key="k1",
            llm_fallback_chain="gemini|https://x/v1|gk|gemini-flash-latest",
            database_url="sqlite://",
            _env_file=None,
        )
        message = await _groq_chat(
            settings,
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "when is he back?"}],
            previous_provider=("groq", "qwen/qwen3.8-27b"),
            captured=[{"field_name": "reason_for_absence", "field_value": "fever"}],
            recent_turns=["caller: he has a fever"],
        )
        assert message["content"] == "noted"
        assert message["served_by"] == {"provider": "gemini", "model": "gemini-flash-latest"}
        fallback_request = _FlakyAsyncClient.requests[-1]["json"]
        first = fallback_request["messages"][0]
        assert first["role"] == "system"
        assert "CONTINUITY" in first["content"]
        assert "reason_for_absence=fever" in first["content"]
        # The original system prompt must still be present underneath it.
        assert any(m.get("content") == "sys" for m in fallback_request["messages"])

    asyncio.run(scenario())


def test_serving_provider_is_persisted_for_the_next_turn(groq_client, session_factory):
    """The handoff only works if the next turn knows who served this one."""
    from sqlalchemy import select

    from app.models import Call
    from test_playground_text import chat, script, start_session

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(chat("Noted."))
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "sick"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        call = db.get(Call, call_id)
        assert call.context.get("llm_provider") == {
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
        }


def test_voice_worker_events_land_in_the_diagnostics_feed(groq_client):
    """The worker posts STT/TTS/LLM events from another process; the panel only
    works if they arrive here."""
    token, _ = register(groq_client)
    groq_client.post("/api/playground/events", headers=auth_headers(token))
    resp = groq_client.post(
        "/internal/telemetry/events",
        json={
            "events": [
                {
                    "kind": "voice_session_start",
                    "provider": "deepgram",
                    "message": "STT=deepgram LLM=FallbackLLM TTS=cartesia",
                    "call_id": 77,
                },
                {
                    "kind": "stt_final",
                    "provider": "deepgram",
                    "message": "transcribed: 'sick leave'",
                    "call_id": 77,
                },
                {"kind": "voice_provider_problem", "level": "error", "message": "DEEPGRAM_API_KEY missing"},
                "not-a-dict",
            ]
        },
        headers={"X-Internal-Token": "test_internal_token"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["recorded"] == 3

    feed = groq_client.get("/api/playground/events?since=0", headers=auth_headers(token)).json()
    kinds = {e["kind"] for e in feed["events"]}
    assert "stt_final" in kinds
    assert "voice_session_start" in kinds
    assert any(e["level"] == "error" for e in feed["events"])


def test_voice_worker_events_require_the_internal_token(groq_client):
    resp = groq_client.post(
        "/internal/telemetry/events", json={"events": [{"kind": "stt_final"}]}
    )
    assert resp.status_code == 401


def test_short_date_answer_is_captured_even_when_another_field_lands(
    groq_client, session_factory
):
    """Live regression: the parent said "2nd oct" and the return date was lost.

    Two separate bugs were involved. The backstop was gated on "the model
    recorded nothing this turn", but this turn ALSO carried a recorded field,
    so the safety net was suppressed; and a short date answer contains none of
    the field's words, so word overlap alone could not match it either.
    """
    from sqlalchemy import select

    from app.models import ExtractedField
    from test_playground_text import chat, script, start_session, tool_call

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(
        # The model records a different field this turn and says nothing else.
        tool_call(
            "record_extracted_field",
            {"field_name": "is_sick_leave", "value": "yes", "confidence": 0.9},
        ),
        chat("Thanks."),
    )
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "2nd oct"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    names = [f["field_name"] for f in resp.json()["extracted_fields"]]
    assert "expected_return_date" in names, names
    with session_factory() as db:
        rows = db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call_id)
        ).all()
        stored = {r.field_name: r.field_value for r in rows}
    # An explicit day-month ("2nd oct") is stored as the resolved ISO date, not
    # the raw phrase - export and speech must agree. Resolved against the live
    # clock (Oct 2 rolls to next year once it has passed).
    assert stored.get("expected_return_date") == _iso_oct2()
    # The model's own record must not be overwritten by the backstop.
    assert stored.get("is_sick_leave") == "yes"


def test_backstop_never_overwrites_a_model_recorded_field(groq_client, session_factory):
    from sqlalchemy import select

    from app.models import ExtractedField
    from test_playground_text import chat, script, start_session, tool_call

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(
        tool_call(
            "record_extracted_field",
            {"field_name": "reason_for_absence", "value": "sick leave", "confidence": 0.9},
        ),
        chat("Thanks."),
    )
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "sick leave on monday"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        rows = db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call_id)
        ).all()
        stored = {r.field_name: r.field_value for r in rows}
    assert stored["reason_for_absence"] == "sick leave"


def test_explicit_date_normalizes_to_iso() -> None:
    import datetime

    from app.routers.playground import _normalize_explicit_date

    today = datetime.date(2026, 9, 30)
    assert _normalize_explicit_date("2nd oct", today) == "2026-10-02"
    assert _normalize_explicit_date("on the 5th of january", today) == "2027-01-05"
    # Already-passed dates roll to next year; vague answers are untouched.
    assert _normalize_explicit_date("20 september", today) == "2027-09-20"
    assert _normalize_explicit_date("after 2 days", today) == "2026-10-02"
    assert _normalize_explicit_date("in 3 days", today) == "2026-10-03"
    assert _normalize_explicit_date("tomorrow", today) == "2026-10-01"
    assert _normalize_explicit_date("soon", today) is None
    assert _normalize_explicit_date("next week", today) is None
    assert _normalize_explicit_date("in a few days", today) is None
    assert _normalize_explicit_date("31st of feb", today) is None
    assert _normalize_explicit_date("", today) is None


def test_deterministic_close_on_a_farewell_after_all_fields(groq_client, session_factory):
    """Live loop: the agent said goodbye four times without calling end_call.
    When every required field is known and the reply is a farewell, the turn
    is marked done server-side."""
    from test_playground_text import chat, script, start_session

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    # Pre-fill the required fields as if an earlier, working turn captured them.
    script(
        chat("Thanks, have a good day."),
        chat("Goodbye."),
        chat("Thanks, bye."),
    )
    from sqlalchemy import select

    from app.models import ExtractedField

    with session_factory() as db:
        db.add_all(
            [
                ExtractedField(call_id=call_id, field_name="reason_for_absence", field_value="sick leave", confidence=1.0, source_turn_index=0),
                ExtractedField(call_id=call_id, field_name="expected_return_date", field_value="2026-10-02", confidence=1.0, source_turn_index=0),
                ExtractedField(call_id=call_id, field_name="call_outcome", field_value="resolved", confidence=1.0, source_turn_index=0),
            ]
        )
        db.commit()
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "okay, bye"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["done"] is True, resp.json()


def test_bare_thanks_is_a_closing_line() -> None:
    """Live loop: the call drifted through tail fragments ("Thanks", "Is",
    "Could you") because a bare "Thanks" was never recognized as the close.
    A short thanks with no question closes; a mid-call thanks that keeps
    talking must never match."""
    from app.routers.playground import _is_closing_line

    assert _is_closing_line("Thanks") is True
    assert _is_closing_line("Thank you, Ram.") is True
    assert _is_closing_line("Thanks, bye.") is True
    assert _is_closing_line("Thanks, Ram. Could you tell me the reason?") is False
    assert _is_closing_line("Thanks, Ram. Abhi was absent from college today.") is False
    assert _is_closing_line("") is False


def test_diagnostics_reports_chain_and_events_without_keys(groq_client):
    """The operator's verification aid: what is configured, which provider
    served, what fell back. It must never leak a key."""
    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(chat("Noted, thank you."))
    turn = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "he has a fever"},
        headers=auth_headers(token),
    )
    assert turn.status_code == 200, turn.text

    resp = client.get("/api/playground/diagnostics", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["components"]["llm"]["configured"] is True
    assert body["components"]["stt"]["name"] == "Deepgram"
    assert body["components"]["tts"]["name"] == "Cartesia"
    assert body["llm_chain"], "chain should list the armed provider"
    entry = body["llm_chain"][0]
    assert entry["key_present"] is True
    assert entry["output_cap"] > 0
    # No secret material anywhere in the payload.
    raw = json.dumps(body)
    assert "test-groq-key" not in raw
    assert "Bearer" not in raw
    # Events exist for this call and are attributable to it.
    kinds = {e["kind"] for e in body["events"]}
    assert "llm_attempt" in kinds
    assert any(e["call_id"] == call_id for e in body["events"])


def test_events_endpoint_supports_incremental_polling(groq_client):
    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(chat("Sure."))
    client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "hello"},
        headers=auth_headers(token),
    )
    first = client.get("/api/playground/events", headers=auth_headers(token)).json()
    assert first["events"]
    seq = first["latest_seq"]
    # Polling with the cursor returns nothing new until something happens.
    second = client.get(
        f"/api/playground/events?since={seq}", headers=auth_headers(token)
    ).json()
    assert second["events"] == []


def test_diagnostics_requires_auth(groq_client):
    assert groq_client.get("/api/playground/diagnostics").status_code == 401


def test_placeholder_key_never_occupies_a_chain_slot() -> None:
    """The shipped OPENAI_API_KEY=your_openai_api_key must not be armed: a
    template key 401s on every turn and reads like a provider outage."""
    from app.config import Settings

    settings = Settings(
        database_url="sqlite://",
        openai_api_key="your_openai_api_key",
        cerebras_api_key="",
        openrouter_api_key="",
        groq_api_key="gsk_real",
        _env_file=None,
    )
    assert [(name, key) for name, _u, key, _m in settings.llm_chain] == [("groq", "gsk_real")]


def test_shorthand_keys_extend_the_chain_in_order() -> None:
    from app.config import Settings

    settings = Settings(
        database_url="sqlite://",
        openai_api_key="sk-real",
        cerebras_api_key="ck-real",
        openrouter_api_key="or-real",
        groq_api_key="gsk_real",
        _env_file=None,
    )
    assert [name for name, _u, _k, _m in settings.llm_chain] == [
        "groq",
        "openai",
        "cerebras",
        "openrouter",
    ]


def test_never_stated_date_is_refused(groq_client, session_factory):
    """Regression from the first live test call: caller answered 'hlooo' and
    the agent recorded expected_return_date='tomorrow at 8am' at 95%."""
    from sqlalchemy import select

    from app.models import ExtractedField
    from test_playground_text import chat, script, start_session, tool_call

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(
        tool_call(
            "record_extracted_field",
            {"field_name": "expected_return_date", "value": "tomorrow at 8am", "confidence": 0.95},
        ),
        chat("Sorry, when do you expect him back?"),
    )
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "hlooo"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["extracted_fields"] == []
    with session_factory() as db:
        rows = db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call_id)
        ).all()
        assert [f.field_name for f in rows] == []


def test_stated_relative_date_is_accepted(groq_client, session_factory):
    """The grounding guard must not block a date the caller really gave."""
    from sqlalchemy import select

    from app.models import ExtractedField
    from test_playground_text import chat, script, start_session, tool_call

    client = groq_client
    token, _ = register(client)
    call_id = start_session(client, token)
    script(
        tool_call(
            "record_extracted_field",
            {"field_name": "expected_return_date", "value": "tomorrow", "confidence": 0.9},
        ),
        chat("Noted, thank you."),
    )
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "he will come tomorrow morning"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    # "tomorrow" is resolvable against a known today, so it is normalized to an
    # ISO date on write. The point of this test is that the value is ACCEPTED
    # (never refused or stored empty), not that it stays a raw phrase.
    assert resp.json()["extracted_fields"] == [
        {
            "field_name": "expected_return_date",
            "field_value": _iso_in(1),
            "confidence": 0.9,
        }
    ]
    with session_factory() as db:
        rows = db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call_id)
        ).all()
        assert [(f.field_name, f.field_value) for f in rows] == [
            ("expected_return_date", _iso_in(1))
        ]


def test_chain_fails_over_to_next_provider_when_one_is_rate_limited(session_factory, monkeypatch):
    """Live failure being fixed: one Groq key 429s mid-conversation and the
    agent goes silent. A second configured provider must serve the turn."""
    from test_playground_text import start_session as _start

    from conftest import make_settings

    monkeypatch.setattr(playground_module.httpx, "AsyncClient", _FlakyAsyncClient)
    _FlakyAsyncClient.planned = []
    _FlakyAsyncClient.requests = []
    from app.main import create_app

    fresh = create_app(
        make_settings(
            groq_api_key="k1",
            llm_fallback_chain="cerebras|https://api.cerebras.ai/v1|ck1|llama-3.3-70b",
        )
    )
    fresh.state.session_factory = session_factory
    with TestClient(fresh) as client:
        token, _ = register(client)
        call_id = _start(client, token)
        _FlakyAsyncClient.planned = [_FlakyResponse(429, headers={"retry-after": "0"})] * 3 + [
            _FlakyResponse(200, {"choices": [{"message": {"role": "assistant", "content": "still here"}}]}),
        ]
        _FlakyAsyncClient.requests = []
        resp = client.post(
            f"/api/playground/sessions/{call_id}/turns",
            json={"text": "hi"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["reply_text"] == "still here"
        bearers = [r["headers"]["Authorization"] for r in _FlakyAsyncClient.requests]
        assert bearers == ["Bearer k1"] * 3 + ["Bearer ck1"]
        assert _FlakyAsyncClient.requests[-1]["url"] == (
            "https://api.cerebras.ai/v1/chat/completions"
        )
    _FlakyAsyncClient.planned = []
    _FlakyAsyncClient.requests = []


def test_exhausted_chain_reports_rate_limit(session_factory, monkeypatch):
    """Every member rate-limited -> the caller sees 429, not a silent 502."""
    from test_playground_text import start_session as _start

    from conftest import make_settings

    monkeypatch.setattr(playground_module.httpx, "AsyncClient", _FlakyAsyncClient)
    _FlakyAsyncClient.planned = []
    _FlakyAsyncClient.requests = []
    from app.main import create_app

    fresh = create_app(
        make_settings(
            groq_api_key="k1",
            llm_fallback_chain="cerebras|https://api.cerebras.ai/v1|ck1|llama-3.3-70b",
        )
    )
    fresh.state.session_factory = session_factory
    with TestClient(fresh) as client:
        token, _ = register(client)
        call_id = _start(client, token)
        _FlakyAsyncClient.planned = [_FlakyResponse(429, headers={"retry-after": "0"})] * 12
        _FlakyAsyncClient.requests = []
        resp = client.post(
            f"/api/playground/sessions/{call_id}/turns",
            json={"text": "hi"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 429
    _FlakyAsyncClient.planned = []
    _FlakyAsyncClient.requests = []


def test_groq_rotates_to_second_key_after_first_exhausted(session_factory, monkeypatch):
    """Two keys: k1 429s through all its retries, k2 answers immediately."""
    from test_playground_text import start_session as _start

    from conftest import make_settings

    monkeypatch.setattr(playground_module.httpx, "AsyncClient", _FlakyAsyncClient)
    _FlakyAsyncClient.planned = []
    _FlakyAsyncClient.requests = []
    from app.main import create_app

    fresh = create_app(make_settings(groq_api_key="k1", groq_api_keys="k2"))
    fresh.state.session_factory = session_factory
    with TestClient(fresh) as client:
        token, _ = register(client)
        call_id = _start(client, token)
        _FlakyAsyncClient.planned = [_FlakyResponse(429, headers={"retry-after": "0"})] * 3 + [
            _FlakyResponse(200, {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}),
        ]
        _FlakyAsyncClient.requests = []
        resp = client.post(
            f"/api/playground/sessions/{call_id}/turns",
            json={"text": "hi"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["reply_text"] == "hello"
        bearers = [r["headers"]["Authorization"] for r in _FlakyAsyncClient.requests]
        assert bearers == ["Bearer k1"] * 3 + ["Bearer k2"]
    _FlakyAsyncClient.planned = []
    _FlakyAsyncClient.requests = []


