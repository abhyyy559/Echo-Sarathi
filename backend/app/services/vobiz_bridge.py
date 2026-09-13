"""Vobiz audio-stream bridge primitives (pure logic, unit-testable).

Vobiz event shapes (docs.vobiz.ai, XML <Stream> bidirectional):
- start: {"event": "start", "start": {"callId", "streamId", "mediaFormat": {...}}}
- media: {"event": "media", "media": {"payload": base64 mu-law 8kHz}}
- stop:  {"event": "stop"}
Outbound (us -> Vobiz): {"event": "playAudio", "streamId": ...,
"media": {"contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": ...}}

routers/vobiz.py keeps the websocket route thin, mirroring routers/twilio.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

PHONE_ROOM_PREFIX = "phone-"


@dataclass(frozen=True)
class VobizMediaEvent:
    event: str
    stream_id: str
    media_payload: str
    call_id: str


def parse_vobiz_event(raw: Any) -> VobizMediaEvent:
    """Parse one Vobiz stream JSON message; raise ValueError on junk."""
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
        call_id = ""
        stream_id = str(msg.get("streamId") or msg.get("stream_id") or "")
        if isinstance(start, Mapping):
            call_id = str(start.get("callId") or start.get("call_id") or "")
            stream_id = stream_id or str(start.get("streamId") or "")
        media = msg.get("media") or {}
        payload = ""
        if isinstance(media, Mapping):
            payload = str(media.get("payload") or "")
        return VobizMediaEvent(
            event=event,
            stream_id=stream_sid_norm(stream_id, msg),
            media_payload=payload,
            call_id=call_id,
        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"bad vobiz event: {exc}") from exc


def stream_sid_norm(stream_id: str, msg: Mapping[str, Any]) -> str:
    """Stream id may arrive top-level or inside start; prefer either."""
    if stream_id:
        return stream_id
    start = msg.get("start") or {}
    if isinstance(start, Mapping):
        return str(start.get("streamId") or start.get("stream_id") or "")
    return ""


def build_play_audio(stream_id: str, ulaw_b64: str) -> str:
    """One outbound playAudio frame (mu-law 8kHz, base64, no container)."""
    return json.dumps(
        {
            "event": "playAudio",
            "streamId": stream_id,
            "media": {
                "contentType": "audio/x-mulaw",
                "sampleRate": 8000,
                "payload": ulaw_b64,
            },
        }
    )
