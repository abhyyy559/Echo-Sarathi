"""Extraction precision fixes (Lane B).

Root causes being fixed:
- record_extracted_field POSTs to the backend even when the coordinator
  REJECTED the value (placeholder / low confidence). It must only persist
  accepted values and otherwise return a clear NOT RECORDED status.
- The per-field confidence_threshold from the extraction_schema (e.g.
  medical_cert_submitted = 0.7) was ignored; only the global 0.6 was used.
- field_name was a free-form string; a name outside the extraction_schema
  must be rejected, never posted.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.extraction_tools import LOW_CONFIDENCE_THRESHOLD, ExtractionCoordinator, VoiceAgentTools

SCHEMA: dict[str, Any] = {
    "reason_for_absence": {"confidence_threshold": 0.7},
    "expected_return_date": {"confidence_threshold": 0.8},
    "is_sick_leave": {"confidence_threshold": 0.7},
    "medical_cert_submitted": {"confidence_threshold": 0.7},
    "call_outcome": {"confidence_threshold": 0.8},
}


def _tools(fake: Any, schema: dict[str, Any] = SCHEMA) -> tuple[ExtractionCoordinator, VoiceAgentTools]:
    coordinator = ExtractionCoordinator(
        required_fields=frozenset({"reason_for_absence"}),
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
        schema=dict(schema),
    )
    return coordinator, VoiceAgentTools(coordinator, fake, "call-x", schema=dict(schema))


def test_placeholder_not_posted_and_returns_not_recorded(fake_backend: Any) -> None:
    coordinator, tools = _tools(fake_backend)
    reply = asyncio.run(
        tools.record_extracted_field("reason_for_absence", "unknown", 0.95)
    )
    assert fake_backend.field_posts == [], "rejected (placeholder) value must never be posted"
    assert coordinator.recorded == {}
    assert "NOT RECORDED" in reply


def test_per_field_threshold_applied_in_record() -> None:
    coordinator = ExtractionCoordinator(
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD, schema=SCHEMA
    )
    # Field threshold is 0.7: 0.65 is above the global 0.6 but below 0.7.
    result = coordinator.record("medical_cert_submitted", "yes", 0.65)
    assert result.accepted is False, "field threshold 0.7 must reject 0.65"
    ok = coordinator.record("medical_cert_submitted", "yes", 0.7)
    assert ok.accepted is True, "0.7 at the field threshold is accepted"


def test_per_field_threshold_respected_in_tool_posting(fake_backend: Any) -> None:
    coordinator, tools = _tools(fake_backend)
    reply = asyncio.run(
        tools.record_extracted_field("medical_cert_submitted", "yes", 0.65)
    )
    assert fake_backend.field_posts == [], "0.65 below field threshold 0.7 must not be posted"
    # Below the per-field threshold -> escalation path (flagged + wrap-up).
    assert "FLAGGED" in reply

    reply2 = asyncio.run(
        tools.record_extracted_field("medical_cert_submitted", "yes", 0.7)
    )
    assert len(fake_backend.field_posts) == 1
    assert "Recorded" in reply2


def test_default_threshold_is_global_when_field_has_none() -> None:
    coordinator = ExtractionCoordinator(
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
        schema={"generic_field": {"type": "string"}},
    )
    result = coordinator.record("generic_field", "value", 0.65)
    assert result.accepted is True, "0.65 >= global 0.6 when no per-field threshold set"


def test_out_of_schema_field_name_rejected_never_posted(fake_backend: Any) -> None:
    coordinator, tools = _tools(fake_backend)
    reply = asyncio.run(
        tools.record_extracted_field("not_a_schema_field", "hello", 0.99)
    )
    assert fake_backend.field_posts == [], "out-of-schema field must never be posted"
    assert coordinator.recorded == {}
    assert "NOT RECORDED" in reply


def test_accepted_field_still_posted_and_recorded(fake_backend: Any) -> None:
    coordinator, tools = _tools(fake_backend)
    reply = asyncio.run(
        tools.record_extracted_field("reason_for_absence", "viral fever", 0.95)
    )
    assert len(fake_backend.field_posts) == 1
    assert coordinator.recorded["reason_for_absence"]["value"] == "viral fever"
    assert "Recorded" in reply


def test_period_terminated_hedges_are_placeholders(fake_backend: Any) -> None:
    """The model emits "I don't know." with a period; without the dotted
    variants the hedge banks as a fact."""
    from app.extraction_tools import _is_placeholder

    for hedge in ("unknown.", "i don't know.", "dont know.", "no idea.", "none."):
        assert _is_placeholder(hedge) is True, hedge
    coordinator, tools = _tools(fake_backend)
    reply = asyncio.run(
        tools.record_extracted_field("reason_for_absence", "I don't know.", 0.95)
    )
    assert fake_backend.field_posts == []
    assert coordinator.recorded == {}
    assert "NOT RECORDED" in reply


def test_accepted_value_clears_earlier_flag(fake_backend: Any) -> None:
    """Placeholder first, real answer second: the field must not stay
    simultaneously recorded AND flagged."""
    coordinator, tools = _tools(fake_backend)
    asyncio.run(tools.record_extracted_field("reason_for_absence", "unknown", 0.9))
    assert "reason_for_absence" in coordinator.flagged_fields
    asyncio.run(tools.record_extracted_field("reason_for_absence", "viral fever", 0.95))
    assert "reason_for_absence" not in coordinator.flagged_fields
    assert coordinator.recorded["reason_for_absence"]["value"] == "viral fever"


def test_grounding_rejection_evicts_banked_value(fake_backend: Any) -> None:
    """A grounding-rejected value must not linger as a ghost in recorded:
    prompts and unfilled_required() would treat it as captured while the
    backend never received it."""
    coordinator, tools = _tools(fake_backend)
    tools.note_caller_text("yes, hello?")
    reply = asyncio.run(
        tools.record_extracted_field("reason_for_absence", "pneumonia", 0.95)
    )
    assert "NOT RECORDED" in reply
    assert "reason_for_absence" not in coordinator.recorded
    assert "reason_for_absence" in coordinator.unfilled_required()


def test_grounding_uses_utterance_window_not_just_latest(fake_backend: Any) -> None:
    """A value stated two turns ago and recorded now must ground: the check
    spans the last 4 caller utterances, not only the latest."""
    coordinator, tools = _tools(fake_backend)
    tools.note_caller_text("he has had a fever since tuesday")
    tools.note_caller_text("yes")
    tools.note_caller_text("uh huh")
    reply = asyncio.run(
        tools.record_extracted_field("reason_for_absence", "fever", 0.9)
    )
    assert "Recorded" in reply
    assert coordinator.recorded["reason_for_absence"]["value"] == "fever"
