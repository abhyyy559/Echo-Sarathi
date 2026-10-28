"""Background plan lifecycle: expire lapsed periods, send renewal reminders.

Expiry never gates calls by itself — ``plans.active_subscription`` already
ignores periods past their end. This loop keeps the stored status readable and
sends the one 7-day renewal email per period.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services import billing

logger = logging.getLogger(__name__)


async def billing_lifecycle_loop(settings: Any, session_factory: Any) -> None:
    interval = max(0, int(getattr(settings, "billing_lifecycle_interval_hours", 6) or 0))
    if interval <= 0:
        return
    await asyncio.sleep(30)
    while True:
        try:
            session = session_factory()
            try:
                counts = billing.run_billing_lifecycle(session, settings)
                session.commit()
            finally:
                session.close()
            if counts["expired"] or counts["reminded"]:
                logger.info("billing lifecycle: %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the loop must survive a bad tick
            logger.exception("billing lifecycle failed")
        await asyncio.sleep(interval * 3600)
