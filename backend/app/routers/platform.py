"""Platform administration: cross-tenant visibility and sales-led plan changes.

Only emails listed in ``PLATFORM_ADMIN_EMAILS`` may call these routes. This is
the operator console for the sales-led motion: assign enterprise contracts,
adjust credits after an offline payment, and see aggregate revenue.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_platform_admin
from app.models import Agent, Call, Organization, Subscription, User
from app.services import billing, plans
from app.services import invoices as invoice_service
from app.timeutil import utcnow

router = APIRouter(prefix="/api/platform", tags=["platform"])


class CreditAdjustment(BaseModel):
    amount_paise: int
    description: str = Field(default="Manual adjustment", max_length=200)


class AssignPlanRequest(BaseModel):
    plan_id: str
    months: int = Field(default=1, ge=1, le=12)
    included_minutes: Optional[int] = Field(default=None, ge=0)
    price_paise: Optional[int] = Field(default=None, ge=0)


def _org_row(db: Session, org: Organization) -> dict[str, Any]:
    plan, subscription = plans.org_plan(db, org.id)
    users = db.scalar(select(func.count(User.id)).where(User.org_id == org.id))
    agents = db.scalar(
        select(func.count(Agent.id)).where(
            Agent.org_id == org.id, Agent.status != "archived"
        )
    )
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "plan_id": plan["id"],
        "subscription_status": subscription.status if subscription else None,
        "period_end": subscription.period_end if subscription else None,
        "cancel_at_period_end": bool(subscription.cancel_at_period_end)
        if subscription
        else False,
        "balance_paise": int(org.credit_balance_paise or 0),
        "users": int(users or 0),
        "agents": int(agents or 0),
        "created_at": org.created_at,
    }


@router.get("/summary")
def platform_summary(
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    now = utcnow()
    organisations = int(
        db.scalar(select(func.count(Organization.id))) or 0
    )
    active = db.scalars(
        select(Subscription).where(
            Subscription.status == "active", Subscription.period_end > now
        )
    ).all()
    wallet_float = int(
        db.scalar(
            select(func.coalesce(func.sum(Organization.credit_balance_paise), 0))
        )
        or 0
    )
    month_start = billing.month_start(now)
    minutes = db.scalar(
        select(func.coalesce(func.sum(Call.duration_seconds), 0.0)).where(
            Call.kind == "phone",
            Call.answered_at.is_not(None),
            Call.started_at >= month_start,
        )
    )
    return {
        "organizations": organisations,
        "active_plans": len(active),
        "active_plan_value_paise": sum(int(sub.price_paise or 0) for sub in active),
        "wallet_float_paise": wallet_float,
        "minutes_this_month": round(float(minutes or 0.0) / 60.0, 1),
        "generated_at": now,
    }


@router.get("/orgs")
def list_orgs(
    query: str = "",
    limit: int = 100,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Organization).order_by(Organization.id.desc()).limit(
        max(1, min(limit, 200))
    )
    needle = query.strip()
    if needle:
        pattern = f"%{needle}%"
        stmt = stmt.where(
            or_(Organization.name.ilike(pattern), Organization.slug.ilike(pattern))
        )
    orgs = db.scalars(stmt).all()
    return {"orgs": [_org_row(db, org) for org in orgs]}


@router.get("/orgs/{org_id}")
def get_org(
    org_id: int,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="not found")
    data = _org_row(db, org)
    data["billing"] = billing.summary(db, org.id, limit=10)
    data["invoices"] = [
        invoice_service.invoice_out(row)
        for row in invoice_service.list_invoices(db, org.id, limit=10)
    ]
    return data


@router.post("/orgs/{org_id}/credits")
def adjust_credits(
    org_id: int,
    payload: CreditAdjustment,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Signed wallet adjustment (offline payment, refund, goodwill)."""
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="not found")
    if payload.amount_paise == 0:
        raise HTTPException(status_code=422, detail="amount must not be zero")
    if int(org.credit_balance_paise or 0) + payload.amount_paise < 0:
        raise HTTPException(
            status_code=400, detail="adjustment would take the balance below zero"
        )
    entry = billing.post_entry(
        db,
        org_id=org_id,
        kind="adjustment",
        amount_paise=payload.amount_paise,
        description=payload.description,
        created_by=admin.id,
    )
    db.commit()
    return {
        "org_id": org_id,
        "amount_paise": entry.amount_paise,
        "balance_after_paise": entry.balance_after_paise,
    }


@router.post("/orgs/{org_id}/plan")
def assign_plan(
    org_id: int,
    payload: AssignPlanRequest,
    request: Request,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Put an organization on a plan directly (contracts, comps, upgrades).

    Prices default to list price; ``price_paise`` overrides it for negotiated
    contracts, and a payable period gets the same manual payment + GST invoice
    as an offline settlement.
    """
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="not found")
    plan = plans.get_plan(payload.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="unknown plan")

    now = utcnow()
    if plan["id"] == plans.FREE_PLAN_ID:
        for subscription in db.scalars(
            select(Subscription).where(
                Subscription.org_id == org_id,
                Subscription.status == "active",
                Subscription.period_end > now,
            )
        ).all():
            subscription.status = "canceled"
            subscription.canceled_at = now
        db.commit()
        return {"plan_id": plans.FREE_PLAN_ID, "subscription": None, "invoice": None}

    effective = dict(plan)
    if payload.included_minutes is not None:
        effective["included_minutes"] = payload.included_minutes
    if payload.price_paise is not None:
        effective["price_paise"] = payload.price_paise
    price = int(effective["price_paise"])

    payment = None
    if price > 0:
        payment = billing.open_manual_payment(
            db,
            org_id=org_id,
            sku=billing.plan_sku(plan["id"]),
            amount_paise=price,
            created_by=admin.id,
        )
    subscription = billing.activate_plan(
        db,
        org_id=org_id,
        plan=effective,
        payment_id=payment.id if payment is not None else None,
        provider_order_id=payment.provider_order_id if payment is not None else None,
        created_by=admin.id,
        months=payload.months,
    )
    invoice = None
    if payment is not None:
        invoice = invoice_service.create_invoice(
            db,
            org,
            description=(
                f"{plan['name']} plan · {payload.months} month(s) · "
                f"{int(effective['included_minutes']):,} included minutes"
            ),
            total_paise=payment.amount_paise,
            payment_id=payment.id,
            subscription_id=subscription.id,
        )
    db.commit()
    if invoice is not None:
        billing.notify_invoice(db, request.app.state.settings, invoice)
    return {
        "plan_id": plan["id"],
        "subscription": {
            "id": subscription.id,
            "period_start": subscription.period_start,
            "period_end": subscription.period_end,
            "included_minutes": subscription.included_minutes,
            "price_paise": subscription.price_paise,
        },
        "invoice": invoice_service.invoice_out(invoice) if invoice is not None else None,
    }


@router.post("/lifecycle/run")
def run_lifecycle(
    request: Request,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Expire lapsed periods and send renewal reminders now."""
    counts = billing.run_billing_lifecycle(db, request.app.state.settings)
    db.commit()
    return counts
