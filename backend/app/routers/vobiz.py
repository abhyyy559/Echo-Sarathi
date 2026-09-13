"""Vobiz webhooks: answer (Voice XML + audio stream), media bridge, status.

Mounted WITHOUT the /api prefix so webhooks are reachable at
{PUBLIC_BASE_URL}/vobiz/... exactly as configured in the Call-create
answer_url. Mirrors routers/twilio.py; Vobiz event names differ (start /
media / stop inbound, playAudio outbound).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Call, Contact
from app.services.calls_service import end_call, log_call_event
from app.services.media_bridge import drain_track, make_frame, put_sentinel
from app.services.twilio_bridge import build_phone_room_token
from app.services.vobiz_bridge import build_play_audio
from app.services.vobiz_bridge import parse_vobiz_event as _parse_bridge_event
from app.timeutil import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vobiz", tags=["vobiz"])

XML_MEDIA_TYPE = "application/xml"

# Vobiz opens the websocket immediately; the start frame carries callId.
HANDSHAKE_TIMEOUT_SECONDS = 10.0

# Best-effort mapping of Vobiz status words onto our call states. Unknown
# values are logged and ignored (never crash a webhook).
VOBIZ_STATUS_MAP = {
    "ringing": "ringing",
    "in-progress": "in_progress",
    "answered": "in_progress",
    "completed": "completed",
    "no-answer": "no_answer",
    "busy": "busy",
    "failed": "failed",
    "canceled": "canceled",
    "cancelled": "canceled",
}


def _build_answer_xml(ws_base_url: str, call_id: int) -> str:
    """Voice XML bridging the call to our media websocket (mu-law 8kHz)."""
    ws_url = f"{ws_base_url}/vobiz/media?call_id={call_id}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        '<Stream bidirectional="true" keepCallAlive="true" '
        'contentType="audio/x-mulaw;rate=8000">'
        f"{ws_url}"
        "</Stream>\n"
        "</Response>"
    )


async def _payload_dict(request: Request) -> dict[str, Any]:
    """Vobiz posts JSON webhooks; tolerate form-encoded just in case."""
    try:
        body = await request.json()
        if isinstance(body, dict):
            return dict(body)
    except Exception:  # noqa: BLE001 — fall through to form parsing
        pass
    try:
        form = await request.form()
        return {str(k): v for k, v in form.items()}
    except Exception:  # noqa: BLE001
        return {}


# --- media bridge (Vobiz <-> LiveKit phone rooms) ---------------------------


async def _pump_vobiz_to_room(
    ws: WebSocket, source: Any
) -> None:
    """Decode caller mu-law frames and publish them into the LiveKit room."""
    import base64
    import binascii

    from app.services.g711 import ulaw_to_pcm16

    import array

    frames = 0
    audio_sum_sq = 0
    audio_n = 0
    audio_peak = 0
    try:
        while True:
            raw = await ws.receive_text()
            try:
                ev = _parse_bridge_event(raw)
            except ValueError:
                continue
            if ev.event == "stop":
                break
            if ev.event != "media" or not ev.media_payload:
                continue
            try:
                pcm = base64.b64decode(ev.media_payload)
            except binascii.Error:
                logger.debug("dropping non-base64 vobiz media frame")
                continue
            frames += 1
            # Heartbeat: proves inbound caller audio is actually arriving from
            # the provider (silence vs dead stream is otherwise indistinguishable).
            if frames == 1 or frames % 500 == 0:
                logger.info("vobiz inbound media frames=%d size=%d", frames, len(pcm))
            pcm16 = ulaw_to_pcm16(pcm)
            samples = array.array("h")
            try:
                samples.frombytes(pcm16)
            except ValueError:
                logger.debug("dropping odd-length vobiz media frame")
                continue
            for sample in samples:
                audio_sum_sq += sample * sample
                magnitude = abs(sample)
                if magnitude > audio_peak:
                    audio_peak = magnitude
            audio_n += len(samples)
            frame = make_frame(pcm16)
            await source.capture_frame(frame)
    finally:
        # Speech-vs-silence verdict, logged even when the pump is cancelled
        # (room disconnect kills the loop mid-wait): peak > ~2000 and
        # RMS > ~200 (16-bit scale) means real speech arrived and any failure
        # is downstream (VAD/STT). Near-zero means the provider sent silence.
        rms_avg = (audio_sum_sq / audio_n) ** 0.5 if audio_n else 0.0
        logger.info(
            "vobiz inbound audio total frames=%d rms_avg=%.1f peak=%d",
            frames, rms_avg, audio_peak,
        )


async def _pump_room_to_vobiz(
    queue: Any, ws: WebSocket, stream_id_box: dict[str, str]
) -> None:
    """Send queued agent mu-law frames to Vobiz as playAudio messages.

    Exits cleanly when any drain puts the b"" sentinel.
    """
    import asyncio
    import base64

    getter = asyncio.ensure_future(queue.get())
    try:
        while True:
            await asyncio.wait({getter})
            ulaw = getter.result()
            getter = asyncio.ensure_future(queue.get())
            if ulaw == b"":
                break
            payload = base64.b64encode(ulaw).decode()
            await ws.send_text(build_play_audio(stream_id_box.get("sid", ""), payload))
    finally:
        getter.cancel()


@router.websocket("/media")
async def vobiz_media(websocket: WebSocket) -> None:
    """Vobiz audio stream -> LiveKit phone-room bridge (one WS per call leg)."""
    import asyncio

    from livekit import rtc

    await websocket.accept()

    # Our answer XML embeds ?call_id=; fall back to matching the provider's
    # call id from the start frame against provider_call_id.
    query_call_id = str(websocket.query_params.get("call_id") or "")

    async def _close(code: int) -> None:
        try:
            await websocket.close(code=code)
        except Exception:  # noqa: BLE001
            pass

    loop = asyncio.get_running_loop()
    deadline = loop.time() + HANDSHAKE_TIMEOUT_SECONDS
    start_call_id = ""
    stream_sid = ""
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            logger.warning("vobiz media handshake timed out")
            await _close(4400)
            return
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
        except asyncio.TimeoutError:
            logger.warning("vobiz media handshake timed out")
            await _close(4400)
            return
        except WebSocketDisconnect:
            return
        try:
            ev = _parse_bridge_event(raw)
        except ValueError:
            continue
        if ev.event != "start":
            continue
        start_call_id = ev.call_id
        stream_sid = ev.stream_id
        break

    with websocket.app.state.session_factory() as db:
        call: Optional[Call] = None
        if query_call_id.isdigit():
            call = db.get(Call, int(query_call_id))
        if call is None and start_call_id:
            call = db.scalar(
                select(Call).where(Call.provider_call_id == start_call_id)
            )
        if call is None or call.agent_version_id is None:
            await _close(4404)
            return
        call_pk = int(call.id)
        contact = db.get(Contact, call.contact_id) if call.contact_id else None
        version_id = int(call.agent_version_id)
        contact_card: dict = {}
        if contact is not None:
            contact_card.update(contact.custom_fields or {})
            contact_card.setdefault("name", contact.name or "")

    settings = websocket.app.state.settings
    token, room_name = build_phone_room_token(
        settings,
        call_id=call_pk,
        version_id=version_id,
        contact={k: str(v) for k, v in contact_card.items() if v},
        identity_prefix="vobiz",
    )
    room = rtc.Room()
    stream_id_box: dict[str, str] = {"sid": stream_sid}

    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
    drains: list[asyncio.Task[None]] = []
    seen_tracks: set[Any] = set()
    room_gone = asyncio.Event()

    def _on_frame(
        track: Any, _publication: Any = None, _participant: Any = None
    ) -> None:
        key = getattr(track, "sid", None) or id(track)
        if key in seen_tracks:
            return
        seen_tracks.add(key)
        drains.append(asyncio.ensure_future(drain_track(track, queue)))

    def _on_room_disconnected(_room: Any = None) -> None:
        room_gone.set()
        put_sentinel(queue)

    room.on("track_subscribed", _on_frame)
    room.on("disconnected", _on_room_disconnected)

    logger.info("vobiz media bridge joining %s (call %s)", room_name, call_pk)
    await room.connect(settings.livekit_url_internal, token)

    for participant in list(room.remote_participants.values()):
        for publication in list(participant.track_publications.values()):
            track = publication.track
            if track is not None and track.kind == rtc.TrackKind.KIND_AUDIO:
                _on_frame(track)

    source = rtc.AudioSource(sample_rate=8000, num_channels=1)
    caller_track = rtc.LocalAudioTrack.create_audio_track(f"vobiz-{call_pk}", source)
    # The worker session only reads SOURCE_MICROPHONE tracks; a default
    # publish lands as SOURCE_UNKNOWN and is never transcribed (silent agent).
    await room.local_participant.publish_track(
        caller_track,
        rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
    )

    to_agent = asyncio.ensure_future(_pump_vobiz_to_room(websocket, source))
    from_agent = asyncio.ensure_future(_pump_room_to_vobiz(queue, websocket, stream_id_box))
    room_gone_waiter = asyncio.ensure_future(room_gone.wait())
    tasks: tuple[asyncio.Future[Any], ...] = (to_agent, from_agent, room_gone_waiter)
    try:
        await asyncio.wait(set(tasks), return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (*tasks, *drains):
            task.cancel()
        await asyncio.gather(*tasks, *drains, return_exceptions=True)
        try:
            await room.disconnect()
        except Exception:  # noqa: BLE001
            logger.warning("room disconnect failed for %s", room_name, exc_info=True)
        # The media leg ending IS the call ending (Vobiz sends no separate
        # completion callback on this path) — never leave the row stuck in
        # a live status, or it vanishes from reports.
        try:
            with websocket.app.state.session_factory() as db:
                done_call = db.get(Call, call_pk)
                if done_call is not None and done_call.status not in (
                    "completed", "failed", "canceled", "no_answer", "busy",
                ):
                    done_call.status = "completed"
                    if done_call.ended_at is None:
                        done_call.ended_at = utcnow()
                    db.commit()
        except Exception:  # noqa: BLE001 — finalize best-effort only
            logger.warning("finalize-on-close failed for call %s", call_pk, exc_info=True)


@router.post("/answer")
async def vobiz_answer(
    request: Request,
    call_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Answer webhook: return Voice XML bridging the call to the media stream."""
    payload = await _payload_dict(request)

    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="unknown call_id")

    now = utcnow()
    if call.status not in ("in_progress", "completed"):
        call.status = "in_progress"
    if call.answered_at is None:
        call.answered_at = now
    contact = db.get(Contact, call.contact_id)
    if contact is not None and contact.status != "completed":
        contact.status = "calling"
    # Record the raw payload: first live call reveals Vobiz's exact field
    # names, and this log is how we confirm them.
    log_call_event(db, call.id, "vobiz_answer", payload)
    db.commit()

    settings = request.app.state.settings
    xml = _build_answer_xml(settings.media_ws_base_url, call_id)
    return Response(content=xml, media_type=XML_MEDIA_TYPE)


@router.post("/status")
async def vobiz_status(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Status callback: best-effort mapping onto call/contact state."""
    payload = await _payload_dict(request)

    provider_id = str(
        payload.get("callSid")
        or payload.get("CallSid")
        or payload.get("callId")
        or payload.get("call_id")
        or ""
    )
    raw_status = str(
        payload.get("status") or payload.get("callStatus") or payload.get("event") or ""
    ).lower()

    call = (
        db.scalar(select(Call).where(Call.provider_call_id == provider_id))
        if provider_id
        else None
    )
    if call is None:
        logger.warning("vobiz status webhook for unknown call: %s", payload)
        return Response(status_code=200)

    log_call_event(db, call.id, f"vobiz_status:{raw_status or 'unknown'}", payload)

    mapped = VOBIZ_STATUS_MAP.get(raw_status, "")
    now = utcnow()
    contact = db.get(Contact, call.contact_id)
    if mapped == "in_progress":
        call.status = "in_progress"
        if call.answered_at is None:
            call.answered_at = now
        if contact is not None:
            contact.status = "calling"
    elif mapped in ("queued", "ringing"):
        if call.status == "queued":
            call.status = mapped
    elif mapped in ("completed", "no_answer", "busy", "failed", "canceled"):
        if call.status != "completed":
            settings = request.app.state.settings
            if contact is not None:
                end_call(db, call, contact, mapped, settings, now=now)
            else:
                call.status = mapped
                call.ended_at = now
    db.commit()
    return Response(status_code=200)
