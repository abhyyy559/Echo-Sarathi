"""Phone-audio repairs: filtered resampling, paced playout, barge-in flush."""
from __future__ import annotations

import asyncio
import json
from typing import Any


def test_resampler_downsamples_with_filter_state() -> None:
    from app.services.g711 import PcmResampler

    resampler = PcmResampler(48000, 8000)
    # 20ms @48kHz mono 16-bit = 960 samples = 1920 bytes -> 160 samples out.
    frame = bytes(1920)
    out1 = resampler.convert(frame)
    assert len(out1) == 320  # 160 samples x 2 bytes
    out2 = resampler.convert(frame)
    assert len(out2) == 320
    # Same rate passes through untouched.
    passthrough = PcmResampler(8000, 8000)
    assert passthrough.convert(b"\x01\x02\x03\x04") == b"\x01\x02\x03\x04"


def test_resampler_preserves_speech_band() -> None:
    import math
    import struct

    from app.services.g711 import PcmResampler

    # 440Hz tone (well inside the voice band) at 48kHz: 960 samples in,
    # exactly 160 samples out, energy preserved, streamable frame by frame.
    samples = [
        int(10000 * math.sin(2 * math.pi * 440 * n / 48000)) for n in range(960)
    ]
    frame = struct.pack("<%dh" % len(samples), *samples)

    def energy(raw: bytes) -> float:
        vals = struct.unpack("<%dh" % (len(raw) // 2), raw)
        return sum(v * v for v in vals) / len(vals)

    resampler = PcmResampler(48000, 8000)
    out = resampler.convert(frame)
    assert len(out) == 320
    assert energy(out) == abs(energy(out))
    assert energy(out) > 0.9 * energy(frame)

    # Non-integer ratios work too (24kHz LiveKit tracks -> factor 3).
    resampler24 = PcmResampler(24000, 8000)
    frame24 = frame[:960]  # 480 samples @24kHz
    assert len(resampler24.convert(frame24)) == 320


def test_flush_drops_backlog_preserves_sentinel() -> None:
    from app.routers.vobiz import _flush_bridge_queue

    queue: asyncio.Queue[bytes] = asyncio.Queue()
    for chunk in (b"a" * 160, b"b" * 160, b"c" * 160):
        queue.put_nowait(chunk)
    assert _flush_bridge_queue(queue) == 3
    assert queue.empty()

    queue.put_nowait(b"x" * 160)
    queue.put_nowait(b"")
    assert _flush_bridge_queue(queue) == 1
    assert queue.get_nowait() == b""  # sentinel preserved: bridge stays up


def test_handle_room_data_barge_in_flushes() -> None:
    from app.routers.vobiz import _handle_room_data

    queue: asyncio.Queue[bytes] = asyncio.Queue()
    queue.put_nowait(b"stale" * 32)
    assert _handle_room_data(json.dumps({"type": "barge_in"}), queue) is True
    assert queue.empty()


def test_handle_room_data_ignores_junk_and_captions() -> None:
    from app.routers.vobiz import _handle_room_data

    queue: asyncio.Queue[bytes] = asyncio.Queue()
    queue.put_nowait(b"keepme")
    assert _handle_room_data("not json{{{", queue) is False
    assert _handle_room_data(
        json.dumps({"type": "caption", "speaker": "agent", "text": "hi"}), queue
    ) is False
    assert queue.get_nowait() == b"keepme"


def test_handle_room_data_accepts_livekit_packet_shape() -> None:
    from app.routers.vobiz import _handle_room_data

    class _Packet:
        def __init__(self, payload: bytes) -> None:
            self.data = payload

    queue: asyncio.Queue[bytes] = asyncio.Queue()
    queue.put_nowait(b"stale")
    packet: Any = _Packet(json.dumps({"type": "barge_in"}).encode())
    assert _handle_room_data(packet, queue) is True
    assert queue.empty()


def test_framer_emits_fixed_160_byte_frames() -> None:
    from app.services.media_bridge import MulawFramer

    framer = MulawFramer()
    # Odd-sized LiveKit chunks: 100 + 100 + 300 = 500 bytes -> 3 full frames.
    assert framer.push(bytes(100)) == []
    assert framer.push(bytes(100)) == [bytes(160)]
    out = framer.push(bytes(300))
    assert out == [bytes(160), bytes(160)]
    assert all(len(f) == 160 for f in out)


def test_framer_flush_pads_tail_with_silence() -> None:
    from app.services.media_bridge import MULAW_SILENCE_BYTE, MulawFramer

    framer = MulawFramer()
    assert framer.push(bytes(200)) == [bytes(160)]
    tail = framer.flush()
    assert len(tail) == 160
    assert tail[:40] == bytes(40)
    assert tail[40:] == bytes([MULAW_SILENCE_BYTE]) * 120
    assert framer.flush() == b""
