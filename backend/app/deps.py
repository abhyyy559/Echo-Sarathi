"""Shared FastAPI dependencies: current-user resolution and tenancy guards.

Tenancy rule (frozen contract §4): every query is filtered by the caller's
``user.org_id``; a foreign id yields **404** — never 403 — so the existence of
other orgs' resources does not leak.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import InvalidTokenError, decode_access_token
from app.database import get_db
from app.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the ``Authorization: Bearer <jwt>`` user; 401 on any failure.

    The token must carry an ``org`` claim matching the user's current org —
    tokens without org context are rejected so stale/foreign credentials can
    never resolve.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="not authenticated")
    settings = request.app.state.settings
    try:
        payload = decode_access_token(credentials.credentials, settings)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid or expired token") from exc
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    org_claim = payload.get("org")
    try:
        org_matches = org_claim is not None and int(org_claim) == user.org_id
    except (TypeError, ValueError):
        org_matches = False
    if not org_matches:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return user


def require_roles(*roles: str):
    """Dependency factory: allow only users whose role is in ``roles``."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return checker


def require_platform_admin(
    request: Request, user: User = Depends(get_current_user)
) -> User:
    """Allow only emails listed in ``PLATFORM_ADMIN_EMAILS`` (empty = nobody)."""
    allowed = request.app.state.settings.platform_admin_email_list
    if user.email.strip().lower() not in allowed:
        raise HTTPException(status_code=403, detail="platform admin only")
    return user


def get_org_or_404(db: Session, model: Any, entity_id: int, org_id: int) -> Any:
    """Fetch an org-scoped entity by primary key.

    Returns the row when it belongs to ``org_id``; raises 404 otherwise
    (including when the row exists under a different org).
    """
    entity = db.get(model, entity_id)
    if entity is None or getattr(entity, "org_id", None) != org_id:
        raise HTTPException(status_code=404, detail="not found")
    return entity
