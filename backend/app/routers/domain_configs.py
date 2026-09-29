"""Domain config listing + manual re-sync from /domain-configs."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.domain_config_service import sync_domain_configs
from app.models import DomainConfig, User
from app.schemas import DomainConfigOut, DomainConfigSyncOut

router = APIRouter(prefix="/api/domain-configs", tags=["domain-configs"])


@router.get("", response_model=list[DomainConfigOut])
def list_domain_configs(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    configs = db.scalars(select(DomainConfig).order_by(DomainConfig.name)).all()
    return [
        {"id": c.id, "name": c.name, "display_name": c.display_name, "version": c.version}
        for c in configs
    ]


@router.post("/sync", response_model=DomainConfigSyncOut)
def sync_configs(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings = request.app.state.settings
    names = sync_domain_configs(db, settings.domain_configs_dir)
    return {"synced": len(names), "names": names}
