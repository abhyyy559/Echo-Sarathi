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
