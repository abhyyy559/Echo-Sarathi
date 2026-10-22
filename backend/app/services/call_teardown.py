"""Closing a live call: drop the carrier leg, then release the room.

The answer XML we hand the provider is a bare bidirectional ``<Stream>`` with
``keepCallAlive="true"``, so the carrier keeps the PSTN leg up after the agent
has said goodbye. Nothing in the conversation path ends it: the caller hears a
dead line, or the agent keeps chatting because no one told the session to stop.
Two actions close a call for real, in this order:

1. provider hangup by leg id (the only thing the caller can hear), and
2. LiveKit room delete, which disconnects the media bridge and the worker job
   (freeing its concurrency slot for the next dial in a campaign).

Both are best-effort and must never raise into a teardown path.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.config import Settings
from app.models import Call
from app.services.telephony import TelephonyClient, hangup_provider_call
from app.services.twilio_bridge import PHONE_ROOM_PREFIX

logger = logging.getLogger(__name__)


def hangup_carrier_leg(
    telephony: Optional[TelephonyClient],
    call: Call,
    *,
    reason: str,
) -> bool:
    """Ask the provider to end the leg for ``call``. False when not attempted."""
    if telephony is None:
        return False
    leg_id = str(call.provider_call_id or "").strip()
    if not leg_id:
        logger.info("no provider leg id for call %s (%s), skip hangup", call.id, reason)
        return False
    hung_up = hangup_provider_call(telephony, leg_id)
    logger.info(
        "carrier hangup call=%s leg=%s reason=%s ok=%s",
        call.id,
        leg_id,
        reason,
        hung_up,
    )
    return hung_up


def _delete_room(settings: Settings, room_name: str) -> bool:
    from livekit import api as livekit_api

    async def _run() -> None:
        client = livekit_api.LiveKitAPI(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret,
        )
        try:
            await client.room.delete_room(livekit_api.DeleteRoomRequest(room=room_name))
        finally:
            await client.aclose()

    try:
        asyncio.run(_run())
    except Exception:  # noqa: BLE001 - the leg is already down; this is cleanup
        logger.warning("Could not delete room %s", room_name, exc_info=True)
        return False
    return True


def room_for_call(call: Call) -> Optional[str]:
    """The LiveKit room a phone call runs in; None for browser playground legs."""
    if str(call.kind or "") == "playground":
        return None
    return f"{PHONE_ROOM_PREFIX}{call.id}"


def close_call_media(
    settings: Settings,
    telephony: Optional[TelephonyClient],
    call: Call,
    *,
    room_name: Optional[str] = None,
    reason: str,
) -> dict[str, Any]:
    """End the carrier leg and release the room. Returns what was attempted."""
    hung_up = hangup_carrier_leg(telephony, call, reason=reason)
    room = room_name or room_for_call(call)
    room_closed = _delete_room(settings, room) if room else False
    return {"hangup": hung_up, "room": room, "room_closed": room_closed}
