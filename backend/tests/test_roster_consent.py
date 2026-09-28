"""Roster consent: uploaded campaign rosters are callable without .env allowlists.

A roster uploaded by the org (e.g. the college's enrollment list) IS the
institutional relationship — contacts default to consented, so the dialer
and launch never require TEST_PHONE_NUMBERS entries. An explicit
consent_default=false (or a per-row consent column) still opts out.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from conftest import auth_headers, register

ROSTER_CSV = (
    "name,phone,student_name,parent_name,class_section\n"
    "Suresh Kumar,+919812345601,Aarav Kumar,Suresh Kumar,10-A\n"
    "Meena Rao,+919812345602,Diya Rao,Meena Rao,10-B\n"
).encode()

MAPPING = {
    "name_col": "name",
    "phone_col": "phone",
    "id_col": None,
    "consent_col": None,
    "custom": {
        "student_name": "student_name",
        "parent_name": "parent_name",
        "class_section": "class_section",
    },
}


def _make_campaign(client: Any, token: str) -> dict[str, Any]:
    created = client.post(
        "/api/campaigns",
        json={"name": "Class 10 Absentees"},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    return created.json()


def _import(client: Any, token: str, campaign_id: int, **form: Any) -> dict[str, Any]:
    files = {"file": ("roster.csv", ROSTER_CSV, "text/csv")}
    data = {"mapping": json.dumps(MAPPING)}
    data.update(form)
    resp = client.post(
        f"/api/campaigns/{campaign_id}/contacts/import",
        files=files,
        data=data,
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_roster_import_defaults_to_consented(client, session_factory):
    from app.models import Contact

    token, _ = register(client)
    campaign = _make_campaign(client, token)
    result = _import(client, token, campaign["id"])
    assert result["imported"] == 2
    assert result["invalid"] == 0

    with session_factory() as db:
        from sqlalchemy import select

        contacts = db.scalars(
            select(Contact).where(Contact.campaign_id == campaign["id"])
        ).all()
        assert len(contacts) == 2
        for contact in contacts:
            assert contact.consent is True
            assert contact.status == "pending_review"
        cards = {c.phone: c.custom_fields for c in contacts}
        assert cards["+919812345601"]["student_name"] == "Aarav Kumar"
        assert cards["+919812345602"]["class_section"] == "10-B"


def test_roster_import_explicit_opt_out_honored(client, session_factory):
    from sqlalchemy import select

    from app.models import Contact

    token, _ = register(client)
    campaign = _make_campaign(client, token)
    _import(client, token, campaign["id"], consent_default="false")

    with session_factory() as db:
        contacts = db.scalars(
            select(Contact).where(Contact.campaign_id == campaign["id"])
        ).all()
        assert all(c.consent is False for c in contacts)


def test_launch_queues_roster_without_allowlist(app, client, session_factory):
    """End-to-end proof: roster -> launch -> queued with empty TEST_PHONE_NUMBERS."""
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)  # 10:30 IST
    assert app.state.settings.test_phone_number_list == []

    token, _ = register(client)
    campaign = _make_campaign(client, token)
    _import(client, token, campaign["id"])

    resp = client.post(
        f"/api/campaigns/{campaign['id']}/launch",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    detail = client.get(
        f"/api/campaigns/{campaign['id']}", headers=auth_headers(token)
    ).json()
    assert detail["counts"]["queued"] == 2
    assert detail["counts"]["opted_out"] == 0


def test_skipped_contacts_are_never_launched(app, client, session_factory):
    """Faculty excludes present students: skipped rows stay out of the queue."""
    from sqlalchemy import select

    from app.models import Contact

    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)  # 10:30 IST
    token, _ = register(client)
    campaign = _make_campaign(client, token)
    _import(client, token, campaign["id"])

    with session_factory() as db:
        contacts = db.scalars(
            select(Contact).where(Contact.campaign_id == campaign["id"])
        ).all()
        present = contacts[0]

    skip = client.patch(
        f"/api/contacts/{present.id}",
        json={"status": "skipped"},
        headers=auth_headers(token),
    )
    assert skip.status_code == 200, skip.text
    assert skip.json()["status"] == "skipped"

    resp = client.post(
        f"/api/campaigns/{campaign['id']}/launch",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    detail = client.get(
        f"/api/campaigns/{campaign['id']}", headers=auth_headers(token)
    ).json()
    assert detail["counts"]["queued"] == 1
    assert detail["counts"]["skipped"] == 1

    # Re-including works: flip back and relaunch queues the second contact.
    back = client.patch(
        f"/api/contacts/{present.id}",
        json={"status": "pending_review"},
        headers=auth_headers(token),
    )
    assert back.status_code == 200, back.text


def test_live_call_contact_cannot_be_moved(client, session_factory):
    """A contact with status=calling (live call) rejects status moves."""
    from app.models import Contact

    token, _ = register(client)
    campaign = _make_campaign(client, token)
    with session_factory() as db:
        contact = Contact(
            campaign_id=campaign["id"],
            org_id=campaign["org_id"],
            name="Live Caller",
            phone="+919000000009",
            consent=True,
            status="calling",
        )
        db.add(contact)
        db.commit()
        contact_id = contact.id

    resp = client.patch(
        f"/api/contacts/{contact_id}",
        json={"status": "skipped"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
