"""Plivo webhooks: voice (Stream XML), status callbacks, recordings, media WS.

Mounted WITHOUT the /api prefix so they are reachable at
{PUBLIC_BASE_URL}/plivo/... exactly as configured on Plivo's number/answer
URLs.

Calls bridge through a single bidirectional <Stream> websocket: Plivo sends
caller audio as base64 mu-law 8 kHz frames in `media` events, and we play agent
audio back on the same socket as `playAudio` events. The internal call id is
carried from answer-time XML (extraHeaders) into the start frame's
extra_headers, so the websocket route can resolve our call row directly.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
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
from app.services.calls_service import PLIVO_STATUS_MAP, end_call, log_call_event
from app.services.media_bridge import drain_track, make_frame, put_sentinel
from app.services.plivo_bridge import (
    build_clearaudio_message,
    build_playaudio_message,
    build_plivo_stream_xml,
    parse_plivo_event,
)
from app.services.twilio_bridge import build_phone_room_token
from app.timeutil import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plivo", tags=["plivo"])

XML_MEDIA_TYPE = "application/xml"

# Plivo opens the socket right after answering; the handshake must tolerate
# junk before the mandatory "start" frame but cannot wait forever.
HANDSHAKE_TIMEOUT_SECONDS = 10.0


async def _check_signature(request: Request, form) -> None:  # type: ignore[no-untyped-def]
    """Validate X-Plivo-Signature-V3 when PLIVO_VALIDATE_SIGNATURE is enabled."""
    settings = request.app.state.settings
    if not getattr(settings, "plivo_validate_signature", False):
        return
    try:
        from plivo.utils.signature_v3 import validate_v3_signature
    except ImportError:  # pragma: no cover - SDK layout varies by version
        from plivo.utils import validate_v3_signature  # type: ignore[no-redef]

    signature = request.headers.get("X-Plivo-Signature-V3", "")
    nonce = request.headers.get("X-Plivo-Signature-V3-Nonce", "")
    uri = str(request.url).split("?", 1)[0]
    if not validate_v3_signature("POST", uri, nonce, settings.plivo_auth_token, signature, dict(form)):
        raise HTTPException(status_code=403, detail="invalid Plivo signature")


# --- media bridge (Plivo <-> LiveKit phone rooms) -----------------------------


async def _pump_plivo_to_room(ws: WebSocket, source: Any) -> None:
    """Decode caller mu-law frames and publish them into the LiveKit room."""
    from app.services.g711 import ulaw_to_pcm16

    while True:
        raw = await ws.receive_text()
        try:
            ev = parse_plivo_event(raw)
        except ValueError:
            continue
        if ev.event == "stop":
            break
        if ev.event != "media" or not ev.media_payload:
            continue
        try:
            pcm = base64.b64decode(ev.media_payload)
        except binascii.Error:
            logger.debug("dropping non-base64 plivo media frame")
            continue
        frame = make_frame(ulaw_to_pcm16(pcm))
        await source.capture_frame(frame)


async def _pump_room_to_plivo(queue: Any, ws: WebSocket) -> None:
    """Send queued agent mu-law frames to Plivo as playAudio events.

    Exits cleanly when any drain puts the b"" sentinel (track ended,
    participant gone, room disconnected).
    """
    getter = asyncio.ensure_future(queue.get())
    try:
        while True:
            await asyncio.wait({getter})
            ulaw = getter.result()
            getter = asyncio.ensure_future(queue.get())
            if ulaw == b"":
                break
            payload = base64.b64encode(ulaw).decode()
            await ws.send_text(json.dumps(build_playaudio_message(payload)))
    finally:
        getter.cancel()


@router.websocket("/media")
async def plivo_media(websocket: WebSocket) -> None:
    """Plivo stream -> LiveKit phone-room bridge (one WS per call leg)."""
    from livekit import rtc

    await websocket.accept()
    settings = websocket.app.state.settings

    async def _close(code: int) -> None:
        try:
            await websocket.close(code=code)
        except Exception:  # noqa: BLE001
            pass

    # --- handshake: read until the mandatory `start` event (10s deadline) ----
    internal_call_id = ""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + HANDSHAKE_TIMEOUT_SECONDS
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            logger.warning("plivo media handshake timed out")
            await _close(4400)
            return
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
        except asyncio.TimeoutError:
            logger.warning("plivo media handshake timed out")
            await _close(4400)
            return
        except WebSocketDisconnect:
            return
        try:
            ev = parse_plivo_event(raw)
        except ValueError:
            continue  # tolerate unparseable junk before start
        if ev.event != "start":
            await _close(4400)
            return
        internal_call_id = ev.internal_call_id
        if not internal_call_id:
            await _close(4400)
            return
        try:
            call_pk = int(internal_call_id)
        except ValueError:
            await _close(4400)
            return
        break

    with websocket.app.state.session_factory() as db:
        call = db.get(Call, call_pk)
        if call is None or call.agent_version_id is None:
            await _close(4404)
            return
        if ev.call_id and ev.call_id != call.provider_call_id:
            logger.warning("CallUUID mismatch on media bridge for call %s", call_pk)
        contact = db.get(Contact, call.contact_id) if call.contact_id else None
        version_id = int(call.agent_version_id)
        contact_card: dict = {}
        if contact is not None:
            contact_card.update(contact.custom_fields or {})
            contact_card.setdefault("name", contact.name or "")

    token, room_name = build_phone_room_token(
        settings,
        call_id=call_pk,
        version_id=version_id,
        contact={k: str(v) for k, v in contact_card.items() if v},
        identity_prefix="plivo",
    )
    room = rtc.Room()

    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
    drains: list[asyncio.Task[None]] = []
    seen_tracks: set[Any] = set()
    room_gone = asyncio.Event()

    def _on_frame(
        track: Any, _publication: Any = None, _participant: Any = None
    ) -> None:
        key = getattr(track, "sid", None) or id(track)
        if key in seen_tracks:
            return  # belt-and-braces scan may double-report an existing track
        seen_tracks.add(key)
        drains.append(asyncio.ensure_future(drain_track(track, queue)))

    def _on_room_disconnected(_room: Any = None) -> None:
        room_gone.set()
        _put_sentinel(queue)

    # Register BEFORE connect so no track_subscribed event can be missed.
    room.on("track_subscribed", _on_frame)
    room.on("disconnected", _on_room_disconnected)

    logger.info("media bridge joining %s (call %s)", room_name, internal_call_id)
    await room.connect(settings.livekit_url_internal, token)

    # Belt-and-braces: feed tracks already published before we finished joining.
    for participant in list(room.remote_participants.values()):
        for publication in list(participant.track_publications.values()):
            track = publication.track
            if track is not None and track.kind == rtc.TrackKind.KIND_AUDIO:
                _on_frame(track)

    source = rtc.AudioSource(sample_rate=8000, num_channels=1)
    caller_track = rtc.LocalAudioTrack.create_audio_track(f"plivo-{call_pk}", source)
    # Worker sessions only read SOURCE_MICROPHONE tracks (see vobiz.py).
    await room.local_participant.publish_track(
        caller_track,
        rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
    )

    to_agent = asyncio.ensure_future(_pump_plivo_to_room(websocket, source))
    from_agent = asyncio.ensure_future(_pump_room_to_plivo(queue, websocket))
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


# --- HTTP webhooks ------------------------------------------------------------


@router.post("/voice")
async def plivo_voice(
    request: Request,
    call_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Answer webhook: return XML that streams the call to the media bridge."""
    form = await request.form()
    await _check_signature(request, form)

    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="unknown call_id")

    call_uuid: Optional[str] = form.get("CallUUID")
    if call_uuid and call.provider_call_id != call_uuid:
        call.provider_call_id = call_uuid  # replace request_uuid with real CallUUID

    now = utcnow()
    if call.status not in ("in_progress", "completed"):
        call.status = "in_progress"
    if call.answered_at is None:
        call.answered_at = now
    contact = db.get(Contact, call.contact_id)
    if contact is not None and contact.status != "completed":
        contact.status = "calling"
    log_call_event(db, call.id, "plivo_voice_webhook", {"CallUUID": call_uuid})
    db.commit()

    settings = request.app.state.settings
    xml = build_plivo_stream_xml(settings.media_ws_base_url, call_id)
    return Response(content=xml, media_type=XML_MEDIA_TYPE)


@router.post("/status")
async def plivo_status(
    request: Request,
    call_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> Response:
    """Status callback: map Plivo events onto call/contact/campaign state.

    The call is resolved by the internal call_id query param first (set on the
    ring/hangup URLs at callback time), falling back to provider_call_id when
    the param is absent.
    """
    form = await request.form()
    await _check_signature(request, form)

    call_uuid: Optional[str] = form.get("CallUUID")
    call_status: Optional[str] = form.get("CallStatus")
    call_duration: Optional[str] = form.get("CallDuration")

    call: Optional[Call] = db.get(Call, call_id) if call_id is not None else None
    if call is None and call_uuid:
        call = db.scalar(select(Call).where(Call.provider_call_id == call_uuid))
    if call is None:
        logger.warning("status webhook for unknown CallUUID=%s", call_uuid)
        return Response(status_code=200)

    if call_uuid and call.provider_call_id != call_uuid:
        call.provider_call_id = call_uuid

    log_call_event(db, call.id, f"plivo_status:{call_status}", dict(form))

    mapped = PLIVO_STATUS_MAP.get(str(call_status), "")
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
        if call.status not in ("completed",):  # allow late webhooks after completion
            duration = float(call_duration) if call_duration else None
            settings = request.app.state.settings
            if contact is not None:
                end_call(db, call, contact, mapped, settings, now=now, duration_seconds=duration)
            else:
                call.status = mapped
                call.ended_at = now
                call.duration_seconds = duration

    db.commit()
    return Response(status_code=200)


@router.post("/recording")
async def plivo_recording(
    request: Request,
    call_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> Response:
    """Recording webhook: persist the recording URL."""
    form = await request.form()
    await _check_signature(request, form)

    call_uuid: Optional[str] = form.get("CallUUID")
    recording_url: Optional[str] = form.get("RecordingUrl")
    call: Optional[Call] = db.get(Call, call_id) if call_id is not None else None
    if call is None and call_uuid:
        call = db.scalar(select(Call).where(Call.provider_call_id == call_uuid))
    if call is not None and recording_url:
        call.recording_url = recording_url
        log_call_event(
            db,
            call.id,
            "plivo_recording",
            {"RecordingUrl": recording_url, "RecordingID": form.get("RecordingID")},
        )
        db.commit()
    else:
        logger.warning("recording webhook for unknown CallUUID=%s", call_uuid)
    return Response(status_code=200)