"""Outbound campaign dialer worker.

An asyncio background task ticks once per second (``DialerService.run``).
Each tick (``DialerService.tick``) is synchronous and independently callable,
which keeps the rate limiting, consent gating and retry logic unit-testable.

Guarantees per tick:
- Skips entirely when outside calling hours (local timezone).
- Respects an in-flight concurrency cap over live phone legs only
  (queued/ringing/in_progress); a stale browser session cannot hold a dial slot.
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
from app.services.telephony import TelephonyClient, mask_phone
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
        # Campaigns already logged as credit-blocked; cleared as soon as the
        # wallet recovers so one log line per outage, not one per second.
        self._credit_blocked: set[int] = set()
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
            # The media bridge will not join a call without a pinned agent
            # version (it closes 4404), so the campaign's version must travel
            # onto the call row or the phone rings and nobody answers.
            agent_version_id=campaign.agent_version_id,
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
        logger.info("dialer: call %s ringing to %s (contact %s)", call.id, mask_phone(contact.phone), contact.id)

    async def run(self, interval_seconds: float = 1.0) -> None:
        """Background loop; each tick runs in a worker thread."""
        logger.info("dialer started (cps=%s concurrency=%s)", self.settings.default_cps_limit, self.settings.default_concurrency_limit)
        loop = asyncio.get_running_loop()
        keepalive_every = max(0, int(self.settings.keepalive_interval_seconds or 0))
        last_keepalive = 0.0
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                logger.info("dialer stopped")
                raise
            except Exception:  # noqa: BLE001 — never let the loop die
                logger.exception("dialer tick failed")
            if keepalive_every and loop.time() - last_keepalive >= keepalive_every:
                last_keepalive = loop.time()
                try:
                    await asyncio.to_thread(self.keepalive_ping)
                except Exception:  # noqa: BLE001 — a failed ping must not stop dialing
                    logger.debug("keepalive ping failed", exc_info=True)
            await asyncio.sleep(interval_seconds)

    def keepalive_ping(self) -> bool:
        """Ping our own public URL while a campaign is running.

        Render's free tier sleeps a service after ~15 minutes without
        *inbound* HTTP; a background dialer alone does not count. Without this
        a campaign stops the moment the operator closes the tab, and a
        campaign that is still running at 9pm never wakes to resume at 9am.
        Returns True when a ping was sent.
        """
        if not self.settings.keepalive_interval_seconds:
            return False
        with self.session_factory() as db:
            running = db.scalar(
                select(Campaign.id).where(Campaign.status == "running").limit(1)
            )
        if running is None:
            return False
        base = (self.settings.public_base_url or "").strip().rstrip("/")
        if not base:
            return False
        import httpx

        try:
            resp = httpx.get(f"{base}/", timeout=20.0)
        except Exception:  # noqa: BLE001 — best effort only
            logger.warning("keepalive ping to %s failed", base, exc_info=True)
            return False
        if resp.status_code >= 400:
            logger.warning("keepalive ping to %s -> %s", base, resp.status_code)
        return True

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
            in_flight: dict[Optional[int], int] = {}
            campaigns = db.scalars(select(Campaign).where(Campaign.status == "running")).all()
            for campaign in campaigns:
                if not self._credit_ok(db, campaign):
                    continue
                limit = self._concurrency_limit(db, campaign)
                if campaign.org_id not in in_flight:
                    in_flight[campaign.org_id] = in_flight_call_count(
                        db, phone_only=True, org_id=campaign.org_id
                    )
                while (
                    in_flight[campaign.org_id] < limit
                    and self._cps_slots_available(now)
                ):
                    outcome = self._process_next(db, campaign, now)
                    if outcome == "idle":
                        break
                    if outcome == "dialled":
                        in_flight[campaign.org_id] += 1
                        placed += 1
                    # "skipped" consumed a pick without a leg: keep looping so a
                    # non-dialable contact cannot stall the campaign, but never
                    # count it as a dial or occupy a concurrency slot.
                maybe_complete_campaign(db, campaign.id)
                db.commit()
            self._sweep_stale_ringing(db, now)
        return placed

    def _credit_ok(self, db: Session, campaign: Campaign) -> bool:
        """False when the campaign's org cannot pay for even a short call.

        A campaign stays ``running`` while blocked — pausing it automatically
        would lose the operator's intent — but it places no legs until the
        wallet is topped up or the plan's included minutes reset.
        """
        from app.services import billing, plans

        if campaign.org_id is None:
            return True
        if billing.can_dial(db, campaign.org_id):
            self._credit_blocked.discard(campaign.id)
            return True
        if campaign.id not in self._credit_blocked:
            self._credit_blocked.add(campaign.id)
            _plan, subscription = plans.org_plan(db, campaign.org_id)
            logger.warning(
                "dialer: campaign %s paused on credits (plan minutes left=%s, balance=%s paise)",
                campaign.id,
                plans.included_seconds_remaining(db, campaign.org_id, subscription) // 60,
                billing.balance_paise(db, campaign.org_id),
            )
        return False

    def _concurrency_limit(self, db: Session, campaign: Campaign) -> int:
        """Per-org concurrent dial cap, bounded by the deployment default."""
        from app.services import plans

        deployment_cap = max(1, int(self.settings.default_concurrency_limit))
        if campaign.org_id is None:
            return deployment_cap
        return max(1, min(plans.concurrency_limit(db, campaign.org_id), deployment_cap))

    def _sweep_stale_ringing(self, db: Session, now: datetime, limit: int = 5) -> int:
        """Reconcile phone calls stuck with no media leg.

        Vobiz now posts hangup_url, so most outcomes close event-driven; this
        sweep is the backstop when that callback is lost (dead tunnel, provider
        bug). A call that never left ``ringing`` cannot be a live conversation,
        so it is checked after two minutes — waiting ten made one unanswered
        contact stall every following campaign dial for ten minutes. Connected
        ``in_progress`` calls keep the ten-minute grace so a real conversation
        is never closed early. Each check asks the provider and only a terminal
        outcome changes the row, so an early check is safe.
        """
        from datetime import timedelta

        from app.services.vobiz_reconcile import reconcile_vobiz_call

        if not (self.settings.vobiz_auth_id and self.settings.vobiz_auth_token):
            return 0
        synced = 0
        for status, age in (("ringing", timedelta(minutes=2)), ("in_progress", timedelta(minutes=10))):
            remaining = limit - synced
            if remaining <= 0:
                break
            cutoff = now - age
            stale = db.scalars(
                select(Call)
                .where(
                    Call.kind == "phone",
                    Call.status == status,
                    Call.started_at.is_not(None),
                    Call.started_at <= cutoff,
                )
                .order_by(Call.id)
                .limit(remaining)
            ).all()
            for call in stale:
                try:
                    reconcile_vobiz_call(db, self.settings, call, now)
                    synced += 1
                except Exception:  # noqa: BLE001 — sweeper never breaks the tick
                    logger.exception("stale ringing sweep failed for call %s", call.id)
        return synced

    def _process_next(self, db: Session, campaign: Campaign, now: datetime) -> str:
        """Pick the next contact: ``"dialled"``, ``"skipped"``, or ``"idle"``.

        ``"skipped"`` means a contact was retired without a leg (no consent);
        the caller must keep going, but the campaign placed no call.
        """
        contact = self._next_eligible_contact(db, campaign.id, now)
        if contact is None:
            return "idle"
        if not self._consent_ok(contact):
            logger.info(
                "dialer: contact %s opted out (no consent, not a test number)", contact.id
            )
            contact.status = "opted_out"
            db.commit()
            return "skipped"
        self._place(db, contact, campaign, now)
        return "dialled"
