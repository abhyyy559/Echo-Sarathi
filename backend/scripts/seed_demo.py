"""Demo seed script — bootstraps a clean beta tenant.

Usage (from backend/):
    python scripts/seed_demo.py                      # create demo login (idempotent)
    python scripts/seed_demo.py --purge-sample-data  # wipe demo org's campaigns/contacts/calls

Creates (idempotently):
- organization "CMR College of Engineering & Technology" (slug cmr-cet)
- owner user demo@example.com / demo1234
- starter agent "Absent Student Follow-up" with v1 built from
  domain-configs/absent-student.json

Beta policy: NO campaigns, NO sample contacts, NO calls are created — testers
start from clean empty states and bring their own data. The starter agent is
kept so the playground is usable immediately.

The seed never places calls and contains no secrets.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, inspect, select  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import init_db  # noqa: E402
from app.models import Agent, AgentVersion, Campaign, Call, Contact, Organization, User  # noqa: E402
from domain_config_schema import validate_agent_version_payload  # noqa: E402

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"


def _alembic_upgrade_head(database_url: str) -> None:
    """Apply migrations programmatically when the schema is missing."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def _load_absent_student_config() -> dict[str, Any]:
    path = PROJECT_ROOT / "domain-configs" / "absent-student.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _version_payload_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Map the legacy domain-config file onto the AgentVersion payload shape."""
    # The file's voice_settings (language, voices, known_context_keys, ...)
    # flow straight into the version: the JSON file stays the source of truth
    # for fresh seeds. VoiceSettings ignores nothing (extra="allow").
    voice_settings = dict(config.get("voice_settings") or {})
    if "known_context_keys" in config and "known_context_keys" not in voice_settings:
        voice_settings["known_context_keys"] = config["known_context_keys"]
    return {
        "system_prompt": config["system_prompt"],
        "company_context": {"institution": "CMR College of Engineering & Technology"},
        "question_flow": config["question_flow"],
        "extraction_schema": config["extraction_schema"],
        "disclosure_script": config["mandatory_disclosure"],
        "escalation_rules": config["escalation_rules"],
        "voice_settings": voice_settings or {"voice_id": "default", "speed": 1.0},
    }


def _demo_org_id(db: Any) -> int | None:
    """Resolve the demo org id from the demo owner user (None if absent)."""
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    return user.org_id if user is not None else None


def seed_demo(database_url: str | None = None) -> dict[str, Any]:
    """Create the demo tenant; returns a summary dict. Safe to run repeatedly."""
    settings = get_settings()
    if database_url:
        settings = settings.model_copy(update={"database_url": database_url})
    engine, session_factory = init_db(settings)

    inspector = inspect(engine)
    if not inspector.has_table("organizations"):
        _alembic_upgrade_head(settings.database_url)

    with session_factory() as db:
        existing = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing is not None:
            return {"status": "already_seeded", "email": DEMO_EMAIL}

        org = Organization(name="CMR College of Engineering & Technology", slug="cmr-cet")
        db.add(org)
        db.flush()

        owner = User(
            org_id=org.id,
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            role="owner",
        )
        db.add(owner)
        db.flush()

        config = _load_absent_student_config()
        payload = _version_payload_from_config(config)
        validated = validate_agent_version_payload(payload)

        agent = Agent(
            org_id=org.id,
            name=config["display_name"] if "display_name" in config else config["name"],
            description="Starter agent — absent student follow-up calls.",
            status="draft",
        )
        db.add(agent)
        db.flush()

        version = AgentVersion(
            agent_id=agent.id,
            version=1,
            system_prompt=validated.system_prompt,
            company_context=validated.company_context,
            question_flow=[step.model_dump() for step in validated.question_flow],
            extraction_schema={
                name: field.model_dump()
                for name, field in validated.extraction_schema.items()
            },
            disclosure_script=validated.disclosure_script,
            escalation_rules=[
                rule if isinstance(rule, str) else rule.model_dump()
                for rule in validated.escalation_rules
            ],
            voice_settings=validated.voice_settings.model_dump(),
            created_by=owner.id,
        )
        db.add(version)
        db.flush()
        agent.current_version_id = version.id

        db.commit()

        return {
            "status": "seeded",
            "org_slug": org.slug,
            "org_id": org.id,
            "user_id": owner.id,
            "agent_id": agent.id,
            "version_id": version.id,
        }


def purge_sample_data(database_url: str | None = None) -> dict[str, Any]:
    """Wipe every campaign/contact/call row in the demo org (children cascade).

    Keeps: organizations, users, agents + agent versions. Removes: campaigns,
    contacts, calls (with their transcripts, extracted fields and events) —
    i.e. everything a beta tester should not inherit from earlier demos.
    """
    settings = get_settings()
    if database_url:
        settings = settings.model_copy(update={"database_url": database_url})
    engine, session_factory = init_db(settings)

    inspector = inspect(engine)
    if not inspector.has_table("organizations"):
        _alembic_upgrade_head(settings.database_url)

    with session_factory() as db:
        org_id = _demo_org_id(db)
        if org_id is None:
            return {"status": "no_demo_tenant", "email": DEMO_EMAIL}

        call_ids = db.scalars(
            select(Call.id).where(Call.org_id == org_id)
        ).all()
        counts: dict[str, int] = {}
        counts["calls"] = 0
        for call_id in call_ids:
            call = db.get(Call, call_id)
            if call is not None:
                db.delete(call)  # ORM cascades events/transcripts/extracted_fields
                counts["calls"] += 1
        db.flush()  # call deletes must hit the DB before campaigns (FK order)
        counts["contacts"] = db.execute(
            delete(Contact).where(Contact.org_id == org_id)
        ).rowcount
        counts["campaigns"] = db.execute(
            delete(Campaign).where(Campaign.org_id == org_id)
        ).rowcount
        db.commit()
        return {"status": "purged", "org_id": org_id, **counts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--purge-sample-data",
        action="store_true",
        help="Delete all demo-org campaigns/contacts/calls instead of seeding.",
    )
    args = parser.parse_args()

    if args.purge_sample_data:
        result = purge_sample_data()
        if result["status"] == "no_demo_tenant":
            print(f"No demo tenant found ({DEMO_EMAIL}) — nothing to purge.")
            return
        print("Demo org sample data purged:")
        print(f"  campaigns: {result['campaigns']}")
        print(f"  contacts : {result['contacts']}")
        print(f"  calls    : {result['calls']} (transcripts/events/fields cascaded)")
        return

    result = seed_demo()
    if result["status"] == "already_seeded":
        print(f"Demo tenant already exists ({DEMO_EMAIL}) — nothing to do.")
        return
    print("Demo tenant seeded:")
    print(f"  login    : {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"  org_id   : {result['org_id']}")
    print(f"  agent_id : {result['agent_id']} (version {result['version_id']})")


if __name__ == "__main__":
    main()
