"""Async HTTP client for the backend's internal (service-token) API.

Endpoints consumed (frozen contract, see
``docs/superpowers/specs/2026-08-23-enterprise-platform-design.md`` §4):

- ``GET  /internal/agent-config?version_id=``   (30s in-memory cache)
- ``POST /internal/calls/{call_id}/transcript-turns``  body: JSON array
- ``POST /internal/calls/{call_id}/extracted-fields``  body: JSON array
- ``POST /internal/calls/{call_id}/activity``            body: JSON object
- ``POST /internal/calls/{call_id}/complete``          body: JSON object

All requests carry the ``X-Internal-Token`` header. Post-style calls are
best-effort: failures are logged and reported via a ``False`` return value so
a flaky backend can never crash the voice session.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Mapping, Optional

import httpx

logger = logging.getLogger("voice_agent.backend")


class BackendError(RuntimeError):
    """Raised when a required read from the backend fails."""


class BackendClient:
    """Small httpx wrapper around the backend internal API.

    Uses a process-wide SHARED AsyncClient: one BackendClient is created per
    job, but AgentSession.start() returns immediately while the room stays
    open — per-job clients were being closed while turns still needed posting.
    """

    _shared_client: Optional[httpx.AsyncClient] = None

    def __init__(
        self,
        base_url: str,
        internal_token: str,
        *,
        timeout_seconds: float = 10.0,
        cache_ttl_seconds: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if BackendClient._shared_client is None:
            BackendClient._shared_client = httpx.AsyncClient(
                timeout=timeout_seconds,
                headers={"X-Internal-Token": internal_token},
            )
        self._client = client or BackendClient._shared_client
        self._owns_client = client is not None
        self._base_url = base_url.rstrip("/")
        self._cache_ttl_seconds = cache_ttl_seconds
        self._config_cache: dict[str, tuple[float, Mapping[str, Any]]] = {}
        self._cache_lock = asyncio.Lock()

    # -- reads ------------------------------------------------------------

    async def fetch_call_context(self, call_id: str) -> dict[str, Any]:
        """Fetch per-call context (institution_name + contact). Never raises.

        Returns the parsed JSON dict on success, or ``{}`` on any failure so a
        flaky backend can never crash the voice session (C token resolution).
        """
        try:
            response = await self._client.get(
                f"{self._base_url}/internal/calls/{call_id}/context"
            )
            response.raise_for_status()
            data: Any = response.json()
            return data if isinstance(data, Mapping) else {}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("call context fetch failed for %s: %s", call_id, exc)
            return {}

    async def get_agent_config(self, version_id: Any) -> Mapping[str, Any]:
        """Fetch a full agent-version config, cached for 30 seconds."""
        key = str(version_id)
        async with self._cache_lock:
            cached = self._config_cache.get(key)
            now = time.monotonic()
            if cached is not None and now < cached[0]:
                return cached[1]
            try:
                response = await self._client.get(
                    f"{self._base_url}/internal/agent-config",
                    params={"version_id": version_id},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error(
                    "agent-config fetch failed for version %s: %s", version_id, exc
                )
                raise BackendError(f"agent-config fetch failed: {exc}") from exc
            config: Mapping[str, Any] = response.json()
            expires_at = time.monotonic() + self._cache_ttl_seconds
            self._config_cache[key] = (expires_at, config)
            return config

    # -- writes (best-effort, never raise) --------------------------------

    async def post_turns(self, call_id: str, turns: list[Mapping[str, Any]]) -> bool:
        """Append transcript/latency turn rows. Returns success."""
        return await self._post_json_array(
            f"/internal/calls/{call_id}/transcript-turns", turns
        )

    async def post_fields(
        self, call_id: str, fields: list[Mapping[str, Any]]
    ) -> bool:
        """Append extracted-field rows. Returns success."""
        return await self._post_json_object(
            f"/internal/calls/{call_id}/extracted-fields", {"fields": fields}
        )

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
        """Publish one LiveKit activity transition. Returns success."""
        try:
            occurred_at_value = float(occurred_at)
        except (TypeError, ValueError, OverflowError):
            logger.error(
                "post_activity failed for call %s: invalid occurred_at %r",
                call_id,
                occurred_at,
            )
            return False
        if not math.isfinite(occurred_at_value):
            logger.error(
                "post_activity failed for call %s: occurred_at is not finite",
                call_id,
            )
            return False
        payload = {
            "state": state,
            "sequence": sequence,
            "event_type": event_type,
            "occurred_at": occurred_at_value,
            "source": source,
            "from_state": from_state,
            "to_state": to_state,
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/internal/calls/{call_id}/activity",
                json=payload,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.error("post_activity failed for call %s: %s", call_id, exc)
            return False
        return True

    async def post_complete(
        self,
        call_id: str,
        *,
        status: str = "completed",
        error: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> bool:
        """Finalize the call row. Returns success.

        ``status`` is one of ``completed``, ``wrapped_up_flagged`` or
        ``error``; ``error`` carries the degradation reason when applicable.
        """
        payload: dict[str, Any] = {"status": status}
        if error is not None:
            payload["error"] = error
        if summary is not None:
            payload["summary"] = summary
        try:
            response = await self._client.post(
                f"{self._base_url}/internal/calls/{call_id}/complete", json=payload
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("post_complete failed for call %s: %s", call_id, exc)
            return False
        return True

    # -- internals ---------------------------------------------------------

    async def _post_json_array(self, path: str, items: list[Mapping[str, Any]]) -> bool:
        if not items:
            return True
        try:
            response = await self._client.post(f"{self._base_url}{path}", json=items)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("POST %s failed (%d items): %s", path, len(items), exc)
            return False
        return True

    async def _post_json_object(
        self, path: str, payload: Mapping[str, Any]
    ) -> bool:
        try:
            response = await self._client.post(f"{self._base_url}{path}", json=dict(payload))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("POST %s failed: %s", path, exc)
            return False
        return True

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "BackendClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()
