"""Demo seed script — bootstraps a clean beta tenant.

Usage (from backend/):
    python scripts/seed_demo.py                      # create demo login (idempotent)
    python scripts/seed_demo.py --purge-sample-data  # wipe demo org's campaigns/contacts/calls

Creates (idempotently):
- organization "CMR College of Engineering & Technology" (slug cmr-cet)
- owner user from DEMO_EMAIL / DEMO_PASSWORD (falls back to
  demo@example.com / demo1234 for local development only)
- starter agents "Priya" (English) and "Sahithi" (Telugu), v1 built from
  domain-configs/absent-student.json and the Telugu preset, plus "Bunty"
  (prankster) and "Anu" (sweet check-in) from their presets

Beta policy: NO campaigns, NO sample contacts, NO calls are created — testers
start from clean empty states and bring their own data. The starter agent is
kept so the playground is usable immediately.

The seed never places calls and contains no secrets.
"""
from __future__ import annotations

import argparse
import json
import os
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

DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@example.com").strip().lower()
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo1234")

#: Institution every starter agent speaks for. The org row and each agent
#: version's company_context must agree on it — a preset ships the unfilled
#: "[Institution Name]" token for a tenant to fill in, and storing that token
#: made the demo agent say "I am from ." ("నేను నుండి AI అసిస్టెంట్") on every
#: call, because an unfilled token is not a name.
DEMO_INSTITUTION = "CMR College of Engineering & Technology"


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


def _load_preset(filename: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "domain-configs" / "presets" / filename
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_telugu_preset() -> dict[str, Any]:
    return _load_preset("absent-student-followup-telugu.json")


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
        "company_context": {"institution": DEMO_INSTITUTION},
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


def _create_agent_version(
    db: Any,
    *,
    org_id: int,
    owner_id: int,
    name: str,
    description: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Create one agent + its v1 version. ``None`` when the name already exists.

    Idempotent by (org, name) so re-running the seed on an existing demo tenant
    adds only the starter agents it is missing — which is how a NEW starter
    agent (the Telugu variant) reaches the demo account on deploy instead of
    requiring a manual purge.
    """
    existing = db.scalar(
        select(Agent).where(Agent.org_id == org_id, Agent.name == name)
    )
    if existing is not None:
        return None

    validated = validate_agent_version_payload(payload)
    agent = Agent(org_id=org_id, name=name, description=description, status="draft")
    db.add(agent)
    db.flush()

    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt=validated.system_prompt,
        company_context=validated.company_context,
        question_flow=[step.model_dump() for step in validated.question_flow],
        extraction_schema={
            field_name: field.model_dump()
            for field_name, field in validated.extraction_schema.items()
        },
        disclosure_script=validated.disclosure_script,
        escalation_rules=[
            rule if isinstance(rule, str) else rule.model_dump()
            for rule in validated.escalation_rules
        ],
        voice_settings=validated.voice_settings.model_dump(),
        created_by=owner_id,
    )
    db.add(version)
    db.flush()
    agent.current_version_id = version.id
    return {"agent_id": agent.id, "version_id": version.id, "name": name}


def _ensure_starter_agents(
    db: Any, *, org_id: int, owner_id: int
) -> dict[str, dict[str, Any]]:
    """Create every starter agent the demo org is missing.

    Keyed by a stable role ("english"/"telugu") rather than list position, so
    the caller can report the primary agent without guessing which one was new.
    """
    config = _load_absent_student_config()
    preset = _load_telugu_preset()
    prankster = _load_preset("prankster.json")
    sweet_checkin = _load_preset("sweet-checkin.json")
    _rename_legacy_starters(db, org_id)
    specs = {
        "english": (
            "Priya",
            "Attendance follow-up specialist · calls guardians of absent students.",
            _version_payload_from_config(config),
        ),
        "telugu": (
            "Sahithi",
            "Attendance follow-up specialist (Telugu) · calls guardians of absent students.",
            {
                **preset["version_payload"],
                # Override the preset's "[Institution Name]" token: the demo
                # tenant has a real institution name (see DEMO_INSTITUTION).
                "company_context": {"institution": DEMO_INSTITUTION},
            },
        ),
        # Both declare their own brand in company_context, so neither speaks
        # the demo tenant's college name on a call.
        "prankster": (
            "Bunty",
            "Prank caller · one harmless, silly bit for a friend, with a clear yes first.",
            prankster["version_payload"],
        ),
        "sweet_checkin": (
            "Anu",
            "Warm check-in companion · a short, sweet call to see how someone's day is going.",
            sweet_checkin["version_payload"],
        ),
    }
    created: dict[str, dict[str, Any]] = {}
    for role, (name, description, payload) in specs.items():
        entry = _create_agent_version(
            db,
            org_id=org_id,
            owner_id=owner_id,
            name=name,
            description=description,
            payload=payload,
        )
        if entry is not None:
            created[role] = entry
    return created


#: Starter agents used to be named after their job ("Absent Student Follow-up").
#: Callers now hear a person's name, so an existing demo tenant is renamed in
#: place instead of gaining a duplicate second pair of starters.
_LEGACY_STARTER_NAMES = {
    "Absent Student Follow-up": "Priya",
    "Absent Student Follow-up (Telugu)": "Sahithi",
}


def _rename_legacy_starters(db: Any, org_id: int) -> None:
    for legacy, persona in _LEGACY_STARTER_NAMES.items():
        agent = db.scalar(
            select(Agent).where(Agent.org_id == org_id, Agent.name == legacy)
        )
        if agent is None:
            continue
        clash = db.scalar(
            select(Agent).where(Agent.org_id == org_id, Agent.name == persona)
        )
        if clash is None:
            agent.name = persona
    # Sessions run with autoflush=False, so the rename must be flushed before
    # the starter lookup below or it recreates the persona as a duplicate.
    db.flush()


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
            # An already-provisioned demo tenant still needs any starter agent
            # it does not have yet, or a new one never reaches the tester.
            added = _ensure_starter_agents(
                db, org_id=existing.org_id, owner_id=existing.id
            )
            # Always commit: renaming a legacy starter also lands here with
            # nothing "added".
            db.commit()
            return {
                "status": "already_seeded",
                "email": DEMO_EMAIL,
                "agents_added": sorted(entry["name"] for entry in added.values()),
            }

        org = Organization(name=DEMO_INSTITUTION, slug="cmr-cet")
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

        agents = _ensure_starter_agents(db, org_id=org.id, owner_id=owner.id)
        db.commit()

        english = agents.get("english", {})
        return {
            "status": "seeded",
            "org_slug": org.slug,
            "org_id": org.id,
            "user_id": owner.id,
            "agent_id": english.get("agent_id"),
            "version_id": english.get("version_id"),
            "agents": sorted(entry["name"] for entry in agents.values()),
        }


def reset_demo_password(database_url: str | None = None) -> dict[str, Any]:
    """Set the demo user's password to the current ``DEMO_PASSWORD``.

    ``seed_demo`` is idempotent and never touches an existing user, so this is
    the supported way to rotate the password on an already-seeded deployment.
    """
    settings = get_settings()
    if database_url:
        settings = settings.model_copy(update={"database_url": database_url})
    engine, session_factory = init_db(settings)

    inspector = inspect(engine)
    if not inspector.has_table("organizations"):
        return {"status": "no_schema", "email": DEMO_EMAIL}

    with session_factory() as db:
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            return {"status": "no_demo_tenant", "email": DEMO_EMAIL}
        user.password_hash = hash_password(DEMO_PASSWORD)
        db.commit()
        return {"status": "password_reset", "email": DEMO_EMAIL}


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
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Set the demo user's password to $DEMO_PASSWORD (no other changes).",
    )
    args = parser.parse_args()

    if args.reset_password:
        result = reset_demo_password()
        if result["status"] == "password_reset":
            print(f"Demo password reset for {result['email']}.")
        elif result["status"] == "no_demo_tenant":
            print(f"No demo tenant found ({result['email']}) — run without flags first.")
        else:
            print("Schema missing — run the migrations first.")
        return

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
        added = result.get("agents_added") or []
        if added:
            print(f"Demo tenant already exists ({DEMO_EMAIL}); added starter agents:")
            for name in added:
                print(f"  + {name}")
        else:
            print(f"Demo tenant already exists ({DEMO_EMAIL}) — nothing to do.")
        return
    print("Demo tenant seeded:")
    print(f"  login    : {DEMO_EMAIL} (password from DEMO_PASSWORD, or the demo default)")
    print(f"  org_id   : {result['org_id']}")
    print(f"  agent_id : {result['agent_id']} (version {result['version_id']})")
    for name in result.get("agents") or []:
        print(f"  agent    : {name}")


if __name__ == "__main__":
    main()
