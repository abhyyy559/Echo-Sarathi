"""Key rotation for Deepgram/Cartesia at session start (2026-11-24).

A provider caps concurrent streams per key, so the platform supports a comma
separated key pool (``DEEPGRAM_API_KEYS`` / ``CARTESIA_API_KEYS``) and rotates
at session start: N keys multiply capacity and one key sitting at its limit
cannot fail every call. With a single key, behavior is unchanged.
"""
from __future__ import annotations

from app.pipeline import _rotating_key


def test_single_key_behaves_as_before() -> None:
    assert _rotating_key("test-single", ("k1",)) == "k1"
    assert _rotating_key("test-single", ()) == None
    assert _rotating_key("test-single", (), "fallback") == "fallback"


def test_pool_rotates_in_order() -> None:
    keys = ("k1", "k2", "k3")
    assert [_rotating_key("test-rot", keys) for _ in range(3)] == ["k1", "k2", "k3"]
    # Cycle repeats instead of stalling or returning only the first key.
    assert [_rotating_key("test-rot", keys) for _ in range(3)] == ["k1", "k2", "k3"]


def test_blank_entries_in_the_pool_are_skipped() -> None:
    keys = ("", "k2", "")
    assert _rotating_key("test-blank", keys) == "k2"
