"""Public surface for the graceful degradation path."""
from app.pipeline import _degrade  # noqa: F401

__all__ = ["_degrade"]
