"""Text-path robustness: pseudo tool-call markup + Groq 429 retry."""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.routers.playground as playground_module
from conftest import auth_headers, register
from test_playground_text import chat, create_groq_app, groq_client, script, start_session  # noqa: F401  (pytest fixture import)


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
    from test_playground_text import start_session as _start

    client = flaky_client
    token, _ = register(client)
    call_id = _start(client, token)
    _FlakyAsyncClient.planned = [_FlakyResponse(429, headers={"retry-after": "0"})] * 3
    _FlakyAsyncClient.requests = []
    resp = client.post(
        f"/api/playground/sessions/{call_id}/turns",
        json={"text": "hi"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 429
    assert len(_FlakyAsyncClient.requests) == 3  # initial + 2 retries


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
    assert resp.json()["extracted_fields"] == [
        {"field_name": "expected_return_date", "field_value": "tomorrow", "confidence": 0.9}
    ]
    with session_factory() as db:
        rows = db.scalars(
            select(ExtractedField).where(ExtractedField.call_id == call_id)
        ).all()
        assert [(f.field_name, f.field_value) for f in rows] == [
            ("expected_return_date", "tomorrow")
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
        _FlakyAsyncClient.planned = [_FlakyResponse(429, headers={"retry-after": "0"})] * 6
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

