"""Admin operations: manual retention trigger."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import User
from app.schemas import RetentionRunOut
from app.services.retention import run_retention

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/retention/run", response_model=RetentionRunOut)
def run_retention_now(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("owner", "admin")),
) -> dict[str, Any]:
    settings = request.app.state.settings
    return run_retention(db, settings)
