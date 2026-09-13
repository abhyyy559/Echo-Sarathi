"""Offline UNIT tests for extraction escalation (app.extraction_tools, Lane B).

Drives VoiceAgentTools against the conftest FakeBackendClient fixture — no
network. Complements the Lane E contract suite in test_escalation.py.
"""

from __future__ import annotations

import asyncio
from typing import Any, Tuple

import pytest

from app.extraction_tools import (
    MAX_ASKS_PER_FIELD,
    ExtractionCoordinator,
    ExtractionTracker,  # alias exported for QA discovery; keep import working
    VoiceAgentTools,
)

CALL_ID = "call-test-123"


def _coordinator(required: Tuple[str, ...] = ("reason_for_absence",)) -> ExtractionCoordinator:
    return ExtractionCoordinator(required_fields=frozenset(required))


def test_alias_tracks_same_class() -> None:
    assert ExtractionTracker is ExtractionCoordinator


def test_low_confidence_flags_field_and_ends_call(fake_backend: Any) -> None:
    async def scenario() -> Tuple[str, ExtractionCoordinator]:
        coordinator = _coordinator()
        tools = VoiceAgentTools(coordinator, fake_backend, CALL_ID)
        reply = await tools.record_extracted_field(
            "reason_for_absence", "uh... maybe sick?", 0.35
        )
        return reply, coordinator

    reply, coordinator = asyncio.run(scenario())

    # The field is flagged, not accepted.
    assert "reason_for_absence" in coordinator.flagged
    assert "reason_for_absence" not in coordinator.recorded

    # A rejected (low-confidence) value must NOT be persisted at all.
    assert fake_backend.field_posts == []

    # Escalation: a wrap-up/complete was posted (end-call path).
    assert len(fake_backend.completions) == 1
    complete_call_id, payload = fake_backend.completions[0]
    assert complete_call_id == CALL_ID
    assert payload["status"] == "wrapped_up_flagged"
    assert "0.35" in str(payload["error"])

    # The tool tells the LLM to wrap up and mentions the flag.
    assert "FLAGGED" in reply
    assert "wrap up" in reply.lower()

    # The pending wrap-up reason is consumable exactly once.
    assert coordinator.consume_wrap_up() is not None
    assert coordinator.consume_wrap_up() is None


def test_three_attempts_on_required_field_triggers_wrap_up(fake_backend: Any) -> None:
    async def scenario() -> str:
        coordinator = _coordinator(("expected_return_date",))
        tools = VoiceAgentTools(coordinator, fake_backend, CALL_ID)
        for _ in range(MAX_ASKS_PER_FIELD):
            coordinator.mark_asked("expected_return_date")
        return await tools.end_call("Caller could not confirm a return date.")

    summary_reply = asyncio.run(scenario())

    completions = fake_backend.completions
    assert len(completions) == 1
    _, payload = completions[0]
    assert payload["status"] == "completed"
    assert "expected_return_date" in str(payload["summary"])
    assert "Unfilled required fields" in str(payload["summary"])
    assert "end_call" not in summary_reply or "Call ended" in summary_reply


def test_two_attempts_does_not_wrap_up() -> None:
    coordinator = _coordinator(("expected_return_date",))
    coordinator.mark_asked("expected_return_date")
    coordinator.mark_asked("expected_return_date")

    assert coordinator.consume_wrap_up() is None
    assert "expected_return_date" not in coordinator.flagged


def test_high_confidence_accepted_without_completion(fake_backend: Any) -> None:
    async def scenario() -> str:
        coordinator = _coordinator()
        tools = VoiceAgentTools(coordinator, fake_backend, CALL_ID)
        return await tools.record_extracted_field(
            "reason_for_absence", "food poisoning", 0.92
        )

    reply = asyncio.run(scenario())

    coordinator_field_state = fake_backend.field_posts[0][1][0]
    assert dict(coordinator_field_state)["confidence"] == pytest.approx(0.92)
    # No escalation: no completion should have been posted.
    assert fake_backend.completions == []
    assert "Recorded" in reply and "FLAGGED" not in reply


def test_end_call_reports_unfilled_required_fields(fake_backend: Any) -> None:
    async def scenario() -> None:
        coordinator = _coordinator(("reason_for_absence", "call_outcome"))
        tools = VoiceAgentTools(coordinator, fake_backend, CALL_ID)
        await tools.record_extracted_field("reason_for_absence", "fever", 0.9)
        await tools.end_call("All done.")

    asyncio.run(scenario())

    assert len(fake_backend.completions) == 1
    _, payload = fake_backend.completions[0]
    assert payload["status"] == "completed"
    assert "call_outcome" in str(payload["summary"])
    assert payload["error"] is None


def test_boundary_confidence_exactly_at_threshold_is_accepted() -> None:
    coordinator = _coordinator()
    result = coordinator.record("reason_for_absence", "fever", 0.6)
    assert result.accepted is True
    assert result.flagged is False
    assert result.should_wrap_up is False


def test_confidence_clamped_to_valid_range() -> None:
    coordinator = _coordinator()
    high = coordinator.record("f", "v", 1.7)
    low = coordinator.record("g", "v", -0.5)
    assert high.confidence == pytest.approx(1.0)
    assert low.confidence == pytest.approx(0.0)
