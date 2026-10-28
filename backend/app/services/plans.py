"""Plan catalog, entitlements and included-minute accounting.

Pricing decisions live in ``docs/BUSINESS_MODEL.md``. Every amount is integer
paise and every plan is monthly; all retail prices are GST-inclusive.

The wallet is *overage money*, not a monthly allowance: included minutes are
consumed first, then calls debit the wallet at the plan's overage rate. A free
organization therefore still uses the wallet for every connected minute.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Call, Campaign, Subscription
from app.timeutil import utcnow

FREE_PLAN_ID = "free"

#: Ordered catalog. ``self_serve`` plans can be bought with a card/UPI;
#: enterprise is a sales-led placeholder with custom limits.
PLANS: tuple[dict[str, Any], ...] = (
    {
        "id": "free",
        "name": "Free",
        "price_paise": 0,
        "included_minutes": 0,
        "overage_per_minute_paise": 300,
        "max_users": 1,
        "max_agents": 3,
        "max_concurrent_calls": 2,
        "max_phone_numbers": 1,
        "retention_days": 30,
        "self_serve": True,
        "custom": False,
        "blurb": "Kick the tyres: 10 trial minutes, one teammate, two simultaneous calls.",
        "features": [
            "10 free trial minutes on signup",
            "3 agents · 2 concurrent calls",
            "Playground tests always free",
            "30-day transcript retention",
            "Top up credits anytime",
        ],
    },
    {
        "id": "starter",
        "name": "Starter",
        "price_paise": 299_000,  # Rs 2,990 incl. GST
        "included_minutes": 1_000,
        "overage_per_minute_paise": 300,
        "max_users": 3,
        "max_agents": 3,
        "max_concurrent_calls": 2,
        "max_phone_numbers": 2,
        "retention_days": 90,
        "self_serve": True,
        "custom": False,
        "blurb": "A short pilot or a single team running daily follow-ups.",
        "features": [
            "1,000 connected minutes / month",
            "3 team seats · 3 agents",
            "2 concurrent calls",
            "90-day transcript retention",
            "GST invoices + email support",
        ],
    },
    {
        "id": "growth",
        "name": "Growth",
        "price_paise": 870_000,  # Rs 8,700 incl. GST
        "included_minutes": 3_000,
        "overage_per_minute_paise": 290,
        "max_users": 10,
        "max_agents": 10,
        "max_concurrent_calls": 5,
        "max_phone_numbers": 5,
        "retention_days": 180,
        "self_serve": True,
        "custom": False,
        "blurb": "Daily calling for a department, with room for retries.",
        "features": [
            "3,000 connected minutes / month",
            "10 team seats · 10 agents",
            "5 concurrent calls",
            "180-day transcript retention",
            "Priority email support",
        ],
    },
    {
        "id": "scale",
        "name": "Scale",
        "price_paise": 2_800_000,  # Rs 28,000 incl. GST
        "included_minutes": 10_000,
        "overage_per_minute_paise": 280,
        "max_users": 30,
        "max_agents": 30,
        "max_concurrent_calls": 15,
        "max_phone_numbers": 15,
        "retention_days": 365,
        "self_serve": True,
        "custom": False,
        "blurb": "High-volume campaigns across several agents and use cases.",
        "features": [
            "10,000 connected minutes / month",
            "30 team seats · 30 agents",
            "15 concurrent calls",
            "365-day transcript retention",
            "Onboarding + priority support",
        ],
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price_paise": 0,
        "included_minutes": 0,
        "overage_per_minute_paise": 280,
        "max_users": 999,
        "max_agents": 999,
        "max_concurrent_calls": 50,
        "max_phone_numbers": 999,
        "retention_days": 730,
        "self_serve": False,
        "custom": True,
        "blurb": "Annual contract, custom limits, SLAs and security review support.",
        "features": [
            "30,000+ minutes, priced on contract",
            "Custom seats and concurrency",
            "SLA + DPO/security support",
            "Dedicated onboarding",
            "Annual invoicing with PO",
        ],
    },
)

PLAN_ORDER = tuple(plan["id"] for plan in PLANS)


def get_plan(plan_id: str) -> Optional[dict[str, Any]]:
    return next((plan for plan in PLANS if plan["id"] == plan_id), None)


def free_plan() -> dict[str, Any]:
    plan = get_plan(FREE_PLAN_ID)
    assert plan is not None
    return plan


def public_plans() -> list[dict[str, Any]]:
    """Catalog for the public pricing page and billing UI."""
    return [dict(plan) for plan in PLANS]


def active_subscription(
    db: Session, org_id: int, now: Optional[datetime] = None
) -> Optional[Subscription]:
    """The plan period covering ``now``, if any.

    Expiry is derived from the period end, not the status column, so a missed
    lifecycle tick can never keep a lapsed plan active.
    """
    now = now or utcnow()
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.org_id == org_id,
            Subscription.status == "active",
            Subscription.period_start <= now,
            Subscription.period_end > now,
        )
        .order_by(Subscription.id.desc())
    )


def org_plan(
    db: Session, org_id: int, now: Optional[datetime] = None
) -> tuple[dict[str, Any], Optional[Subscription]]:
    """Return the organization's effective plan and its subscription row."""
    subscription = active_subscription(db, org_id, now)
    if subscription is None:
        return free_plan(), None
    return get_plan(subscription.plan_id) or free_plan(), subscription


def included_seconds_used(
    db: Session,
    org_id: int,
    period_start: datetime,
    period_end: datetime,
    *,
    exclude_call_id: Optional[int] = None,
) -> int:
    """Connected phone seconds counted against a plan period."""
    query = (
        select(func.coalesce(func.sum(Call.duration_seconds), 0.0))
        .outerjoin(Campaign, Campaign.id == Call.campaign_id)
        .where(
            or_(Call.org_id == org_id, Campaign.org_id == org_id),
            Call.kind == "phone",
            Call.answered_at.is_not(None),
            Call.started_at.is_not(None),
            Call.started_at >= period_start,
            Call.started_at < period_end,
        )
    )
    if exclude_call_id is not None:
        query = query.where(Call.id != exclude_call_id)
    seconds = float(db.scalar(query) or 0.0)
    return max(0, int(math.ceil(seconds)))


def included_seconds_remaining(
    db: Session, org_id: int, subscription: Optional[Subscription]
) -> int:
    """Unused included seconds in the current period (0 without a plan)."""
    if subscription is None:
        return 0
    allowance = max(0, int(subscription.included_minutes or 0)) * 60
    used = included_seconds_used(
        db, org_id, subscription.period_start, subscription.period_end
    )
    return max(0, allowance - used)


def concurrency_limit(db: Session, org_id: int) -> int:
    plan, _subscription = org_plan(db, org_id)
    return max(1, int(plan["max_concurrent_calls"]))


def retention_days(db: Session, org_id: int) -> int:
    plan, _subscription = org_plan(db, org_id)
    return int(plan["retention_days"])


def limit_message(plan: dict[str, Any], resource: str, limit: int) -> str:
    """Human error text for a blocked create action."""
    next_plan = {
        "free": "Starter (Rs 2,990/mo)",
        "starter": "Growth (Rs 8,700/mo)",
        "growth": "Scale (Rs 28,000/mo)",
        "scale": "Enterprise",
        "enterprise": "Enterprise",
    }.get(plan["id"], "a larger plan")
    label = {
        "users": "team seats",
        "agents": "active agents",
        "concurrent_calls": "concurrent calls",
        "phone_numbers": "phone numbers",
    }.get(resource, resource)
    return (
        f"The {plan['name']} plan allows {limit} {label}. "
        f"Upgrade to {next_plan} or contact hello@echosarathi.ai."
    )
