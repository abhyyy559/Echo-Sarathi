"""Contact-aware test calls: version pin + lead card + derived domain config."""
from __future__ import annotations

from typing import Any

from conftest import auth_headers, make_settings, register
from test_agents import version_payload
from test_playground import _make_agent_and_version


def _test_number_app(session_factory):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from app.main import create_app

    fresh = create_app(
        make_settings(test_phone_numbers="+919812345601")
    )
    fresh.state.session_factory = session_factory
    return fresh


def test_test_call_forwards_version_and_contact(client, session_factory):
    from fastapi.testclient import TestClient

    from app.models import Call, Contact

    token, user = register(client)
    ids = _make_agent_and_version(client, token)
    version_id = ids["version"]["id"]
    with TestClient(_test_number_app(session_factory)) as numbered:
        resp = numbered.post(
            "/api/test-call",
            json={
                "to": "+919812345601",
                "agent_version_id": version_id,
                "contact": {"student_name": "Aarav Kumar", "parent_name": "Suresh Kumar"},
            },
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider_call_id"].startswith("CAfake")
    with session_factory() as db:
        call = db.get(Call, body["call_id"])
        assert call.agent_version_id == version_id
        contact = db.get(Contact, call.contact_id)
        assert contact.custom_fields["student_name"] == "Aarav Kumar"
        assert contact.custom_fields["parent_name"] == "Suresh Kumar"


def test_test_call_derives_domain_config_when_omitted(client, session_factory):
    from fastapi.testclient import TestClient

    from app.models import Call, DomainConfig

    token, _user = register(client)
    ids = _make_agent_and_version(client, token)
    with TestClient(_test_number_app(session_factory)) as numbered:
        resp = numbered.post(
            "/api/test-call",
            json={"to": "+919812345601", "agent_version_id": ids["version"]["id"]},
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        call = db.get(Call, resp.json()["call_id"])
        derived = db.get(DomainConfig, call.campaign.domain_config_id)
        assert derived is not None
        assert derived.name.startswith(f"agent-{ids['agent']['id']}-")
        assert "system_prompt" in (derived.config or {})


def test_test_call_explicit_to_needs_no_allowlist_entry(client, session_factory):
    """An explicitly requested number works with an empty TEST_PHONE_NUMBERS."""
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.main import create_app
    from app.models import Contact

    token, _user = register(client)
    ids = _make_agent_and_version(client, token)
    fresh = create_app(make_settings(test_phone_numbers=""))
    fresh.state.session_factory = session_factory
    with TestClient(fresh) as bare:
        resp = bare.post(
            "/api/test-call",
            json={"to": "+919812345602", "agent_version_id": ids["version"]["id"]},
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        contact = db.scalar(
            select(Contact).where(Contact.phone == "+919812345602")
        )
        assert contact is not None
        assert contact.consent is True
        assert contact.consent_source == "manual_test_call"
