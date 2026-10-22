"""Provider usage snapshots + shared helpers.

The dev dashboard needs a durable, provider-agnostic record of quota and
credit state. Every collector writes the same narrow shape:

    provider, key_id, model, metric, value, timestamp

``key_id`` is always a masked identifier (for example ``gsk_...a3f2``); raw
credentials must never be persisted or returned. ``value`` is numeric so the
dashboard can compare, sum and threshold without provider-specific parsing.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import UsageSnapshot
from app.timeutil import utcnow

logger = logging.getLogger(__name__)

#: Sarvam bills INR 30 per 10,000 characters for Bulbul TTS.
SARVAM_INR_PER_CHARACTER = 30.0 / 10_000.0

#: Balance thresholds used by the dev dashboard alert banner.
LOW_BALANCE_FRACTION = 0.10
WARN_BALANCE_FRACTION = 0.25

_SESSION_FACTORY: Optional[sessionmaker[Session]] = None


def configure_session_factory(factory: sessionmaker[Session]) -> None:
    """Give the response interceptor a process-wide DB factory."""
    global _SESSION_FACTORY
    _SESSION_FACTORY = factory


def mask_key(value: Any) -> str:
    """Return a non-reversible-enough key identifier for display.

    ``gsk_...a3f2`` for Groq keys; ``sk-...a3f2`` for other OpenAI-compatible
    keys. Short values expose only the last two characters. The full value is
    never logged, stored, or returned.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "..." + text[-2:] if len(text) >= 2 else "..."
    prefix = "gsk_" if text.startswith("gsk_") else ("sk-" if text.startswith("sk-") else "")
    head = prefix or text[:3]
    return f"{head}...{text[-4:]}"


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number:  # NaN
        return None
    return number


def record_snapshot(
    db: Session,
    *,
    provider: str,
    key_id: str,
    model: str,
    metric: str,
    value: Any,
    timestamp: Optional[Any] = None,
) -> Optional[UsageSnapshot]:
    """Add one snapshot row to an open session (caller commits)."""
    number = _number(value)
    if number is None:
        return None
    row = UsageSnapshot(
        provider=str(provider or "").strip()[:40],
        key_id=mask_key(key_id) if key_id else "",
        model=str(model or "").strip()[:120],
        metric=str(metric or "").strip()[:60],
        value=number,
        timestamp=timestamp or utcnow(),
    )
    if not row.provider or not row.metric:
        return None
    db.add(row)
    return row


def record_snapshots(
    rows: Iterable[Mapping[str, Any]],
    *,
    session_factory: Optional[sessionmaker[Session]] = None,
) -> int:
    """Persist snapshot mappings using a short-lived session.

    Best effort: a collector failure must never break a live call. Returns the
    number of rows written.
    """
    factory = session_factory or _SESSION_FACTORY
    if factory is None:
        logger.debug("usage snapshot dropped: no session factory configured")
        return 0
    prepared: list[Mapping[str, Any]] = list(rows)
    if not prepared:
        return 0
    try:
        with factory() as db:
            written = 0
            for item in prepared:
                row = record_snapshot(
                    db,
                    provider=str(item.get("provider") or ""),
                    key_id=str(item.get("key_id") or ""),
                    model=str(item.get("model") or ""),
                    metric=str(item.get("metric") or ""),
                    value=item.get("value"),
                    timestamp=item.get("timestamp"),
                )
                if row is not None:
                    written += 1
            db.commit()
            return written
    except Exception:  # noqa: BLE001 - usage accounting must never break a call
        logger.warning("usage snapshot write failed", exc_info=True)
        return 0


#: Response headers emitted by OpenAI-compatible providers. Names verified
#: against Groq's live responses (requests + tokens, limits + remaining).
_HEADER_METRICS: dict[str, str] = {
    "x-ratelimit-limit-requests": "limit_requests",
    "x-ratelimit-remaining-requests": "remaining_requests",
    "x-ratelimit-limit-tokens": "limit_tokens",
    "x-ratelimit-remaining-tokens": "remaining_tokens",
}


def snapshots_from_response(
    response: Any,
    *,
    provider: str,
    api_key: str,
    model: str,
) -> list[dict[str, Any]]:
    """Extract quota headers from one provider response.

    Works with both ``httpx.Response`` and SDK response wrappers: only
    ``headers`` and ``status_code`` are touched. A 429 also records
    ``retry_after_seconds`` when the provider supplied a numeric value.
    """
    headers = getattr(response, "headers", {}) or {}
    key_id = mask_key(api_key)
    rows: list[dict[str, Any]] = []
    for header, metric in _HEADER_METRICS.items():
        value = _number(headers.get(header))
        if value is not None:
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


def record_response(
    response: Any,
    *,
    provider: str,
    api_key: str,
    model: str,
    settings: Any = None,
) -> None:
    """Persist response headers and update the NIM Redis counters.

    Safe to call on every response: with no headers there is no DB write.
    """
    rows = snapshots_from_response(
        response, provider=provider, api_key=api_key, model=model
    )
    if rows:
        record_snapshots(rows)
    if str(provider or "").lower() in {"nvidia", "nim"}:
        record_nim_request(
            settings,
            key_id=mask_key(api_key),
            model=model,
            status=int(getattr(response, "status_code", 0) or 0),
            retry_after=_number((getattr(response, "headers", {}) or {}).get("retry-after")),
        )


def record_nim_request(
    settings: Any,
    *,
    key_id: str,
    model: str,
    status: int,
    retry_after: Optional[float] = None,
) -> None:
    """Track NVIDIA NIM requests per key/model in Redis (no usage API)."""
    redis_url = str(getattr(settings, "redis_url", "") or "").strip()
    if not redis_url:
        return
    try:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(
            redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        try:
            stamp = utcnow().strftime("%Y%m%d%H")
            base = f"usage:nim:{key_id}:{model}:{stamp}"
            client.incr(base)
            client.expire(base, 60 * 60 * 3)
            if status == 429:
                retry_key = f"usage:nim:{key_id}:{model}:retry_after"
                client.set(retry_key, str(retry_after or 0), ex=300)
        finally:
            client.close()
    except Exception:  # noqa: BLE001 - Redis is optional on local/demo
        logger.debug("NIM usage counter skipped (redis unavailable)", exc_info=True)


def latest_snapshots(
    db: Session, *, limit: int = 20_000
) -> dict[tuple[str, str, str, str], UsageSnapshot]:
    """Latest row per ``(provider, key_id, model, metric)``."""
    rows = db.scalars(
        select(UsageSnapshot)
        .order_by(desc(UsageSnapshot.timestamp), desc(UsageSnapshot.id))
        .limit(limit)
    ).all()
    latest: dict[tuple[str, str, str, str], UsageSnapshot] = {}
    for row in rows:
        marker = (row.provider, row.key_id, row.model, row.metric)
        latest.setdefault(marker, row)
    return latest


def recent_snapshots(db: Session, *, minutes: int = 60) -> list[UsageSnapshot]:
    cutoff = utcnow() - timedelta(minutes=minutes)
    return list(
        db.scalars(
            select(UsageSnapshot)
            .where(UsageSnapshot.timestamp >= cutoff)
            .order_by(desc(UsageSnapshot.timestamp))
            .limit(20_000)
        ).all()
    )


def summarize_sarvam(
    db: Session,
    latest: Mapping[tuple[str, str, str, str], UsageSnapshot],
) -> dict[str, Any]:
    """Aggregate locally-counted Sarvam characters and requests."""
    from sqlalchemy import func

    characters = float(
        db.scalar(
            select(func.coalesce(func.sum(UsageSnapshot.value), 0.0)).where(
                UsageSnapshot.provider == "sarvam",
                UsageSnapshot.metric == "characters",
            )
        )
        or 0.0
    )
    recent = recent_snapshots(db, minutes=1)
    rpm_used = sum(
        1 for row in recent if row.provider == "sarvam" and row.metric == "requests"
    )
    models = sorted(
        {
            row.model
            for row in latest.values()
            if row.provider == "sarvam" and row.model
        }
    )
    return {
        "characters": round(characters, 1),
        "cost_inr": round(characters * SARVAM_INR_PER_CHARACTER, 2),
        "requests_last_minute": rpm_used,
        "models": models,
    }
