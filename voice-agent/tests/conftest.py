"""Shared fixtures for voice-agent offline unit tests (no network).

Also makes ``voice-agent`` importable as the root for the ``app`` package and
purges any foreign cached ``app`` modules (e.g. backend's) from earlier
collection in combined pytest runs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest

VOICE_AGENT_DIR = Path(__file__).resolve().parents[1]
if str(VOICE_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_AGENT_DIR))

# If another package named `app` (backend) was already imported in this
# process, drop it so our imports resolve to voice-agent/app.
for _mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
    del sys.modules[_mod]


class FakeBackendClient:
    """In-memory stand-in for :class:`app.backend_client.BackendClient`."""

    def __init__(self) -> None:
        self.configs: dict[str, Mapping[str, Any]] = {}
        self.config_fetches: list[str] = []
        self.turn_posts: list[tuple[str, list[Mapping[str, Any]]]] = []
        self.field_posts: list[tuple[str, list[Mapping[str, Any]]]] = []
        self.activity_posts: list[dict[str, Any]] = []
        self.completions: list[tuple[str, Mapping[str, Any]]] = []
        self.raise_on_config: bool = False

    async def get_agent_config(self, version_id: Any) -> Mapping[str, Any]:
        key = str(version_id)
        self.config_fetches.append(key)
        if self.raise_on_config or key not in self.configs:
            raise RuntimeError(f"no config for version {version_id}")
        return self.configs[key]

    async def post_turns(
        self, call_id: str, turns: list[Mapping[str, Any]]
    ) -> bool:
        self.turn_posts.append((call_id, turns))
        return True

    async def post_fields(
        self, call_id: str, fields: list[Mapping[str, Any]]
    ) -> bool:
        self.field_posts.append((call_id, fields))
        return True

    async def post_activity(
        self,
        call_id: str,
        state: str,
        sequence: int,
        event_type: str,
        occurred_at: float,
        source: str = "livekit-1.8.3",
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
    ) -> bool:
        self.activity_posts.append(
            {
                "call_id": call_id,
                "state": state,
                "sequence": sequence,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "source": source,
                "from_state": from_state,
                "to_state": to_state,
            }
        )
        return True

    async def post_complete(
        self,
        call_id: str,
        *,
        status: str = "completed",
        error: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> bool:
        payload: dict[str, Any] = {"status": status, "error": error, "summary": summary}
        self.completions.append((call_id, payload))
        return True


@pytest.fixture()
def fake_backend() -> FakeBackendClient:
    """Fresh FakeBackendClient per test."""
    return FakeBackendClient()
