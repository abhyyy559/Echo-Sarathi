"""Worker-side provider usage capture (app.usage_reporter).

Groq publishes quota ONLY in response headers, and this worker is the only
place that sees them — so these tests pin both the extraction and the masking
(a raw key must never leave the process).
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import usage_reporter


@pytest.fixture(autouse=True)
def _reset_reporter(monkeypatch) -> None:
    """Isolate module state between tests (it is a process-wide singleton)."""
    monkeypatch.setattr(usage_reporter, "_STATE", {
        "base_url": "",
        "token": "",
        "client": None,
        "pending": [],
        "task": None,
    })


class _Response:
    def __init__(self, headers: dict[str, str], status_code: int = 200) -> None:
        self.headers = headers
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_masks_key_never_leaks_raw_value() -> None:
    assert usage_reporter.mask_key("gsk_1234567890abcdef") == "gsk_...cdef"
    assert usage_reporter.mask_key("sk-abcdefghijklmnop") == "sk-...mnop"
    assert usage_reporter.mask_key("") == ""
    assert usage_reporter.mask_key("ab") == "...ab"


def test_snapshots_from_response_captures_groq_headers() -> None:
    response = _Response(
        {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "998",
            "x-ratelimit-limit-tokens": "8000",
            "x-ratelimit-remaining-tokens": "6421",
        }
    )
    rows = usage_reporter.snapshots_from_response(
        response, provider="groq", api_key="gsk_secretsecretsecret", model="qwen/qwen3.8-27b"
    )
    metrics = {row["metric"]: row["value"] for row in rows}
    assert metrics == {
        "limit_requests": 1000.0,
        "remaining_requests": 998.0,
        "limit_tokens": 8000.0,
        "remaining_tokens": 6421.0,
    }
    assert {row["key_id"] for row in rows} == {"gsk_...cret"}
    assert not any("secret" in str(row["key_id"]) for row in rows[1:])
    assert all(row["provider"] == "groq" for row in rows)


def test_snapshots_from_response_records_retry_after_on_429() -> None:
    response = _Response(
        {"x-ratelimit-remaining-tokens": "0", "retry-after": "12.5"}, status_code=429
    )
    rows = usage_reporter.snapshots_from_response(
        response, provider="groq", api_key="gsk_x", model="m"
    )
    metrics = {row["metric"]: row["value"] for row in rows}
    assert metrics["remaining_tokens"] == 0.0
    assert metrics["retry_after_seconds"] == 12.5


def test_snapshots_from_response_is_empty_without_headers() -> None:
    assert usage_reporter.snapshots_from_response(
        _Response({}), provider="groq", api_key="k", model="m"
    ) == []
    # A non-response object must not raise: this runs inside an httpx hook.
    assert usage_reporter.snapshots_from_response(
        object(), provider="groq", api_key="k", model="m"
    ) == []


def test_record_tts_characters_counts_billable_text() -> None:
    telugu = "నమస్కారం!"
    usage_reporter.record_tts_characters(telugu)
    pending = usage_reporter._STATE["pending"]
    assert len(pending) == 1
    assert pending[0]["metric"] == "characters"
    assert pending[0]["value"] == float(len(telugu))
    assert pending[0]["provider"] == "sarvam"
    # Nothing to bill for an empty utterance.
    usage_reporter.record_tts_characters("")
    assert len(usage_reporter._STATE["pending"]) == 1


def test_flush_posts_buffered_rows_and_clears_them(monkeypatch) -> None:
    posts: list[dict[str, Any]] = []

    class _Client:
        async def post(self, url: str, json: Any = None, headers: Any = None):
            posts.append({"url": url, "json": json, "headers": headers})
            return _Response({})

    usage_reporter.configure("https://api.example.com/", "internal-tok")
    monkeypatch.setattr(usage_reporter, "_http", lambda: _Client())

    usage_reporter.record_tts_characters("hello", model="bulbul:v3")
    written = asyncio.run(usage_reporter.flush())

    assert written == 1
    assert usage_reporter._STATE["pending"] == []
    assert posts[0]["url"] == "https://api.example.com/internal/usage"
    assert posts[0]["headers"]["X-Internal-Token"] == "internal-tok"
    assert posts[0]["json"]["snapshots"][0]["metric"] == "characters"


def test_flush_is_a_noop_without_a_configured_backend(monkeypatch) -> None:
    usage_reporter.record_tts_characters("hello")

    def _boom():  # pragma: no cover - must never be reached
        raise AssertionError("no HTTP call may happen without a base url")

    monkeypatch.setattr(usage_reporter, "_http", _boom)
    assert asyncio.run(usage_reporter.flush()) == 0


def test_flush_swallows_transport_failure(monkeypatch) -> None:
    class _Client:
        async def post(self, *args: Any, **kwargs: Any):
            raise OSError("connection reset")

    usage_reporter.configure("https://api.example.com", "tok")
    monkeypatch.setattr(usage_reporter, "_http", lambda: _Client())

    usage_reporter.record_tts_characters("hello")
    # Lost usage must never break a call: rows are dropped, no exception.
    assert asyncio.run(usage_reporter.flush()) == 0