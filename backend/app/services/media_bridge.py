"""Shared phone-bridge helpers (pure audio plumbing for twilio/plivo routers).

The provider routers (twilio.py, plivo.py) keep their provider-specific pump
loops; everything identical across providers lives here: LiveKit AudioFrame
construction, end-of-stream queue sentinels, and remote-track draining into a
shared queue as 8 kHz mu-law bytes.
"""
from __future__ import annotations

import asyncio
from typing import Any


def make_frame(pcm16_8k: bytes) -> Any:
    """Build an rtc.AudioFrame from 16-bit LE PCM at 8 kHz."""
    from livekit import rtc

    if hasattr(rtc.AudioFrame, "from_s16"):
        return rtc.AudioFrame.from_s16(pcm16_8k, sample_rate=8000, num_channels=1)
    return rtc.AudioFrame(
        data=pcm16_8k,
        samples_per_channel=len(pcm16_8k) // 2,
        sample_rate=8000,
        num_channels=1,
    )


def put_sentinel(queue: Any) -> None:
    """Enqueue the b"" end-of-stream sentinel, dropping backlog if full."""
    try:
        queue.put_nowait(b"")
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(b"")
        except asyncio.QueueFull:
            pass


def build_bridge_token(call_id: Any, secret: str) -> str:
    """Per-call media-bridge token: HMAC-SHA256(call_id) hex (truncated).

    Minted when the answer XML is built, verified on websocket handshake, so
    only the provider leg we actually placed can join the LiveKit phone room.
    """
    import hashlib
    import hmac

    return hmac.new(
        str(secret or "").encode(), str(call_id).encode(), hashlib.sha256
    ).hexdigest()[:32]


def verify_bridge_token(token: Any, call_id: Any, secret: str) -> bool:
    """Constant-time check of a presented bridge token.

    Empty secret (tests / local dev without INTERNAL_API_TOKEN) accepts with
    no check — real protection requires the internal token to be set.
    """
    import hmac

    if not secret:
        return True
    presented = str(token or "")
    if not presented:
        return False
    return hmac.compare_digest(presented, build_bridge_token(call_id, secret))


async def drain_track(track: Any, queue: Any) -> None:
    """Forward one subscribed remote audio track into the bridge queue.

    Resamples to 8 kHz with a proper low-pass (not naive decimation) and
    encodes to mu-law; drops frames when the queue is full (live caller
    audio wins over stale backlog). Always ends by putting the end-of-stream
    sentinel.
    """
    from livekit import rtc

    from app.services.g711 import PcmResampler, pcm16_to_ulaw

    audio_stream = rtc.AudioStream(track)
    resampler: Any = None
    last_rate = 0
    try:
        async for event in audio_stream:
            pcm = bytes(event.frame.data)
            in_rate = int(event.frame.sample_rate or 8000)
            if resampler is None or in_rate != last_rate:
                resampler = PcmResampler(in_rate, 8000)
                last_rate = in_rate
            pcm = resampler.convert(pcm)
            try:
                queue.put_nowait(pcm16_to_ulaw(pcm))
            except asyncio.QueueFull:
                pass  # drop backlog: live caller audio wins over stale frames
    finally:
        await audio_stream.aclose()
        put_sentinel(queue)


#: Bytes per PSTN frame: 20ms of 8kHz mu-law. Telephony endpoints expect
#: constant-size frames; LiveKit delivers variable-size chunks, and forwarding
#: them raw is heard as crackle/robotic noise (classic on car speakers).
TELEPHONY_FRAME_BYTES = 160

#: mu-law silence byte, used to pad a trailing partial frame.
MULAW_SILENCE_BYTE = 0xFF


class MulawFramer:
    """Accumulate variable-size mu-law chunks into fixed 20ms PSTN frames.

    One instance per call leg. :meth:`push` returns zero or more full frames;
    :meth:`flush` returns the padded tail (or ``b""`` when nothing buffered).
    """

    def __init__(self, frame_bytes: int = TELEPHONY_FRAME_BYTES) -> None:
        self._size = int(frame_bytes)
        self._buf = bytearray()

    def push(self, data: bytes) -> list[bytes]:
        """Buffer a chunk; return every full frame now available."""
        if data:
            self._buf.extend(data)
        frames: list[bytes] = []
        while len(self._buf) >= self._size:
            frames.append(bytes(self._buf[: self._size]))
            del self._buf[: self._size]
        return frames

    def flush(self) -> bytes:
        """Return the leftover tail padded with silence to one full frame."""
        if not self._buf:
            return b""
        tail = bytes(self._buf)
        self._buf.clear()
        return tail + bytes([MULAW_SILENCE_BYTE]) * (self._size - len(tail))