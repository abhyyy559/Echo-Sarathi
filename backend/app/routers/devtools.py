"""Dev-tools endpoints — DEV ONLY, removed in production builds.

- ``GET /api/health``: service + provider-key PRESENCE booleans (never values)
- ``GET /api/dev/status``: calling-hours window, CPS/concurrency limits and
  the current alembic revision (bearer auth required).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.timeutil import is_within_calling_hours, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["devtools"])

_REDIS_TIMEOUT_SECONDS = 0.5

# Provider hosts the voice worker must reach (STT / TTS / LLM). Key PRESENCE
# alone is not enough — a container can hold valid keys yet fail DNS/egress
# (seen live: Deepgram ClientConnectorDNSError with a good key), so health
# probes real TCP reachability, never key values.
_EGRESS_TARGETS = {
    "deepgram": ("api.deepgram.com", 443),
    "cartesia": ("api.cartesia.ai", 443),
    "groq": ("api.groq.com", 443),
}
_EGRESS_TIMEOUT_SECONDS = 2.0
_EGRESS_TOTAL_TIMEOUT_SECONDS = 6.0


def _tcp_ok(host: str, port: int, timeout: float = _EGRESS_TIMEOUT_SECONDS) -> bool:
    """True when a TCP connection to host:port succeeds within timeout."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:  # noqa: BLE001 — health checks must never raise
        return False


def _pipeline_reachability(settings) -> dict[str, Any]:
    """Egress + LiveKit reachability, bounded in time, never raising.

    Runs each probe in a worker thread with an overall cap so one slow DNS
    lookup cannot hang the health endpoint.
    """
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urlparse

    jobs: dict[str, tuple[str, int]] = dict(_EGRESS_TARGETS)
    livekit_host, livekit_port = "", 0
    try:
        parsed = urlparse(settings.livekit_url_internal or "")
        if parsed.hostname:
            livekit_host, livekit_port = parsed.hostname, parsed.port or 7880
    except Exception:  # noqa: BLE001 — malformed URL just means "uncheckable"
        pass
    if livekit_host:
        jobs["livekit_server"] = (livekit_host, livekit_port)

    results: dict[str, bool] = {}
    if not jobs:
        return results
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {
            name: pool.submit(_tcp_ok, host, port) for name, (host, port) in jobs.items()
        }
        deadline = _EGRESS_TOTAL_TIMEOUT_SECONDS / max(1, len(jobs))
        for name, fut in futures.items():
            try:
                results[name] = bool(fut.result(timeout=deadline))
            except Exception:  # noqa: BLE001 — timeout or worker error → down
                results[name] = False
    return results


def _redis_ping(redis_url: str) -> bool:
    """True when redis answers PING; any failure means 'down', never a crash."""
    try:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(
            redis_url,
            socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
            socket_timeout=_REDIS_TIMEOUT_SECONDS,
        )
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception:  # noqa: BLE001 — health checks must never raise
        return False


def _alembic_revision(db: Session) -> dict[str, Any]:
    """Current alembic revision recorded in the DB, if the table exists."""
    try:
        row = db.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception:  # noqa: BLE001 — table simply not created yet
        return {"db_revision": None, "table_present": False}
    return {"db_revision": row[0] if row else None, "table_present": True}


@router.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    from app.main import db_ping

    reachability = _pipeline_reachability(settings)
    livekit_ws = reachability.pop("livekit_server", None)
    return {
        "db": db_ping(request.app.state.session_factory),
        "redis": _redis_ping(settings.redis_url),
        # No service registry this phase; the voice worker is checked manually.
        "voice_agent": "unknown",
        "providers": settings.provider_presence,
        # Armed LLM failover members, in the order they will be tried. Names
        # and models only, never keys: it is the fastest way to confirm a
        # pasted key actually parsed into the chain.
        "llm_chain": [
            {"name": name, "model": model} for name, _url, _key, model in settings.llm_chain
        ],
        # Real TCP reachability from the backend network (keys can be present
        # while egress/DNS is broken — this is what actually pages).
        "egress": reachability,
        "livekit_ws": livekit_ws,
    }


@router.get("/api/dev/status")
def dev_status(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    now = utcnow()
    with request.app.state.session_factory() as db:
        alembic = _alembic_revision(db)

    return {
        "environment": settings.environment,
        "dev_only": True,
        "calling_hours": {
            "start": settings.calling_hours_start,
            "end": settings.calling_hours_end,
            "timezone": settings.timezone,
            "within_hours_now": is_within_calling_hours(
                now,
                settings.timezone,
                settings.calling_hours_start,
                settings.calling_hours_end,
            ),
        },
        "limits": {
            "cps": settings.default_cps_limit,
            "concurrency": settings.default_concurrency_limit,
            "retry_max_attempts": settings.retry_max_attempts,
            "retry_backoff_minutes": settings.retry_backoff_minutes,
        },
        "dialer_enabled": settings.dialer_enabled,
        "recording_retention_days": settings.recording_retention_days,
        "consent_enforcement": settings.consent_enforcement,
        "alembic": alembic,
        "providers": settings.provider_presence,
    }
