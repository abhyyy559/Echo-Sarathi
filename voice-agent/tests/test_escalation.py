"""Lane E — extraction escalation contract tests (Lane B voice-agent).

Frozen contract (spec §5 FR-12, plan Global Constraints):
- extraction confidence < 0.6 -> flag + graceful wrap-up
- required field unfilled after N=3 asks -> escalate/flag
- a low-confidence/unfilled value is NEVER fabricated into extracted fields

Primary seam (merged Lane B): ``app.extraction_tools`` — ExtractionCoordinator
(aliased ExtractionTracker for this suite) plus the framework-free
VoiceAgentTools function tools, driven against a FakeBackendClient.
A discovery-based fallback keeps the suite runnable if module paths shift.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

import pytest

from _qa_voice_contract import FakeBackendClient, locate_symbols

POLICY_MODULES: list[str] = [
    "app.extraction_tools",
    "app.escalation",
    "app.pipeline",
    "agent",
]
COORDINATOR_ATTRS: list[str] = [
    "ExtractionTracker",
    "ExtractionCoordinator",
    "EscalationPolicy",
    "ExtractionState",
]
TOOLS_ATTRS: list[str] = ["VoiceAgentTools"]

LOW_CONFIDENCE_THRESHOLD = 0.6
MAX_ASKS = 3


@pytest.fixture(scope="module")
def coordinator_cls() -> type:
    cls, why = locate_symbols(COORDINATOR_ATTRS, POLICY_MODULES)
    if cls is None:
        pytest.skip(f"[Lane B] escalation tracker not merged yet: {why}")
    return cls


@pytest.fixture(scope="module")
def tools_cls() -> Optional[type]:
    tools, _why = locate_symbols(TOOLS_ATTRS, ["app.extraction_tools"])
    return tools


def make_coordinator(coordinator_cls: type, required: set[str]) -> Any:
    """Build a tracker, tolerating constructors without a required_fields kwarg."""
    try:
        return coordinator_cls(required_fields=frozenset(required))
    except TypeError:
        instance = coordinator_cls()
        for attr in ("required_fields",):
            if hasattr(instance, attr) and isinstance(getattr(instance, attr), (set, frozenset)):
                setattr(instance, attr, frozenset(required))
                break
        return instance


def test_low_confidence_value_is_flagged_and_wraps_up(
    coordinator_cls: type,
) -> None:
    coordinator = make_coordinator(coordinator_cls, {"reason_for_absence"})
    result = coordinator.record("reason_for_absence", "uh maybe not feeling well", 0.45)

    assert getattr(result, "flagged", False), f"confidence<0.6 must flag: {result!r}"
    assert getattr(result, "should_wrap_up", False), (
        f"low confidence must trigger graceful wrap-up: {result!r}"
    )
    assert not getattr(result, "accepted", True), f"low-confidence value must not be accepted: {result!r}"
    assert "reason_for_absence" in coordinator.flagged, (
        f"field must appear in flagged view: {coordinator.flagged!r}"
    )
    assert coordinator.consume_wrap_up() is not None, "a wrap-up reason must be queued"


def test_low_confidence_value_is_never_recorded_as_extracted(
    coordinator_cls: type,
) -> None:
    coordinator = make_coordinator(coordinator_cls, {"reason_for_absence"})
    coordinator.record("reason_for_absence", "I dunno something", 0.3)
    recorded = getattr(coordinator, "recorded", {})
    assert "reason_for_absence" not in recorded, (
        f"low-confidence turn must not land in extracted values: {recorded!r}"
    )


def test_confident_value_is_accepted_control_case(
    coordinator_cls: type,
) -> None:
    coordinator = make_coordinator(coordinator_cls, {"reason_for_absence"})
    result = coordinator.record("reason_for_absence", "viral fever", 0.92)
    assert getattr(result, "accepted", False), f"high-confidence capture must be accepted: {result!r}"
    assert not getattr(result, "flagged", True)
    assert "reason_for_absence" in getattr(coordinator, "recorded", {})


def test_required_field_unfilled_after_three_asks_escalates(
    coordinator_cls: type,
) -> None:
    coordinator = make_coordinator(coordinator_cls, {"expected_return_date"})
    for ask_number in range(1, MAX_ASKS + 1):
        count = coordinator.mark_asked("expected_return_date")
        assert count == ask_number
        assert "expected_return_date" not in coordinator.flagged or ask_number == MAX_ASKS
    assert "expected_return_date" in coordinator.flagged, (
        f"required field unfilled after {MAX_ASKS} asks must be flagged: "
        f"{coordinator.flagged!r}"
    )
    assert "expected_return_date" in coordinator.unfilled_required()


def test_two_asks_do_not_yet_escalate(coordinator_cls: type) -> None:
    coordinator = make_coordinator(coordinator_cls, {"expected_return_date"})
    for _ in range(MAX_ASKS - 1):
        coordinator.mark_asked("expected_return_date")
    assert "expected_return_date" not in coordinator.flagged, (
        f"escalating before {MAX_ASKS} asks violates the policy: {coordinator.flagged!r}"
    )


def test_escalated_field_is_never_fabricated_in_end_call_summary(
    coordinator_cls: type,
) -> None:
    coordinator = make_coordinator(coordinator_cls, {"expected_return_date"})
    for _ in range(MAX_ASKS):
        coordinator.mark_asked("expected_return_date")
    unfilled = coordinator.unfilled_required()
    assert unfilled == ["expected_return_date"]
    placeholders = {"unknown", "n/a", "na", "none", "null", "tbd", "?", ""}
    for name, entry in getattr(coordinator, "recorded", {}).items():
        value = entry.get("value") if isinstance(entry, dict) else entry
        assert str(value).strip().lower() not in placeholders, (
            f"placeholder fabrication detected for {name}: {value!r}"
        )

def test_placeholder_values_are_never_accepted(coordinator_cls: type) -> None:
    """'unknown' / 'n/a' / empty are NOT values - record() must reject them
    even at high confidence (PE the LLM hedging with 'unknown')."""
    coordinator = make_coordinator(coordinator_cls, set())
    for value in ("unknown", "n/a", "N/A", "none", "", "  "):
        result = coordinator.record("any_field", value, 0.95)
        assert result.accepted is False, (
            f"placeholder {value!r} must not be accepted"
        )
        assert result.flagged is True
        assert "any_field" not in coordinator.recorded
    # A real value at the same confidence is accepted.
    ok = coordinator.record("any_field", "high fever since yesterday", 0.95)
    assert ok.accepted is True
    assert coordinator.recorded["any_field"]["value"] == "high fever since yesterday"

def test_tool_call_flags_and_posts_wrap_up_via_fake_backend(
    coordinator_cls: type,
    tools_cls: Optional[type],
) -> None:
    if tools_cls is None:
        pytest.skip("[Lane B] VoiceAgentTools seam not found")
    fake = FakeBackendClient()
    coordinator = make_coordinator(coordinator_cls, set())
    tools = tools_cls(coordinator, fake, "call-qa-1")

    reply = asyncio.run(
        tools.record_extracted_field("reason_for_absence", "uh maybe sick", 0.45)
    )
    assert "FLAGGED" in reply.upper(), f"tool must announce the flag: {reply!r}"

    assert fake.completions, "wrap-up must post to backend complete endpoint"
    completion = fake.completions[-1]
    assert completion["status"] == "wrapped_up_flagged", (
        f"completion status must mark the wrap-up: {completion!r}"
    )
    assert completion["error"], "completion should carry the escalation reason"

    assert "not guess" in reply.lower() or "do not guess" in reply.lower(), (
        f"tool instruction must forbid guessing: {reply!r}"
    )


def test_end_call_reports_unfilled_required_fields_never_fabricated(
    coordinator_cls: type,
    tools_cls: Optional[type],
) -> None:
    if tools_cls is None:
        pytest.skip("[Lane B] VoiceAgentTools seam not found")
    fake = FakeBackendClient()
    coordinator = make_coordinator(coordinator_cls, {"expected_return_date"})
    for _ in range(MAX_ASKS):
        coordinator.mark_asked("expected_return_date")
    tools = tools_cls(coordinator, fake, "call-qa-2")

    asyncio.run(tools.end_call("caller hung up"))
    assert fake.completions, "end_call must post a completion"
    summary = fake.completions[-1].get("summary") or ""
    assert "expected_return_date" in summary and "never" in summary.lower(), (
        f"summary must disclose unfilled required fields as never-fabricated: {summary!r}"
    )


def test_fake_backend_client_matches_frozen_interface() -> None:
    async def scenario() -> FakeBackendClient:
        fake = FakeBackendClient()
        fake.configs[7] = {"system_prompt": "x"}
        config = await fake.get_agent_config(7)
        assert config["system_prompt"] == "x"
        assert await fake.get_agent_config(999) is None
        await fake.post_turns("call-1", [{"turn_index": 0, "speaker": "caller", "text": "hi"}])
        await fake.post_fields("call-1", [{"field_name": "a", "field_value": "b"}])
        await fake.post_complete("call-1", status="completed", error=None, summary="done")
        return fake

    fake = asyncio.run(scenario())
    assert fake.turns and fake.fields and fake.completions[-1]["summary"] == "done"
