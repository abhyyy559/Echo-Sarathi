"""Daily provider usage pollers.

Deepgram and Cartesia expose usage/credit endpoints; neither should be called
per request. The worker/backend record Groq headers and Sarvam characters
inline, while this module refreshes the two remaining provider balances once a
day (and on an explicit /api/dev/usage/refresh).

All failures are logged and skipped: a missing project id, an admin key that
was not provisioned, or a provider outage must never prevent the API from
starting.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Optional

import httpx

from app.services.usage import mask_key, record_snapshots
from app.timeutil import utcnow

logger = logging.getLogger(__name__)

DEEPGRAM_USAGE_URL = "https://api.deepgram.com/v1/projects/{project_id}/usage"
CARTESIA_CREDITS_URL = "https://api.cartesia.ai/usage/credits"

#: Metrics that are meaningful even if the provider wraps them differently.
_PREFERRED_CARTESIA = {
    "remaining": "credits_remaining",
    "used": "credits_used",
    "total": "credits_total",
    "limit": "credits_total",
    "credits_remaining": "credits_remaining",
    "credits_used": "credits_used",
    "credits_total": "credits_total",
}


def _numeric_leaves(value: Any, prefix: str = "") -> dict[str, float]:
    """Flatten numeric JSON leaves into ``dotted.path -> sum``."""
    leaves: dict[str, float] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            for leaf, number in _numeric_leaves(child, name).items():
                leaves[leaf] = leaves.get(leaf, 0.0) + number
    elif isinstance(value, list):
        for child in value:
            for leaf, number in _numeric_leaves(child, prefix).items():
                leaves[leaf] = leaves.get(leaf, 0.0) + number
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        leaves[prefix or "value"] = float(value)
    return leaves


def _best_metric_name(path: str) -> str:
    """Normalize a nested leaf name to the short metric the UI expects."""
    lowered = path.lower().rsplit(".", 1)[-1]
    return _PREFERRED_CARTESIA.get(lowered, f"usage_{lowered}")


async def _fetch_deepgram(
    client: httpx.AsyncClient, settings: Any
) -> list[dict[str, Any]]:
    project_id = str(getattr(settings, "deepgram_project_id", "") or "").strip()
    api_key = str(getattr(settings, "deepgram_api_key", "") or "").strip()
    if not project_id or not api_key:
        return []
    end = utcnow().date()
    start = end - timedelta(days=30)
    try:
        response = await client.get(
            DEEPGRAM_USAGE_URL.format(project_id=project_id),
            params={"start": start.isoformat(), "end": end.isoformat()},
            headers={"Authorization": f"Token {api_key}"},
        )
        response.raise_for_status()
        payload: Any = response.json()
    except Exception as exc:  # noqa: BLE001 - optional collector
        logger.warning("Deepgram usage poll failed: %s", exc)
        return []
    rows: list[dict[str, Any]] = []
    key_id = mask_key(api_key)
    for path, value in _numeric_leaves(payload).items():
        # Keep the useful top-level totals, drop noisy nested ids/counts.
        metric = path.rsplit(".", 1)[-1].lower()
        if not any(
            marker in metric
            for marker in ("request", "hour", "minute", "token", "audio", "cost", "usage")
        ):
            continue
        rows.append(
            {
                "provider": "deepgram",
                "key_id": key_id,
                "model": "nova-3",
                "metric": metric[:60],
                "value": value,
            }
        )
    return rows


async def _fetch_cartesia(
    client: httpx.AsyncClient, settings: Any
) -> list[dict[str, Any]]:
    admin_key = str(getattr(settings, "cartesia_admin_api_key", "") or "").strip()
    if not admin_key:
        return []
    try:
        response = await client.get(
            CARTESIA_CREDITS_URL,
            headers={
                "X-API-Key": admin_key,
                "Cartesia-Version": "2024-06-10",
            },
        )
        response.raise_for_status()
        payload: Any = response.json()
    except Exception as exc:  # noqa: BLE001 - optional collector
        logger.warning("Cartesia credits poll failed: %s", exc)
        return []
    rows: list[dict[str, Any]] = []
    key_id = mask_key(admin_key)
    seen: set[str] = set()
    for path, value in _numeric_leaves(payload).items():
        metric = _best_metric_name(path)
        if metric in seen:
            continue
        seen.add(metric)
        rows.append(
            {
                "provider": "cartesia",
                "key_id": key_id,
                "model": "sonic",
                "metric": metric,
                "value": value,
            }
        )
    return rows


async def refresh_provider_usage(
    settings: Any,
    session_factory: Any,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Poll both usage APIs and persist whatever succeeded.

    Returns a small status dict for the manual-refresh response. Never raises.
    """
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    rows: list[dict[str, Any]] = []
    try:
        deepgram_rows, cartesia_rows = await asyncio.gather(
            _fetch_deepgram(http, settings),
            _fetch_cartesia(http, settings),
            return_exceptions=True,
        )
        for result in (deepgram_rows, cartesia_rows):
            if isinstance(result, Exception):
                logger.warning("usage collector raised: %s", result)
            elif isinstance(result, list):
                rows.extend(result)
    finally:
        if owns_client:
            await http.aclose()
    written = record_snapshots(rows, session_factory=session_factory)
    return {
        "written": written,
        "deepgram_configured": bool(
            str(getattr(settings, "deepgram_project_id", "") or "").strip()
            and str(getattr(settings, "deepgram_api_key", "") or "").strip()
        ),
        "cartesia_configured": bool(
            str(getattr(settings, "cartesia_admin_api_key", "") or "").strip()
        ),
        "at": utcnow().isoformat(timespec="seconds"),
    }


async def usage_refresh_loop(settings: Any, session_factory: Any) -> None:
    """Background daily poll. Cancelled at app shutdown."""
    interval = max(0, int(getattr(settings, "usage_refresh_interval_hours", 24) or 0))
    if interval <= 0:
        return
    has_source = bool(
        (str(getattr(settings, "deepgram_project_id", "") or "").strip()
         and str(getattr(settings, "deepgram_api_key", "") or "").strip())
        or str(getattr(settings, "cartesia_admin_api_key", "") or "").strip()
    )
    if not has_source:
        logger.info("provider usage poller idle: no Deepgram project/Cartesia admin key")
        return
    # Let API startup finish before making outbound calls.
    await asyncio.sleep(5)
    while True:
        try:
            result = await refresh_provider_usage(settings, session_factory)
            logger.info("provider usage poll complete: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - loop must survive a bad poll
            logger.exception("provider usage poll failed")
        await asyncio.sleep(interval * 3600)
