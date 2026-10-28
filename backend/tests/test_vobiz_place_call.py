"""Vobiz call-create: carrier refusals must reach the operator in plain words."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.telephony import VobizClient

from conftest import make_settings


def _client(monkeypatch, handler, public_base_url: str = "https://api.example.com") -> VobizClient:
    real_client = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    settings = make_settings(
        public_base_url=public_base_url,
        vobiz_auth_id="MA_TEST",
        vobiz_auth_token="test-token",
        vobiz_phone_number="+911234567890",
    )
    return VobizClient(settings)


def test_carrier_reason_is_surfaced_not_just_the_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"api_id": "x", "error": "answer_url parameter is not valid"},
            request=request,
        )

    client = _client(monkeypatch, handler)
    with pytest.raises(RuntimeError) as excinfo:
        client.place_call("+919000000001", 7)
    message = str(excinfo.value)
    assert "400" in message
    assert "answer_url parameter is not valid" in message
    assert "developer.mozilla.org" not in message


def test_loopback_answer_url_is_refused_before_the_api_call(monkeypatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json={"request_uuid": "nope"}, request=request)

    client = _client(monkeypatch, handler, public_base_url="http://localhost:8000")
    with pytest.raises(RuntimeError) as excinfo:
        client.place_call("+919000000001", 7)
    assert "PUBLIC_BASE_URL" in str(excinfo.value)
    assert calls == []


def test_queued_call_returns_provider_id(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"request_uuid": "abc-123"}, request=request)

    client = _client(monkeypatch, handler)
    assert client.place_call("+919000000001", 7) == "abc-123"
