"""Plivo webhook routes: answer XML, status mapping, recording, media-WS rejects."""
import json
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from app.models import Agent, AgentVersion, Call, Campaign, Contact, DomainConfig, Organization


def _seed_call(
    session_factory: Any,
    provider_call_id: str = "PN-uuid-1",
    *,
    with_agent_version: bool = True,
) -> tuple[int, int]:
    """Minimal domain->campaign->contact->call chain; returns (call_id, contact_id)."""
    with session_factory() as db:
        dc = DomainConfig(name=f"cfg-{provider_call_id}", version=1, config={})
        db.add(dc)
        db.flush()
        campaign = Campaign(
            name=f"campaign-{provider_call_id}",
            domain_config_id=dc.id,
            status="running",
        )
        db.add(campaign)
        db.flush()
        contact = Contact(
            campaign_id=campaign.id,
            name="Aarav",
            phone="+910000000000",
            status="pending_review",
            consent=True,
            consent_source="test",
        )
        db.add(contact)
        db.flush()
        version_id = None
        if with_agent_version:
            org = Organization(name=f"org-{provider_call_id}", slug=f"org-{provider_call_id}")
            db.add(org)
            db.flush()
            agent = Agent(org_id=org.id, name="Plivo Agent")
            db.add(agent)
            db.flush()
            version = AgentVersion(
                agent_id=agent.id,
                version=1,
                system_prompt="You call about absences.",
                disclosure_script="Hello, this is an automated call.",
            )
            db.add(version)
            db.flush()
            version_id = int(version.id)
        call = Call(
            campaign_id=campaign.id,
            contact_id=contact.id,
            agent_version_id=version_id,
            provider_call_id=provider_call_id,
            status="ringing",
        )
        db.add(call)
        db.commit()
        return int(call.id), int(contact.id)


def _start_frame(call_uuid: str = "8c43a765-94fa-4ee9-b9a3-242703e41f63", internal_call_id: str = "42") -> str:
    return json.dumps(
        {
            "sequenceNumber": 0,
            "event": "start",
            "start": {
                "callId": call_uuid,
                "streamId": "str_001",
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
            },
            "extra_headers": f"call_id={internal_call_id}",
        }
    )


def _get_call(session_factory: Any, call_id: int) -> Call:
    with session_factory() as db:
        return db.get(Call, call_id)


# --- voice (answer) webhook ---------------------------------------------------


def test_voice_unknown_call_404(client):
    assert client.post("/plivo/voice", params={"call_id": 424242}).status_code == 404


def test_voice_returns_stream_xml_and_marks_in_progress(client, session_factory):
    call_id, contact_id = _seed_call(session_factory)
    resp = client.post(
        "/plivo/voice",
        params={"call_id": call_id},
        data={"CallUUID": "PN-uuid-1", "CallStatus": "in-progress"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert 'bidirectional="true"' in resp.text
    assert 'keepCallAlive="true"' in resp.text
    assert "/plivo/media" in resp.text

    call = _get_call(session_factory, call_id)
    assert call.status == "in_progress"
    assert call.answered_at is not None
    with session_factory() as db:
        contact = db.get(Contact, contact_id)
        assert contact.status == "calling"


def test_voice_replaces_request_uuid_with_calluuid(client, session_factory):
    call_id, _ = _seed_call(session_factory, provider_call_id="req-uuid-1")
    client.post(
        "/plivo/voice", params={"call_id": call_id}, data={"CallUUID": "PN-uuid-1"}
    )
    assert _get_call(session_factory, call_id).provider_call_id == "PN-uuid-1"


# --- status webhook -----------------------------------------------------------


def test_status_ringing_links_calluuid(client, session_factory):
    call_id, _ = _seed_call(session_factory, provider_call_id="req-uuid-1")
    resp = client.post(
        "/plivo/status",
        params={"call_id": call_id},
        data={"CallUUID": "PN-uuid-1", "CallStatus": "ringing"},
    )
    assert resp.status_code == 200
    call = _get_call(session_factory, call_id)
    assert call.status == "ringing"
    assert call.provider_call_id == "PN-uuid-1"


def test_status_completed_updates_call_and_contact(client, session_factory):
    call_id, contact_id = _seed_call(session_factory)
    resp = client.post(
        "/plivo/status",
        params={"call_id": call_id},
        data={"CallUUID": "PN-uuid-1", "CallStatus": "completed", "CallDuration": "42"},
    )
    assert resp.status_code == 200
    call = _get_call(session_factory, call_id)
    assert call.status == "completed"
    assert call.duration_seconds == 42.0
    assert call.ended_at is not None
    with session_factory() as db:
        assert db.get(Contact, contact_id).status == "completed"


def test_status_lookup_by_calluuid_without_query_param(client, session_factory):
    call_id, _ = _seed_call(session_factory)
    resp = client.post(
        "/plivo/status",
        data={"CallUUID": "PN-uuid-1", "CallStatus": "completed", "CallDuration": "10"},
    )
    assert resp.status_code == 200
    assert _get_call(session_factory, call_id).status == "completed"


def test_status_unknown_calluuid_is_noop(client):
    resp = client.post(
        "/plivo/status", data={"CallUUID": "nope", "CallStatus": "completed"}
    )
    assert resp.status_code == 200


# --- recording webhook --------------------------------------------------------


def test_recording_persists_url(client, session_factory):
    call_id, _ = _seed_call(session_factory)
    resp = client.post(
        "/plivo/recording",
        params={"call_id": call_id},
        data={
            "CallUUID": "PN-uuid-1",
            "RecordingID": "rec-1",
            "RecordingUrl": "https://s3.plivo.com/rec.mp3",
        },
    )
    assert resp.status_code == 200
    assert _get_call(session_factory, call_id).recording_url == "https://s3.plivo.com/rec.mp3"


# --- media websocket reject paths ---------------------------------------------


def test_media_junk_and_non_start_close_4400(client):
    with client.websocket_connect("/plivo/media") as ws:
        ws.send_text("total garbage")
        ws.send_text(json.dumps({"event": "dtmf", "streamId": "s1", "dtmf": {"digit": "1"}}))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4400


def test_media_unknown_internal_call_close_4404(client, session_factory):
    _seed_call(session_factory)
    with client.websocket_connect("/plivo/media") as ws:
        ws.send_text(_start_frame(internal_call_id="424242"))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4404


def test_media_call_without_agent_version_close_4404(client, session_factory):
    call_id, _ = _seed_call(session_factory, with_agent_version=False)
    with client.websocket_connect("/plivo/media") as ws:
        ws.send_text(_start_frame(internal_call_id=str(call_id)))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4404