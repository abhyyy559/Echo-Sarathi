"""GST invoices for successful plan and top-up payments.

Retail prices are quoted GST-inclusive, so the invoice splits the total into a
taxable value and the 18% GST component instead of adding tax on top. Customer
details are snapshotted at issue time; editing the billing profile later must
never rewrite an issued invoice.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Invoice, Organization, User
from app.timeutil import utcnow

GST_RATE_PERCENT = 18


def split_gst_inclusive(total_paise: int) -> tuple[int, int]:
    """Return ``(taxable_paise, gst_paise)`` for a GST-inclusive total."""
    total = max(0, int(total_paise))
    taxable = int(round(total * 100 / (100 + GST_RATE_PERCENT)))
    return taxable, total - taxable


def financial_year(moment: datetime) -> str:
    """Indian financial year label, e.g. ``2026-27`` (April–March)."""
    start = moment.year if moment.month >= 4 else moment.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def next_invoice_number(db: Session, issued_at: Optional[datetime] = None) -> str:
    """Sequential per financial year: ``ES/2026-27/0001``.

    Volume is low enough that COUNT+1 inside the payment transaction is fine;
    the unique constraint on ``invoices.number`` catches the rare race rather
    than silently duplicating a tax document.
    """
    issued_at = issued_at or utcnow()
    prefix = f"ES/{financial_year(issued_at)}/"
    used = db.scalar(
        select(func.count(Invoice.id)).where(Invoice.number.like(f"{prefix}%"))
    )
    return f"{prefix}{int(used or 0) + 1:04d}"


def _billing_email(db: Session, org: Organization) -> str:
    if org.billing_email:
        return org.billing_email
    owner_email = db.scalar(
        select(User.email)
        .where(User.org_id == org.id, User.role == "owner")
        .order_by(User.id)
    )
    if owner_email:
        return str(owner_email)
    any_email = db.scalar(select(User.email).where(User.org_id == org.id).order_by(User.id))
    return str(any_email or "")


def create_invoice(
    db: Session,
    org: Organization,
    *,
    description: str,
    total_paise: int,
    payment_id: Optional[int] = None,
    subscription_id: Optional[int] = None,
    issued_at: Optional[datetime] = None,
) -> Invoice:
    """Append an invoice row; caller owns the transaction and commit."""
    issued_at = issued_at or utcnow()
    subtotal, gst = split_gst_inclusive(total_paise)
    invoice = Invoice(
        org_id=org.id,
        subscription_id=subscription_id,
        payment_id=payment_id,
        number=next_invoice_number(db, issued_at),
        description=description[:255],
        subtotal_paise=subtotal,
        gst_paise=gst,
        total_paise=int(total_paise),
        customer_name=(org.legal_name or org.name or "")[:200],
        customer_email=_billing_email(db, org)[:255],
        customer_gstin=(org.gstin or "")[:20],
        customer_address=org.billing_address or "",
        customer_state=(org.billing_state or "")[:100],
        issued_at=issued_at,
    )
    db.add(invoice)
    db.flush()
    return invoice


def invoice_out(invoice: Invoice) -> dict[str, Any]:
    return {
        "id": invoice.id,
        "number": invoice.number,
        "description": invoice.description,
        "subtotal_paise": invoice.subtotal_paise,
        "gst_paise": invoice.gst_paise,
        "total_paise": invoice.total_paise,
        "gst_rate_percent": GST_RATE_PERCENT,
        "customer_name": invoice.customer_name,
        "customer_email": invoice.customer_email,
        "customer_gstin": invoice.customer_gstin,
        "customer_address": invoice.customer_address,
        "customer_state": invoice.customer_state,
        "payment_id": invoice.payment_id,
        "subscription_id": invoice.subscription_id,
        "issued_at": invoice.issued_at,
    }


def list_invoices(db: Session, org_id: int, limit: int = 50) -> list[Invoice]:
    return list(
        db.scalars(
            select(Invoice)
            .where(Invoice.org_id == org_id)
            .order_by(Invoice.id.desc())
            .limit(max(1, min(limit, 200)))
        ).all()
    )
