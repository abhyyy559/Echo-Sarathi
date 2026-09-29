"""Pure logic for the Twilio media bridge: event parsing + room token minting."""
import base64
import json
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from app.models import Agent, AgentVersion, Call, Organization
from app.services.twilio_bridge import (
    PHONE_ROOM_PREFIX,
    build_phone_room_token,
    parse_stream_event,
)

from conftest import make_settings


def _media_frame() -> str:
    return base64.b64encode(bytes([0xFF]) * 160).decode()


def _start_frame(call_id: Any = "42", call_sid: str = "CAfixed123", bridge_token: str | None = "valid") -> str:
    from app.services.media_bridge import build_bridge_token

    if bridge_token == "valid":
        bridge_token = build_bridge_token(call_id, "test_internal_token")
    return json.dumps(
        {
            "event": "start",
            "streamSid": "MZ1234567890",
            "start": {
                "streamSid": "MZ1234567890",
                "callSid": call_sid,
                "customParameters": {"call_id": str(call_id), "bridge_token": bridge_token},
            },
        }
    )


def test_parse_media_event():
    raw = json.dumps(
        {
            "event": "media",
            "streamSid": "MZ1234567890",
            "media": {"payload": _media_frame()},
        }
    )
    ev = parse_stream_event(raw)
    assert ev.event == "media"
    assert ev.stream_sid == "MZ1234567890"
    assert ev.media_payload == _media_frame()


def test_parse_start_carries_call_id_parameter():
    ev = parse_stream_event(_start_frame())
    assert ev.event == "start"
    assert ev.call_id == "42"
    assert ev.call_sid == "CAfixed123"


def test_parse_start_legacy_parameters_fallback():
    raw = json.dumps(
        {
            "event": "start",
            "streamSid": "MZ1234567890",
            "start": {"streamSid": "MZ1234567890", "parameters": {"call_id": "42"}},
        }
    )
    ev = parse_stream_event(raw)
    assert ev.event == "start"
    assert ev.call_id == "42"
    assert ev.call_sid == ""


def test_parse_junk_raises_valueerror():
    import pytest

    with pytest.raises(ValueError):
        parse_stream_event("not json")


def test_build_phone_room_token_shape():
    settings = make_settings(livekit_api_key="devkey", livekit_api_secret="devsecret")
    token, room = build_phone_room_token(
        settings, call_id=84, version_id=3, contact={"student_name": "Aarav"}
    )
    assert room == f"{PHONE_ROOM_PREFIX}84"
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert claims["iss"] == "devkey"
    assert '"call_id": "84"' in claims["metadata"]
    assert claims["video"]["room"] == room


# --- websocket route: handshake + callSid binding ----------------------------


def _seed_call(session_factory: Any, provider_call_id: str = "CAfixed123") -> int:
    """Minimal org->agent->version->call chain; returns the call id."""
    with session_factory() as db:
        org = Organization(name="Bridge Org", slug="bridge-org")
        db.add(org)
        db.flush()
        agent = Agent(org_id=org.id, name="Phone Agent")
        db.add(agent)
        db.flush()
        version = AgentVersion(
            agent_id=agent.id,
            version=1,
            system_prompt="You call parents about absences.",
            disclosure_script="Hello, this is an automated call.",
        )
        db.add(version)
        db.flush()
        call = Call(
            agent_version_id=version.id,
            provider_call_id=provider_call_id,
            status="ringing",
        )
        db.add(call)
        db.commit()
        return int(call.id)


def test_wrong_callsid_rejected_4403(client, session_factory):
    call_id = _seed_call(session_factory)
    with client.websocket_connect("/twilio/media") as ws:
        ws.send_text(json.dumps({"event": "connected"}))
        ws.send_text(_start_frame(call_id=call_id, call_sid="CAWRONG"))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4403


def test_handshake_skips_connected_and_junk_then_closes_on_non_start(client):
    with client.websocket_connect("/twilio/media") as ws:
        ws.send_text("total garbage")  # unparseable junk is skipped
        ws.send_text(json.dumps({"event": "connected"}))  # mandatory greeting
        ws.send_text(json.dumps({"event": "stop", "streamSid": "MZ1"}))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4400


def test_forged_bridge_token_rejected_4403(client, session_factory):
    call_id = _seed_call(session_factory)
    with client.websocket_connect("/twilio/media") as ws:
        ws.send_text(json.dumps({"event": "connected"}))
        ws.send_text(_start_frame(call_id=call_id, bridge_token="forged"))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4403
