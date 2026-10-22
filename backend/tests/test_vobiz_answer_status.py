"""The answer webhook must believe the carrier.

Production incident (call 25, campaign 2): Vobiz answered our XML request with
``CallStatus=busy``/``Event=Hangup``/``HangupCause=USER_BUSY`` and the handler
stamped the call ``in_progress`` anyway. The agent never joined, the row looked
live, and it held the campaign's single dial slot until the 10-minute sweeper
ran. The handler now applies the terminal outcome and returns ``<Hangup/>``.
"""
from __future__ import annotations

from typing import Any

# Verbatim shape from the production call_events row (#411).
BUSY_PAYLOAD = {
    "AnswerTime": "",
    "BillDuration": "0",
    "CallStatus": "busy",
    "CallUUID": "ff3ce48f-f339-4040-9c84-6439dfe36c04",
    "EndTime": "2026-10-22 21:52:02",
    "Event": "Hangup",
    "From": "+918065354620",
    "HangupCause": "USER_BUSY",
    "To": "+917842594002",
}


def _seed_call(client, session_factory, status="ringing") -> int:
    from app.models import Call, Campaign, Contact, Organization
    from app.timeutil import utcnow

    with session_factory() as db:
        org = Organization(name="Answer Webhook Org", slug="answer-webhook-org")
        db.add(org)
        db.flush()
        campaign = Campaign(org_id=org.id, name="Answer Campaign", status="running")
        db.add(campaign)
        db.flush()
        contact = Contact(
            campaign_id=campaign.id,
            org_id=org.id,
            name="jeevana",
            phone="+917842594002",
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
            provider_call_id=BUSY_PAYLOAD["CallUUID"],
            started_at=utcnow(),
        )
        db.add(call)
        db.commit()
        return call.id


def _post_answer(client, call_id: int, payload: dict[str, Any]) -> Any:
    return client.post(f"/vobiz/answer?call_id={call_id}", json=payload)


def test_a_refused_leg_ends_the_call_and_frees_the_dial_slot(client, session_factory) -> None:
    from app.models import Call, Contact
    from app.services.calls_service import in_flight_call_count

    call_id = _seed_call(client, session_factory)
    resp = _post_answer(client, call_id, BUSY_PAYLOAD)

    assert resp.status_code == 200
    assert "<Hangup/>" in resp.text
    assert "<Stream" not in resp.text

    with session_factory() as db:
        call = db.get(Call, call_id)
        assert call.status == "busy"
        assert call.answered_at is None  # nobody spoke; the row must not claim so
        assert call.ended_at is not None
        assert call.duration_seconds == 0.0
        contact = db.get(Contact, call.contact_id)
        assert contact.status == "queued"  # retry policy re-queues, not kills
        assert contact.attempt_count == 1
        assert contact.next_attempt_at is not None
        assert in_flight_call_count(db, phone_only=True) == 0


def test_a_genuine_answer_still_bridges_media(client, session_factory) -> None:
    from app.models import Call

    call_id = _seed_call(client, session_factory, status="ringing")
    resp = _post_answer(client, call_id, {"CallStatus": "ringing", "From": "+918065354620"})

    assert resp.status_code == 200
    assert "<Stream" in resp.text

    with session_factory() as db:
        call = db.get(Call, call_id)
        assert call.status == "in_progress"
        assert call.ended_at is None


def test_a_bare_hangup_on_an_unanswered_call_is_not_a_success(client, session_factory) -> None:
    from app.models import Call

    call_id = _seed_call(client, session_factory, status="ringing")
    resp = _post_answer(client, call_id, {"Event": "Hangup", "CallUUID": "VB-x"})

    assert "<Hangup/>" in resp.text
    with session_factory() as db:
        assert db.get(Call, call_id).status == "no_answer"


def test_an_unmapped_status_word_is_read_through_the_hangup_cause(client, session_factory) -> None:
    from app.models import Call

    call_id = _seed_call(client, session_factory, status="ringing")
    resp = _post_answer(
        client, call_id, {"CallStatus": "failed_call", "HangupCause": "NO_ANSWER"}
    )

    assert "<Hangup/>" in resp.text
    with session_factory() as db:
        assert db.get(Call, call_id).status == "no_answer"


def test_the_status_webhook_applies_the_same_terminal_rule(client, session_factory) -> None:
    """Both webhook routes must agree; drift here stranded contacts before."""
    from app.models import Call, Contact
    from app.services.calls_service import in_flight_call_count

    call_id = _seed_call(client, session_factory, status="in_progress")
    resp = client.post(
        "/vobiz/status",
        json={"CallUUID": BUSY_PAYLOAD["CallUUID"], "CallStatus": "busy"},
    )

    assert resp.status_code == 200
    with session_factory() as db:
        assert db.get(Call, call_id).status == "busy"
        assert db.get(Contact, db.get(Call, call_id).contact_id).status == "queued"
        assert in_flight_call_count(db, phone_only=True) == 0


def test_a_late_answer_cannot_resurrect_a_closed_call(client, session_factory) -> None:
    from app.models import Call

    call_id = _seed_call(client, session_factory, status="no_answer")
    resp = _post_answer(client, call_id, {"CallStatus": "answered"})

    assert "<Hangup/>" in resp.text
    with session_factory() as db:
        call = db.get(Call, call_id)
        assert call.status == "no_answer"
