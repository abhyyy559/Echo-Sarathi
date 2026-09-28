"""Provider-status reconciliation: carrier truth reaches our rows.

Vobiz pushes no status webhooks, so without this: stuck ringing rows,
USER_BUSY reported as completed, and worker error sessions shown as success.
"""
from __future__ import annotations

from datetime import timedelta

from conftest import auth_headers, make_settings, register


def _seed_call(db, org_name="Recon Org", status="ringing", minutes_old=0):
    from app.models import Call, Campaign, Contact, Organization
    from app.timeutil import utcnow

    org = Organization(name=org_name, slug=org_name.lower().replace(" ", "-"))
    db.add(org)
    db.flush()
    campaign = Campaign(org_id=org.id, name="Recon Campaign", status="running")
    db.add(campaign)
    db.flush()
    contact = Contact(
        campaign_id=campaign.id,
        org_id=org.id,
        name="Ravi",
        phone="+919000000011",
        consent=True,
        consent_source="test",
        status="calling",
    )
    db.add(contact)
    db.flush()
    call = Call(
        campaign_id=campaign.id,
        contact_id=contact.id,
        org_id=org.id,
        kind="phone",
        status=status,
        provider_call_id="VBtest0001",
        started_at=utcnow() - timedelta(minutes=minutes_old),
    )
    db.add(call)
    db.commit()
    return call


def test_map_vobiz_outcome() -> None:
    from app.services.vobiz_reconcile import map_vobiz_outcome

    assert map_vobiz_outcome({"bill_duration": "12.5", "hangup_cause": "NORMAL_CLEARING"}) == "completed"
    assert map_vobiz_outcome({"hangup_cause": "USER_BUSY"}) == "busy"
    assert map_vobiz_outcome({"hangup_cause": "NO_ANSWER"}) == "no_answer"
    assert map_vobiz_outcome({}) == "ringing"
    assert map_vobiz_outcome({"hangup_cause": "WEIRD_CARRIER_BLAH"}) == "failed"
    assert map_vobiz_outcome({"hangup_cause": "ORIGINATOR_CANCEL"}) == "no_answer"


def test_reconcile_applies_busy_with_retry(session_factory) -> None:
    from app.models import Contact
    from app.services.vobiz_reconcile import apply_provider_status
    from app.timeutil import utcnow

    settings = make_settings()
    with session_factory() as db:
        call = _seed_call(db)
        applied = apply_provider_status(
            db, call, "busy", settings, utcnow(), {"hangup_cause": "USER_BUSY"}
        )
        assert applied == "busy"
        assert call.status == "busy"
        contact = db.get(Contact, call.contact_id)
        assert contact.status == "queued"  # retry scheduled, not dead
        assert contact.attempt_count == 1


def test_reconcile_never_regresses_terminal(session_factory) -> None:
    from app.services.vobiz_reconcile import reconcile_vobiz_call
    from app.timeutil import utcnow

    settings = make_settings(vobiz_auth_id="A", vobiz_auth_token="T")
    with session_factory() as db:
        call = _seed_call(db, org_name="Recon Org 2", status="completed")
        assert reconcile_vobiz_call(db, settings, call, utcnow()) == "completed"


def test_reconcile_skips_without_creds(session_factory) -> None:
    from app.services.vobiz_reconcile import reconcile_vobiz_call
    from app.timeutil import utcnow

    settings = make_settings()  # no vobiz creds
    with session_factory() as db:
        call = _seed_call(db, org_name="Recon Org 3")
        assert reconcile_vobiz_call(db, settings, call, utcnow()) == "ringing"
        assert call.status == "ringing"


def test_sweeper_recovers_stale_ringing(session_factory, monkeypatch) -> None:
    import app.services.vobiz_reconcile as recon
    from app.models import Call
    from app.services.dialer import DialerService

    monkeypatch.setattr(
        recon, "fetch_vobiz_call",
        lambda settings, provider_id: {"hangup_cause": "USER_BUSY"},
    )
    settings = make_settings(vobiz_auth_id="A", vobiz_auth_token="T")

    class _NeverDial:
        def place_call(self, to: str, call_id: int) -> str:
            raise AssertionError("sweeper must not place calls")

    with session_factory() as db:
        call = _seed_call(db, org_name="Recon Org 4", minutes_old=30)
        call_id = call.id

    dialer = DialerService(settings, session_factory, _NeverDial())
    with session_factory() as db:
        assert dialer._sweep_stale_ringing(db, dialer.clock()) == 1
        assert db.get(Call, call_id).status == "busy"


def test_internal_complete_honors_worker_error(client, session_factory) -> None:
    token, _ = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_name="Recon Org 5").id
    resp = client.post(
        f"/internal/calls/{call_id}/complete",
        json={"status": "error", "error": "groq 429 on all keys"},
        headers={"X-Internal-Token": "test_internal_token"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "failed"
    with session_factory() as db:
        from app.models import Call, CallEvent

        assert db.get(Call, call_id).status == "failed"
        kinds = [e.event_type for e in db.query(CallEvent).filter_by(call_id=call_id)]
        assert "worker_error" in kinds


def test_internal_complete_wrapped_up_flags_human(client, session_factory) -> None:
    token, _ = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_name="Recon Org 6").id
    resp = client.post(
        f"/internal/calls/{call_id}/complete",
        json={"status": "wrapped_up_flagged", "summary": "got reason, date unclear"},
        headers={"X-Internal-Token": "test_internal_token"},
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        from app.models import Call

        call = db.get(Call, call_id)
        assert call.status == "completed"
        assert call.flagged_for_human is True


def test_test_call_row_is_kind_phone(client, session_factory) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.models import Call
    from test_playground import _make_agent_and_version

    token, _ = register(client)
    ids = _make_agent_and_version(client, token)
    fresh = create_app(make_settings(test_phone_numbers="+919812345699"))
    fresh.state.session_factory = session_factory
    with TestClient(fresh) as numbered:
        resp = numbered.post(
            "/api/test-call",
            json={"to": "+919812345699", "agent_version_id": ids["version"]["id"]},
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        assert db.get(Call, resp.json()["call_id"]).kind == "phone"
