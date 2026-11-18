"""Public surface for per-turn latency telemetry.

The implementation still lives in :mod:`app.pipeline` because its helpers are
shared with session wiring. Importing from here is the stable path for callers;
the physical extraction is tracked as follow-up work in the implementation plan.
"""
from app.pipeline import TurnTelemetry  # noqa: F401

__all__ = ["TurnTelemetry"]
