"""Prepaid credit wallet: balance, usage history and top-ups."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import billing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


class TopupRequest(BaseModel):
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
    return data


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
