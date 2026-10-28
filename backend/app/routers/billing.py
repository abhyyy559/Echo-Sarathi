"""Plans, subscriptions, GST invoices and the prepaid credit wallet."""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import Invoice, Organization, Payment, User
from app.services import billing, plans
from app.services import invoices as invoice_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"

_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

require_billing_admin = require_roles("owner", "admin")


class TopupRequest(BaseModel):
    pack_id: str


class CheckoutRequest(BaseModel):
    pack_id: str


class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    pack_id: str


class SubscribeRequest(BaseModel):
    plan_id: str


class ProfileUpdate(BaseModel):
    legal_name: str = ""
    gstin: str = ""
    billing_email: str = ""
    billing_address: str = ""
    billing_state: str = ""


@router.get("")
def get_billing(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Plan state, minutes, wallet, this month's spend, packs and ledger."""
    settings: Settings = request.app.state.settings
    data = billing.summary(db, user.org_id)
    data["manual_payments_enabled"] = bool(settings.allow_manual_payments)
    data["checkout_enabled"] = bool(settings.checkout_enabled)
    return data


@router.get("/plans")
def get_plans(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Public plan catalog plus where this organization currently sits."""
    settings: Settings = request.app.state.settings
    plan, subscription = plans.org_plan(db, user.org_id)
    return {
        "plans": plans.public_plans(),
        "current_plan_id": plan["id"],
        "subscription": billing.summary(db, user.org_id)["subscription"],
        "checkout_enabled": bool(settings.checkout_enabled),
        "manual_payments_enabled": bool(settings.allow_manual_payments),
        "enterprise_contact": "hello@echosarathi.ai",
    }


def _razorpay_signature(order_id: str, payment_id: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _create_order(
    settings: Settings,
    *,
    org_id: int,
    user_id: int,
    sku: str,
    amount_paise: int,
) -> dict[str, Any]:
    """Open a Razorpay order for any SKU (pack or plan). No credits granted."""
    import httpx

    try:
        resp = httpx.post(
            RAZORPAY_ORDERS_URL,
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            json={
                "amount": int(amount_paise),
                "currency": "INR",
                "receipt": f"org{org_id}-{sku}"[:40],
                "notes": {
                    "org_id": str(org_id),
                    "pack_id": sku,
                    "user_id": str(user_id),
                },
            },
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("razorpay order create failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="could not reach the payment gateway"
        ) from exc
    if resp.status_code >= 400:
        logger.warning(
            "razorpay order create refused status=%s body=%s",
            resp.status_code,
            resp.text[:300],
        )
        raise HTTPException(status_code=502, detail="payment gateway refused the order")
    return resp.json()


def _notify_payment_invoice(
    db: Session, settings: Settings, payment_id: int
) -> Optional[dict[str, Any]]:
    invoice = billing.invoice_for_payment(db, payment_id)
    if invoice is None:
        return None
    billing.notify_invoice(db, settings, invoice)
    return invoice_service.invoice_out(invoice)


@router.post("/subscribe")
def subscribe(
    payload: SubscribeRequest,
    request: Request,
    user: User = Depends(require_billing_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start a plan period — via gateway checkout, or instantly when manual."""
    settings: Settings = request.app.state.settings
    plan = plans.get_plan(payload.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="unknown plan")
    if plan["id"] == plans.FREE_PLAN_ID:
        raise HTTPException(
            status_code=400,
            detail="the free plan is automatic — no checkout needed",
        )
    if plan["custom"] or not plan["self_serve"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{plan['name']} is arranged with our team — "
                "write to hello@echosarathi.ai"
            ),
        )

    if settings.checkout_enabled:
        order = _create_order(
            settings,
            org_id=user.org_id,
            user_id=user.id,
            sku=billing.plan_sku(plan["id"]),
            amount_paise=int(plan["price_paise"]),
        )
        billing.open_payment(
            db,
            org_id=user.org_id,
            pack=billing.plan_pack(plan),
            provider_order_id=str(order["id"]),
            created_by=user.id,
        )
        db.commit()
        return {
            "mode": "checkout",
            "order_id": order["id"],
            "amount": int(order["amount"]),
            "currency": order.get("currency", "INR"),
            "key_id": settings.razorpay_key_id,
            "pack_id": billing.plan_sku(plan["id"]),
            "plan_id": plan["id"],
            "plan_name": plan["name"],
            "minutes": plan["included_minutes"],
        }

    if settings.allow_manual_payments:
        payment = billing.open_manual_payment(
            db,
            org_id=user.org_id,
            sku=billing.plan_sku(plan["id"]),
            amount_paise=int(plan["price_paise"]),
            created_by=user.id,
        )
        org = db.get(Organization, user.org_id)
        assert org is not None
        billing.purchase_plan(db, org, plan, payment)
        db.commit()
        invoice = _notify_payment_invoice(db, settings, payment.id)
        logger.info(
            "plan: org=%s plan=%s manual payment=%s", user.org_id, plan["id"], payment.id
        )
        return billing.summary(db, user.org_id) | {
            "mode": "manual",
            "invoice": invoice,
        }

    raise HTTPException(
        status_code=503,
        detail=(
            "online payments are not configured — write to hello@echosarathi.ai "
            "to activate a plan"
        ),
    )


@router.post("/cancel")
def cancel(
    user: User = Depends(require_billing_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Stop renewal at period end; the paid period keeps running."""
    subscription = billing.cancel_subscription(db, user.org_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="no active plan period")
    db.commit()
    return billing.summary(db, user.org_id)


@router.get("/profile")
def get_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return billing.summary(db, user.org_id)["billing_profile"]


@router.patch("/profile")
def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(require_billing_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Billing details used on future invoices (issued ones stay frozen)."""
    org = db.get(Organization, user.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="organization not found")
    gstin = payload.gstin.strip().upper()
    if gstin and not _GSTIN_RE.match(gstin):
        raise HTTPException(
            status_code=400,
            detail="GSTIN must be 15 characters, e.g. 29ABCDE1234F1Z5",
        )
    email = payload.billing_email.strip().lower()
    if email and "@" not in email:
        raise HTTPException(status_code=400, detail="billing email is not valid")
    org.legal_name = payload.legal_name.strip()[:200]
    org.gstin = gstin[:20]
    org.billing_email = email[:255]
    org.billing_address = payload.billing_address.strip()
    org.billing_state = payload.billing_state.strip()[:100]
    db.commit()
    return billing.summary(db, user.org_id)["billing_profile"]


def _invoice_detail(settings: Settings, invoice) -> dict[str, Any]:
    data = invoice_service.invoice_out(invoice)
    data["seller"] = {
        "name": settings.company_legal_name,
        "gstin": settings.company_gstin,
        "address": settings.company_address,
        "state": settings.company_state,
    }
    data["gst_rate_percent"] = invoice_service.GST_RATE_PERCENT
    return data


@router.get("/invoices")
def list_invoices(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    rows = invoice_service.list_invoices(db, user.org_id)
    return {
        "invoices": [invoice_service.invoice_out(row) for row in rows],
        "seller": {
            "name": settings.company_legal_name,
            "gstin": settings.company_gstin,
            "address": settings.company_address,
            "state": settings.company_state,
        },
    }


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="not found")
    return _invoice_detail(request.app.state.settings, invoice)


@router.post("/checkout")
def checkout(
    payload: CheckoutRequest,
    request: Request,
    user: User = Depends(require_billing_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Open a gateway order for a top-up pack. Credits are NOT granted here."""
    settings: Settings = request.app.state.settings
    if not settings.checkout_enabled:
        raise HTTPException(
            status_code=503,
            detail="online payments are not configured in this environment",
        )
    pack = billing.get_pack(payload.pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="unknown pack")

    order = _create_order(
        settings,
        org_id=user.org_id,
        user_id=user.id,
        sku=str(pack["id"]),
        amount_paise=int(pack["price_paise"]),
    )
    billing.open_payment(
        db,
        org_id=user.org_id,
        pack=pack,
        provider_order_id=str(order["id"]),
        created_by=user.id,
    )
    db.commit()
    logger.info(
        "checkout: org=%s pack=%s order=%s amount=%s",
        user.org_id,
        pack["id"],
        order["id"],
        pack["price_paise"],
    )
    return {
        "order_id": order["id"],
        "amount": int(order["amount"]),
        "currency": order.get("currency", "INR"),
        "key_id": settings.razorpay_key_id,
        "pack_id": pack["id"],
        "pack_name": pack["name"],
        "minutes": pack["minutes"],
    }


@router.post("/verify")
def verify(
    payload: VerifyRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Verify the checkout signature, then settle the SKU exactly once."""
    settings: Settings = request.app.state.settings
    if not settings.checkout_enabled:
        raise HTTPException(status_code=503, detail="online payments are not configured")
    expected = _razorpay_signature(
        payload.razorpay_order_id,
        payload.razorpay_payment_id,
        settings.razorpay_key_secret,
    )
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        logger.warning(
            "checkout verify: bad signature org=%s order=%s",
            user.org_id,
            payload.razorpay_order_id,
        )
        raise HTTPException(status_code=400, detail="payment signature verification failed")

    payment = db.scalar(
        select(Payment).where(
            Payment.provider_order_id == payload.razorpay_order_id,
            Payment.org_id == user.org_id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="unknown payment order")
    if payment.pack_id != payload.pack_id:
        raise HTTPException(status_code=400, detail="pack does not match the order")
    granted = billing.settle_payment(db, payment, payload.razorpay_payment_id)
    db.commit()
    invoice = _notify_payment_invoice(db, settings, payment.id)
    return billing.summary(db, user.org_id) | {
        "credits_granted": granted,
        "invoice": invoice,
    }


@router.post("/webhook")
async def razorpay_webhook(
    request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Gateway callback: the authoritative path when the browser never returns."""
    settings: Settings = request.app.state.settings
    secret = settings.razorpay_webhook_secret
    if not secret:
        raise HTTPException(status_code=503, detail="webhook secret not configured")
    raw = await request.body()
    presented = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not presented or not hmac.compare_digest(expected, presented):
        raise HTTPException(status_code=403, detail="invalid webhook signature")
    try:
        event = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid webhook payload")
    if str(event.get("event", "")) not in ("payment.captured", "order.paid"):
        return {"status": "ignored"}
    entity = (
        (event.get("payload") or {}).get("payment", {}).get("entity")
        or (event.get("payload") or {}).get("order", {}).get("entity")
        or {}
    )
    order_id = str(entity.get("order_id") or entity.get("id") or "")
    payment_id = str(entity.get("id") or "")
    if not order_id:
        return {"status": "ignored"}
    payment = db.scalar(
        select(Payment).where(Payment.provider_order_id == order_id)
    )
    if payment is None:
        logger.warning("razorpay webhook for unknown order %s", order_id)
        return {"status": "ignored"}
    if entity.get("amount") is not None and int(entity["amount"]) != payment.amount_paise:
        logger.warning(
            "razorpay webhook amount mismatch order=%s expected=%s got=%s",
            order_id,
            payment.amount_paise,
            entity.get("amount"),
        )
        return {"status": "amount_mismatch"}
    granted = billing.settle_payment(db, payment, payment_id or f"webhook-{order_id}")
    db.commit()
    if granted:
        _notify_payment_invoice(db, settings, payment.id)
    logger.info(
        "razorpay webhook: order=%s payment=%s granted=%s",
        order_id,
        payment_id,
        granted,
    )
    return {"status": "ok", "credits_granted": granted}


@router.post("/topup")
def topup(
    payload: TopupRequest,
    request: Request,
    user: User = Depends(require_billing_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Credit a pack. Only available when a payment path is configured.

    There is deliberately no self-service free-credit route: in production the
    flag is off until a real gateway (Razorpay) is wired, so this endpoint
    cannot mint money. Local development sets ALLOW_MANUAL_PAYMENTS=true to
    exercise the wallet end to end.
    """
    settings: Settings = request.app.state.settings
    if not settings.allow_manual_payments:
        raise HTTPException(
            status_code=403,
            detail="payments are not enabled yet — contact hello@echosarathi.ai",
        )
    pack = billing.get_pack(payload.pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="unknown pack")
    payment = billing.open_manual_payment(
        db,
        org_id=user.org_id,
        sku=str(pack["id"]),
        amount_paise=int(pack["price_paise"]),
        created_by=user.id,
    )
    entry = billing.purchase_pack(db, user.org_id, pack, created_by=user.id)
    org = db.get(Organization, user.org_id)
    if org is not None:
        invoice_service.create_invoice(
            db,
            org,
            description=f"{pack['name']} pack · {pack['minutes']} minutes",
            total_paise=payment.amount_paise,
            payment_id=payment.id,
        )
    db.commit()
    invoice = _notify_payment_invoice(db, settings, payment.id)
    logger.info(
        "credits: org=%s pack=%s value=%s paid=%s",
        user.org_id,
        pack["id"],
        entry.amount_paise,
        entry.paid_paise,
    )
    return billing.summary(db, user.org_id) | {"invoice": invoice}
