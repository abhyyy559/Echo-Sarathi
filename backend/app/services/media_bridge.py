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


async def drain_track(track: Any, queue: Any) -> None:
    """Forward one subscribed remote audio track into the bridge queue.

    Resamples down to 8 kHz and encodes to mu-law; drops frames when the queue
    is full (live caller audio wins over stale backlog). Always ends by putting
    the end-of-stream sentinel.
    """
    from livekit import rtc

    from app.services.g711 import downsample_pcm16, pcm16_to_ulaw

    audio_stream = rtc.AudioStream(track)
    try:
        async for event in audio_stream:
            pcm = bytes(event.frame.data)
            factor = max(1, round(int(event.frame.sample_rate) / 8000))
            if factor > 1:
                pcm = downsample_pcm16(pcm, factor)
            try:
                queue.put_nowait(pcm16_to_ulaw(pcm))
            except asyncio.QueueFull:
                pass  # drop backlog: live caller audio wins over stale frames
    finally:
        await audio_stream.aclose()
        put_sentinel(queue)