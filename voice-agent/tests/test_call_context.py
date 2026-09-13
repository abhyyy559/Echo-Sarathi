"""Call context fetch (C): BackendClient.fetch_call_context.

GETs /internal/calls/{call_id}/context and returns the parsed dict, or {} on
failure (non-fatal for the voice session).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.backend_client import BackendClient


class _Resp:
    def __init__(self, payload: Any, error: bool = False) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error:
            raise httpx.ConnectError("boom")

    def json(self) -> Any:
        return self._payload


class _BadJsonResp:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        raise ValueError("not json")


class _FakeClient:
    def __init__(self, resp: Any) -> None:
        self.resp = resp
        self.gets: list[tuple[str, Any]] = []

    async def get(self, url: str, **kwargs: Any) -> Any:
        self.gets.append((url, kwargs))
        return self.resp


def _client(resp: Any) -> BackendClient:
    return BackendClient("http://base", "tok", client=_FakeClient(resp))


def test_fetch_call_context_returns_parsed_dict() -> None:
    fake = _FakeClient(_Resp({"institution_name": "Demo Univ", "contact": {"name": "A"}}))
    bc = BackendClient("http://base", "tok", client=fake)
    result = asyncio.run(bc.fetch_call_context("call-9"))
    assert result["institution_name"] == "Demo Univ"
    assert result["contact"]["name"] == "A"
    assert fake.gets[0][0].endswith("/internal/calls/call-9/context")


def test_fetch_call_context_returns_empty_on_http_error() -> None:
    bc = _client(_Resp(None, error=True))
    assert asyncio.run(bc.fetch_call_context("c1")) == {}


def test_fetch_call_context_returns_empty_on_bad_json() -> None:
    bc = _client(_BadJsonResp())
    assert asyncio.run(bc.fetch_call_context("c1")) == {}
