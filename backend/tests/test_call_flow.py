"""/api/test-call resolves an agent version, stamps the call, returns room name."""
from __future__ import annotations

from typing import Any

import pytest

from app.models import Agent, AgentVersion, Call, DomainConfig, Organization
from conftest import auth_headers, register

TO = "+919391470646"


def _seed_domain_and_agent(db: Any, org_id: int, dc_name: str = "call-flow-test") -> tuple[int, int]:
    """Seed a minimal domain config + agent version; return (domain_config_id, version_id)."""
    dc = DomainConfig(name=dc_name, version=1)
    db.add(dc)
    db.flush()
    agent = Agent(org_id=org_id, name="Phone Agent", description="", status="draft")
    db.add(agent)
    db.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="You call parents about absences.",
        company_context={},
        question_flow=[{"question": "Why absent?"}],
        extraction_schema={"reason_for_absence": {"type": "string", "validation": "required"}},
        disclosure_script="Hello, this is an automated call.",
        escalation_rules=[],
        voice_settings={},
    )
    db.add(version)
    db.commit()
    return dc.id, version.id


@pytest.fixture()
def allowlisted(app):
    """Consent enforcement is ON by default — allowlist the test number."""
    app.state.settings.test_phone_numbers = TO


class FakeTelephony:
    def place_call(self, to: str, call_id: int) -> str:
        return f"CAfake{call_id}"


@pytest.fixture()
def fake_telephony(monkeypatch):
    monkeypatch.setattr(
        "app.routers.test_call._get_telephony", lambda request: FakeTelephony()
    )


def _post(client: Any, token: str, payload: dict[str, Any]):  # type: ignore[no-untyped-def]
    return client.post("/api/test-call", headers=auth_headers(token), json=payload)


def test_requires_auth(client):
    assert client.post("/api/test-call", json={}).status_code == 401


def test_unknown_agent_version_422(client, session_factory, allowlisted):
    token, user = register(client)
    with session_factory() as db:
        dc_id, _version_id = _seed_domain_and_agent(db, user["org_id"])
    resp = _post(
        client,
        token,
        {"to": TO, "domain_config_id": dc_id, "agent_version_id": 99999},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "unknown agent_version_id"


def test_foreign_org_agent_version_422(client, session_factory, allowlisted):
    token, user = register(client)
    with session_factory() as db:
        dc_id, _own_version_id = _seed_domain_and_agent(db, user["org_id"])
        foreign_org = Organization(name="Foreign Org", slug="foreign-org")
        db.add(foreign_org)
        db.flush()
        _, foreign_version_id = _seed_domain_and_agent(
            db, foreign_org.id, dc_name="call-flow-foreign"
        )
    resp = _post(
        client,
        token,
        {
            "to": TO,
            "domain_config_id": dc_id,
            "agent_version_id": foreign_version_id,
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "unknown agent_version_id"


def test_happy_path_stamps_version_and_room(
    client, session_factory, fake_telephony, allowlisted
):
    token, user = register(client)
    with session_factory() as db:
        dc_id, version_id = _seed_domain_and_agent(db, user["org_id"])
    resp = _post(
        client,
        token,
        {"to": TO, "domain_config_id": dc_id, "agent_version_id": version_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["room_name"] == f"phone-{body['call_id']}"
    with session_factory() as db:
        call = db.get(Call, body["call_id"])
        assert call.agent_version_id == version_id

def test_contact_details_reach_contact_custom_fields(
    client, session_factory, fake_telephony, allowlisted
):
    """The agent must KNOW whom it is calling: per-contact details supplied in
    the test-call request are stored on the contact and reach the room metadata
    path (custom_fields -> CALLER CONTEXT)."""
    token, user = register(client)
    with session_factory() as db:
        dc_id, version_id = _seed_domain_and_agent(db, user["org_id"])
    resp = _post(
        client,
        token,
        {
            "to": TO,
            "domain_config_id": dc_id,
            "agent_version_id": version_id,
            "contact": {
                "student_name": "Abhiram",
                "parent_name": "Suresh",
                "class_section": "10-B",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        from app.models import Contact

        contact = (
            db.query(Contact).filter(Contact.phone == TO).one()
        )
        fields = contact.custom_fields or {}
        assert fields["student_name"] == "Abhiram"
        assert fields["parent_name"] == "Suresh"
        assert fields["class_section"] == "10-B"

def test_latest_org_version_used_when_omitted(
    client, session_factory, fake_telephony, allowlisted
):
    token, user = register(client)
    with session_factory() as db:
        dc_id, version_id = _seed_domain_and_agent(db, user["org_id"])
    resp = _post(client, token, {"to": TO, "domain_config_id": dc_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    with session_factory() as db:
        call = db.get(Call, body["call_id"])
        assert call.agent_version_id == version_id
