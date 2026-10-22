"""Campaign sequencing: three contacts, one call after another, data collected.

Nothing in the suite used to call ``DialerService.tick()`` more than once, so the
loop *between* calls was unproven - and that loop is the whole campaign feature:
a dial blocks on the in-flight cap, the worker's hangup releases the LiveKit
room (freeing the worker's concurrency slot for the next job), the contact moves
out of ``calling``, and only then does the next number get dialled.

The worker is played by its own HTTP calls (``/internal/...``) - the same ones
voice-agent makes in production - and the provider is ``FakeTelephonyClient``, so
this proves the campaign plumbing without dialling a real phone number.

Three failure modes this pins, each of which would look like "the campaign broke"
in the field:
  - a call whose room is never deleted, glueing the worker slot and freezing the
    campaign after the first contact;
  - a no-answer that either re-dials immediately (a harassment risk) or never
    re-dials at all (the contact is silently dropped);
  - a contact whose consent went missing mid-flight still getting dialled.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from conftest import auth_headers, make_settings, register

PHONE_1 = "+919000000001"
PHONE_2 = "+919000000002"
PHONE_3 = "+919000000003"

#: 05:00 UTC == 10:30 IST: inside the default 09:00-21:00 calling window.
LAUNCH_TIME = datetime(2026, 8, 24, 5, 0)

INTERNAL = {"X-Internal-Token": "test_internal_token"}


def _seed_running_campaign(
    app: Any,
    client: Any,
    session_factory: Any,
    phones: list[str],
    *,
    org_name: str = "Seq University",
) -> tuple[str, dict[str, Any]]:
    """Register an org, pin an agent, launch a campaign over ``phones``."""
    token, _user = register(client, org_name=org_name)
    from test_playground import _make_agent_and_version

    ids = _make_agent_and_version(client, token)
    created = client.post(
        "/api/campaigns",
        json={"name": "Absent Students", "agent_version_id": ids["version"]["id"]},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    campaign = created.json()

    from app.models import Contact

    with session_factory() as db:
        for index, phone in enumerate(phones):
            db.add(
                Contact(
                    campaign_id=campaign["id"],
                    org_id=campaign["org_id"],
                    name=f"Friend {index + 1}",
                    phone=phone,
                    consent=True,
                    consent_source="manual_test_call",
                )
            )
        db.commit()

    app.state.clock = lambda: LAUNCH_TIME
    launched = client.post(
        f"/api/campaigns/{campaign['id']}/launch", headers=auth_headers(token)
    )
    assert launched.status_code == 200, launched.text
    return token, campaign


def _moving_dialer(
    session_factory: Any,
    telephony: Any,
    **overrides: Any,
) -> tuple[Any, dict[str, datetime]]:
    """A dialer whose clock the test can push forward between ticks."""
    from app.services.dialer import DialerService

    now: dict[str, datetime] = {"value": LAUNCH_TIME}
    settings = make_settings(**overrides)
    dialer = DialerService(settings, session_factory, telephony, clock=lambda: now["value"])
    return dialer, now


def _finish_call(
    client: Any,
    call_id: int,
    *,
    summary: str,
    field_value: str,
) -> dict[str, Any]:
    """Run the worker's closing HTTP sequence for one live call."""
    turns = client.post(
        f"/internal/calls/{call_id}/transcript-turns",
        json={
            "turns": [
                {"turn_index": 0, "speaker": "agent", "text": "Hi, is this a good time?"},
                {"turn_index": 1, "speaker": "caller", "text": "Yes, go ahead."},
            ]
        },
        headers=INTERNAL,
    )
    assert turns.status_code == 200, turns.text

    fields = client.post(
        f"/internal/calls/{call_id}/extracted-fields",
        json={
            "fields": [
                {
                    "field_name": "will_reenroll",
                    "field_value": field_value,
                    "confidence": 0.9,
                    "source_turn_index": 1,
                }
            ],
            "complete": True,
        },
        headers=INTERNAL,
    )
    assert fields.status_code == 200, fields.text

    done = client.post(
        f"/internal/calls/{call_id}/complete",
        json={"status": "completed", "summary": summary, "outcome": "info_collected"},
        headers=INTERNAL,
    )
    assert done.status_code == 200, done.text

    hung = client.post(
        f"/internal/calls/{call_id}/hangup",
        json={"room": f"phone-{call_id}"},
        headers=INTERNAL,
    )
    assert hung.status_code == 200, hung.text
    return hung.json()


def _record_room_deletes(monkeypatch: Any) -> list[str]:
    """Capture room releases instead of calling LiveKit from the test."""
    import app.services.call_teardown as teardown

    deleted: list[str] = []

    def _fake(settings: Any, room_name: str) -> bool:
        deleted.append(room_name)
        return True

    monkeypatch.setattr(teardown, "_delete_room", _fake)
    return deleted


def test_campaign_dials_one_contact_after_another(app, client, session_factory, monkeypatch):
    """The campaign contract: 3 contacts -> 3 sequential calls, data retained."""
    from app.models import Call
    from app.services.telephony import FakeTelephonyClient

    rooms = _record_room_deletes(monkeypatch)
    telephony = FakeTelephonyClient()
    dialer, _now = _moving_dialer(
        session_factory,
        telephony,
        # One live call at a time: the next contact waits for this call to end,
        # which is the behaviour the user asked to see proven.
        default_concurrency_limit=1,
        # Generous, so any stall is the in-flight cap rather than the CPS window.
        default_cps_limit=5,
    )

    token, campaign = _seed_running_campaign(
        app, client, session_factory, [PHONE_1, PHONE_2, PHONE_3], org_name="Seq One University"
    )

    assert dialer.tick() == 1
    first_id = telephony.placed[-1][1]
    assert dialer.tick() == 0
    assert len(telephony.placed) == 1

    # What the worker fetches before it can speak: the call context must carry
    # the pinned agent version (a campaign call used to arrive without one, so
    # the bridge closed 4404 and the phone rang with nobody answering), and the
    # agent version must actually hold the questions to ask and the fields to
    # extract. Without these two, a campaign "call" produces no data.
    ctx = client.get(f"/internal/calls/{first_id}/context", headers=INTERNAL).json()
    assert ctx["call"]["agent_version_id"] == campaign["agent_version_id"]
    assert ctx["contact"]["name"] == "Friend 1"
    assert ctx["campaign"]["name"] == "Absent Students"
    cfg = client.get(
        "/internal/agent-config",
        params={"version_id": campaign["agent_version_id"]},
        headers=INTERNAL,
    ).json()
    assert cfg["question_flow"]
    assert cfg["extraction_schema"]

    hung = _finish_call(client, first_id, summary="Will re-enroll next month.", field_value="yes")
    assert hung["room"] == f"phone-{first_id}"
    assert hung["room_closed"] is True
    # FakeTelephony mints a synthetic leg id that exists only in our database, so
    # no provider hangup is attempted; the real-provider path is test_call_hangup.py.
    assert hung["hangup"] is False
    assert telephony.hung_up == []

    assert dialer.tick() == 1
    second_id = telephony.placed[-1][1]
    assert second_id != first_id
    assert dialer.tick() == 0
    _finish_call(client, second_id, summary="No decision yet.", field_value="maybe")

    assert dialer.tick() == 1
    third_id = telephony.placed[-1][1]
    _finish_call(client, third_id, summary="Not returning this term.", field_value="no")

    assert [phone for phone, _ in telephony.placed] == [PHONE_1, PHONE_2, PHONE_3]
    # Each call released its own room - that release is what frees the worker slot.
    assert rooms == [f"phone-{first_id}", f"phone-{second_id}", f"phone-{third_id}"]
    assert dialer.tick() == 0

    with session_factory() as db:
        for call_id in (first_id, second_id, third_id):
            call = db.get(Call, call_id)
            assert call.status == "completed"
            assert call.duration_seconds is not None
            # Regression guard: without a pinned agent version the media bridge
            # closes 4404 and the phone rings with nobody answering.
            assert call.agent_version_id == campaign["agent_version_id"]

    detail = client.get(f"/api/campaigns/{campaign['id']}", headers=auth_headers(token)).json()
    assert detail["status"] == "completed"
    assert detail["counts"]["completed"] == 3

    board = client.get(
        f"/api/campaigns/{campaign['id']}/dashboard", headers=auth_headers(token)
    ).json()
    assert board["campaign_status"] == "completed"
    assert board["calls_in_flight"] == 0
    assert board["counts"]["completed"] == 3
    assert {row["outcome"] for row in board["recent_calls"]} == {"info_collected"}

    # What the dashboard renders for a finished campaign.
    listing = client.get(
        f"/api/campaigns/{campaign['id']}/calls", headers=auth_headers(token)
    ).json()
    assert len(listing) == 3
    assert {row["contact_phone"] for row in listing} == {PHONE_1, PHONE_2, PHONE_3}
    assert all(row["summary"] for row in listing)
    assert all(row["outcome"] == "info_collected" for row in listing)

    call_detail = client.get(f"/api/calls/{third_id}", headers=auth_headers(token)).json()
    assert call_detail["status"] == "completed"
    assert call_detail["summary"] == "Not returning this term."
    assert [t["speaker"] for t in call_detail["transcript"]] == ["agent", "caller"]
    assert call_detail["extracted_fields"][0]["field_name"] == "will_reenroll"
    assert call_detail["extracted_fields"][0]["field_value"] == "no"


def test_no_answer_backs_off_then_redials_then_gives_up(app, client, session_factory):
    """A refused call re-queues on the backoff schedule and stops at max attempts."""
    from app.models import Call, Contact
    from app.services.telephony import FakeTelephonyClient
    from app.services.vobiz_reconcile import apply_provider_status

    token, campaign = _seed_running_campaign(
        app, client, session_factory, [PHONE_1], org_name="Seq Two University"
    )

    telephony = FakeTelephonyClient()
    dialer, now = _moving_dialer(
        session_factory, telephony, retry_backoff_minutes=15, retry_max_attempts=3
    )

    def _refuse(call_id: int, status: str) -> None:
        with session_factory() as db:
            call = db.get(Call, call_id)
            apply_provider_status(db, call, status, dialer.settings, now["value"])
            db.commit()

    assert dialer.tick() == 1
    first_id = telephony.placed[-1][1]
    _refuse(first_id, "no_answer")

    with session_factory() as db:
        contact = db.get(Contact, db.get(Call, first_id).contact_id)
        assert contact.status == "queued"
        assert contact.attempt_count == 1
        assert contact.next_attempt_at == LAUNCH_TIME + timedelta(minutes=15)

    # Still inside the backoff window: the redial must wait.
    assert dialer.tick() == 0
    assert len(telephony.placed) == 1

    now["value"] = LAUNCH_TIME + timedelta(minutes=16)
    assert dialer.tick() == 1
    second_id = telephony.placed[-1][1]
    assert telephony.placed[-1][0] == PHONE_1

    _refuse(second_id, "busy")
    now["value"] = LAUNCH_TIME + timedelta(minutes=32)
    assert dialer.tick() == 1
    third_id = telephony.placed[-1][1]

    _refuse(third_id, "busy")
    assert dialer.tick() == 0
    assert len(telephony.placed) == 3

    with session_factory() as db:
        contact = db.get(Contact, db.get(Call, third_id).contact_id)
        assert contact.attempt_count == 3
        # RETRY_MAX_ATTEMPTS reached: the contact is finished, not left queued.
        assert contact.status == "failed"
    detail = client.get(f"/api/campaigns/{campaign['id']}", headers=auth_headers(token)).json()
    assert detail["status"] == "completed"


def test_dialer_refuses_a_contact_whose_consent_disappeared(app, client, session_factory):
    """Consent is checked at dial time, and a refusal costs the campaign nothing.

    The opt-out must not occupy a concurrency slot or count as a dial: the next
    consenting contact still has to be reached on the same pass.
    """
    from app.models import Contact
    from app.services.telephony import FakeTelephonyClient

    _token, campaign = _seed_running_campaign(
        app, client, session_factory, [PHONE_1, PHONE_2, PHONE_3], org_name="Seq Three University"
    )
    with session_factory() as db:
        row = db.query(Contact).filter_by(campaign_id=campaign["id"], phone=PHONE_2).first()
        row.consent = False
        row.consent_source = None
        db.commit()

    telephony = FakeTelephonyClient()
    dialer, now = _moving_dialer(
        session_factory, telephony, default_concurrency_limit=10, default_cps_limit=1
    )

    # CPS 1/second, so each tick may put exactly one leg out.
    assert dialer.tick() == 1
    assert [phone for phone, _ in telephony.placed] == [PHONE_1]

    now["value"] = LAUNCH_TIME + timedelta(seconds=2)
    # This tick retires PHONE_2 (no consent) and must still dial PHONE_3.
    assert dialer.tick() == 1
    assert [phone for phone, _ in telephony.placed] == [PHONE_1, PHONE_3]

    with session_factory() as db:
        refused = db.query(Contact).filter_by(campaign_id=campaign["id"], phone=PHONE_2).first()
        assert refused.status == "opted_out"
        assert refused.attempt_count == 0
