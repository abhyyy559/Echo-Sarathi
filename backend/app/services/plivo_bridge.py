"""Plivo audio-streaming bridge primitives (pure logic, unit-testable).

routers/plivo.py keeps the websocket route thin: parse events with
parse_plivo_event and build the answer XML with build_plivo_stream_xml.

Plivo's bidirectional <Stream> uses a single websocket per call: Plivo sends
caller audio as base64 mu-law 8 kHz frames in `media` events, and your server
plays audio back with `playAudio` events on the same socket.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from urllib.parse import unquote

PLIVO_STREAM_CONTENT_TYPE = "audio/x-mulaw"
PLIVO_STREAM_SAMPLE_RATE = 8000

# Plivo writes the internal call id into the Stream XML as an extra header;
# the start frame relays it back in ``extra_headers`` so the websocket route
# can resolve our call row directly.
EXTRA_HEADER_KEY = "call_id"


@dataclass(frozen=True)
class PlivoStreamEvent:
    event: str
    stream_id: str
    call_id: str  # Plivo CallUUID (start.callId); may be empty on media frames
    internal_call_id: str  # our call id carried in extra_headers; "" if absent
    media_payload: str
    content_type: str = ""
    sample_rate: int = 0


def _parse_extra_headers(raw: Any) -> dict[str, str]:
    """Parse Plivo's ``extraHeaders="k=v;k2=v2"`` value (values URI-decoded)."""
    if not isinstance(raw, str) or not raw.strip():
        return {}
    headers: dict[str, str] = {}
    for pair in raw.split(";"):
        key, sep, value = pair.partition("=")
        if sep and key.strip():
            headers[key.strip()] = unquote(value.strip())
    return headers


def parse_plivo_event(raw: Any) -> PlivoStreamEvent:
    """Parse one Plivo audio-streaming JSON message; raise ValueError on junk.

    Media frames carry a top-level ``streamId``; the ``start`` frame carries
    both ``streamId`` and ``callId`` (the Plivo call UUID) inside ``start``
    plus the ``extra_headers`` we injected at answer time.
    """
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        msg = json.loads(str(raw))
        if not isinstance(msg, Mapping):
            raise ValueError("not an object")
        event = str(msg.get("event") or "")
        if not event:
            raise ValueError("missing event")

        start = msg.get("start") or {}
        start_map = start if isinstance(start, Mapping) else {}
        media = msg.get("media") or {}
        media_map = media if isinstance(media, Mapping) else {}

        media_format = start_map.get("mediaFormat") or {}
        fmt = media_format if isinstance(media_format, Mapping) else {}

        call_id = str(start_map.get("callId") or "")
        stream_id = str(msg.get("streamId") or start_map.get("streamId") or "")
        extra = _parse_extra_headers(msg.get("extra_headers"))
        return PlivoStreamEvent(
            event=event,
            stream_id=stream_id,
            call_id=call_id,
            internal_call_id=str(extra.get(EXTRA_HEADER_KEY) or ""),
            media_payload=str(media_map.get("payload") or ""),
            content_type=str(fmt.get("encoding") or ""),
            sample_rate=int(fmt.get("sampleRate") or 0),
        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"bad plivo event: {exc}") from exc


def build_plivo_stream_xml(media_ws_base_url: str, call_id: int) -> str:
    """Answer XML starting a bidirectional mu-law 8 kHz stream for the call."""
    ws_url = f"{media_ws_base_url.rstrip('/')}/plivo/media"
    return (
        "<Response>"
        f'<Stream bidirectional="true" keepCallAlive="true" '
        f'contentType="audio/x-mulaw;rate={PLIVO_STREAM_SAMPLE_RATE}" '
        f'extraHeaders="{EXTRA_HEADER_KEY}={call_id}">'
        f"{ws_url}"
        "</Stream>"
        "</Response>"
    )


def build_playaudio_message(payload_b64: str) -> dict[str, Any]:
    """Envelope for playing one mu-law 8 kHz audio chunk to the caller."""
    return {
        "event": "playAudio",
        "media": {
            "contentType": PLIVO_STREAM_CONTENT_TYPE,
            "sampleRate": PLIVO_STREAM_SAMPLE_RATE,
            "payload": payload_b64,
        },
    }


def build_clearaudio_message(stream_id: str = "") -> dict[str, Any]:
    """Envelope interrupting queued playAudio playback (barge-in)."""
    return {"event": "clearAudio", "streamId": stream_id}