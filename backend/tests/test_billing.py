"""Prepaid credits: pricing math, idempotent debits and dial gating."""
from __future__ import annotations

from datetime import timedelta

from conftest import auth_headers, register

from app.models import Call, CreditLedger, Organization


def _org_with_balance(session_factory, paise: int) -> int:
    from app.models import Organization

    with session_factory() as db:
        org = Organization(
            name="Wallet Org", slug=f"wallet-{paise}", credit_balance_paise=paise
        )
        db.add(org)
        db.commit()
        return org.id


def _seed_campaign(session_factory, org_id: int) -> tuple[int, int]:
    from app.models import Campaign, Contact

    with session_factory() as db:
        campaign = Campaign(org_id=org_id, name="Wallet Campaign", status="running")
        db.add(campaign)
        db.flush()
        contact = Contact(
            campaign_id=campaign.id,
            org_id=org_id,
            name="Ravi",
            phone="+919000000001",
            consent=True,
            consent_source="test",
            status="pending",
        )
        db.add(contact)
        db.commit()
        return campaign.id, contact.id


def _seed_call(session_factory, org_id, campaign_id, contact_id, *, kind, seconds, answered=True):
    from app.models import Call
    from app.timeutil import utcnow

    with session_factory() as db:
        now = utcnow()
        call = Call(
            campaign_id=campaign_id,
            contact_id=contact_id,
            org_id=org_id,
            kind=kind,
            status="completed",
            started_at=now - timedelta(seconds=seconds),
            answered_at=None,
            ended_at=now,
            duration_seconds=seconds,
        )
        if answered:
            call.answered_at = now - timedelta(seconds=seconds)
        db.add(call)
        db.commit()
        return call.id


def test_seconds_round_up_to_the_whole_second() -> None:
    from app.services.billing import PRICE_PER_MINUTE_PAISE, seconds_to_paise

    assert PRICE_PER_MINUTE_PAISE == 300
    assert seconds_to_paise(0) == 0
    assert seconds_to_paise(1) == 5
    assert seconds_to_paise(12) == 60
    assert seconds_to_paise(60) == 300
    assert seconds_to_paise(61) == 305


def test_answered_call_debits_exactly_once(session_factory) -> None:
    from app.services.billing import charge_call

    org_id = _org_with_balance(session_factory, 3000)
    campaign_id, contact_id = _seed_campaign(session_factory, org_id)
    call_id = _seed_call(
        session_factory, org_id, campaign_id, contact_id, kind="phone", seconds=42
    )
    with session_factory() as db:
        for _ in range(3):  # duplicate provider webhooks
            charge_call(db, db.get(Call, call_id))
            db.commit()
        org = db.get(Organization, org_id)
        assert org.credit_balance_paise == 3000 - 210  # 42s * 5 paise
        assert (
            db.query(CreditLedger).filter_by(call_id=call_id, kind="usage").count() == 1
        )


def test_unanswered_and_playground_calls_are_free(session_factory) -> None:
    from app.services.billing import charge_call

    org_id = _org_with_balance(session_factory, 3000)
    campaign_id, contact_id = _seed_campaign(session_factory, org_id)
    busy_id = _seed_call(
        session_factory, org_id, campaign_id, contact_id, kind="phone", seconds=0, answered=False
    )
    play_id = _seed_call(
        session_factory, org_id, campaign_id, contact_id, kind="playground", seconds=90
    )

    with session_factory() as db:
        charge_call(db, db.get(Call, busy_id))
        charge_call(db, db.get(Call, play_id))
        db.commit()
        assert db.get(Organization, org_id).credit_balance_paise == 3000
        assert db.query(CreditLedger).count() == 0


def test_dialer_places_no_call_on_an_empty_wallet(session_factory, monkeypatch) -> None:
    from app.services.dialer import DialerService
    from conftest import make_settings

    org_id = _org_with_balance(session_factory, 0)
    _seed_campaign(session_factory, org_id)

    class _Telephony:
        placed: list[str] = []

        def place_call(self, phone, call_id):  # pragma: no cover - must not run
            self.placed.append(phone)
            return "sid"

    telephony = _Telephony()
    dialer = DialerService(make_settings(), session_factory, telephony)
    assert dialer.tick() == 0
    assert telephony.placed == []
    with session_factory() as db:
        assert db.query(Call).count() == 0


def test_topup_requires_manual_payments_flag(client, app) -> None:
    token, _user = register(client, org_name="Topup Org")
    resp = client.post(
        "/api/billing/topup", headers=auth_headers(token), json={"pack_id": "starter"}
    )
    assert resp.status_code == 403, resp.text

    app.state.settings.allow_manual_payments = True
    resp = client.post(
        "/api/billing/topup", headers=auth_headers(token), json={"pack_id": "growth"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 10 free minutes from registration + 300 from the Growth pack.
    assert body["balance_paise"] == 3000 + 300 * 300
    assert body["minutes_remaining"] == 310.0
    assert body["ledger"][0]["kind"] == "purchase"
    assert body["ledger"][0]["paid_rupees"] == 870.0
    assert body["margin_per_minute_paise"] == 70


def test_billing_summary_is_org_scoped(client) -> None:
    token_a, _ = register(client, org_name="Org A")
    token_b, _ = register(client, org_name="Org B")
    a = client.get("/api/billing", headers=auth_headers(token_a)).json()
    b = client.get("/api/billing", headers=auth_headers(token_b)).json()
    assert a["balance_paise"] == 3000 and b["balance_paise"] == 3000
    assert a["price_per_minute_rupees"] == 3.0
    assert len(a["packs"]) == 3


def test_test_calls_count_toward_monthly_usage(session_factory) -> None:
    """Campaign-less test calls must show up in minutes used, like their debit does."""
    from app.services.billing import charge_call, summary
    from app.timeutil import utcnow

    org_id = _org_with_balance(session_factory, 3000)
    with session_factory() as db:
        now = utcnow()
        call = Call(
            org_id=org_id,
            kind="phone",
            status="completed",
            started_at=now - timedelta(seconds=90),
            answered_at=now - timedelta(seconds=90),
            ended_at=now,
            duration_seconds=90,
        )
        db.add(call)
        db.commit()
        charge_call(db, call)
        db.commit()
        body = summary(db, org_id)

    assert body["minutes_used_this_month"] == 1.5
    assert body["spent_this_month_paise"] == 450
    assert body["balance_paise"] == 2550
