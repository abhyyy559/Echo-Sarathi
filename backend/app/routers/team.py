"""Team management: members, invitations and seat limits.

Seats are a plan entitlement: members plus live pending invites may never
exceed the plan's ``max_users``. Invite tokens are stored hashed and only the
emailed link carries the raw value.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import new_token
from app.config import Settings
from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import Invite, Organization, User
from app.services import email as email_service
from app.services import plans
from app.timeutil import utcnow

router = APIRouter(prefix="/api/team", tags=["team"])

INVITE_DAYS = 7
INVITABLE_ROLES = ("admin", "member")

require_team_admin = require_roles("owner", "admin")


class InviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: str = "member"


class MemberRoleUpdate(BaseModel):
    role: str


def _pending_invites(db: Session, org_id: int) -> list[Invite]:
    return list(
        db.scalars(
            select(Invite)
            .where(
                Invite.org_id == org_id,
                Invite.accepted_at.is_(None),
                Invite.expires_at > utcnow(),
            )
            .order_by(Invite.id.desc())
        ).all()
    )


def _member_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at,
    }


def _invite_out(invite: Invite) -> dict[str, Any]:
    return {
        "id": invite.id,
        "email": invite.email,
        "role": invite.role,
        "expires_at": invite.expires_at,
        "created_at": invite.created_at,
    }


def _seats(db: Session, org_id: int) -> tuple[int, int]:
    """``(used, limit)`` where used counts members plus live pending invites."""
    members = int(
        db.scalar(select(func.count(User.id)).where(User.org_id == org_id)) or 0
    )
    pending = len(_pending_invites(db, org_id))
    plan, _subscription = plans.org_plan(db, org_id)
    return members + pending, int(plan["max_users"])


@router.get("")
def list_team(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    members = db.scalars(
        select(User).where(User.org_id == user.org_id).order_by(User.id)
    ).all()
    used, limit = _seats(db, user.org_id)
    data: dict[str, Any] = {
        "members": [_member_out(member) for member in members],
        "seats_used": used,
        "seats_limit": limit,
        "invites": [],
    }
    if user.role in ("owner", "admin"):
        data["invites"] = [_invite_out(invite) for invite in _pending_invites(db, user.org_id)]
    return data


@router.post("/invites", status_code=201)
def create_invite(
    payload: InviteRequest,
    request: Request,
    user: User = Depends(require_team_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="invalid email address")
    role = payload.role if payload.role in INVITABLE_ROLES else None
    if role is None:
        raise HTTPException(
            status_code=422, detail="role must be 'admin' or 'member'"
        )
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="that email already has an account")

    used, limit = _seats(db, user.org_id)
    existing = db.scalar(
        select(Invite).where(
            Invite.org_id == user.org_id,
            Invite.email == email,
            Invite.accepted_at.is_(None),
        )
    )
    if existing is None and used >= limit:
        plan, _subscription = plans.org_plan(db, user.org_id)
        raise HTTPException(
            status_code=403, detail=plans.limit_message(plan, "users", limit)
        )

    raw, token_hash = new_token()
    now = utcnow()
    if existing is not None:
        invite = existing
        invite.role = role
        invite.token_hash = token_hash
        invite.expires_at = now + timedelta(days=INVITE_DAYS)
        invite.created_by = user.id
    else:
        invite = Invite(
            org_id=user.org_id,
            email=email,
            role=role,
            token_hash=token_hash,
            expires_at=now + timedelta(days=INVITE_DAYS),
            created_by=user.id,
        )
        db.add(invite)
    db.commit()
    db.refresh(invite)

    org = db.get(Organization, user.org_id)
    accept_url = (
        f"{settings.frontend_base_url.rstrip('/')}/accept-invite?token={raw}"
    )
    email_service.invite(
        settings,
        to=email,
        org_name=org.name if org is not None else "Echo Sarathi",
        inviter_email=user.email,
        role=role,
        accept_url=accept_url,
    )
    return _invite_out(invite)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(
    invite_id: int,
    user: User = Depends(require_team_admin),
    db: Session = Depends(get_db),
) -> None:
    invite = db.get(Invite, invite_id)
    if invite is None or invite.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(invite)
    db.commit()


def _get_member(db: Session, member_id: int, org_id: int) -> User:
    member = db.get(User, member_id)
    if member is None or member.org_id != org_id:
        raise HTTPException(status_code=404, detail="not found")
    return member


@router.patch("/members/{member_id}")
def update_member_role(
    member_id: int,
    payload: MemberRoleUpdate,
    user: User = Depends(require_team_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    member = _get_member(db, member_id, user.org_id)
    if payload.role not in INVITABLE_ROLES:
        raise HTTPException(
            status_code=422, detail="role must be 'admin' or 'member'"
        )
    if member.role == "owner":
        raise HTTPException(
            status_code=403, detail="the owner role cannot be changed here"
        )
    if user.role == "admin" and member.role == "admin" and member.id != user.id:
        raise HTTPException(
            status_code=403, detail="only the owner can change another admin's role"
        )
    member.role = payload.role
    db.commit()
    return _member_out(member)


@router.delete("/members/{member_id}", status_code=204)
def remove_member(
    member_id: int,
    user: User = Depends(require_team_admin),
    db: Session = Depends(get_db),
) -> None:
    member = _get_member(db, member_id, user.org_id)
    if member.role == "owner":
        raise HTTPException(
            status_code=403, detail="the owner account cannot be removed"
        )
    if member.id != user.id and user.role == "admin" and member.role == "admin":
        raise HTTPException(
            status_code=403, detail="only the owner can remove another admin"
        )
    db.delete(member)
    db.commit()
