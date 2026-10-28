"""Prepaid credits: pricing constants, wallet mutations and call billing.

The retail price is derived from what a connected minute actually costs us.
Every rate below is a published list price for the providers this stack runs:

    Vobiz SIP (India, in+out)          Rs 0.45 / min
    Sarvam Saaras STT                  Rs 30  / hour  -> Rs 0.50 / min
    Sarvam Bulbul TTS                  Rs 30  / 10k chars
    Groq Qwen (agent turns)            ~Rs 0.12 / min
    LiveKit Cloud + Render/Neon        ~Rs 0.15 / min

TTS is the variable that moves most: a minute of agent speech is roughly 350
characters at conversational pace, which is where the Rs 1.05 minute comes
from. The total lands near Rs 2.30, and we sell the minute at Rs 3.00 — a
gross margin of about Rs 0.70 (23%), inside the Rs 0.50-1.00 target.

All wallet amounts are integer paise. Never floats: a rounding drift on a
per-second debit is money.
"""
from __future__ import annotations

import calendar
import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Call,
    Campaign,
    CreditLedger,
    Invoice,
    Organization,
    Payment,
    Subscription,
    User,
)
from app.services import email as email_service
from app.services import invoices as invoice_service
from app.services import plans
from app.timeutil import utcnow

#: What a connected call minute sells for (Rs 3.00).
PRICE_PER_MINUTE_PAISE = 300  # = 5 paise per second

#: Our own cost per connected minute, decomposed for the dashboard.
COST_BREAKDOWN_PAISE_PER_MINUTE: dict[str, int] = {
    "telephony_vobiz": 45,
    "stt_sarvam_saaras": 50,
    "tts_sarvam_bulbul": 105,
    "llm_groq": 12,
    "platform": 18,
}
COST_PER_MINUTE_PAISE = sum(COST_BREAKDOWN_PAISE_PER_MINUTE.values())

#: Won't start a dial below roughly 12 seconds of credit: a call that connects
#: at zero balance costs us real carrier money we can never bill.
MINIMUM_DIAL_BALANCE_PAISE = 60
MINIMUM_DIAL_SECONDS = 12

#: One-time welcome credit for a new organization (10 minutes).
TRIAL_CREDITS_PAISE = 10 * PRICE_PER_MINUTE_PAISE

#: Payments for a plan period are stored in ``payments.pack_id`` with this
#: prefix so the existing order/webhook plumbing can settle both SKUs.
PLAN_SKU_PREFIX = "plan:"

#: How close to empty the wallet can get before the low-balance email fires.
LOW_BALANCE_ALERT_MINUTES = 10
LOW_BALANCE_ALERT_COOLDOWN = timedelta(days=7)

CREDIT_PACKS: tuple[dict[str, Any], ...] = (
    {
        "id": "starter",
        "name": "Quick top-up",
        "minutes": 60,
        "price_paise": 18_000,  # Rs 180  -> Rs 3.00/min
        "per_minute_paise": 300,
        "blurb": "A short pilot: one campaign, a hundred contacts or fewer.",
    },
    {
        "id": "growth",
        "name": "Standard top-up",
        "minutes": 300,
        "price_paise": 87_000,  # Rs 870  -> Rs 2.90/min
        "per_minute_paise": 290,
        "blurb": "Daily calling for a single team, with headroom for retries.",
    },
    {
        "id": "scale",
        "name": "Volume top-up",
        "minutes": 1000,
        "price_paise": 280_000,  # Rs 2,800 -> Rs 2.80/min
        "per_minute_paise": 280,
        "blurb": "High-volume campaigns across several agents and use cases.",
    },
)


def get_pack(pack_id: str) -> Optional[dict[str, Any]]:
    return next((p for p in CREDIT_PACKS if p["id"] == pack_id), None)


def plan_sku(plan_id: str) -> str:
    return f"{PLAN_SKU_PREFIX}{plan_id}"


def plan_from_sku(sku: str) -> Optional[dict[str, Any]]:
    if not str(sku).startswith(PLAN_SKU_PREFIX):
        return None
    return plans.get_plan(str(sku)[len(PLAN_SKU_PREFIX):])


def plan_pack(plan: dict[str, Any]) -> dict[str, Any]:
    """Shape a plan like a credit pack so the order plumbing accepts both."""
    return {
        "id": plan_sku(plan["id"]),
        "name": plan["name"],
        "minutes": plan["included_minutes"],
        "price_paise": plan["price_paise"],
        "per_minute_paise": plan["overage_per_minute_paise"],
        "blurb": plan["blurb"],
    }


def add_month(moment: datetime) -> datetime:
    """Same day next month, clamped to the shorter month (Jan 31 -> Feb 28)."""
    year = moment.year + (1 if moment.month == 12 else 0)
    month = 1 if moment.month == 12 else moment.month + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def add_months(moment: datetime, months: int) -> datetime:
    result = moment
    for _ in range(max(1, int(months))):
        result = add_month(result)
    return result


def seconds_to_paise(seconds: float, rate_per_minute_paise: int = PRICE_PER_MINUTE_PAISE) -> int:
    """Retail charge for a call length, rounded up to the whole second."""
    if seconds is None or seconds <= 0:
        return 0
    return max(1, math.ceil(seconds)) * int(rate_per_minute_paise) // 60


def paise_to_rupees(paise: int) -> float:
    return round(paise / 100.0, 2)


def balance_paise(db: Session, org_id: int) -> int:
    value = db.scalar(
        select(Organization.credit_balance_paise).where(Organization.id == org_id)
    )
    return int(value or 0)


def post_entry(
    db: Session,
    *,
    org_id: int,
    kind: str,
    amount_paise: int,
    description: str,
    paid_paise: Optional[int] = None,
    call_id: Optional[int] = None,
    created_by: Optional[int] = None,
) -> CreditLedger:
    """Apply one wallet delta and append the matching ledger row.

    Caller owns the transaction; every caller commits on the same business
    action (call end, top-up) so the balance and its history cannot diverge.
    """
    org = db.get(Organization, org_id)
    if org is None:
        raise ValueError(f"unknown organization {org_id}")
    new_balance = int(org.credit_balance_paise or 0) + int(amount_paise)
    org.credit_balance_paise = new_balance
    entry = CreditLedger(
        org_id=org_id,
        kind=kind,
        amount_paise=int(amount_paise),
        paid_paise=paid_paise,
        balance_after_paise=new_balance,
        call_id=call_id,
        description=description[:255],
        created_by=created_by,
    )
    db.add(entry)
    return entry


def grant_trial(db: Session, org_id: int, paise: int = TRIAL_CREDITS_PAISE) -> CreditLedger:
    return post_entry(
        db,
        org_id=org_id,
        kind="grant",
        amount_paise=paise,
        paid_paise=0,
        description="Welcome credit",
    )


def purchase_pack(
    db: Session, org_id: int, pack: dict[str, Any], created_by: Optional[int] = None
) -> CreditLedger:
    """Credit a purchased pack's minutes and record what was actually paid."""
    value = int(pack["minutes"]) * PRICE_PER_MINUTE_PAISE
    return post_entry(
        db,
        org_id=org_id,
        kind="purchase",
        amount_paise=value,
        paid_paise=int(pack["price_paise"]),
        description=f"{pack['name']} · {pack['minutes']} minutes",
        created_by=created_by,
    )


def activate_plan(
    db: Session,
    *,
    org_id: int,
    plan: dict[str, Any],
    payment_id: Optional[int] = None,
    provider_order_id: Optional[str] = None,
    created_by: Optional[int] = None,
    months: int = 1,
) -> Subscription:
    """Start a fresh plan period, retiring any current one.

    No proration in v1: an upgrade or renewal starts a new period now and the
    old period ends immediately. The UI says so before checkout.
    """
    now = utcnow()
    current = db.scalars(
        select(Subscription).where(
            Subscription.org_id == org_id,
            Subscription.status == "active",
            Subscription.period_end > now,
        )
    ).all()
    for subscription in current:
        subscription.status = "canceled"
        subscription.canceled_at = now
    subscription = Subscription(
        org_id=org_id,
        plan_id=str(plan["id"]),
        status="active",
        period_start=now,
        period_end=add_months(now, months),
        included_minutes=int(plan["included_minutes"]),
        price_paise=int(plan["price_paise"]),
        payment_id=payment_id,
        provider_order_id=provider_order_id,
        created_by=created_by,
    )
    db.add(subscription)
    db.flush()
    return subscription


def open_manual_payment(
    db: Session,
    *,
    org_id: int,
    sku: str,
    amount_paise: int,
    created_by: Optional[int] = None,
) -> Payment:
    """Record an offline (operator-approved) payment that is already settled."""
    payment = Payment(
        org_id=org_id,
        pack_id=sku[:40],
        amount_paise=int(amount_paise),
        provider="manual",
        provider_order_id=f"manual-{uuid.uuid4().hex}",
        status="paid",
        created_by=created_by,
        paid_at=utcnow(),
    )
    db.add(payment)
    db.flush()
    return payment


def purchase_plan(
    db: Session,
    org: Organization,
    plan: dict[str, Any],
    payment: Payment,
) -> tuple[Subscription, Invoice]:
    """Start a plan period and issue its GST invoice. Caller commits."""
    subscription = activate_plan(
        db,
        org_id=org.id,
        plan=plan,
        payment_id=payment.id,
        provider_order_id=payment.provider_order_id,
        created_by=payment.created_by,
    )
    invoice = invoice_service.create_invoice(
        db,
        org,
        description=(
            f"{plan['name']} plan · 1 month · "
            f"{int(plan['included_minutes']):,} included minutes"
        ),
        total_paise=payment.amount_paise,
        payment_id=payment.id,
        subscription_id=subscription.id,
    )
    return subscription, invoice


def open_payment(
    db: Session,
    *,
    org_id: int,
    pack: dict[str, Any],
    provider_order_id: str,
    created_by: Optional[int] = None,
) -> Payment:
    """Record a checkout attempt before the customer is sent to the gateway."""
    payment = Payment(
        org_id=org_id,
        pack_id=str(pack["id"]),
        amount_paise=int(pack["price_paise"]),
        provider="razorpay",
        provider_order_id=provider_order_id,
        status="created",
        created_by=created_by,
    )
    db.add(payment)
    db.flush()
    return payment


def settle_payment(
    db: Session, payment: Payment, provider_payment_id: str
) -> bool:
    """Mark a payment paid and apply its SKU exactly once.

    The status flip is a conditional UPDATE, so a browser verify callback and
    a webhook for the same payment cannot both credit the wallet or start two
    plan periods: only one row update reports ``rowcount == 1``.
    """
    if payment.status == "paid":
        return False
    plan = plan_from_sku(payment.pack_id)
    pack = None if plan is not None else get_pack(payment.pack_id)
    if plan is None and pack is None:
        raise ValueError(f"unknown SKU on payment {payment.id}: {payment.pack_id}")
    flipped = db.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status != "paid")
        .values(
            status="paid",
            provider_payment_id=provider_payment_id,
            paid_at=utcnow(),
        )
    ).rowcount
    if not flipped:
        return False
    org = db.get(Organization, payment.org_id)
    if org is None:
        return True
    if plan is not None:
        purchase_plan(db, org, plan, payment)
    else:
        assert pack is not None
        purchase_pack(db, payment.org_id, pack, created_by=payment.created_by)
        invoice_service.create_invoice(
            db,
            org,
            description=f"{pack['name']} · {pack['minutes']} minutes",
            total_paise=payment.amount_paise,
            payment_id=payment.id,
        )
    return True


def invoice_for_payment(db: Session, payment_id: int) -> Optional[Invoice]:
    return db.scalar(select(Invoice).where(Invoice.payment_id == payment_id))


def notify_invoice(db: Session, settings: Settings, invoice: Optional[Invoice]) -> None:
    """Email a receipt for an invoice just issued (best-effort)."""
    if invoice is None:
        return
    org = db.get(Organization, invoice.org_id)
    email_service.receipt(
        settings,
        to=invoice.customer_email,
        org_name=org.name if org is not None else invoice.customer_name,
        invoice_number=invoice.number,
        description=invoice.description,
        total_paise=invoice.total_paise,
        invoice_id=invoice.id,
    )


def _call_org_id(db: Session, call: Call) -> Optional[int]:
    if call.org_id is not None:
        return int(call.org_id)
    if call.campaign_id is not None:
        org_id = db.scalar(
            select(Campaign.org_id).where(Campaign.id == call.campaign_id)
        )
        return int(org_id) if org_id is not None else None
    return None


def call_charge_paise(
    call: Call, rate_per_minute_paise: int = PRICE_PER_MINUTE_PAISE
) -> int:
    """List-price charge for a call. Unanswered legs are free."""
    if call.kind != "phone":
        return 0
    if call.answered_at is None and call.status != "completed":
        return 0
    return seconds_to_paise(call.duration_seconds or 0, rate_per_minute_paise)


def _maybe_low_balance_alert(
    db: Session, settings: Settings, org_id: int, rate_per_minute_paise: int
) -> None:
    org = db.get(Organization, org_id)
    if org is None:
        return
    threshold = LOW_BALANCE_ALERT_MINUTES * int(rate_per_minute_paise)
    if int(org.credit_balance_paise or 0) >= threshold:
        return
    now = utcnow()
    if (
        org.low_balance_alerted_at is not None
        and now - org.low_balance_alerted_at < LOW_BALANCE_ALERT_COOLDOWN
    ):
        return
    to = org.billing_email or db.scalar(
        select(User.email)
        .where(User.org_id == org.id, User.role == "owner")
        .order_by(User.id)
    )
    if not to:
        return
    org.low_balance_alerted_at = now
    email_service.low_balance(
        settings,
        to=str(to),
        org_name=org.name,
        balance_paise=int(org.credit_balance_paise or 0),
    )


def charge_call(
    db: Session, call: Call, *, settings: Optional[Settings] = None
) -> Optional[CreditLedger]:
    """Debit the org for one finished call. Idempotent per call.

    Every completion path (provider webhook, reconciliation sweep, worker
    hangup) funnels through ``end_call``, and carriers happily deliver the same
    terminal status twice — so the guard is the ledger row itself, not a call
    column some path might forget to set. A zero-amount usage row marks a call
    fully covered by plan minutes, preserving the same idempotency.
    """
    org_id = _call_org_id(db, call)
    if org_id is None:
        return None
    if call.kind != "phone":
        return None
    if call.answered_at is None and call.status != "completed":
        return None
    already = db.scalar(
        select(CreditLedger.id).where(
            CreditLedger.call_id == call.id, CreditLedger.kind == "usage"
        )
    )
    if already is not None:
        return None

    seconds = int(math.ceil(call.duration_seconds or 0))
    if seconds <= 0:
        return None

    plan, subscription = plans.org_plan(db, org_id)
    rate = int(plan["overage_per_minute_paise"])
    included_seconds = 0
    if subscription is not None:
        used = plans.included_seconds_used(
            db,
            org_id,
            subscription.period_start,
            subscription.period_end,
            exclude_call_id=call.id,
        )
        allowance = max(0, int(subscription.included_minutes or 0)) * 60
        included_seconds = max(0, allowance - used)
    covered_seconds = min(seconds, included_seconds)
    billable_seconds = seconds - covered_seconds
    charge = seconds_to_paise(billable_seconds, rate)

    description = f"Call #{call.id} · {seconds}s"
    if covered_seconds:
        description += f" · {covered_seconds}s included in plan"
    entry = post_entry(
        db,
        org_id=org_id,
        kind="usage",
        amount_paise=-charge,
        call_id=call.id,
        description=description,
    )
    if settings is not None and charge > 0:
        _maybe_low_balance_alert(db, settings, org_id, rate)
    return entry


def available_call_seconds(db: Session, org_id: int) -> int:
    """Included seconds left plus what the wallet can pay for at the plan rate."""
    plan, subscription = plans.org_plan(db, org_id)
    included = plans.included_seconds_remaining(db, org_id, subscription)
    rate = max(1, int(plan["overage_per_minute_paise"]))
    wallet_seconds = int(balance_paise(db, org_id)) * 60 // rate
    return included + wallet_seconds


def can_dial(db: Session, org_id: int) -> bool:
    """True when the org can pay for at least a short connected call.

    This replaces the old wallet-only gate: a plan with included minutes but an
    empty wallet must keep dialing until the allowance is exhausted.
    """
    return available_call_seconds(db, org_id) >= MINIMUM_DIAL_SECONDS


def _ledger_out(entry: CreditLedger) -> dict[str, Any]:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "amount_paise": entry.amount_paise,
        "amount_rupees": paise_to_rupees(entry.amount_paise),
        "paid_paise": entry.paid_paise,
        "paid_rupees": paise_to_rupees(entry.paid_paise) if entry.paid_paise is not None else None,
        "balance_after_paise": entry.balance_after_paise,
        "call_id": entry.call_id,
        "description": entry.description,
        "created_at": entry.created_at,
    }


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def summary(db: Session, org_id: int, limit: int = 25) -> dict[str, Any]:
    balance = balance_paise(db, org_id)
    org = db.get(Organization, org_id)
    plan, subscription = plans.org_plan(db, org_id)
    rate = int(plan["overage_per_minute_paise"])
    spent = db.scalar(
        select(func.coalesce(func.sum(CreditLedger.amount_paise), 0)).where(
            CreditLedger.org_id == org_id,
            CreditLedger.kind == "usage",
            CreditLedger.created_at >= month_start(),
        )
    )
    minutes_used = db.scalar(
        select(func.coalesce(func.sum(Call.duration_seconds), 0.0))
        .outerjoin(Campaign, Campaign.id == Call.campaign_id)
        .where(
            or_(Call.org_id == org_id, Campaign.org_id == org_id),
            Call.kind == "phone",
            Call.answered_at.is_not(None),
            Call.started_at >= month_start(),
        )
    )
    entries = db.scalars(
        select(CreditLedger)
        .where(CreditLedger.org_id == org_id)
        .order_by(CreditLedger.id.desc())
        .limit(limit)
    ).all()

    included_total = int(subscription.included_minutes) if subscription else 0
    if subscription is not None:
        included_used_seconds = plans.included_seconds_used(
            db, org_id, subscription.period_start, subscription.period_end
        )
    else:
        included_used_seconds = 0
    included_remaining_seconds = max(0, included_total * 60 - included_used_seconds)
    wallet_minutes = round(balance / rate, 1) if rate else 0.0
    available_minutes = round(
        (included_remaining_seconds + (balance * 60 // rate if rate else 0)) / 60.0, 1
    )
    low_balance = available_minutes < 5

    subscription_out = None
    if subscription is not None:
        subscription_out = {
            "id": subscription.id,
            "plan_id": subscription.plan_id,
            "status": subscription.status,
            "period_start": subscription.period_start,
            "period_end": subscription.period_end,
            "cancel_at_period_end": bool(subscription.cancel_at_period_end),
            "included_minutes": included_total,
            "included_used_minutes": round(included_used_seconds / 60.0, 1),
            "included_remaining_minutes": round(included_remaining_seconds / 60.0, 1),
            "price_paise": subscription.price_paise,
            "payment_id": subscription.payment_id,
        }

    return {
        "balance_paise": balance,
        "balance_rupees": paise_to_rupees(balance),
        # Kept for existing clients: total payable minutes, not wallet-only.
        "minutes_remaining": available_minutes,
        "wallet_minutes_remaining": wallet_minutes,
        "available_minutes_remaining": available_minutes,
        "included_minutes_total": included_total,
        "included_minutes_used": round(included_used_seconds / 60.0, 1),
        "included_minutes_remaining": round(included_remaining_seconds / 60.0, 1),
        "price_per_minute_paise": rate,
        "price_per_minute_rupees": paise_to_rupees(rate),
        "overage_per_minute_paise": rate,
        "cost_per_minute_paise": COST_PER_MINUTE_PAISE,
        "margin_per_minute_paise": rate - COST_PER_MINUTE_PAISE,
        "cost_breakdown": COST_BREAKDOWN_PAISE_PER_MINUTE,
        "low_balance": low_balance,
        "can_dial": available_minutes * 60 >= MINIMUM_DIAL_SECONDS,
        "spent_this_month_paise": -int(spent or 0),
        "spent_this_month_rupees": paise_to_rupees(-int(spent or 0)),
        "minutes_used_this_month": round(float(minutes_used or 0) / 60.0, 1),
        "plan": dict(plan),
        "plan_catalog": plans.public_plans(),
        "subscription": subscription_out,
        "packs": list(CREDIT_PACKS),
        "billing_profile": {
            "legal_name": org.legal_name if org else "",
            "gstin": org.gstin if org else "",
            "billing_email": org.billing_email if org else "",
            "billing_address": org.billing_address if org else "",
            "billing_state": org.billing_state if org else "",
        },
        "ledger": [_ledger_out(entry) for entry in entries],
    }


def cancel_subscription(db: Session, org_id: int) -> Optional[Subscription]:
    """Stop renewal at period end; the customer keeps the paid period.

    There is no auto-renew in v1, so this is mostly a UI signal. It still
    matters because a renewal reminder must not be sent after cancellation.
    """
    subscription = plans.active_subscription(db, org_id)
    if subscription is None:
        return None
    subscription.cancel_at_period_end = True
    subscription.reminder_sent_at = utcnow()
    db.add(subscription)
    return subscription


def _billing_contact(db: Session, org: Organization) -> str:
    if org.billing_email:
        return org.billing_email
    return str(
        db.scalar(
            select(User.email)
            .where(User.org_id == org.id, User.role == "owner")
            .order_by(User.id)
        )
        or ""
    )


def run_billing_lifecycle(db: Session, settings: Settings) -> dict[str, int]:
    """Expire finished periods and send one renewal reminder per period.

    Called by the background loop and by the platform admin refresh. Expiry is
    already enforced by ``active_subscription``; this makes the status column
    readable and sends the 7-day nudge.
    """
    now = utcnow()
    expired = db.scalars(
        select(Subscription).where(
            Subscription.status == "active", Subscription.period_end <= now
        )
    ).all()
    for subscription in expired:
        subscription.status = "expired"
    reminded = 0
    upcoming = db.scalars(
        select(Subscription).where(
            Subscription.status == "active",
            Subscription.period_end > now,
            Subscription.period_end <= now + timedelta(days=7),
            Subscription.reminder_sent_at.is_(None),
            Subscription.cancel_at_period_end.is_(False),
        )
    ).all()
    for subscription in upcoming:
        org = db.get(Organization, subscription.org_id)
        if org is None:
            continue
        plan = plans.get_plan(subscription.plan_id)
        if plan is None:
            continue
        days_left = max(
            1, int(math.ceil((subscription.period_end - now).total_seconds() / 86400))
        )
        to = _billing_contact(db, org)
        if to:
            email_service.plan_expiring(
                settings,
                to=to,
                org_name=org.name,
                plan_name=str(plan["name"]),
                days_left=days_left,
                period_end=subscription.period_end.strftime("%d %b %Y"),
            )
        subscription.reminder_sent_at = now
        reminded += 1
    return {"expired": len(expired), "reminded": reminded}
