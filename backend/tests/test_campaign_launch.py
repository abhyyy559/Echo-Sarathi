"""Campaign lifecycle contract tests — POST /api/campaigns/{id}/launch.

Regression context (2026-08-24): a launch click in the UI surfaced 422 twice.
The endpoint takes NO request body; its 422s are business guards only:
  - campaign already running
  - nothing left to call for this run (no contacts, or none pending)
  - outside the calling-hours window (default 09:00-21:00 IST, PRD §8)

A campaign is a reusable daily roster, not a one-shot batch: `completed` and
`canceled` campaigns launch again with whoever is pending that day, and
cancelling hands un-dialled people back to review so tomorrow's operator picks
the roster afresh. These tests pin that contract, plus the successful call
shape (empty-body POST -> 200, status "running", consenting pending_review
contacts queued).

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
    from test_playground import _make_agent_and_version

    ids = _make_agent_and_version(client, token)
    created = client.post(
        "/api/campaigns",
        json={
            "name": "Absent Students - Demo Week",
            "agent_version_id": ids["version"]["id"],
        },
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


def _set_status(session_factory: Any, campaign_id: int, campaign: str, contact: str) -> None:
    from app.models import Campaign, Contact

    with session_factory() as db:
        db.get(Campaign, campaign_id).status = campaign
        db.query(Contact).filter_by(campaign_id=campaign_id).update({"status": contact})
        db.commit()


def test_cancel_hands_queued_contacts_back_for_review(app, client, session_factory):
    """Cancelling mid-run must not leave the roster stuck as `queued`."""
    from app.models import Contact

    token, campaign = _seed_campaign_with_contact(client, session_factory)
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)
    assert client.post(
        f"/api/campaigns/{campaign['id']}/launch", headers=auth_headers(token)
    ).status_code == 200

    resp = client.post(
        f"/api/campaigns/{campaign['id']}/cancel", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "canceled"

    with session_factory() as db:
        statuses = {
            c.status for c in db.query(Contact).filter_by(campaign_id=campaign["id"])
        }
    assert statuses == {"pending_review"}


def test_relaunch_after_cancel_and_completion(app, client, session_factory):
    """The same campaign is launched every day with a changing roster."""
    from app.models import Contact

    token, campaign = _seed_campaign_with_contact(client, session_factory)
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)
    launch_url = f"/api/campaigns/{campaign['id']}/launch"

    assert client.post(launch_url, headers=auth_headers(token)).status_code == 200
    assert client.post(
        f"/api/campaigns/{campaign['id']}/cancel", headers=auth_headers(token)
    ).status_code == 200

    again = client.post(launch_url, headers=auth_headers(token))
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "running"
    detail = client.get(
        f"/api/campaigns/{campaign['id']}", headers=auth_headers(token)
    ).json()
    assert detail["counts"]["queued"] == 1

    # Yesterday's calls stay on record; only the still-pending people redial.
    # Next day: the earlier student is `completed`, today's absentee is imported.
    _set_status(session_factory, campaign["id"], "completed", "completed")
    with session_factory() as db:
        db.add(
            Contact(
                campaign_id=campaign["id"],
                org_id=campaign["org_id"],
                name="Today Absent",
                phone="+919000000003",
                consent=True,
            )
        )
        db.commit()

    done = client.post(launch_url, headers=auth_headers(token))
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "running"

    with session_factory() as db:
        by_phone = {
            c.phone: c.status
            for c in db.query(Contact).filter_by(campaign_id=campaign["id"])
        }
    assert by_phone == {"+919000000001": "completed", "+919000000003": "queued"}


def test_relaunch_with_nobody_pending_is_422_and_keeps_status(app, client, session_factory):
    """An empty day must not flip the campaign to running and instantly complete."""
    from app.models import Campaign

    token, campaign = _seed_campaign_with_contact(client, session_factory)
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)
    _set_status(session_factory, campaign["id"], "completed", "completed")

    resp = client.post(
        f"/api/campaigns/{campaign['id']}/launch", headers=auth_headers(token)
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"].startswith("no contacts are pending for this run")

    with session_factory() as db:
        assert db.get(Campaign, campaign["id"]).status == "completed"


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


def test_launch_without_an_agent_is_422(app, client, session_factory):
    """A campaign with no pinned agent produces calls nobody can answer."""
    token, _user = register(client)
    created = client.post(
        "/api/campaigns", json={"name": "No Agent"}, headers=auth_headers(token)
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
                phone="+919000000002",
                consent=True,
            )
        )
        db.commit()
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)

    resp = client.post(
        f"/api/campaigns/{campaign['id']}/launch", headers=auth_headers(token)
    )
    assert resp.status_code == 422, resp.text
    assert "no agent" in resp.json()["detail"]


def test_dialer_pins_the_agent_version_on_each_call(app, client, session_factory):
    """vobiz/twilio close the media socket when the call has no agent
    version, so a dialer-placed call must carry the campaign's."""
    from app.models import Call
    from app.services.dialer import DialerService
    from conftest import make_settings

    token, campaign = _seed_campaign_with_contact(client, session_factory)
    app.state.clock = lambda: datetime(2026, 8, 24, 5, 0)
    launch = client.post(
        f"/api/campaigns/{campaign['id']}/launch", headers=auth_headers(token)
    )
    assert launch.status_code == 200, launch.text

    class _Recorder:
        def __init__(self) -> None:
            self.placed: list[int] = []

        def place_call(self, to: str, call_id: int) -> str:
            self.placed.append(call_id)
            return f"CAfake{call_id:010d}"

    dialer = DialerService(
        make_settings(),
        session_factory,
        _Recorder(),
        clock=lambda: datetime(2026, 8, 24, 5, 0),
    )
    assert dialer.tick() == 1

    with session_factory() as db:
        call = db.query(Call).filter_by(campaign_id=campaign["id"]).one()
        assert call.agent_version_id == campaign["agent_version_id"]
        assert call.status == "ringing"
