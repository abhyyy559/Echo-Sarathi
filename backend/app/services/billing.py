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

import math
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Call, Campaign, CreditLedger, Organization
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

#: One-time welcome credit for a new organization (10 minutes).
TRIAL_CREDITS_PAISE = 10 * PRICE_PER_MINUTE_PAISE

CREDIT_PACKS: tuple[dict[str, Any], ...] = (
    {
        "id": "starter",
        "name": "Starter",
        "minutes": 60,
        "price_paise": 18_000,  # Rs 180  -> Rs 3.00/min
        "per_minute_paise": 300,
        "blurb": "A short pilot: one campaign, a hundred contacts or fewer.",
    },
    {
        "id": "growth",
        "name": "Growth",
        "minutes": 300,
        "price_paise": 87_000,  # Rs 870  -> Rs 2.90/min
        "per_minute_paise": 290,
        "blurb": "Daily calling for a single team, with headroom for retries.",
    },
    {
        "id": "scale",
        "name": "Scale",
        "minutes": 1000,
        "price_paise": 280_000,  # Rs 2,800 -> Rs 2.80/min
        "per_minute_paise": 280,
        "blurb": "High-volume campaigns across several agents and use cases.",
    },
)


def get_pack(pack_id: str) -> Optional[dict[str, Any]]:
    return next((p for p in CREDIT_PACKS if p["id"] == pack_id), None)


def seconds_to_paise(seconds: float) -> int:
    """Retail charge for a call length, rounded up to the whole second."""
    if seconds is None or seconds <= 0:
        return 0
    return max(1, math.ceil(seconds)) * PRICE_PER_MINUTE_PAISE // 60


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
        description=f"{pack['name']} pack · {pack['minutes']} minutes",
        created_by=created_by,
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


def call_charge_paise(call: Call) -> int:
    """What this call costs the customer. Unanswered legs are free."""
    if call.kind != "phone":
        return 0
    if call.answered_at is None and call.status != "completed":
        return 0
    return seconds_to_paise(call.duration_seconds or 0)


def charge_call(db: Session, call: Call) -> Optional[CreditLedger]:
    """Debit the org for one finished call. Idempotent per call.

    Every completion path (provider webhook, reconciliation sweep, worker
    hangup) funnels through ``end_call``, and carriers happily deliver the same
    terminal status twice — so the guard is the ledger row itself, not a call
    column some path might forget to set.
    """
    org_id = _call_org_id(db, call)
    if org_id is None:
        return None
    charge = call_charge_paise(call)
    if charge <= 0:
        return None
    already = db.scalar(
        select(CreditLedger.id).where(
            CreditLedger.call_id == call.id, CreditLedger.kind == "usage"
        )
    )
    if already is not None:
        return None
    seconds = int(math.ceil(call.duration_seconds or 0))
    return post_entry(
        db,
        org_id=org_id,
        kind="usage",
        amount_paise=-charge,
        call_id=call.id,
        description=f"Call #{call.id} · {seconds}s",
    )


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
    spent = db.scalar(
        select(func.coalesce(func.sum(CreditLedger.amount_paise), 0)).where(
            CreditLedger.org_id == org_id,
            CreditLedger.kind == "usage",
            CreditLedger.created_at >= month_start(),
        )
    )
    minutes_used = db.scalar(
        select(func.coalesce(func.sum(Call.duration_seconds), 0.0))
        .join(Campaign, Campaign.id == Call.campaign_id)
        .where(
            Campaign.org_id == org_id,
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
    return {
        "balance_paise": balance,
        "balance_rupees": paise_to_rupees(balance),
        "minutes_remaining": round(balance / PRICE_PER_MINUTE_PAISE, 1),
        "price_per_minute_paise": PRICE_PER_MINUTE_PAISE,
        "price_per_minute_rupees": paise_to_rupees(PRICE_PER_MINUTE_PAISE),
        "cost_per_minute_paise": COST_PER_MINUTE_PAISE,
        "margin_per_minute_paise": PRICE_PER_MINUTE_PAISE - COST_PER_MINUTE_PAISE,
        "cost_breakdown": COST_BREAKDOWN_PAISE_PER_MINUTE,
        "low_balance": balance < 5 * 60 * PRICE_PER_MINUTE_PAISE // 60,
        "spent_this_month_paise": -int(spent or 0),
        "spent_this_month_rupees": paise_to_rupees(-int(spent or 0)),
        "minutes_used_this_month": round(float(minutes_used or 0) / 60.0, 1),
        "packs": list(CREDIT_PACKS),
        "ledger": [_ledger_out(entry) for entry in entries],
    }
