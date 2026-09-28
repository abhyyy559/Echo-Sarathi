"""Campaign management endpoints (/api/campaigns, org-scoped per contract §4)."""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Agent, AgentVersion, Campaign, Call, Contact, DomainConfig, User
from app.schemas import CampaignCreate, CampaignDetail, CampaignListItem, CampaignOut
from app.services.calls_service import in_flight_call_count
from app.timeutil import is_within_calling_hours, utcnow

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def _contact_counts(db: Session, campaign_id: int) -> dict[str, int]:
    rows = db.execute(
        select(Contact.status, func.count())
        .where(Contact.campaign_id == campaign_id)
        .group_by(Contact.status)
    ).all()
    by_status: dict[str, int] = {status: count for status, count in rows}
    total = sum(by_status.values())
    return {
        "total": total,
        "pending_review": by_status.get("pending_review", 0),
        "invalid": by_status.get("invalid", 0),
        "queued": by_status.get("queued", 0),
        "calling": by_status.get("calling", 0),
        "completed": by_status.get("completed", 0),
        "no_answer": by_status.get("no_answer", 0),
        "busy": by_status.get("busy", 0),
        "failed": by_status.get("failed", 0),
        "opted_out": by_status.get("opted_out", 0),
        "skipped": by_status.get("skipped", 0),
    }


def _get_campaign_or_404(db: Session, campaign_id: int, user: User) -> Campaign:
    """Org-scoped fetch: foreign-org campaigns return 404 (existence-leak guard)."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign


def _campaign_out(db: Session, campaign: Campaign) -> dict[str, Any]:
    domain_config = (
        db.get(DomainConfig, campaign.domain_config_id)
        if campaign.domain_config_id
        else None
    )
    return {
        "id": campaign.id,
        "org_id": campaign.org_id,
        "name": campaign.name,
        "status": campaign.status,
        "domain_config_id": campaign.domain_config_id,
        "domain_config_name": domain_config.name if domain_config else None,
        "agent_version_id": campaign.agent_version_id,
        "schedule_window_start": campaign.schedule_window_start,
        "schedule_window_end": campaign.schedule_window_end,
        "created_at": campaign.created_at,
        "updated_at": campaign.updated_at,
    }


def consent_ok(db: Session, contact: Contact, settings) -> bool:
    """Consent gate shared by launch + dialer (see PRD §8)."""
    if not settings.consent_enforcement:
        return True
    return bool(contact.consent) or contact.phone in settings.test_phone_number_list


@router.get("", response_model=list[CampaignListItem])
def list_campaigns(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    campaigns = db.scalars(
        select(Campaign)
        .where(Campaign.org_id == user.org_id)
        .order_by(Campaign.id.desc())
    ).all()
    items: list[dict[str, Any]] = []
    for campaign in campaigns:
        base = _campaign_out(db, campaign)
        base["counts"] = _contact_counts(db, campaign.id)
        items.append(base)
    return items


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.domain_config_id and db.get(DomainConfig, payload.domain_config_id) is None:
        raise HTTPException(status_code=422, detail="unknown domain_config_id")
    agent_version_id: Optional[int] = payload.agent_version_id
    if agent_version_id is not None:
        version = db.get(AgentVersion, agent_version_id)
        # Foreign-org versions must be indistinguishable from missing ones.
        parent_agent = (
            db.get(Agent, version.agent_id)
            if version is not None
            else None
        )
        if version is None or parent_agent is None or parent_agent.org_id != user.org_id:
            raise HTTPException(status_code=404, detail="agent version not found")
    campaign = Campaign(
        name=payload.name,
        domain_config_id=payload.domain_config_id,
        agent_version_id=agent_version_id,
        org_id=user.org_id,
        status="draft",
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return _campaign_out(db, campaign)


@router.get("/{campaign_id}", response_model=CampaignDetail)
def get_campaign(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_campaign_or_404(db, campaign_id, user)
    out = _campaign_out(db, campaign)
    out["counts"] = _contact_counts(db, campaign.id)
    return out


@router.post("/{campaign_id}/launch", response_model=CampaignOut)
def launch_campaign(
    campaign_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_campaign_or_404(db, campaign_id, user)
    settings = request.app.state.settings
    if campaign.status == "running":
        raise HTTPException(status_code=422, detail="campaign is already running")
    if campaign.status in ("completed", "canceled"):
        raise HTTPException(status_code=422, detail=f"campaign is {campaign.status}")

    contact_count = (
        db.scalar(select(func.count()).select_from(Contact).where(Contact.campaign_id == campaign.id))
        or 0
    )
    if contact_count == 0:
        raise HTTPException(status_code=422, detail="campaign has no contacts to call")

    clock: Callable = getattr(request.app.state, "clock", None) or utcnow
    now = clock()
    if not is_within_calling_hours(
        now, settings.timezone, settings.calling_hours_start, settings.calling_hours_end
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"outside calling hours ({settings.calling_hours_start:02d}:00–"
                f"{settings.calling_hours_end:02d}:00 {settings.timezone})"
            ),
        )

    campaign.status = "running"
    pending = db.scalars(
        select(Contact).where(
            Contact.campaign_id == campaign.id, Contact.status == "pending_review"
        )
    ).all()
    for contact in pending:
        if contact.phone and consent_ok(db, contact, settings):
            contact.status = "queued"
    db.commit()
    db.refresh(campaign)
    return _campaign_out(db, campaign)


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
def pause_campaign(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_campaign_or_404(db, campaign_id, user)
    if campaign.status != "running":
        raise HTTPException(status_code=422, detail=f"cannot pause a {campaign.status} campaign")
    campaign.status = "paused"
    db.commit()
    db.refresh(campaign)
    return _campaign_out(db, campaign)


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
def cancel_campaign(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_campaign_or_404(db, campaign_id, user)
    if campaign.status in ("completed", "canceled"):
        raise HTTPException(status_code=422, detail=f"campaign is already {campaign.status}")
    campaign.status = "canceled"
    db.commit()
    db.refresh(campaign)
    return _campaign_out(db, campaign)


@router.get("/{campaign_id}/dashboard")
def campaign_dashboard(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_campaign_or_404(db, campaign_id, user)
    recent_calls = db.execute(
        select(Call, Contact.name, Contact.phone)
        .join(Contact, Contact.id == Call.contact_id)
        .where(Call.campaign_id == campaign_id)
        .order_by(Call.id.desc())
        .limit(20)
    ).all()
    return {
        "campaign_id": campaign.id,
        "campaign_status": campaign.status,
        "counts": _contact_counts(db, campaign.id),
        "calls_in_flight": in_flight_call_count(db),
        "recent_calls": [
            {
                "id": call.id,
                "contact_name": name,
                "phone": phone,
                "status": call.status,
                "started_at": call.started_at,
                "duration_seconds": call.duration_seconds,
                "outcome": call.outcome,
            }
            for call, name, phone in recent_calls
        ],
    }
