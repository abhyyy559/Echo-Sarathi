"""Outbound campaign dialer worker.

An asyncio background task ticks once per second (``DialerService.run``).
Each tick (``DialerService.tick``) is synchronous and independently callable,
which keeps the rate limiting, consent gating and retry logic unit-testable.

Guarantees per tick:
- Skips entirely when outside calling hours (local timezone).
- Respects a global in-flight concurrency cap (queued/ringing/in_progress calls).
- Respects a global CPS limit via an in-memory timestamp window.
- Consent gate: with enforcement on, a queued contact without consent whose
  phone is not on the TEST_PHONE_NUMBERS allowlist is set to ``opted_out``.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Call, Campaign, Contact
from app.services.calls_service import (
    apply_contact_retry,
    in_flight_call_count,
    log_call_event,
    maybe_complete_campaign,
)
from app.services.import_service import normalize_phone
from app.services.telephony import TelephonyClient
from app.timeutil import is_within_calling_hours, utcnow

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class DialerService:
    """Rate-limited outbound dialer for running campaigns."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        telephony: TelephonyClient,
        clock: Optional[Clock] = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.telephony = telephony
        self.clock: Clock = clock or utcnow
        self._recent_call_times: deque[datetime] = deque()
        self._test_phones = {
            phone for phone in (normalize_phone(p)[0] for p in settings.test_phone_number_list)
        }

    # --- rate limiting -----------------------------------------------------

    def _cps_slots_available(self, now: datetime) -> bool:
        cutoff = now - timedelta(seconds=1)
        while self._recent_call_times and self._recent_call_times[0] <= cutoff:
            self._recent_call_times.popleft()
        return len(self._recent_call_times) < self.settings.default_cps_limit

    def _record_cps(self, now: datetime) -> None:
        self._recent_call_times.append(now)

    # --- consent -------------------------------------------------------------

    def _consent_ok(self, contact: Contact) -> bool:
        if not self.settings.consent_enforcement:
            return True
        return bool(contact.consent) or contact.phone in self._test_phones

    # --- core ----------------------------------------------------------------

    def within_calling_hours(self, now: Optional[datetime] = None) -> bool:
        now = now or self.clock()
        return is_within_calling_hours(
            now,
            self.settings.timezone,
            self.settings.calling_hours_start,
            self.settings.calling_hours_end,
        )

    def _next_eligible_contact(self, db: Session, campaign_id: int, now: datetime) -> Optional[Contact]:
        return db.scalars(
            select(Contact)
            .where(
                Contact.campaign_id == campaign_id,
                Contact.status == "queued",
                Contact.attempt_count < self.settings.retry_max_attempts,
                (Contact.next_attempt_at.is_(None)) | (Contact.next_attempt_at <= now),
            )
            .order_by(Contact.id)
            .limit(1)
        ).first()

    def _place(self, db: Session, contact: Contact, campaign: Campaign, now: datetime) -> None:
        """Create a call row and place it; on failure apply retry rules."""
        call = Call(
            campaign_id=campaign.id,
            contact_id=contact.id,
            kind="phone",
            org_id=campaign.org_id,
            status="queued",
            started_at=now,
            # P0-2: pack the contact card at call creation so any room/token
            # created for this call carries the same personalization metadata
            # as the playground path.
            context={"contact": dict(contact.custom_fields or {})},
        )
        db.add(call)
        db.commit()  # persist queued call first so it counts as in-flight on failure paths

        self._record_cps(now)
        try:
            sid = self.telephony.place_call(contact.phone, call.id)
        except Exception as exc:  # noqa: BLE001 — per-call isolation by design
            logger.warning("dialer: placing call failed call_id=%s contact=%s: %s", call.id, contact.id, exc)
            call.status = "failed"
            call.ended_at = now
            log_call_event(db, call.id, "dial_failed", {"error": str(exc)})
            apply_contact_retry(contact, self.settings, now)
            db.commit()
            return

        call.provider_call_id = sid
        call.status = "ringing"
        contact.status = "calling"
        contact.last_call_id = call.id
        db.commit()
        logger.info("dialer: call %s ringing to %s (contact %s)", call.id, contact.phone, contact.id)

    async def run(self, interval_seconds: float = 1.0) -> None:
        """Background loop; each tick runs in a worker thread."""
        logger.info("dialer started (cps=%s concurrency=%s)", self.settings.default_cps_limit, self.settings.default_concurrency_limit)
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                logger.info("dialer stopped")
                raise
            except Exception:  # noqa: BLE001 — never let the loop die
                logger.exception("dialer tick failed")
            await asyncio.sleep(interval_seconds)

    def tick(self) -> int:
        """One dialer pass. Returns the number of calls placed."""
        now = self.clock()
        with self.session_factory() as db:
            # Stuck-row recovery runs around the clock: a carrier-refused call
            # at 11pm must not glue its contact to "calling" until morning.
            self._sweep_stale_ringing(db, now)
        if not self.within_calling_hours(now):
            return 0
        placed = 0
        with self.session_factory() as db:
            in_flight = in_flight_call_count(db)
            campaigns = db.scalars(select(Campaign).where(Campaign.status == "running")).all()
            for campaign in campaigns:
                while (
                    in_flight < self.settings.default_concurrency_limit
                    and self._cps_slots_available(now)
                ):
                    if not self._process_next(db, campaign, now):
                        break
                    in_flight += 1
                    placed += 1
                maybe_complete_campaign(db, campaign.id)
                db.commit()
            self._sweep_stale_ringing(db, now)
        return placed

    def _sweep_stale_ringing(self, db: Session, now: datetime, limit: int = 5) -> int:
        """Reconcile phone calls stuck ringing with no media leg.

        Vobiz pushes no status webhooks, so a call whose PSTN leg never
        connects (carrier refuse, dead tunnel at answer time) would sit in
        ``ringing`` forever with its contact glued to ``calling`` — freezing
        the campaign. Anything still ringing after 10 minutes gets one
        provider reconciliation per tick (bounded, best-effort).
        """
        from datetime import timedelta

        from app.services.vobiz_reconcile import reconcile_vobiz_call

        if not (self.settings.vobiz_auth_id and self.settings.vobiz_auth_token):
            return 0
        cutoff = now - timedelta(minutes=10)
        stale = db.scalars(
            select(Call)
            .where(
                Call.kind == "phone",
                Call.status == "ringing",
                Call.started_at.is_not(None),
                Call.started_at <= cutoff,
            )
            .order_by(Call.id)
            .limit(limit)
        ).all()
        synced = 0
        for call in stale:
            try:
                reconcile_vobiz_call(db, self.settings, call, now)
                synced += 1
            except Exception:  # noqa: BLE001 — sweeper never breaks the tick
                logger.exception("stale ringing sweep failed for call %s", call.id)
        return synced

    def _process_next(self, db: Session, campaign: Campaign, now: datetime) -> bool:
        """Pick and dial the next eligible contact. False when nothing to do."""
        contact = self._next_eligible_contact(db, campaign.id, now)
        if contact is None:
            return False
        if not self._consent_ok(contact):
            logger.info(
                "dialer: contact %s opted out (no consent, not a test number)", contact.id
            )
            contact.status = "opted_out"
            db.commit()
            return True  # consumed a pick; loop continues to next contact
        self._place(db, contact, campaign, now)
        return True
