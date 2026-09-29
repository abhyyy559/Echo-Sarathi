"""Text-path robustness: pseudo tool-call markup + Groq 429 retry."""
from __future__ import annotations

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
        self.text = "rate limited" if status_code == 429 else ""

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
            llm_fallback_chain="cerebras:https://api.cerebras.ai/v1:ck1:llama-3.3-70b",
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
            llm_fallback_chain="cerebras:https://api.cerebras.ai/v1:ck1:llama-3.3-70b",
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
