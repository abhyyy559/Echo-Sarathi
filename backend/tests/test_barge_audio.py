"""Phone-audio repairs: filtered resampling, paced playout, barge-in flush."""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any


def test_resampler_downsamples_with_filter_state() -> None:
    from app.services.g711 import PcmResampler

    resampler = PcmResampler(48000, 8000)
    # 10ms @48kHz mono 16-bit = 480 samples = 960 bytes -> 80 samples (160B).
    # The first frame only primes the FIR look-ahead; from there every frame
    # yields the exact 6:1 count (a per-frame shortfall is the stutter bug).
    frame = bytes(960)
    resampler.convert(frame)
    assert len(resampler.convert(frame)) == 160
    assert len(resampler.convert(frame)) == 160

    # Whole stream: exactly 6:1 minus the one-off held look-ahead (22 samples).
    fresh = PcmResampler(48000, 8000)
    total = 0
    for _ in range(60):
        total += len(fresh.convert(bytes(960)))
    assert total == 60 * 480 // 6 * 2 - 44

    # Same rate passes through untouched.
    passthrough = PcmResampler(8000, 8000)
    assert passthrough.convert(b"\x01\x02\x03\x04") == b"\x01\x02\x03\x04"


def test_resampler_preserves_speech_band() -> None:
    import math
    import struct

    from app.services.g711 import PcmResampler

    def tone(freq: float, rate: int, count: int) -> bytes:
        samples = [int(10000 * math.sin(2 * math.pi * freq * n / rate)) for n in range(count)]
        return struct.pack("<%dh" % count, *samples)

    def energy(raw: bytes) -> float:
        vals = struct.unpack("<%dh" % (len(raw) // 2), raw)
        return sum(v * v for v in vals) / len(vals)

    # 440Hz sits inside the 3400Hz passband: streamed frame by frame it comes
    # out at 1:6 the sample count with its energy preserved.
    src = tone(440, 48000, 4800)
    resampler = PcmResampler(48000, 8000)
    out = b"".join(resampler.convert(src[i : i + 960]) for i in range(0, len(src), 960))
    assert abs(len(out) - len(src) // 6) <= 44  # 2 bytes in -> 2 bytes out
    assert energy(out) > 0.9 * energy(src)

    # 24kHz tracks decimate by 3: same contract, steady state 160 samples.
    resampler24 = PcmResampler(24000, 8000)
    frame24 = tone(440, 24000, 480)
    resampler24.convert(frame24)
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


def test_pump_keeps_real_time_when_each_send_costs_time(monkeypatch) -> None:
    """Send cost must be absorbed by the pace, not added to it.

    Regression: the paced pump computed its next deadline as "now + 20ms"
    *after* each send, so the base64+WebSocket write and any sleep overshoot
    were charged on top of the 20ms and written off instead of repaid. On a
    free-tier CPU that compounded into seconds of lag; the worker's barge_in
    then discarded 24-368 queued chunks the caller had never heard, which is
    the agent cutting out mid-sentence. The schedule is now anchored to a
    fixed t0, so frame n is due at t0 + n*20ms however slow the sends are.
    """
    import time as time_module

    from app.routers import vobiz as vobiz_module

    clock = [1000.0]
    real_sleep = asyncio.sleep
    monkeypatch.setattr(time_module, "monotonic", lambda: clock[0])

    async def fake_sleep(delay: float) -> None:
        clock[0] += max(delay, 0.0)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    sends: list[float] = []

    class _SlowWS:
        async def send_text(self, _text: str) -> None:
            clock[0] += 0.008  # a real playAudio write is never free
            sends.append(clock[0])

    frames = 30
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    for _ in range(frames):
        queue.put_nowait(bytes(160))  # one 20ms mu-law frame each
    queue.put_nowait(b"")  # end of stream
    stats: dict[str, Any] = {}

    asyncio.run(
        vobiz_module._pump_room_to_vobiz(queue, _SlowWS(), {"sid": "S"}, stats)
    )

    assert len(sends) == frames
    span = sends[-1] - sends[0]
    # 29 intervals of 20ms with the send cost absorbed: ~0.58s. The old
    # relative deadline would have taken 29 x 28ms = 0.81s.
    assert span <= 29 * 0.021, span
    assert stats["frames_out"] == frames
    # Never behind: the 8ms write is charged against the 20ms budget.
    assert stats["max_late_ms"] == 0.0


def test_pump_repays_a_stall_instead_of_compounding_it(monkeypatch) -> None:
    """A one-off hiccup must be caught back up, not carried for the call.

    A 200ms stall on the first write is the worst case a free-tier CPU
    produces. With an absolute schedule the following frames fire with no
    sleep until the deficit is paid off (~5 frames), so the pump is back on
    the caller's timeline; a relative deadline would have kept the lag.
    """
    import time as time_module

    from app.routers import vobiz as vobiz_module

    t0 = 1000.0
    clock = [t0]
    real_sleep = asyncio.sleep
    monkeypatch.setattr(time_module, "monotonic", lambda: clock[0])

    async def fake_sleep(delay: float) -> None:
        clock[0] += max(delay, 0.0)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    sends: list[float] = []

    class _StallingWS:
        async def send_text(self, _text: str) -> None:
            clock[0] += 0.2 if not sends else 0.008
            sends.append(clock[0])

    frames = 30
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    for _ in range(frames):
        queue.put_nowait(bytes(160))
    queue.put_nowait(b"")
    stats: dict[str, Any] = {}

    asyncio.run(
        vobiz_module._pump_room_to_vobiz(queue, _StallingWS(), {"sid": "S"}, stats)
    )

    assert stats["frames_out"] == frames
    # The stall itself is still visible...
    assert stats["max_late_ms"] == 180.0
    # ...but the last frame lands ON the ideal timeline (frame 30 is due at
    # t0 + 30*20ms, and the write starts one 8ms budget ahead of that), i.e.
    # the hiccup was fully repaid rather than added to the call's delay. A
    # carried stall would have finished ~0.2s later still.
    assert sends[-1] + 0.008 <= t0 + 30 * 0.02 + 0.002, sends[-1] - t0


def test_pump_pads_a_partial_tail_frame(monkeypatch) -> None:
    """A non-multiple of 160 bytes must still leave as whole 20ms frames."""
    from app.routers import vobiz as vobiz_module

    sent: list[str] = []

    class _WS:
        async def send_text(self, text: str) -> None:
            sent.append(text)

    queue: asyncio.Queue[bytes] = asyncio.Queue()
    queue.put_nowait(bytes(100))
    queue.put_nowait(b"")
    stats: dict[str, Any] = {}

    asyncio.run(vobiz_module._pump_room_to_vobiz(queue, _WS(), {"sid": "S"}, stats))

    assert stats["frames_out"] == 1
    payload = json.loads(sent[-1])["media"]["payload"]
    assert len(base64.b64decode(payload)) == 160
    assert base64.b64decode(payload)[100:] == bytes([0xFF]) * 60


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
