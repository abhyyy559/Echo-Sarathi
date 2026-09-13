"""FastAPI application factory — mounts every router (enterprise platform).

Module path: ``app.main:app`` (see infra/docker-compose.yml). The legacy
``backend/main.py`` remains as a thin re-export so ``uvicorn main:app`` keeps
working too.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.database import init_db
from app.services.telephony import (
    FakeTelephonyClient,
    PlivoClient,
    TelephonyClient,
    TwilioClient,
    VobizClient,
)

logger = logging.getLogger(__name__)


def _provider_configured(settings: Settings) -> bool:
    """True when the selected (or auto-detected) provider has credentials.

    The explicit ``telephony_provider`` setting wins; auto-detection prefers
    Plivo (cheaper India legs) over Twilio. Never true without credentials —
    the guardrail that stops the dialer from trying to place real calls.
    """
    provider = settings.telephony_provider
    if provider == "plivo":
        return bool(settings.plivo_auth_id and settings.plivo_auth_token)
    if provider == "twilio":
        return bool(settings.twilio_account_sid and settings.twilio_auth_token)
    if provider == "vobiz":
        return bool(settings.vobiz_auth_id and settings.vobiz_auth_token)
    return bool(
        (settings.plivo_auth_id and settings.plivo_auth_token)
        or (settings.twilio_account_sid and settings.twilio_auth_token)
        or (settings.vobiz_auth_id and settings.vobiz_auth_token)
    )


def _build_telephony(settings: Settings) -> TelephonyClient:
    """Real provider client only when its credentials exist; otherwise a fake
    that never dials (guardrail: no real outbound calls without credentials)."""
    if not _provider_configured(settings):
        return FakeTelephonyClient()
    provider = settings.telephony_provider
    if provider == "twilio":
        return TwilioClient(settings)
    if provider == "plivo":
        return PlivoClient(settings)
    if provider == "vobiz":
        return VobizClient(settings)
    if settings.plivo_auth_id and settings.plivo_auth_token:
        return PlivoClient(settings)
    return TwilioClient(settings)


def _should_run_dialer(settings: Settings) -> bool:
    """The dialer places REAL calls — run it only with real telephony configured."""
    return bool(settings.dialer_enabled and _provider_configured(settings))


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app: DB engine, telephony client, routers, CORS."""
    app_settings = settings or get_settings()
    fast_app = FastAPI(
        title="AI Voice Calling Agent API",
        description=(
            "Multi-tenant AI voice calling platform. "
            "Dev-only tools (/api/health, /api/dev/status) are removed in production."
        ),
        version="2.0.0",
    )
    fast_app.state.settings = app_settings
    engine, session_factory = init_db(app_settings)
    fast_app.state.engine = engine
    fast_app.state.session_factory = session_factory
    fast_app.state.telephony = _build_telephony(app_settings)

    fast_app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origin_list,
        allow_credentials=False,  # cookie-less bearer auth
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    # --- routers ---------------------------------------------------------------
    from app.routers import (
        admin,
        agents,
        analytics,
        auth,
        calls,
        campaigns,
        contacts,
        devtools,
        domain_configs,
        export,
        internal,
        playground,
        plivo,
        test_call,
        twilio,
        vobiz,
    )

    fast_app.include_router(auth.router)
    fast_app.include_router(agents.router)
    fast_app.include_router(agents.agent_versions_router)
    fast_app.include_router(analytics.router)
    fast_app.include_router(playground.router)
    # Dev-only endpoints (removed in production builds).
    fast_app.include_router(devtools.router)
    fast_app.include_router(campaigns.router)
    fast_app.include_router(calls.router)
    fast_app.include_router(contacts.router)
    fast_app.include_router(domain_configs.router)
    fast_app.include_router(export.router)
    fast_app.include_router(admin.router)
    fast_app.include_router(test_call.router)
    # Mounted WITHOUT /api prefix by design (provider webhook URLs).
    fast_app.include_router(twilio.router)
    fast_app.include_router(plivo.router)
    fast_app.include_router(vobiz.router)
    # Internal voice-agent API (service-token protected).
    fast_app.include_router(internal.router)

    @fast_app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {"message": "AI Voice Calling Agent Backend", "docs": "/api/docs"}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=app_settings.log_level.upper())

        # Sync /domain-configs/*.json into the legacy table (best effort; only
        # when the schema exists).
        if schema_ready(session_factory):
            from app.domain_config_service import sync_domain_configs

            try:
                sync_domain_configs(session_factory(), app_settings.domain_configs_dir)
            except Exception:  # noqa: BLE001 — never block startup on config sync
                logger.exception("domain config sync failed at startup")
        else:
            logger.info("schema not ready at startup — skipping domain config sync")

        if not app_settings.internal_api_token:
            logger.warning(
                "INTERNAL_API_TOKEN is empty — /internal/* endpoints reject all calls"
            )

        dialer_task: asyncio.Task | None = None
        if _should_run_dialer(app_settings):
            from app.services.dialer import DialerService

            dialer = DialerService(app_settings, session_factory, app.state.telephony)
            dialer_task = asyncio.create_task(dialer.run())
            logger.info("dialer background task started")
        elif app_settings.dialer_enabled:
            logger.info(
                "dialer NOT started: telephony credentials missing "
                "(no outbound calls will be placed)"
            )
        try:
            yield
        finally:
            if dialer_task is not None:
                dialer_task.cancel()
                try:
                    await dialer_task
                except asyncio.CancelledError:
                    pass

    fast_app.router.lifespan_context = lifespan

    return fast_app


def db_ping(session_factory: sessionmaker) -> bool:
    """True when the bound database answers SELECT 1 (used by /api/health)."""
    try:
        with session_factory() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — health checks must never raise
        return False


def schema_ready(session_factory: sessionmaker) -> bool:
    """True when the core tables exist (migrations applied / create_all run)."""
    try:
        from sqlalchemy import inspect

        inspector = inspect(session_factory.kw["bind"])
        return inspector.has_table("domain_configs")
    except Exception:  # noqa: BLE001 — readiness probes never raise
        return False


app = create_app()
