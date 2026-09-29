"""In-process ring buffer of LLM/pipeline events for the playground panel.

Why this exists: when a call stalls, the only evidence used to be the docker
log, which is scrolled away and not attributable to a session. Every provider
attempt is recorded here (who was tried, what they answered, how long, why we
moved on) so the operator can see the failover happen live instead of
guessing after the fact.

Deliberately in-process and bounded: this is a dev/verification aid, not a
durable audit trail (transcripts and call events in Postgres remain the record
of what was said).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Optional

#: 500 events is roughly the last few full calls; enough to see a stall and
#: its cause, small enough to never be a memory concern.
_MAX_EVENTS = 500


@dataclass
class PipelineEvent:
    """One observable thing that happened in the LLM/pipeline path."""

    seq: int
    at: float
    kind: str  # llm_attempt | llm_result | llm_chain_exhausted | turn | note
    level: str = "info"  # info | warn | error
    provider: str = ""
    model: str = ""
    status: Optional[int] = None
    latency_ms: Optional[int] = None
    message: str = ""
    call_id: Optional[int] = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["at_iso"] = time.strftime("%H:%M:%S", time.localtime(self.at))
        return data


class EventRecorder:
    """Thread-safe bounded event log shared by the playground routes."""

    def __init__(self, max_events: int = _MAX_EVENTS) -> None:
        self._events: Deque[PipelineEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._seq = 0

    def record(
        self,
        kind: str,
        *,
        level: str = "info",
        provider: str = "",
        model: str = "",
        status: Optional[int] = None,
        latency_ms: Optional[int] = None,
        message: str = "",
        call_id: Optional[int] = None,
        **detail: Any,
    ) -> PipelineEvent:
        with self._lock:
            self._seq += 1
            event = PipelineEvent(
                seq=self._seq,
                at=time.time(),
                kind=kind,
                level=level,
                provider=provider,
                model=model,
                status=status,
                latency_ms=latency_ms,
                message=message,
                call_id=call_id,
                detail=detail,
            )
            self._events.append(event)
            return event

    def since(self, seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        """Events newer than ``seq``, oldest first."""
        with self._lock:
            items = [e for e in self._events if e.seq > int(seq or 0)]
        return [e.as_dict() for e in items[-limit:]]

    def latest_seq(self) -> int:
        with self._lock:
            return self._seq

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._seq = 0


#: Process-wide recorder. One instance: the playground routes and the LLM
#: client both write to it.
recorder = EventRecorder()
