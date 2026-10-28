"""Auth endpoints (frozen contract §4): register / login / Google / me, plus
the self-service account flows a SaaS needs: password reset and invite
acceptance.

Cookie-less JWT bearer auth. Registration creates the organization, its owner
user and returns a token in one call.
"""
from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from app.config import Settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Invite, Organization, PasswordReset, User
from app.services import email as email_service
from app.services import plans
from app.services.google_auth import GoogleTokenError, verify_google_credential
from app.timeutil import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

RESET_TOKEN_MINUTES = 30
INVITE_TOKEN_DAYS = 7


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


class GoogleLoginRequest(BaseModel):
    # Signed ID token ("credential") issued by Google Identity Services.
    credential: str = Field(min_length=20, max_length=8192)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    org_id: int
    is_platform_admin: bool = False


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


def _is_platform_admin(user: User, settings: Settings) -> bool:
    return user.email.strip().lower() in settings.platform_admin_email_list


def _user_out(user: User, settings: Settings) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        org_id=user.org_id,
        is_platform_admin=_is_platform_admin(user, settings),
    )


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
    from app.services.billing import PRICE_PER_MINUTE_PAISE, TRIAL_CREDITS_PAISE, grant_trial

    grant_trial(db, org.id)
    user = User(
        org_id=org.id,
        email=email,
        password_hash=hash_password(payload.password),
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    email_service.welcome(
        settings,
        to=email,
        org_name=org.name,
        trial_minutes=TRIAL_CREDITS_PAISE // PRICE_PER_MINUTE_PAISE,
    )
    token = create_access_token(user.id, user.org_id, user.role, settings)
    return {"token": token, "user": _user_out(user, settings).model_dump()}


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    email = _validate_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    # Google-only accounts have no password hash; they must use Google.
    if (
        user is None
        or not user.password_hash
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="invalid email or password")
    token = create_access_token(user.id, user.org_id, user.role, settings)
    return {"token": token, "user": _user_out(user, settings).model_dump()}


@router.post("/google", response_model=TokenResponse)
def google_login(
    payload: GoogleLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Sign in with a Google ID token; sign up when the email is unknown.

    An existing email/password account is linked to the Google identity on
    first use: Google has already proven ownership of the email, and both
    paths keep working afterwards. New accounts follow the same public-
    registration gate as ``/register`` and create their own organization.
    """
    settings: Settings = request.app.state.settings
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    try:
        claims = verify_google_credential(payload.credential, settings.google_client_id)
    except GoogleTokenError as exc:
        raise HTTPException(
            status_code=401, detail="Google sign-in failed — please try again"
        ) from exc

    sub = str(claims["sub"])
    email = _validate_email(str(claims["email"]))
    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None and user.google_sub not in (None, sub):
            raise HTTPException(
                status_code=409,
                detail="this email is linked to a different Google account",
            )
    if user is not None:
        if user.google_sub != sub:
            user.google_sub = sub
            db.commit()
    else:
        if not settings.allow_public_registration:
            raise HTTPException(
                status_code=403,
                detail=(
                    "no account uses this Google email — "
                    "ask your admin for an invitation"
                ),
            )
        raw_name = str(claims.get("name") or "").strip()
        org_name = (raw_name or email.split("@")[0])[:200] or "My workspace"
        org = Organization(name=org_name, slug=_unique_org_slug(db, slugify(org_name)))
        db.add(org)
        db.flush()
        from app.services.billing import grant_trial

        grant_trial(db, org.id)
        user = User(
            org_id=org.id,
            email=email,
            password_hash=None,
            google_sub=sub,
            role="owner",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    token = create_access_token(user.id, user.org_id, user.role, settings)
    return {"token": token, "user": _user_out(user, settings).model_dump()}


@router.get("/me", response_model=UserOut)
def me(
    request: Request, user: User = Depends(get_current_user)
) -> UserOut:
    return _user_out(user, request.app.state.settings)


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Email a one-time reset link. The response is identical for unknown
    addresses so the endpoint cannot be used to enumerate accounts."""
    settings: Settings = request.app.state.settings
    email = _validate_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        now = utcnow()
        # Only the newest link stays valid.
        for old in db.scalars(
            select(PasswordReset).where(
                PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
            )
        ).all():
            old.used_at = now
        raw, token_hash = new_token()
        db.add(
            PasswordReset(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=now + timedelta(minutes=RESET_TOKEN_MINUTES),
            )
        )
        db.commit()
        reset_url = (
            f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={raw}"
        )
        email_service.password_reset(settings, to=email, reset_url=reset_url)
    return {"status": "sent"}


@router.post("/reset-password")
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    now = utcnow()
    row = db.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == hash_token(payload.token))
    )
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise HTTPException(
            status_code=400, detail="this reset link is invalid or has expired"
        )
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="this reset link is no longer valid")
    user.password_hash = hash_password(payload.password)
    row.used_at = now
    db.commit()
    return {"status": "ok"}


@router.post("/accept-invite", response_model=TokenResponse)
def accept_invite(
    payload: AcceptInviteRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Join the inviting organization with the emailed one-time link."""
    settings: Settings = request.app.state.settings
    now = utcnow()
    invite = db.scalar(
        select(Invite).where(Invite.token_hash == hash_token(payload.token))
    )
    if invite is None or invite.accepted_at is not None or invite.expires_at <= now:
        raise HTTPException(
            status_code=400, detail="this invitation is invalid or has expired"
        )
    if db.scalar(select(User).where(User.email == invite.email)) is not None:
        raise HTTPException(
            status_code=409,
            detail="this email already has an account — sign in instead",
        )
    org = db.get(Organization, invite.org_id)
    if org is None:
        raise HTTPException(status_code=400, detail="this invitation is no longer valid")
    plan, _subscription = plans.org_plan(db, org.id)
    seats = db.scalar(
        select(func.count(User.id)).where(User.org_id == org.id)
    )
    limit = int(plan["max_users"])
    if int(seats or 0) >= limit:
        raise HTTPException(
            status_code=403, detail=plans.limit_message(plan, "users", limit)
        )
    user = User(
        org_id=org.id,
        email=invite.email,
        password_hash=hash_password(payload.password),
        role=invite.role if invite.role in ("admin", "member") else "member",
    )
    invite.accepted_at = now
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id, user.org_id, user.role, settings)
    return {"token": token, "user": _user_out(user, settings).model_dump()}
