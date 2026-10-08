"""Campaign lifecycle contract tests — POST /api/campaigns/{id}/launch.

Regression context (2026-08-24): a launch click in the UI surfaced 422 twice.
The endpoint takes NO request body; its 422s are business guards only:
  - campaign already running / completed / canceled
  - zero contacts on the roster
  - outside the calling-hours window (default 09:00-21:00 IST, PRD §8)

These tests pin the successful call shape (empty-body POST -> 200, status
"running", consenting pending_review contacts queued) and the two rejections
users are most likely to hit, so frontend work has a stable contract to mirror.

The clock is injected via ``app.state.clock`` — the same seam the router reads
(campaigns.py: ``getattr(request.app.state, "clock", None) or utcnow``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from conftest import auth_headers, register


def _seed_campaign_with_contact(
    client: Any,
    session_factory: Any,
    *,
    consent: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Register an org, create a draft campaign, insert one contact row."""
    token, _user = register(client)
    created = client.post(
        "/api/campaigns",
        json={"name": "Absent Students - Demo Week"},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    campaign = created.json()

    from app.models import Contact

    with session_factory() as db:
        db.add(
            Contact(
                campaign_id=campaign["id"],
                org_id=campaign["org_id"],
                name="Ravi Kumar",
                phone="+919000000001",
                consent=consent,
            )
        )
        db.commit()
    return token, campaign


def test_launch_success_with_empty_body(app, client, session_factory):
    """The exact call shape the frontend makes: bare POST, no JSON body."""
    token, campaign = _seed_campaign_with_contact(client, session_factory)
    # 05:00 UTC == 10:30 IST -> inside the default 9..21 window.
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)

    resp = client.post(
        f"/api/campaigns/{campaign['id']}/launch",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert body["id"] == campaign["id"]
    assert body["org_id"] == campaign["org_id"]

    detail = client.get(
        f"/api/campaigns/{campaign['id']}", headers=auth_headers(token)
    ).json()
    assert detail["counts"]["queued"] >= 1


def test_launch_outside_calling_hours_is_422(app, client, session_factory):
    token, campaign = _seed_campaign_with_contact(client, session_factory)
    # 18:45 UTC == 00:15 IST next day -> outside 9..21 (the owner's scenario).
    app.state.clock = lambda: datetime(2026, 8, 23, 18, 45)

    resp = client.post(
        f"/api/campaigns/{campaign['id']}/launch",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "outside calling hours" in resp.json()["detail"]


def test_launch_without_contacts_is_422(app, client):
    token, _user = register(client)
    created = client.post(
        "/api/campaigns",
        json={"name": "Empty roster"},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    campaign = created.json()
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)

    resp = client.post(
        f"/api/campaigns/{campaign['id']}/launch",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "campaign has no contacts to call"


def test_launch_twice_second_attempt_rejected(app, client, session_factory):
    token, campaign = _seed_campaign_with_contact(client, session_factory)
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)

    first = client.post(
        f"/api/campaigns/{campaign['id']}/launch", headers=auth_headers(token)
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/campaigns/{campaign['id']}/launch", headers=auth_headers(token)
    )
    assert second.status_code == 422, second.text
    assert second.json()["detail"] == "campaign is already running"


def test_delete_campaign_removes_contacts(app, client, session_factory):
    token, campaign = _seed_campaign_with_contact(client, session_factory)

    resp = client.delete(f"/api/campaigns/{campaign['id']}", headers=auth_headers(token))
    assert resp.status_code == 204, resp.text

    from app.models import Campaign, Contact
    with session_factory() as db:
        assert db.get(Campaign, campaign["id"]) is None
        assert db.query(Contact).filter_by(campaign_id=campaign["id"]).count() == 0


def test_delete_campaign_while_running_is_conflict(app, client, session_factory):
    token, campaign = _seed_campaign_with_contact(client, session_factory)
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)
    launch = client.post(f"/api/campaigns/{campaign['id']}/launch", headers=auth_headers(token))
    assert launch.status_code == 200, launch.text

    from app.models import Call, Contact

    with session_factory() as db:
        contact = db.query(Contact).filter_by(campaign_id=campaign["id"]).first()
        db.add(
            Call(
                campaign_id=campaign["id"],
                contact_id=contact.id,
                org_id=campaign["org_id"],
                status="in_progress",
            )
        )
        db.commit()

    resp = client.delete(f"/api/campaigns/{campaign['id']}", headers=auth_headers(token))
    assert resp.status_code == 409, resp.text
    assert "in flight" in resp.json()["detail"]


def test_delete_requires_auth(client, session_factory):
    from conftest import auth_headers

    token, campaign = _seed_campaign_with_contact(client, session_factory)
    resp = client.delete(f"/api/campaigns/{campaign['id']}")
    assert resp.status_code == 401
