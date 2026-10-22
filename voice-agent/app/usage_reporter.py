"""Worker-side provider usage reporting for the dashboard.

Groq publishes its quota state ONLY in response headers (``x-ratelimit-*``),
and the voice worker is the only process that sees them — so the worker
captures and forwards them. Deepgram and Cartesia balances are polled by the
backend instead (they have no per-response headers).

Design constraints, in order of importance:

1. Never raise. A usage-accounting bug must never break a live call, and this
   code runs inside an httpx response hook on the critical path.
2. Never persist or log a raw key. Only masked ids (``gsk_...a3f2``) leave the
   process; the backend masks again on ingest.
3. Never add latency. Rows are buffered and flushed by a debounced background
   task, so a turn never waits for the report.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("voice_agent.usage")

#: Response headers emitted by OpenAI-compatible providers (verified against
#: Groq's live responses). Names map to the dashboard's metric vocabulary.
_HEADER_METRICS: dict[str, str] = {
    "x-ratelimit-limit-requests": "limit_requests",
    "x-ratelimit-remaining-requests": "remaining_requests",
    "x-ratelimit-limit-tokens": "limit_tokens",
    "x-ratelimit-remaining-tokens": "remaining_tokens",
}

_FLUSH_DEBOUNCE_S = 1.0
#: Flush immediately past this many buffered rows so a long call cannot grow
#: the buffer without bound between debounce ticks.
_FLUSH_MAX_ROWS = 60

_STATE: dict[str, Any] = {
    "base_url": "",
    "token": "",
    "client": None,
    "pending": [],
    "task": None,
}


def mask_key(value: Any) -> str:
    """Masked key id for display (``gsk_...a3f2``). Never returns the raw key."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "..." + text[-2:] if len(text) >= 2 else "..."
    prefix = "gsk_" if text.startswith("gsk_") else ("sk-" if text.startswith("sk-") else "")
    head = prefix or text[:3]
    return f"{head}...{text[-4:]}"


def configure(base_url: str, token: str) -> None:
    """Point the reporter at the backend internal API. Idempotent."""
    _STATE["base_url"] = str(base_url or "").rstrip("/")
    _STATE["token"] = str(token or "")


def _number(value: Any) -> Optional[float]:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number:  # NaN
        return None
    return number


def snapshots_from_response(
    response: Any, *, provider: str, api_key: str, model: str
) -> list[dict[str, Any]]:
    """Extract quota headers from one LLM response (no I/O, never raises)."""
    headers = getattr(response, "headers", None) or {}
    try:
        key_id = mask_key(api_key)
    except Exception:  # noqa: BLE001 - accounting must never break a call
        return []
    rows: list[dict[str, Any]] = []
    for header, metric in _HEADER_METRICS.items():
        value = _number(headers.get(header))
        if value is None:
            continue
        rows.append(
            {
                "provider": provider,
                "key_id": key_id,
                "model": model,
                "metric": metric,
                "value": value,
            }
        )
    if int(getattr(response, "status_code", 0) or 0) == 429:
        retry_after = _number(headers.get("retry-after"))
        if retry_after is not None:
            rows.append(
                {
                    "provider": provider,
                    "key_id": key_id,
                    "model": model,
                    "metric": "retry_after_seconds",
                    "value": retry_after,
                }
            )
    return rows


def record_llm_response(
    provider: str, api_key: str, model: str, response: Any
) -> None:
    """Buffer one LLM response's quota headers. Safe inside an httpx hook."""
    try:
        rows = snapshots_from_response(
            response, provider=provider, api_key=api_key, model=model
        )
    except Exception:  # noqa: BLE001 - hook must never raise into the transport
        return
    if rows:
        _enqueue(rows)


def record_tts_characters(
    text: str, *, provider: str = "sarvam", model: str = "", api_key: str = ""
) -> None:
    """Count spoken characters for a provider billed per character (Bulbul).

    ``text`` is the exact string the agent asked the TTS to synthesize, so the
    sum is a faithful local estimate of the billable volume.
    """
    count = len(str(text or ""))
    if count <= 0:
        return
    _enqueue(
        [
            {
                "provider": provider,
                "key_id": mask_key(api_key) if api_key else "",
                "model": model,
                "metric": "characters",
                "value": float(count),
            }
        ]
    )


def _enqueue(rows: list[dict[str, Any]]) -> None:
    pending = _STATE["pending"]
    pending.extend(rows)
    _schedule_flush(immediate=len(pending) >= _FLUSH_MAX_ROWS)


def _schedule_flush(*, immediate: bool) -> None:
    if not _STATE["base_url"]:
        return
    task = _STATE.get("task")
    if task is not None and not task.done():
        # A flush is already queued and drains everything pending, so a new
        # row needs no second task (and no second request).
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop (sync context): drop, next turn will flush
        return
    try:
        _STATE["task"] = loop.create_task(
            _delayed_flush(0.0 if immediate else _FLUSH_DEBOUNCE_S)
        )
    except Exception:  # noqa: BLE001 - accounting must never break a call
        logger.debug("usage flush scheduling failed", exc_info=True)


async def _delayed_flush(delay: float) -> None:
    if delay > 0:
        await asyncio.sleep(delay)
    await flush()


def _http() -> httpx.AsyncClient:
    client = _STATE.get("client")
    if client is None:
        client = httpx.AsyncClient(timeout=5.0)
        _STATE["client"] = client
    return client


async def flush() -> int:
    """POST buffered rows to the backend. Returns rows accepted (0 on failure)."""
    rows = _STATE["pending"]
    base_url = _STATE["base_url"]
    if not rows or not base_url:
        return 0
    batch = list(rows)
    _STATE["pending"] = []
    try:
        response = await _http().post(
            f"{base_url}/internal/usage",
            json={"snapshots": batch},
            headers={"X-Internal-Token": _STATE["token"]},
        )
        response.raise_for_status()
        return len(batch)
    except Exception as exc:  # noqa: BLE001 - lost usage must not break a call
        logger.debug("usage report failed (%d rows): %s", len(batch), exc)
        return 0


async def aclose() -> None:
    """Flush and release the client (worker shutdown)."""
    try:
        await flush()
    finally:
        client = _STATE.get("client")
        _STATE["client"] = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("usage client close failed", exc_info=True)