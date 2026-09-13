"""Twilio Media Streams bridge primitives (pure logic, unit-testable).

routers/twilio.py keeps the websocket route thin: parse events with
parse_stream_event, mint one room token per stream via build_phone_room_token.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

PHONE_ROOM_PREFIX = "phone-"


@dataclass(frozen=True)
class MediaEvent:
    event: str
    stream_sid: str
    media_payload: str
    call_id: str
    call_sid: str = ""


def parse_stream_event(raw: Any) -> MediaEvent:
    """Parse one Twilio Media Streams JSON message; raise ValueError on junk."""
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
        params: Mapping[str, Any] = {}
        call_sid = ""
        if isinstance(start, Mapping):
            # Real start frames carry call_id in customParameters; keep the
            # legacy flat `parameters` key as a fallback.
            custom = start.get("customParameters")
            if isinstance(custom, Mapping):
                params = custom
            else:
                legacy = start.get("parameters")
                params = legacy if isinstance(legacy, Mapping) else {}
            call_sid = str(start.get("callSid") or "")
        media = msg.get("media") or {}
        return MediaEvent(
            event=event,
            stream_sid=str(msg.get("streamSid") or ""),
            media_payload=str(media.get("payload") or "") if isinstance(media, Mapping) else "",
            call_id=str(params.get("call_id") or "") if isinstance(params, Mapping) else "",
            call_sid=call_sid,
        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"bad twilio event: {exc}") from exc


def build_phone_room_token(
    settings: Any,
    *,
    call_id: int,
    version_id: int,
    contact: Mapping[str, Any],
    identity_prefix: str = "twilio",
) -> tuple[str, str]:
    """Mint a join token for the phone room carrying pipeline metadata."""
    from livekit import api as livekit_api

    room_name = f"{PHONE_ROOM_PREFIX}{call_id}"
    metadata = json.dumps(
        {"version_id": version_id, "call_id": str(call_id), "contact": dict(contact)}
    )
    token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"{identity_prefix}-{str(call_id)[-8:]}")
        .with_metadata(metadata)
        .with_grants(livekit_api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )
    return token, room_name
