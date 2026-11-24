"""Dialer resilience under provider failure, restarts and huge rosters.

These pin the four failure modes found by load-testing ``DialerService`` on
2026-11-24 (measured, not theoretical):

- a provider 5xx spent each contact's three-attempt budget, so a three-second
  outage permanently failed a whole list;
- a process dying between "call row committed" and "provider accepted" left a
  ``queued`` row holding a concurrency slot forever, freezing the campaign;
- mutually-visible workers could pick the same contact because the status only
  flipped to ``calling`` after the provider call;
- a roster whose consent was revoked was retired in one tick, holding the
  single dialer thread (and every other campaign) for the whole sweep.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models import Base, Call, Campaign, Contact
from app.services.dialer import DialerService

LAUNCH = datetime(2026, 8, 24, 5, 0)  # 10:30 IST, inside 09:00-21:00


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite://",
        jwt_secret="test",
        internal_api_token="test",
        livekit_api_key="k",
        livekit_api_secret="s",
        dialer_enabled=False,
        consent_enforcement=True,
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk(conn, _record):  # pragma: no cover - pragma only
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


class _Telephony:
    def __init__(self, *, fail: bool = False, on_place=None):
        self.placed: list[tuple[str, int]] = []
        self.fail = fail
        self.on_place = on_place

    def place_call(self, to: str, call_id: int) -> str:
        if self.on_place is not None:
            self.on_place(to, call_id)
        if self.fail:
            raise RuntimeError("provider 503")
        self.placed.append((to, call_id))
        return f"sid-{call_id}"

    def hangup(self, provider_call_id: str) -> bool:
        return True


def _seed(factory, count: int, *, consent: bool = True) -> int:
    with factory() as db:
        campaign = Campaign(name="Load", status="running", org_id=None)
        db.add(campaign)
        db.flush()
        for index in range(count):
            db.add(
                Contact(
                    campaign_id=campaign.id,
                    name=f"C{index}",
                    phone=f"+9190000{index:05d}",
                    status="queued",
                    consent=consent,
                )
            )
        db.commit()
        return campaign.id


def _dialer(factory, telephony, **overrides) -> DialerService:
    return DialerService(
        _settings(**overrides), factory, telephony, clock=lambda: LAUNCH
    )


def test_provider_outage_does_not_fail_the_roster(factory):
    """A 5xx is infrastructure, not a refusal: no attempts, no lost contacts."""
    _seed(factory, 50)
    telephony = _Telephony(fail=True)
    dialer = _dialer(
        factory,
        telephony,
        default_concurrency_limit=10,
        default_cps_limit=100,
    )

    assert dialer.tick() == 0  # no leg was placed, so no dial is reported
    with factory() as db:
        contacts = db.query(Contact).all()
        assert {c.status for c in contacts} == {"queued"}
        assert {c.attempt_count for c in contacts} == {0}
        parked = [c for c in contacts if c.next_attempt_at is not None]
        assert len(parked) == 3  # exactly the probes the failure cap allowed
        assert all(c.next_attempt_at > LAUNCH for c in parked)
        # Only the consecutive-failure cap was tried, not the whole roster.
        assert db.query(Call).count() == 3


def test_orphan_queued_call_is_reclaimed(factory):
    """A restart mid-placement must not eat a dial slot forever."""
    campaign_id = _seed(factory, 8)
    with factory() as db:
        db.add(
            Call(
                campaign_id=campaign_id,
                kind="phone",
                status="queued",
                started_at=LAUNCH - timedelta(hours=1),
            )
        )
        db.commit()

    telephony = _Telephony()
    dialer = _dialer(
        factory, telephony, default_concurrency_limit=1, default_cps_limit=100
    )

    # The ghost is swept in the same tick, freeing the only slot.
    assert dialer.tick() == 1
    assert len(telephony.placed) == 1
    with factory() as db:
        ghost = db.query(Call).filter(Call.provider_call_id.is_(None)).one()
        assert ghost.status == "failed"


def test_contact_is_claimed_before_the_provider_call(factory):
    """Two workers must never dial the same contact: flip status first."""
    _seed(factory, 2)
    seen: list[tuple[str, int]] = []

    def inspect(_phone: str, call_id: int) -> None:
        with factory() as db:
            call = db.get(Call, call_id)
            contact = db.get(Contact, call.contact_id)
            seen.append((contact.status, contact.last_call_id))

    telephony = _Telephony(on_place=inspect)
    dialer = _dialer(
        factory, telephony, default_concurrency_limit=1, default_cps_limit=1
    )
    assert dialer.tick() == 1
    assert seen == [("calling", telephony.placed[0][1])]


def test_consent_sweep_is_budgeted_per_tick(factory):
    """A 50k roster with revoked consent cannot monopolise the dialer thread."""
    _seed(factory, 250, consent=False)
    dialer = _dialer(
        factory,
        _Telephony(),
        default_concurrency_limit=10,
        default_cps_limit=100,
        dialer_max_skips_per_tick=40,
    )

    started = time.perf_counter()
    assert dialer.tick() == 0
    elapsed = time.perf_counter() - started

    with factory() as db:
        assert db.query(Contact).filter_by(status="opted_out").count() == 40
        assert db.query(Contact).filter_by(status="queued").count() == 210
    assert elapsed < 5.0


def test_cps_caps_a_large_roster(factory):
    """Concurrency 50 with CPS 5 places five legs, not fifty."""
    _seed(factory, 200)
    telephony = _Telephony()
    dialer = _dialer(
        factory, telephony, default_concurrency_limit=50, default_cps_limit=5
    )
    assert dialer.tick() == 5
    assert len(telephony.placed) == 5
