"""Password hashing (bcrypt) and JWT issuing/verification.

Tokens are cookie-less bearer JWTs: ``{"sub": "<user_id>", "org": "<org_id>",
"role": "owner|admin|member", "exp": <epoch>}`` signed HS256 with
``settings.jwt_secret``.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import Settings


class InvalidTokenError(Exception):
    """Raised when a bearer token is missing/expired/invalid."""


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (salt embedded in the hash)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time bcrypt verification; False on any mismatch/format error."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def hash_token(raw: str) -> str:
    """SHA-256 of a one-time token; only the hash is ever persisted."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str]:
    """Return ``(raw_token, token_hash)`` for invite/reset links."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def create_access_token(user_id: int, org_id: int, role: str, settings: Settings) -> str:
    """Sign a bearer JWT for the given user."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(org_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode+verify a bearer JWT; raises InvalidTokenError on any problem."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if not isinstance(payload.get("sub"), str):
        raise InvalidTokenError("token has no subject")
    return payload
