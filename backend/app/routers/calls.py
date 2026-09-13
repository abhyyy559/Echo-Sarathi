"""Call list + detail endpoints (org-scoped per contract §4).

``GET /api/calls`` is the cross-campaign call history feed (Overview page and
the Call History table both read it); ``GET /api/calls/{call_id}`` is the
per-call detail payload used by the transcript view.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Agent, AgentVersion, Call, Campaign, Contact, ExtractedField, Transcript, User
from app.schemas import CampaignCallOut, CallDetailOut, CallListItemOut
from app.services.export_service import (
    CSV_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    export_call_csv,
    export_call_xlsx,
)

router = APIRouter(prefix="/api", tags=["calls"])


def _call_org_id(db: Session, call: Call) -> Any:
    """Effective org of a call: denormalized column, else campaign lineage."""
    if call.org_id is not None:
        return call.org_id
    campaign = db.get(Campaign, call.campaign_id) if call.campaign_id else None
    return campaign.org_id if campaign else None


def _org_call_filter(org_id: int):
    """SQL predicate matching calls whose effective org is ``org_id``."""
    return or_(Call.org_id == org_id, Campaign.org_id == org_id)


# Avg end-to-end latency per call (single grouped scan, joined in below).
_avg_e2e_subq = (
    select(Transcript.call_id, func.avg(Transcript.e2e_ms).label("avg_e2e_ms"))
    .where(Transcript.e2e_ms.isnot(None))
    .group_by(Transcript.call_id)
    .subquery()
)


@router.get("/calls", response_model=list[CallListItemOut])
def list_calls(
    limit: int = 500,
    agent_version_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Most recent org-scoped calls across every campaign + playground."""
    capped_limit = max(1, min(limit, 1000))
    stmt = (
        select(
            Call,
            Contact.name,
            Contact.phone,
            Agent.name,
            _avg_e2e_subq.c.avg_e2e_ms,
        )
        .outerjoin(Contact, Contact.id == Call.contact_id)
        .outerjoin(Campaign, Campaign.id == Call.campaign_id)
        .outerjoin(AgentVersion, AgentVersion.id == Call.agent_version_id)
        .outerjoin(Agent, Agent.id == AgentVersion.agent_id)
        .outerjoin(_avg_e2e_subq, _avg_e2e_subq.c.call_id == Call.id)
        .where(_org_call_filter(user.org_id))
    )
    if agent_version_id is not None:
        stmt = stmt.where(Call.agent_version_id == agent_version_id)
    rows = db.execute(stmt.order_by(Call.id.desc()).limit(capped_limit)).all()
    return [
        {
            "id": call.id,
            "status": call.status,
            "kind": call.kind or "phone",
            "duration_seconds": call.duration_seconds,
            "started_at": call.started_at,
            "created_at": call.created_at,
            "agent_version_id": call.agent_version_id,
            "agent_name": agent_name,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "avg_e2e_ms": round(float(avg_e2e), 1) if avg_e2e is not None else None,
            "flagged_for_human": call.flagged_for_human,
        }
        for call, contact_name, contact_phone, agent_name, avg_e2e in rows
    ]


@router.get("/campaigns/{campaign_id}/calls", response_model=list[CampaignCallOut])
def list_campaign_calls(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="campaign not found")
    rows = db.execute(
        select(Call, Contact.name, Contact.phone)
        .join(Contact, Contact.id == Call.contact_id)
        .where(Call.campaign_id == campaign_id)
        .order_by(Call.id.desc())
    ).all()
    return [
        {
            "id": call.id,
            "campaign_id": call.campaign_id,
            "contact_id": call.contact_id,
            "provider_call_id": call.provider_call_id,
            "status": call.status,
            "started_at": call.started_at,
            "answered_at": call.answered_at,
            "ended_at": call.ended_at,
            "duration_seconds": call.duration_seconds,
            "recording_url": call.recording_url,
            "summary": call.summary,
            "outcome": call.outcome,
            "flagged_for_human": call.flagged_for_human,
            "cost": call.cost,
            "latency": call.latency,
            "created_at": call.created_at,
            "contact_name": name,
            "contact_phone": phone,
        }
        for call, name, phone in rows
    ]


@router.get("/calls/{call_id}", response_model=CallDetailOut)
def get_call(
    call_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    call = db.get(Call, call_id)
    if call is None or _call_org_id(db, call) != user.org_id:
        raise HTTPException(status_code=404, detail="call not found")
    contact = db.get(Contact, call.contact_id)
    turns = db.scalars(
        select(Transcript).where(Transcript.call_id == call.id).order_by(Transcript.turn_index)
    ).all()
    fields = db.scalars(
        select(ExtractedField).where(ExtractedField.call_id == call.id).order_by(ExtractedField.id)
    ).all()
    return {
        "id": call.id,
        "campaign_id": call.campaign_id,
        "contact_id": call.contact_id,
        "provider_call_id": call.provider_call_id,
        "status": call.status,
        "started_at": call.started_at,
        "answered_at": call.answered_at,
        "ended_at": call.ended_at,
        "duration_seconds": call.duration_seconds,
        "recording_url": call.recording_url,
        "summary": call.summary,
        "outcome": call.outcome,
        "flagged_for_human": call.flagged_for_human,
        "cost": call.cost,
        "latency": call.latency,
        "created_at": call.created_at,
        "contact_name": contact.name if contact else None,
        "contact_phone": contact.phone if contact else None,
        "transcript": [
            {
                "turn_index": t.turn_index,
                "speaker": t.speaker,
                "text": t.text,
                "timestamp": t.timestamp,
            }
            for t in turns
        ],
        "extracted_fields": [
            {
                "field_name": f.field_name,
                "field_value": f.field_value,
                "source_turn_index": f.source_turn_index,
                "confidence": f.confidence,
            }
            for f in fields
        ],
    }


@router.get("/calls/{call_id}/export")
def export_call(
    call_id: int,
    format: str = "csv",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export ONE call row (campaign or contact-less playground call) as CSV/XLSX."""
    call = db.get(Call, call_id)
    if call is None or _call_org_id(db, call) != user.org_id:
        raise HTTPException(status_code=404, detail="call not found")
    if format == "csv":
        return Response(
            content=export_call_csv(db, call),
            media_type=CSV_MEDIA_TYPE,
            headers={"Content-Disposition": f'attachment; filename="call-{call.id}.csv"'},
        )
    if format == "xlsx":
        return Response(
            content=export_call_xlsx(db, call),
            media_type=XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": f'attachment; filename="call-{call.id}.xlsx"'},
        )
    raise HTTPException(status_code=422, detail="format must be csv or xlsx")
