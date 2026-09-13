"""Extraction bookkeeping and framework-agnostic tool implementations.

``VoiceAgentTools`` implements the two LLM function tools of the pipeline:

- ``record_extracted_field(field_name, value, confidence)``
- ``end_call(summary)``

The class is intentionally free of livekit imports so the escalation logic can
be unit tested offline against a fake backend client; ``app.pipeline`` wraps
these callables as LiveKit ``@function_tool`` methods.

Escalation policy (FR-12): confidence < 0.6, or a required field still unfilled
after 3 asks -> graceful wrap-up + flag. Values are never fabricated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol

logger = logging.getLogger("voice_agent.extraction")

LOW_CONFIDENCE_THRESHOLD: float = 0.6
MAX_ASKS_PER_FIELD: int = 3

#: Values that are NOT a value. An extraction carrying one of these means the
#: caller did not actually provide the information (PE the LLM hedging with
#: "unknown"). Recording these would be fabricating data - the #1 violation the
#: defense pack must never be caught doing. Reject them as not-captured.
PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {
        "",
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "not sure",
        "not sure.",
        "unsure",
        "i don't know",
        "i dont know",
        "don't know",
        "dont know",
        "no idea",
        "not provided",
        "-",
        "?",
    }
)


def _is_placeholder(value: str) -> bool:
    return str(value or "").strip().lower() in PLACEHOLDER_VALUES


class ExtractionBackend(Protocol):
    """Minimal backend surface needed by the tools (real or fake)."""

    async def post_fields(
        self, call_id: str, fields: list[Mapping[str, Any]]
    ) -> bool: ...

    async def post_complete(
        self,
        call_id: str,
        *,
        status: str = "completed",
        error: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> bool: ...


@dataclass(frozen=True)
class RecordResult:
    """Outcome of a single ``record_extracted_field`` attempt."""

    field_name: str
    value: str
    confidence: float
    accepted: bool
    flagged: bool
    should_wrap_up: bool
    reason: str


@dataclass
class ExtractionCoordinator:
    """Tracks recorded fields, ask counts, and pending wrap-up flags."""

    required_fields: frozenset[str] = field(default_factory=frozenset)
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD
    max_asks_per_field: int = MAX_ASKS_PER_FIELD
    #: The domain extraction_schema (field_name -> spec). When non-empty it is
    #: used to validate field names and to apply per-field confidence_threshold.
    schema: Mapping[str, Any] = field(default_factory=dict)

    recorded: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    flagged_fields: Dict[str, str] = field(default_factory=dict)
    ask_counts: Dict[str, int] = field(default_factory=dict)
    _wrap_up_reasons: List[str] = field(default_factory=list)

    def mark_asked(self, field_name: str) -> int:
        """Record that a question about ``field_name`` was asked once more."""
        count = self.ask_counts.get(field_name, 0) + 1
        self.ask_counts[field_name] = count
        if (
            count >= self.max_asks_per_field
            and field_name in self.required_fields
            and field_name not in self.recorded
            and field_name not in self.flagged_fields
        ):
            reason = (
                f"Required field '{field_name}' still unfilled after "
                f"{self.max_asks_per_field} asks - giving up on it and wrapping up."
            )
            self.flagged_fields[field_name] = reason
            self._wrap_up_reasons.append(reason)
            logger.warning("escalation: %s", reason)
        return count

    def _threshold_for(self, field_name: str) -> float:
        """Effective confidence threshold: per-field over the global default."""
        spec = self.schema.get(str(field_name))
        if isinstance(spec, Mapping):
            per_field = spec.get("confidence_threshold")
            if per_field is not None:
                try:
                    return float(per_field)
                except (TypeError, ValueError):
                    pass
        return self.low_confidence_threshold

    def record(self, field_name: str, value: str, confidence: float) -> RecordResult:
        """Store (or flag) one extracted value. Never invents data."""
        clamped = max(0.0, min(1.0, float(confidence)))
        # Validate the field name against the known schema when one is loaded.
        if self.schema and str(field_name) not in self.schema:
            reason = (
                f"'{field_name}' is not a known field in the extraction schema "
                f"- NOT recorded."
            )
            logger.warning("rejected out-of-schema field: %s", reason)
            return RecordResult(
                field_name=field_name,
                value=str(value),
                confidence=clamped,
                accepted=False,
                flagged=False,
                should_wrap_up=False,
                reason=reason,
            )
        if _is_placeholder(value):
            reason = (
                f"Value for '{field_name}' is a placeholder ('{value}') - NOT a "
                f"captured value; never fabricate. Ask again or skip this field."
            )
            self.flagged_fields.setdefault(field_name, reason)
            logger.warning("refused placeholder extraction: %s", reason)
            return RecordResult(
                field_name=field_name,
                value=str(value),
                confidence=clamped,
                accepted=False,
                flagged=True,
                should_wrap_up=False,
                reason=reason,
            )
        effective = self._threshold_for(field_name)
        if clamped < effective:
            reason = (
                f"Low confidence ({clamped:.2f}) for '{field_name}' below "
                f"{effective:.2f} - not captured."
            )
            self.flagged_fields.setdefault(field_name, reason)
            self._wrap_up_reasons.append(reason)
            logger.warning("escalation: %s", reason)
            return RecordResult(
                field_name=field_name,
                value=value,
                confidence=clamped,
                accepted=False,
                flagged=True,
                should_wrap_up=True,
                reason=reason,
            )
        self.recorded[field_name] = {"value": value, "confidence": clamped}
        return RecordResult(
            field_name=field_name,
            value=value,
            confidence=clamped,
            accepted=True,
            flagged=False,
            should_wrap_up=False,
            reason="",
        )

    def consume_wrap_up(self) -> Optional[str]:
        """Pop the oldest pending wrap-up reason, or ``None`` if none."""
        if self._wrap_up_reasons:
            return self._wrap_up_reasons.pop(0)
        return None

    @property
    def flagged(self) -> Dict[str, str]:
        """Read-only view of flagged fields (contract/QA discovery seam)."""
        return self.flagged_fields

    def unfilled_required(self) -> List[str]:
        """Required fields with no accepted value yet."""
        return sorted(self.required_fields - set(self.recorded))


class VoiceAgentTools:
    """Framework-free implementations of the two pipeline function tools."""

    def __init__(
        self,
        coordinator: ExtractionCoordinator,
        backend: ExtractionBackend,
        call_id: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._coordinator = coordinator
        self._backend = backend
        self._call_id = call_id
        self._schema = schema or {}

    async def heuristic_extract(self, transcript: str) -> int:
        """Deterministic safety-net extraction (FR-12 companion).

        For every schema field the LLM has NOT recorded, scan the final user
        transcript for sentences whose words overlap the field name or its
        description; record the best sentence at modest confidence so a value
        is never lost just because the model skipped its tool call.
        Returns how many fields were captured.
        """
        import re

        text = (transcript or "").strip()
        if not text:
            return 0
        captured = 0
        recorded = set(self._coordinator.recorded.keys())
        for field_name, spec in self._schema.items():
            if field_name in recorded:
                continue
            cue_words: set[str] = {w.lower() for w in re.split(r"[^a-z0-9]+", field_name) if len(w) > 3}
            description = ""
            if isinstance(spec, dict):
                description = str(spec.get("description") or "")
            cue_words |= {w.lower() for w in re.split(r"[^a-z0-9]+", description) if len(w) > 3}
            if not cue_words:
                continue
            for sentence in re.split(r"(?<=[.!?])\s+|,\s+", text):
                words = set(re.findall(r"[a-z0-9']+", sentence.lower()))
                if words & cue_words:
                    if _is_placeholder(sentence):
                        continue  # "unknown"/"n/a" is not a value - never record it
                    await self.record_extracted_field(
                        field_name,
                        sentence.strip(" ."),
                        0.7,
                    )
                    captured += 1
                    break
        return captured

    async def record_extracted_field(
        self,
        field_name: str,
        value: str,
        confidence: float,
        *,
        source_turn_index: int = 0,
    ) -> str:
        """Record one extracted field and escalate when it is unreliable.

        Only ACCEPTED values are persisted to the backend. A value the
        coordinator rejects (placeholder, low confidence, or out-of-schema
        field name) is never posted — the LLM is told to re-ask or keep going.
        """
        result = self._coordinator.record(field_name, str(value), float(confidence))
        if not result.accepted:
            if result.should_wrap_up:
                await self._backend.post_complete(
                    self._call_id,
                    status="wrapped_up_flagged",
                    error=result.reason,
                )
                return (
                    f"FLAGGED - {result.reason} Do NOT guess this value. Wrap up the "
                    f"call gracefully now and call `end_call` with a summary noting "
                    f"that '{result.field_name}' could not be reliably captured."
                )
            return (
                f"NOT RECORDED: {result.reason} Re-ask specifically, or record it "
                f"once you have a real value."
            )
        await self._backend.post_fields(
            self._call_id,
            [
                {
                    "field_name": result.field_name,
                    "field_value": result.value,
                    "confidence": result.confidence,
                    "source_turn_index": source_turn_index,
                }
            ],
        )
        return (
            f"Recorded {result.field_name}='{result.value}' "
            f"(confidence {result.confidence:.2f})."
        )

    async def end_call(self, summary: str) -> str:
        """Finalize the call, annotating any unfilled required fields."""
        unfilled = self._coordinator.unfilled_required()
        final_summary = str(summary or "").strip()
        if unfilled:
            final_summary = (
                f"{final_summary} | Unfilled required fields (flagged, never "
                f"fabricated): {', '.join(unfilled)}."
            ).strip()
        await self._backend.post_complete(
            self._call_id,
            status="completed",
            error=None,
            summary=final_summary or None,
        )
        return f"Call ended. Summary posted: {final_summary}"


# Alias used by the QA contract suite (Lane E) to discover the escalation
# seam without coupling to this module's internal naming.
ExtractionTracker = ExtractionCoordinator
