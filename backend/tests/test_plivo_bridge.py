"""Pure logic for the Plivo media bridge: event parsing + XML/audio builders."""
import base64
import json

import pytest

from app.services.plivo_bridge import (
    build_clearaudio_message,
    build_plivo_stream_xml,
    build_playaudio_message,
    parse_plivo_event,
)


def _media_frame() -> str:
    return base64.b64encode(bytes([0xFF]) * 320).decode()


def _start_frame(
    call_uuid: str = "8c43a765-94fa-4ee9-b9a3-242703e41f63",
    stream_id: str = "str_001",
    internal_call_id: str = "42",
) -> str:
    extra_headers = f"call_id={internal_call_id}" if internal_call_id else ""
    return json.dumps(
        {
            "sequenceNumber": 0,
            "event": "start",
            "start": {
                "callId": call_uuid,
                "streamId": stream_id,
                "accountId": "155747",
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
            },
            "extra_headers": extra_headers,
        }
    )


def test_parse_start_frame():
    ev = parse_plivo_event(_start_frame())
    assert ev.event == "start"
    assert ev.stream_id == "str_001"
    assert ev.call_id == "8c43a765-94fa-4ee9-b9a3-242703e41f63"
    assert ev.internal_call_id == "42"
    assert ev.content_type == "audio/x-mulaw"
    assert ev.sample_rate == 8000
    assert ev.media_payload == ""


def test_parse_start_without_extra_headers():
    ev = parse_plivo_event(_start_frame(internal_call_id=""))
    assert ev.event == "start"
    assert ev.internal_call_id == ""


def test_parse_media_event():
    raw = json.dumps(
        {
            "sequenceNumber": 887,
            "streamId": "str_001",
            "event": "media",
            "media": {"track": "inbound", "payload": _media_frame()},
        }
    )
    ev = parse_plivo_event(raw)
    assert ev.event == "media"
    assert ev.stream_id == "str_001"
    assert ev.media_payload == _media_frame()


def test_parse_stop_event():
    ev = parse_plivo_event(
        json.dumps({"event": "stop", "streamId": "str_001", "sequenceNumber": 100})
    )
    assert ev.event == "stop"


def test_parse_junk_raises_valueerror():
    with pytest.raises(ValueError):
        parse_plivo_event("not json")


def test_build_plivo_stream_xml():
    xml = build_plivo_stream_xml("wss://backend.example.test", call_id=42)
    assert xml.startswith("<Response>")
    assert xml.endswith("</Response>")
    assert 'bidirectional="true"' in xml
    assert 'keepCallAlive="true"' in xml
    assert 'contentType="audio/x-mulaw;rate=8000"' in xml
    assert 'extraHeaders="call_id=42"' in xml
    assert "wss://backend.example.test/plivo/media" in xml


def test_build_playaudio_message():
    assert build_playaudio_message("aGVsbG8=") == {
        "event": "playAudio",
        "media": {
            "contentType": "audio/x-mulaw",
            "sampleRate": 8000,
            "payload": "aGVsbG8=",
        },
    }


def test_build_clearaudio_message():
    msg = build_clearaudio_message(stream_id="str_001")
    assert msg["event"] == "clearAudio"
    assert msg["streamId"] == "str_001"