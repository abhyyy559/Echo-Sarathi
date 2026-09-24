"""Internal API tests: extracted-fields wire shape + call context enrichment.

The voice-agent posts extracted fields with ``field_name``/``field_value``
rows; the backend must accept that shape (and the legacy ``name``/``value``
shape), persist accepted rows, and skip placeholder values.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Agent, AgentVersion, Call, CallEvent, Campaign, ExtractedField, Organization
from conftest import register

INTERNAL = {"X-Internal-Token": "test_internal_token"}


def _seed_call(db, org_id=None, campaign=None, **kwargs) -> int:
    call = Call(
        org_id=org_id,
        campaign_id=campaign.id if campaign else None,
        **kwargs,
    )
    db.add(call)
    db.commit()
    return call.id


def test_extracted_fields_accepts_voice_agent_shape(client, session_factory):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=user["org_id"])

    resp = client.post(
        f"/internal/calls/{call_id}/extracted-fields",
        json={
            "fields": [
                {
                    "field_name": "reason_for_absence",
                    "field_value": "fever",
                    "confidence": 0.92,
                    "source_turn_index": 1,
                },
                {
                    "field_name": "followup_needed",
                    "field_value": "unknown",
                    "confidence": 0.31,
                },
            ]
        },
        headers=INTERNAL,
    )
    assert resp.status_code == 200, resp.text

    with session_factory() as db:
        fields = list(
            db.scalars(select(ExtractedField).where(ExtractedField.call_id == call_id))
        )
        assert len(fields) == 1, "placeholder row must be skipped"
        assert fields[0].field_name == "reason_for_absence"
        assert fields[0].field_value == "fever"
        assert fields[0].confidence == 0.92
        assert fields[0].source_turn_index == 1


def test_extracted_fields_skips_empty_and_na_placeholders(client, session_factory):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=user["org_id"])

    resp = client.post(
        f"/internal/calls/{call_id}/extracted-fields",
        json={
            "fields": [
                {"field_name": "a", "field_value": ""},
                {"field_name": "b", "field_value": "n/a"},
                {"field_name": "c", "field_value": "Not Provided"},
                {"field_name": "d", "field_value": "real value"},
            ]
        },
        headers=INTERNAL,
    )
    assert resp.status_code == 200, resp.text

    with session_factory() as db:
        fields = list(
            db.scalars(select(ExtractedField).where(ExtractedField.call_id == call_id))
        )
        assert [f.field_name for f in fields] == ["d"]
        assert fields[0].field_value == "real value"


def test_extracted_fields_still_accepts_legacy_name_value(client, session_factory):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=user["org_id"])

    resp = client.post(
        f"/internal/calls/{call_id}/extracted-fields",
        json={"fields": [{"name": "reason_for_absence", "value": "fever"}]},
        headers=INTERNAL,
    )
    assert resp.status_code == 200, resp.text

    with session_factory() as db:
        fields = list(
            db.scalars(select(ExtractedField).where(ExtractedField.call_id == call_id))
        )
        assert len(fields) == 1
        assert fields[0].field_name == "reason_for_absence"
        assert fields[0].field_value == "fever"


def test_extracted_fields_missing_name_is_400(client, session_factory):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=user["org_id"])

    resp = client.post(
        f"/internal/calls/{call_id}/extracted-fields",
        json={"fields": [{"value": "orphan"}]},
        headers=INTERNAL,
    )
    assert resp.status_code == 400


def test_context_includes_institution_name_from_org(client, session_factory):
    token, user = register(client, org_name="Acme University")
    with session_factory() as db:
        org = db.get(Organization, user["org_id"])
        campaign = Campaign(org_id=org.id, name="Absents - Aug")
        db.add(campaign)
        db.flush()
        call_id = _seed_call(db, org_id=org.id, campaign=campaign)

    resp = client.get(f"/internal/calls/{call_id}/context", headers=INTERNAL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["institution_name"] == "Acme University"
    assert body["campaign"]["name"] == "Absents - Aug"
    assert body["call"]["id"] == call_id


def test_context_institution_name_falls_back_to_campaign(client, session_factory):
    token, _ = register(client)
    with session_factory() as db:
        campaign = Campaign(org_id=None, name="Legacy Campaign")
        db.add(campaign)
        db.flush()
        call_id = _seed_call(db, org_id=None, campaign=campaign)

    resp = client.get(f"/internal/calls/{call_id}/context", headers=INTERNAL)
    assert resp.status_code == 200, resp.text
    assert resp.json()["institution_name"] == "Legacy Campaign"


def test_context_institution_name_is_empty_string_when_absent(client, session_factory):
    token, _ = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=None)

    resp = client.get(f"/internal/calls/{call_id}/context", headers=INTERNAL)
    assert resp.status_code == 200, resp.text
    assert resp.json()["institution_name"] == ""


def _make_agent_version(db, org_id: int, company_context: dict) -> AgentVersion:
    agent = Agent(org_id=org_id, name="Activity Agent", description="")
    db.add(agent)
    db.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="test",
        company_context=company_context,
        disclosure_script="test",
    )
    db.add(version)
    db.flush()
    return version


def test_context_prefers_agent_version_institution(client, session_factory):
    token, user = register(client, org_name="Demo University")
    with session_factory() as db:
        version = _make_agent_version(
            db, user["org_id"], {"institution": "CMR COLLEGE OF ENGINEERING AND TECHNOLOGY"}
        )
        call_id = _seed_call(db, org_id=user["org_id"], agent_version_id=version.id)

    resp = client.get(f"/internal/calls/{call_id}/context", headers=INTERNAL)
    assert resp.status_code == 200, resp.text
    assert resp.json()["institution_name"] == "CMR COLLEGE OF ENGINEERING AND TECHNOLOGY"


def test_context_accepts_institution_name_alias(client, session_factory):
    token, user = register(client, org_name="Demo University")
    with session_factory() as db:
        version = _make_agent_version(
            db,
            user["org_id"],
            {"institution": "   ", "institution_name": "CMR Alias University"},
        )
        call_id = _seed_call(db, org_id=user["org_id"], agent_version_id=version.id)

    resp = client.get(f"/internal/calls/{call_id}/context", headers=INTERNAL)
    assert resp.status_code == 200, resp.text
    assert resp.json()["institution_name"] == "CMR Alias University"


def test_context_blank_version_institution_falls_back_to_organization(client, session_factory):
    token, user = register(client, org_name="Acme University")
    with session_factory() as db:
        version = _make_agent_version(
            db, user["org_id"], {"institution": " ", "institution_name": ""}
        )
        call_id = _seed_call(db, org_id=user["org_id"], agent_version_id=version.id)

    resp = client.get(f"/internal/calls/{call_id}/context", headers=INTERNAL)
    assert resp.status_code == 200, resp.text
    assert resp.json()["institution_name"] == "Acme University"


def _activity_payload(
    sequence: int = 1,
    state: str = "agent_connecting",
    event_type: str = "agent_state_changed",
    **overrides,
):
    payload = {
        "sequence": sequence,
        "state": state,
        "event_type": event_type,
        "occurred_at": 1_700_000_000.125,
        "source": "livekit-1.8.3",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "state", ["agent_connecting", "listening", "understanding", "agent_speaking"]
)
def test_activity_accepts_allowed_states(client, session_factory, state):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=user["org_id"])

    event_type = "session_pre_start" if state == "agent_connecting" else "agent_state_changed"
    payload = _activity_payload(state=state, event_type=event_type)
    resp = client.post(
        f"/internal/calls/{call_id}/activity", json=payload, headers=INTERNAL
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    with session_factory() as db:
        events = list(
            db.scalars(
                select(CallEvent).where(
                    CallEvent.call_id == call_id, CallEvent.event_type == "voice_activity"
                )
            )
        )
        assert len(events) == 1
        assert events[0].event_type == "voice_activity"
        assert events[0].payload == payload


def test_activity_rejects_invalid_state_and_sequence(client, session_factory):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=user["org_id"])

    invalid_state = client.post(
        f"/internal/calls/{call_id}/activity",
        json=_activity_payload(state="paused"),
        headers=INTERNAL,
    )
    assert invalid_state.status_code == 422

    invalid_sequence = client.post(
        f"/internal/calls/{call_id}/activity",
        json=_activity_payload(sequence=0),
        headers=INTERNAL,
    )
    assert invalid_sequence.status_code == 422


def test_activity_requires_internal_token(client, session_factory):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=user["org_id"])

    missing = client.post(
        f"/internal/calls/{call_id}/activity", json=_activity_payload()
    )
    invalid = client.post(
        f"/internal/calls/{call_id}/activity",
        json=_activity_payload(),
        headers={"X-Internal-Token": "wrong"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_activity_unknown_call_returns_404(client):
    token, _ = register(client)
    resp = client.post(
        "/internal/calls/999999/activity", json=_activity_payload(), headers=INTERNAL
    )
    assert resp.status_code == 404


def test_activity_is_idempotent_and_rejects_conflicts(client, session_factory):
    token, user = register(client)
    with session_factory() as db:
        call_id = _seed_call(db, org_id=user["org_id"])

    first_payload = _activity_payload(sequence=2, state="listening")
    higher_payload = _activity_payload(sequence=3, state="agent_speaking")
    first = client.post(
        f"/internal/calls/{call_id}/activity", json=first_payload, headers=INTERNAL
    )
    higher = client.post(
        f"/internal/calls/{call_id}/activity", json=higher_payload, headers=INTERNAL
    )
    duplicate = client.post(
        f"/internal/calls/{call_id}/activity", json=first_payload, headers=INTERNAL
    )
    conflict = client.post(
        f"/internal/calls/{call_id}/activity",
        json=_activity_payload(sequence=2, state="understanding"),
        headers=INTERNAL,
    )
    lower = client.post(
        f"/internal/calls/{call_id}/activity",
        json=_activity_payload(sequence=1, state="agent_speaking"),
        headers=INTERNAL,
    )

    assert first.status_code == 200
    assert higher.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["activity"]["sequence"] == 2
    assert duplicate.json()["activity"]["state"] == "listening"
    assert conflict.status_code == 409
    assert lower.status_code == 409

    with session_factory() as db:
        events = list(
            db.scalars(
                select(CallEvent).where(
                    CallEvent.call_id == call_id, CallEvent.event_type == "voice_activity"
                )
            )
        )
        assert [event.payload["sequence"] for event in events] == [2, 3]
