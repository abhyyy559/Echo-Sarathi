"""Shared phone-bridge helpers: frame building, queue sentinels, track drains."""
import asyncio
import inspect
from array import array

import pytest

from app.services.media_bridge import drain_track, make_frame, put_sentinel


def _pcm16(*samples: int) -> bytes:
    return array("h", samples).tobytes()


def test_module_exports_helpers():
    assert callable(make_frame)
    assert callable(put_sentinel)
    assert inspect.iscoroutinefunction(drain_track)


class TestMakeFrame:
    def test_builds_8k_mono_frame(self):
        pcm = _pcm16(*range(-600, 600), *range(600, -600, -1))
        frame = make_frame(pcm)
        assert frame.sample_rate == 8000
        assert frame.num_channels == 1
        assert bytes(frame.data) == pcm
        assert frame.samples_per_channel == len(pcm) // 2

    def test_zero_filled_frame_is_valid(self):
        frame = make_frame(bytes(320))
        assert frame.sample_rate == 8000
        assert frame.num_channels == 1
        assert len(bytes(frame.data)) == 320


class TestPutSentinel:
    def test_places_end_marker(self):
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        put_sentinel(queue)
        assert queue.get_nowait() == b""

    def test_drains_backlog_when_full(self):
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        queue.put_nowait(b"\x01")
        put_sentinel(queue)
        assert queue.get_nowait() == b""


class _FakeFrame:
    def __init__(self, data: bytes, sample_rate: int) -> None:
        self.data = data
        self.sample_rate = sample_rate


class _FakeEvent:
    def __init__(self, frame: _FakeFrame) -> None:
        self.frame = frame


class _FakeAudioStream:
    def __init__(self, frames: list[_FakeFrame]) -> None:
        self._frames = frames
        self.closed = False

    def __aiter__(self):
        async def gen():
            for frame in self._frames:
                yield _FakeEvent(frame)

        return gen()

    async def aclose(self) -> None:
        self.closed = True


class TestDrainTrackStats:
    def test_collects_rates_drops_and_peak(self, monkeypatch):
        pcm = _pcm16(*([1000] * 160 + [-2000] * 160))
        frames = [
            _FakeFrame(pcm, 48000),
            _FakeFrame(pcm, 48000),
            _FakeFrame(pcm, 24000),
        ]
        monkeypatch.setattr(
            "livekit.rtc.AudioStream", lambda track: _FakeAudioStream(frames)
        )
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        stats: dict = {}
        asyncio.run(drain_track(object(), queue, stats))
        # 3 frames in, queue held 1: the rest dropped (recorded, not lost).
        assert stats["tracks"] == 1
        assert stats["frames_in"] == 3
        assert stats["drops"] == 2
        assert stats["in_rates"] == {48000, 24000}
        assert stats["out_peak"] == 2000
        # Sentinel evicts backlog and terminates the stream.
        assert queue.get_nowait() == b""
        assert queue.empty()

    def test_stats_optional_for_legacy_callers(self, monkeypatch):
        pcm = _pcm16(*([500] * 160))
        monkeypatch.setattr(
            "livekit.rtc.AudioStream",
            lambda track: _FakeAudioStream([_FakeFrame(pcm, 8000)]),
        )
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        asyncio.run(drain_track(object(), queue))
        assert queue.get_nowait() != b""
        assert queue.get_nowait() == b""