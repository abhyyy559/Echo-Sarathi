"""Internal API tests: extracted-fields wire shape + call context enrichment.

The voice-agent posts extracted fields with ``field_name``/``field_value``
rows; the backend must accept that shape (and the legacy ``name``/``value``
shape), persist accepted rows, and skip placeholder values.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Call, Campaign, ExtractedField, Organization
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