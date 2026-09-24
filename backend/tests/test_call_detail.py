"""GET /api/calls/{id} for PLAYGROUND calls (regression: campaign_id/contact_id NULL).

Playground calls carry no campaign/contact lineage; the detail endpoint used to
explode with ResponseValidationError (int_type on None) which surfaced in the
browser as a fake CORS failure.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import Call, CallEvent, Transcript
from conftest import auth_headers, register


def _seed_playground_call(db: Any, org_id: int) -> int:
    call = Call(
        kind="playground",
        org_id=org_id,
        status="completed",
        duration_seconds=24.0,
        summary="test summary",
    )
    db.add(call)
    db.commit()
    return call.id


def test_call_detail_ok_for_playground_call(client, session_factory):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_playground_call(db, user["org_id"])

    resp = client.get(f"/api/calls/{call_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == call_id
    assert body["campaign_id"] is None
    assert body["contact_id"] is None
    assert body["contact_name"] is None


def _activity_event(
    call_id: int,
    sequence: int,
    state: str,
    created_at: datetime,
    *,
    occurred_at: datetime | None = None,
    event_type: str = "agent_state_changed",
    **payload_fields: Any,
) -> CallEvent:
    event_time = occurred_at or created_at
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    payload = {
        "sequence": sequence,
        "state": state,
        "event_type": event_type,
        "occurred_at": event_time.timestamp(),
        "source": "agent_state_changed",
    }
    payload.update(payload_fields)
    return CallEvent(
        call_id=call_id,
        event_type="voice_activity",
        payload=payload,
        created_at=created_at,
    )


def test_call_detail_activity_history_is_sequence_ordered_and_capped(client, session_factory):
    token, user = register(client)
    base = datetime(2026, 1, 1, 12, 0, 0)
    with session_factory() as db:
        call = Call(
            kind="phone",
            org_id=user["org_id"],
            status="in_progress",
            answered_at=base,
        )
        db.add(call)
        db.flush()
        db.add_all(
            [
                _activity_event(
                    call.id,
                    sequence,
                    "listening",
                    base + timedelta(seconds=sequence),
                )
                for sequence in range(205, 0, -1)
            ]
        )
        db.commit()
        call_id = call.id

    resp = client.get(f"/api/calls/{call_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sequences = [event["sequence"] for event in body["activity_history"]]
    assert sequences == list(range(6, 206))
    assert body["activity"]["sequence"] == 205
    assert body["activity"]["state"] == "listening"


def test_call_detail_computes_pickup_and_agent_opening_timing(client, session_factory):
    token, user = register(client)
    base = datetime(2026, 1, 1, 12, 0, 0)
    with session_factory() as db:
        call = Call(
            kind="phone",
            org_id=user["org_id"],
            status="completed",
            answered_at=base,
        )
        db.add(call)
        db.flush()
        db.add(
            _activity_event(
                call.id,
                1,
                "agent_speaking",
                base + timedelta(seconds=100),
                occurred_at=base + timedelta(seconds=2),
                from_state="thinking",
                to_state="speaking",
            )
        )
        db.add(
            _activity_event(
                call.id,
                2,
                "understanding",
                base + timedelta(seconds=10),
                occurred_at=base + timedelta(seconds=2.5),
                event_type="user_state_changed",
                source="user_state_changed",
                from_state="speaking",
                to_state="listening",
            )
        )
        db.add(
            Transcript(
                call_id=call.id,
                turn_index=0,
                speaker="caller",
                text="hello",
                timestamp=base + timedelta(seconds=1.5),
            )
        )
        db.add(
            _activity_event(
                call.id,
                3,
                "listening",
                base + timedelta(seconds=50),
                occurred_at=base + timedelta(seconds=5),
                from_state="speaking",
                to_state="thinking",
            )
        )
        db.commit()
        call_id = call.id

    resp = client.get(f"/api/calls/{call_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pickup_to_first_audio_seconds"] == 2.0
    assert body["opening_duration_seconds"] == 3.0


def test_call_detail_terminal_call_without_activity_has_null_timing(client, session_factory):
    token, user = register(client)
    base = datetime(2026, 1, 1, 12, 0, 0)
    with session_factory() as db:
        call = Call(
            kind="phone",
            org_id=user["org_id"],
            status="completed",
            answered_at=base,
        )
        db.add(call)
        db.commit()
        call_id = call.id

    resp = client.get(f"/api/calls/{call_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["activity"] is None
    assert body["activity_history"] == []
    assert body["pickup_to_first_audio_seconds"] is None
    assert body["opening_duration_seconds"] is None


def test_call_detail_missing_timing_prerequisites_return_null(client, session_factory):
    token, user = register(client)
    base = datetime(2026, 1, 1, 12, 0, 0)
    with session_factory() as db:
        call = Call(
            kind="phone",
            org_id=user["org_id"],
            status="in_progress",
        )
        db.add(call)
        db.flush()
        db.add(_activity_event(call.id, 1, "agent_speaking", base + timedelta(seconds=2)))
        db.commit()
        call_id = call.id

    resp = client.get(f"/api/calls/{call_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pickup_to_first_audio_seconds"] is None
    assert body["opening_duration_seconds"] is None
