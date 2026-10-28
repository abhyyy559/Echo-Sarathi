"""Agents & immutable versions (frozen contract §4).

- ``GET/POST /api/agents``, ``GET/PATCH/DELETE /api/agents/{id}``
  (DELETE = soft archive; role-gated to owner/admin)
- ``POST /api/agents/{id}/versions`` validates via domain_config_schema rules
  and appends an immutable row, advancing ``agent.current_version_id``
- ``GET /api/agents/{id}/versions``, ``GET /api/agent-versions/{vid}``

Tenancy: every query is filtered by the caller's org; foreign ids return 404.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_org_or_404, require_roles
from app.models import AGENT_STATUSES, Agent, AgentVersion, DomainConfig, User
from app.services import plans
from app.services.token_substitution import unfilled_enterprise_keys
from domain_config_schema import validate_agent_version_payload

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Versions are also reachable directly by id (voice-agent + frontend use this).
agent_versions_router = APIRouter(prefix="/api/agent-versions", tags=["agents"])

# Role presets ("default prompts"): ready-made agent configs users pick in the
# builder and edit. Kept as versioned JSON files next to the domain configs so
# they are data, not code (CLAUDE.md convention).
# agents.py lives at backend/app/routers/ -> parents[3] is the project root.
PRESETS_DIR = Path(__file__).resolve().parents[3] / "domain-configs" / "presets"


# --- request/response schemas ---------------------------------------------------


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class AgentPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = None


class AgentOut(BaseModel):
    id: int
    org_id: int
    name: str
    description: str
    status: str
    current_version_id: Optional[int]
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None


class AgentVersionOut(BaseModel):
    id: int
    agent_id: int
    version: int
    system_prompt: str
    company_context: dict[str, Any]
    question_flow: list[Any]
    extraction_schema: dict[str, Any]
    disclosure_script: str
    escalation_rules: list[Any]
    voice_settings: dict[str, Any]
    created_by: Optional[int] = None
    created_at: Optional[Any] = None


# --- role presets ("default prompts") -------------------------------------------


class PresetOut(BaseModel):
    preset_id: str
    name: str
    description: str
    version_payload: dict[str, Any]


@router.get("/presets", response_model=list[PresetOut])
def list_presets(user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Ready-made role presets ("default prompts") for the agent builder.

    Each preset is a complete, validated AgentVersion payload, so the frontend
    can prefill the entire builder from one object. Route ordering matters:
    FastAPI matches this literal path before ``/{agent_id}`` routes below.
    """
    presets: list[dict[str, Any]] = []
    if PRESETS_DIR.is_dir():
        for path in sorted(PRESETS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Validate the embedded payload so a broken preset file fails
                # loudly here instead of breaking the builder at save time.
                validate_agent_version_payload(data.get("version_payload") or {})
            except Exception as exc:  # noqa: BLE001 - skip malformed, don't 500
                presets.append(
                    {
                        "preset_id": path.stem,
                        "name": path.stem,
                        "description": f"preset unavailable: {exc}",
                        "version_payload": {},
                    }
                )
                continue
            presets.append(
                {
                    "preset_id": data.get("preset_id") or path.stem,
                    "name": data.get("name") or path.stem,
                    "description": data.get("description") or "",
                    "version_payload": data.get("version_payload") or {},
                }
            )
    return presets


def _agent_out(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "org_id": agent.org_id,
        "name": agent.name,
        "description": agent.description,
        "status": agent.status,
        "current_version_id": agent.current_version_id,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }


def _version_out(version: AgentVersion) -> dict[str, Any]:
    """Single serializer shared by create/list/detail so snapshots compare equal."""
    return {
        "id": version.id,
        "agent_id": version.agent_id,
        "version": version.version,
        "system_prompt": version.system_prompt,
        "company_context": version.company_context or {},
        "question_flow": version.question_flow or [],
        "extraction_schema": version.extraction_schema or {},
        "disclosure_script": version.disclosure_script,
        "escalation_rules": version.escalation_rules or [],
        "voice_settings": version.voice_settings or {},
        "created_by": version.created_by,
        "created_at": version.created_at,
    }


def _get_own_agent(db: Session, agent_id: int, user: User) -> Agent:
    return get_org_or_404(db, Agent, agent_id, user.org_id)


# --- agent CRUD ------------------------------------------------------------------


@router.get("", response_model=list[AgentOut])
def list_agents(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    agents = db.scalars(
        select(Agent)
        .where(Agent.org_id == user.org_id, Agent.status != "archived")
        .order_by(Agent.id.desc())
    ).all()
    return [_agent_out(agent) for agent in agents]


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(
    payload: AgentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    plan, _subscription = plans.org_plan(db, user.org_id)
    active = db.scalar(
        select(func.count(Agent.id)).where(
            Agent.org_id == user.org_id, Agent.status != "archived"
        )
    )
    limit = int(plan["max_agents"])
    if int(active or 0) >= limit:
        raise HTTPException(
            status_code=403,
            detail=plans.limit_message(plan, "agents", limit),
        )
    agent = Agent(
        org_id=user.org_id,
        name=payload.name.strip(),
        description=payload.description,
        status="draft",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _agent_out(agent)


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _agent_out(_get_own_agent(db, agent_id, user))


@router.patch("/{agent_id}", response_model=AgentOut)
def patch_agent(
    agent_id: int,
    payload: AgentPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Meta-only update (name/description/status). Version content is immutable."""
    agent = _get_own_agent(db, agent_id, user)
    if payload.name is not None:
        agent.name = payload.name.strip()
    if payload.description is not None:
        agent.description = payload.description
    if payload.status is not None:
        if payload.status not in AGENT_STATUSES:
            raise HTTPException(status_code=422, detail=f"invalid status: {payload.status}")
        agent.status = payload.status
    db.commit()
    db.refresh(agent)
    return _agent_out(agent)


@router.delete("/{agent_id}")
def archive_agent(
    agent_id: int,
    user: User = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Soft delete: status -> archived. Hidden from lists; versions remain queryable."""
    agent = _get_own_agent(db, agent_id, user)
    agent.status = "archived"
    db.commit()
    return {"ok": True, "id": agent.id, "status": agent.status}


# --- versions ----------------------------------------------------------------------


@router.post("/{agent_id}/versions", response_model=AgentVersionOut, status_code=201)
def create_version(
    agent_id: int,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Validate a config snapshot and store it as an immutable new version.

    Validation reuses the legacy ``domain_config_schema`` structural rules via
    ``validate_agent_version_payload`` — pydantic errors surface as 422 with
    field-level locations.
    """
    try:
        validated = validate_agent_version_payload(payload)
    except Exception as exc:  # pydantic ValidationError -> field-level 422
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # A preset ships "[Company Name]" for the author to replace. Saving it
    # as-is would launch an agent that represents no one (or, worse, the
    # account's own organization — a college's feedback agent answering as
    # the college). Institution is exempt: absence agents may inherit it.
    unfilled = unfilled_enterprise_keys(validated.company_context)
    if unfilled:
        raise HTTPException(
            status_code=422,
            detail=(
                "Fill in the enterprise name before saving: "
                f"{', '.join(unfilled)} still holds a placeholder. This agent "
                "belongs to its own company, not to the account's organization."
            ),
        )

    agent = _get_own_agent(db, agent_id, user)
    latest = db.scalar(
        select(AgentVersion.version)
        .where(AgentVersion.agent_id == agent.id)
        .order_by(AgentVersion.version.desc())
        .limit(1)
    )
    next_version = (latest or 0) + 1
    version = AgentVersion(
        agent_id=agent.id,
        version=next_version,
        system_prompt=validated.system_prompt,
        company_context=validated.company_context,
        question_flow=[step.model_dump() for step in validated.question_flow],
        extraction_schema={
            name: field.model_dump() for name, field in validated.extraction_schema.items()
        },
        disclosure_script=validated.disclosure_script,
        escalation_rules=[
            rule if isinstance(rule, str) else rule.model_dump()
            for rule in validated.escalation_rules
        ],
        voice_settings=validated.voice_settings.model_dump(),
        created_by=user.id,
    )
    db.add(version)
    db.flush()
    agent.current_version_id = version.id
    db.commit()
    db.refresh(version)
    return _version_out(version)


@router.get("/{agent_id}/versions", response_model=list[AgentVersionOut])
def list_versions(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    agent = _get_own_agent(db, agent_id, user)  # archived stays queryable
    versions = db.scalars(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent.id)
        .order_by(AgentVersion.version)
    ).all()
    return [_version_out(v) for v in versions]


@agent_versions_router.get("/{version_id}", response_model=AgentVersionOut)
def get_version(
    version_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    version = db.get(AgentVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="not found")
    # Org check through the parent agent (404 on foreign org — no leak).
    get_org_or_404(db, Agent, version.agent_id, user.org_id)
    return _version_out(version)


def ensure_domain_config(db: Session, agent: Agent, version: AgentVersion) -> DomainConfig:
    """Find-or-create the legacy DomainConfig row anchoring an agent's phone path.

    The voice brain is version-based, but campaigns and /api/test-call still
    carry a ``domain_config_id`` FK. ``DomainConfig.name`` is globally unique,
    so the auto row is namespaced per agent and never collides across orgs.
    """
    wanted = f"agent-{agent.id}-phone"
    existing = db.scalar(select(DomainConfig).where(DomainConfig.name == wanted))
    if existing is not None:
        return existing
    row = DomainConfig(
        name=wanted,
        display_name=agent.name,
        config={
            "domain_id": wanted,
            "name": agent.name,
            "version": version.version,
            "system_prompt": version.system_prompt,
            "mandatory_disclosure": version.disclosure_script,
            "question_flow": version.question_flow or [],
            "extraction_schema": version.extraction_schema or {},
            "escalation_rules": version.escalation_rules or [],
            "voice_settings": version.voice_settings or {},
        },
    )
    db.add(row)
    db.flush()
    return row
