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