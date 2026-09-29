"""Auth endpoints (frozen contract §4): register / login / me.

Cookie-less JWT bearer auth. Registration creates the organization, its owner
user and returns a token in one call.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, hash_password, verify_password
from app.config import Settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Organization, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def slugify(value: str) -> str:
    """Lowercase kebab slug; non-alphanumerics collapse to single dashes."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "org"


class RegisterRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    org_id: int


class TokenResponse(BaseModel):
    token: str
    user: UserOut


def _validate_email(email: str) -> str:
    if not _EMAIL_RE.match(email.strip()):
        raise HTTPException(status_code=422, detail="invalid email address")
    return email.strip().lower()


def _unique_org_slug(db: Session, base: str) -> str:
    candidate = base
    suffix = 2
    while db.scalar(select(Organization).where(Organization.slug == candidate)) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, role=user.role, org_id=user.org_id)


@router.post("/register", response_model=TokenResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    if not settings.allow_public_registration:
        # H5: open registration mints owner-role orgs. Closed by default in
        # hardened deployments via ALLOW_PUBLIC_REGISTRATION=false.
        raise HTTPException(status_code=403, detail="public registration is disabled")
    email = _validate_email(payload.email)
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    org = Organization(
        name=payload.org_name.strip(),
        slug=_unique_org_slug(db, slugify(payload.org_name)),
    )
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email=email,
        password_hash=hash_password(payload.password),
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id, user.org_id, user.role, settings)
    return {"token": token, "user": _user_out(user).model_dump()}


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    email = _validate_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    token = create_access_token(user.id, user.org_id, user.role, settings)
    return {"token": token, "user": _user_out(user).model_dump()}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)
