"""Contact endpoints: list, import (CSV/XLSX), patch, delete (org-scoped)."""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import CONTACT_STATUSES, Campaign, ConsentRecord, Contact, User
from app.schemas import ContactOut, ContactPage, ContactPatch, ImportResult
from app.services.import_service import import_contacts, normalize_phone
from app.timeutil import utcnow

router = APIRouter(prefix="/api", tags=["contacts"])


def _get_campaign_or_404(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign


def _contact_out(contact: Contact) -> dict[str, Any]:
    return {
        "id": contact.id,
        "campaign_id": contact.campaign_id,
        "name": contact.name,
        "phone": contact.phone,
        "external_id": contact.external_id,
        "custom_fields": contact.custom_fields or {},
        "status": contact.status,
        "consent": bool(contact.consent),
        "consent_source": contact.consent_source,
        "attempt_count": contact.attempt_count,
        "next_attempt_at": contact.next_attempt_at,
        "last_call_id": contact.last_call_id,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


@router.get("/campaigns/{campaign_id}/contacts", response_model=ContactPage)
def list_contacts(
    campaign_id: int,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_campaign_or_404(db, campaign_id, user)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    conditions = [Contact.campaign_id == campaign_id]
    if status:
        conditions.append(Contact.status == status)
    total = db.scalar(select(func.count()).select_from(Contact).where(*conditions)) or 0
    contacts = db.scalars(
        select(Contact)
        .where(*conditions)
        .order_by(Contact.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_contact_out(c) for c in contacts],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post(
    "/campaigns/{campaign_id}/contacts/import", response_model=ImportResult
)
async def import_contacts_endpoint(
    campaign_id: int,
    file: UploadFile = File(...),
    mapping: str = Form(...),
    consent_default: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_campaign_or_404(db, campaign_id, user)
    try:
        mapping_dict = json.loads(mapping)
        if not isinstance(mapping_dict, dict):
            raise ValueError("mapping must be a JSON object")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"invalid mapping JSON: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    # Roster default: a campaign roster uploaded by the org (e.g. the
    # college's own enrollment list) IS the institutional relationship, so
    # contacts count as consented unless the uploader explicitly opts out.
    # No TEST_PHONE_NUMBERS entry is ever needed for roster numbers. An
    # explicit consent_default=true/false (or a per-row consent column) still
    # wins over this default.
    if consent_default is None:
        default_consent = True
    else:
        default_consent = consent_default.strip().lower() in (
            "1", "true", "yes", "y", "on",
        )
    try:
        result = import_contacts(
            db,
            campaign_id,
            data,
            file.filename or "upload.csv",
            mapping_dict,
            consent_default=default_consent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Backfill the denormalized org column on freshly imported rows.
    campaign = _get_campaign_or_404(db, campaign_id, user)
    if campaign.org_id is not None:
        db.execute(
            update(Contact)
            .where(Contact.campaign_id == campaign_id, Contact.org_id.is_(None))
            .values(org_id=campaign.org_id)
        )
        db.commit()
    return result


def _get_own_contact_or_404(db: Session, contact_id: int, user: User) -> Contact:
    """Fetch a contact and verify its campaign belongs to the caller's org."""
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")
    _get_campaign_or_404(db, contact.campaign_id, user)
    return contact


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def patch_contact(
    contact_id: int,
    payload: ContactPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    contact = _get_own_contact_or_404(db, contact_id, user)
    if payload.status is not None:
        if payload.status not in CONTACT_STATUSES:
            raise HTTPException(status_code=422, detail=f"invalid status: {payload.status}")
        if contact.status == "calling" and payload.status != "calling":
            raise HTTPException(
                status_code=422,
                detail="contact has a live call in progress and cannot be moved",
            )
        contact.status = payload.status
    if payload.phone is not None:
        phone, ok = normalize_phone(payload.phone)
        if not ok:
            raise HTTPException(status_code=422, detail=f"invalid phone number: {payload.phone}")
        contact.phone = phone
    if payload.name is not None:
        contact.name = payload.name
    if payload.custom_fields is not None:
        contact.custom_fields = payload.custom_fields
    if payload.consent is not None:
        contact.consent = payload.consent
        if payload.consent:
            contact.consent_source = "api"
            db.add(
                ConsentRecord(
                    contact_id=contact.id,
                    phone=contact.phone,
                    consent_type="calling",
                    consent_given=True,
                    source="api:patch",
                    captured_at=utcnow(),
                )
            )
    db.commit()
    db.refresh(contact)
    return _contact_out(contact)


@router.delete("/contacts/{contact_id}")
def delete_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    contact = _get_own_contact_or_404(db, contact_id, user)
    db.delete(contact)
    db.commit()
    return {"ok": True, "id": contact_id}
