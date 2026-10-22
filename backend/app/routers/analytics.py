"""Org-scoped analytics for the Overview page (GET /api/analytics/summary).

Tenancy: a call belongs to the caller's org when its denormalized
``calls.org_id`` matches, else when its campaign's org matches — the same
"effective org" rule used by the call detail endpoint. Transcript latency
stats and extracted-field counts are computed over that same call set.
"""
from __future__ import annotations

import math
import statistics
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Agent, AgentVersion, Call, Campaign, ExtractedField, Transcript, User
from app.schemas import AnalyticsCostsOut, AnalyticsSummaryOut, UsageSummaryOut
from app.services.usage import (
    LOW_BALANCE_FRACTION,
    WARN_BALANCE_FRACTION,
    latest_snapshots,
    summarize_sarvam,
)
from app.timeutil import utcnow

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

RECENT_CALLS_LIMIT = 8

# update per invoice
PRICING_USD_PER_MINUTE: dict[str, float] = {
    "telephony": 0.0120,          # Plivo outbound local (India) sample rate
    "stt_deepgram_nova3": 0.0043, # Deepgram nova-3 streaming
    "tts_cartesia": 0.0080,       # Cartesia sonic English
    "llm_groq": 0.0007,           # Groq small-model share per voice minute
}
_RATE_PER_MINUTE_USD = sum(PRICING_USD_PER_MINUTE.values())


def _org_call_filter(org_id: int):
    """SQL filter matching calls whose effective org is ``org_id``."""
    return or_(Call.org_id == org_id, Campaign.org_id == org_id)


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile on a pre-sorted list."""
    if not sorted_values:
        return None
    idx = max(0, min(len(sorted_values) - 1, math.ceil(pct * len(sorted_values)) - 1))
    value = sorted_values[idx]
    return round(float(value), 1)


@router.get("/summary", response_model=AnalyticsSummaryOut)
def analytics_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_filter = _org_call_filter(user.org_id)

    # --- call set ----------------------------------------------------------
    calls = db.scalars(
        select(Call).outerjoin(Campaign, Campaign.id == Call.campaign_id).where(org_filter)
    ).all()

    total_calls = len(calls)
    completed_calls = sum(1 for c in calls if c.status == "completed")
    success_rate_pct = round((completed_calls / total_calls * 100.0), 1) if total_calls else 0.0
    call_ids = [c.id for c in calls]

    # --- e2e latency from per-turn transcripts ------------------------------
    e2e_values: list[float] = []
    total_extracted_fields = 0
    if call_ids:
        e2e_rows = db.execute(
            select(Transcript.e2e_ms)
            .where(
                and_(
                    Transcript.call_id.in_(call_ids),
                    Transcript.e2e_ms.isnot(None),
                )
            )
        ).scalars().all()
        e2e_values = [float(v) for v in e2e_rows]

        field_ids = db.scalars(
            select(ExtractedField.id).where(ExtractedField.call_id.in_(call_ids))
        ).all()
        total_extracted_fields = len(field_ids)

    avg_e2e_ms = round(sum(e2e_values) / len(e2e_values), 1) if e2e_values else None
    median_e2e_ms = (
        round(float(statistics.median(e2e_values)), 1) if e2e_values else None
    )
    p95_e2e_ms = _percentile(sorted(e2e_values), 0.95)

    # --- last-7-day histogram (UTC day buckets, zero-filled) ---------------
    today = utcnow().date()
    start_day = today - timedelta(days=6)
    buckets: dict[str, int] = {
        (start_day + timedelta(days=i)).isoformat(): 0 for i in range(7)
    }
    for call in calls:
        stamp = call.started_at or call.created_at
        if stamp is None:
            continue
        key = stamp.date().isoformat()
        if key in buckets:
            buckets[key] += 1
    calls_last_7d = [{"date": day, "count": count} for day, count in buckets.items()]

    # --- recent calls with resolved agent names ----------------------------
    version_ids = {c.agent_version_id for c in calls[:RECENT_CALLS_LIMIT] if c.agent_version_id}
    agent_names: dict[int, str] = {}
    if version_ids:
        rows = db.execute(
            select(AgentVersion.id, Agent.name)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(AgentVersion.id.in_(version_ids))
        ).all()
        agent_names = {vid: name for vid, name in rows}

    recent_source = sorted(calls, key=lambda c: c.id, reverse=True)[:RECENT_CALLS_LIMIT]
    recent_calls = [
        {
            "id": c.id,
            "status": c.status,
            "kind": c.kind or "phone",
            "duration_seconds": c.duration_seconds,
            "started_at": c.started_at,
            "agent_name": agent_names.get(c.agent_version_id),
        }
        for c in recent_source
    ]

    return {
        "total_calls": total_calls,
        "completed_calls": completed_calls,
        "success_rate_pct": success_rate_pct,
        "avg_e2e_ms": avg_e2e_ms,
        "median_e2e_ms": median_e2e_ms,
        "p95_e2e_ms": p95_e2e_ms,
        "total_extracted_fields": total_extracted_fields,
        "calls_last_7d": calls_last_7d,
        "recent_calls": recent_calls,
    }


def _minutes(duration_seconds: Any) -> float:
    return round(float(duration_seconds) / 60.0, 1) if duration_seconds else 0.0


@router.get("/costs", response_model=AnalyticsCostsOut)
def analytics_costs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Org-scoped estimated spend from per-call durations and PRICING consts.

    Minutes come from ``calls.duration_seconds``; calls without a duration
    (still in flight, or never answered) contribute nothing.
    """
    calls = db.scalars(
        select(Call)
        .outerjoin(Campaign, Campaign.id == Call.campaign_id)
        .where(_org_call_filter(user.org_id), Call.duration_seconds.isnot(None))
        .order_by(Call.id)
    ).all()

    total_minutes = 0.0
    per_call: list[dict[str, Any]] = []
    monthly: dict[str, dict[str, float]] = {}
    for call in calls:
        minutes = _minutes(call.duration_seconds)
        if minutes <= 0:
            continue
        cost = round(minutes * _RATE_PER_MINUTE_USD, 4)
        total_minutes += minutes
        per_call.append({"call_id": call.id, "minutes": minutes, "est_cost_usd": cost})
        stamp = call.started_at or call.created_at
        month_key = (stamp.date().strftime("%Y-%m")) if stamp else "unknown"
        bucket = monthly.setdefault(month_key, {"minutes": 0.0, "est_cost_usd": 0.0})
        bucket["minutes"] += minutes
        bucket["est_cost_usd"] += cost

    for bucket in monthly.values():
        bucket["minutes"] = round(bucket["minutes"], 1)
        bucket["est_cost_usd"] = round(bucket["est_cost_usd"], 4)

    return {
        "total_minutes": round(total_minutes, 1),
        "est_cost_usd": round(total_minutes * _RATE_PER_MINUTE_USD, 4),
        "per_call": per_call,
        "monthly": monthly,
    }


# --- provider key utilization -------------------------------------------------

#: Display ordering so the tier that actually limits calls (Groq) reads first.
_PROVIDER_ORDER = {
    "groq": 0,
    "groq-secondary": 1,
    "deepgram": 2,
    "cartesia": 3,
    "sarvam": 4,
}

#: Groq's free tier is metered per MINUTE (tokens) and per DAY (requests), and
#: the token bucket is shared across every key in the organization. The tighter
#: of the two is what decides when a key stops answering, so both are compared.
_QUOTA_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("limit_tokens", "remaining_tokens", "tokens/min"),
    ("limit_requests", "remaining_requests", "requests/day"),
)


def _key_status(metrics: dict[str, float]) -> tuple[str, Optional[float], str]:
    """Return ``(status, remaining_fraction, headline)`` for one key.

    The fraction is the tightest of the provider's quota pairs — one number the
    UI can sort by and colour. ``unknown`` when the provider published nothing
    (a key that has not served a request yet, or a non-metered provider).
    """
    candidates: list[tuple[float, str]] = []
    for limit_key, remaining_key, label in _QUOTA_PAIRS:
        limit = metrics.get(limit_key)
        remaining = metrics.get(remaining_key)
        if not limit or limit <= 0 or remaining is None:
            continue
        fraction = max(0.0, remaining / limit)
        candidates.append(
            (fraction, f"{int(remaining):,} of {int(limit):,} {label}")
        )
    if not candidates:
        return "unknown", None, "no quota data yet"
    fraction, detail = min(candidates, key=lambda item: item[0])
    if fraction <= 0:
        return "critical", fraction, f"exhausted — {detail} left"
    if fraction <= LOW_BALANCE_FRACTION:
        return "critical", fraction, f"{fraction * 100:.0f}% left — {detail}"
    if fraction <= WARN_BALANCE_FRACTION:
        return "warn", fraction, f"{fraction * 100:.0f}% left — {detail}"
    return "ok", fraction, f"{fraction * 100:.0f}% left — {detail}"


@router.get("/usage", response_model=UsageSummaryOut)
def analytics_usage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Latest quota snapshot per provider key (the "which key dies first" view).

    Data comes from two collectors: the voice worker forwards Groq's
    ``x-ratelimit-*`` headers and its Sarvam character counts on every call,
    and a daily backend poller refreshes the Deepgram/Cartesia balances. A
    provider that has never reported is simply absent from ``keys`` — the card
    renders an empty state rather than inventing numbers.
    """
    latest = latest_snapshots(db)

    grouped: dict[tuple[str, str, str], dict[str, float]] = {}
    stamps: dict[tuple[str, str, str], Any] = {}
    for (provider, key_id, model, metric), row in latest.items():
        if provider == "sarvam" and metric == "characters":
            # Characters are a cumulative local count, not a quota snapshot:
            # they are summarized separately so they cannot mask the balance.
            continue
        marker = (provider, key_id, model)
        grouped.setdefault(marker, {})[metric] = float(row.value)
        current = stamps.get(marker)
        if current is None or row.timestamp > current:
            stamps[marker] = row.timestamp

    keys: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for (provider, key_id, model), metrics in grouped.items():
        status, fraction, headline = _key_status(metrics)
        keys.append(
            {
                "provider": provider,
                "key_id": key_id,
                "model": model,
                "status": status,
                "headline": headline,
                "remaining_fraction": fraction,
                "metrics": {name: round(value, 4) for name, value in metrics.items()},
                "updated_at": stamps.get((provider, key_id, model)),
            }
        )
        if status in ("warn", "critical"):
            alerts.append(
                {
                    "level": status,
                    "provider": provider,
                    "key_id": key_id,
                    "message": f"{provider} {key_id or '(default key)'}: {headline}",
                }
            )

    keys.sort(
        key=lambda item: (
            item["remaining_fraction"] is None,
            item["remaining_fraction"] if item["remaining_fraction"] is not None else 1.0,
            _PROVIDER_ORDER.get(item["provider"], 99),
            item["key_id"],
        )
    )
    alerts.sort(key=lambda item: (item["level"] != "critical", item["provider"]))

    return {
        "generated_at": utcnow(),
        "keys": keys,
        "sarvam": summarize_sarvam(db, latest),
        "alerts": alerts,
    }
