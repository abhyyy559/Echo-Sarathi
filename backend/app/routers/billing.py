"""Prepaid credit wallet: balance, usage history and top-ups."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Payment, User
from app.services import billing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"


class TopupRequest(BaseModel):
    pack_id: str


class CheckoutRequest(BaseModel):
    pack_id: str


class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    pack_id: str


@router.get("")
def get_billing(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Wallet state, this month's spend, packs and recent ledger."""
    settings: Settings = request.app.state.settings
    data = billing.summary(db, user.org_id)
    data["manual_payments_enabled"] = bool(settings.allow_manual_payments)
    data["checkout_enabled"] = bool(settings.checkout_enabled)
    return data


def _razorpay_signature(order_id: str, payment_id: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@router.post("/checkout")
def checkout(
    payload: CheckoutRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Open a gateway order for a pack. Credits are NOT granted here."""
    settings: Settings = request.app.state.settings
    if not settings.checkout_enabled:
        raise HTTPException(
            status_code=503,
            detail="online payments are not configured in this environment",
        )
    pack = billing.get_pack(payload.pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="unknown pack")

    import httpx

    try:
        resp = httpx.post(
            RAZORPAY_ORDERS_URL,
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            json={
                "amount": int(pack["price_paise"]),
                "currency": "INR",
                "receipt": f"org{user.org_id}-{pack['id']}",
                "notes": {
                    "org_id": str(user.org_id),
                    "pack_id": str(pack["id"]),
                    "user_id": str(user.id),
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
    order = resp.json()
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
    """Verify the checkout signature, then credit the pack exactly once."""
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
    return billing.summary(db, user.org_id) | {"credits_granted": granted}


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
    user: User = Depends(get_current_user),
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
    entry = billing.purchase_pack(db, user.org_id, pack, created_by=user.id)
    db.commit()
    logger.info(
        "credits: org=%s pack=%s value=%s paid=%s",
        user.org_id,
        pack["id"],
        entry.amount_paise,
        entry.paid_paise,
    )
    return billing.summary(db, user.org_id)
