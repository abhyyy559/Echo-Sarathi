"""SaaS business layer: plan periods, included minutes, invoices, team, admin.

Money paths are exercised through the API where a customer would touch them
(subscribe, cancel, invoices, team, reset) and through the service layer where
a webhook or dialer would (charge_call, can_dial).
"""
from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.services import billing, email as email_service, invoices, plans
from app.timeutil import utcnow
from conftest import auth_headers, make_settings, register


@pytest.fixture()
def manual_client(session_factory: Any) -> Iterator[TestClient]:
    """Client with offline payments on (the operator-settled path)."""
    application = create_app(make_settings(allow_manual_payments=True))
    application.state.session_factory = session_factory
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def platform_client(session_factory: Any) -> Iterator[TestClient]:
    application = create_app(
        make_settings(
            allow_manual_payments=True,
            platform_admin_emails="boss@example.test",
        )
    )
    application.state.session_factory = session_factory
    with TestClient(application) as test_client:
        yield test_client


def _org_id(session_factory: Any) -> int:
    from app.models import Organization

    with session_factory() as db:
        org = db.scalar(select(Organization).order_by(Organization.id))
        assert org is not None
        return org.id


def _subscribe(client: TestClient, token: str, plan_id: str = "starter") -> dict[str, Any]:
    resp = client.post(
        "/api/billing/subscribe",
        json={"plan_id": plan_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- plans & subscriptions ---------------------------------------------------


def test_plan_catalog_is_public(manual_client):
    token, _ = register(manual_client)
    resp = manual_client.get("/api/billing/plans", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = [plan["id"] for plan in data["plans"]]
    assert ids == ["free", "starter", "growth", "scale", "enterprise"]
    assert data["current_plan_id"] == "free"


def test_manual_subscribe_starts_period_and_issues_gst_invoice(manual_client):
    token, user = register(manual_client, org_name="Sarathi U", email="owner@su.test")
    data = _subscribe(manual_client, token, "starter")

    assert data["mode"] == "manual"
    assert data["invoice"] is not None
    invoice = data["invoice"]
    assert invoice["number"].startswith("ES/")
    assert invoice["total_paise"] == 299_000
    assert invoice["subtotal_paise"] + invoice["gst_paise"] == invoice["total_paise"]
    assert invoice["gst_paise"] == round(299_000 * 18 / 118)

    summary = data
    assert summary["plan"]["id"] == "starter"
    assert summary["subscription"]["included_minutes"] == 1000
    assert summary["included_minutes_remaining"] == 1000
    assert summary["balance_paise"] == 3000  # wallet untouched by a plan buy

    invoices_resp = manual_client.get(
        "/api/billing/invoices", headers=auth_headers(token)
    )
    assert invoices_resp.status_code == 200
    rows = invoices_resp.json()["invoices"]
    assert len(rows) == 1 and rows[0]["payment_id"] is not None
    assert invoices_resp.json()["seller"]["name"]

    detail = manual_client.get(
        f"/api/billing/invoices/{rows[0]['id']}", headers=auth_headers(token)
    )
    assert detail.status_code == 200
    assert detail.json()["customer_email"] == "owner@su.test"


def test_cancel_keeps_period_but_stops_renewal(manual_client):
    token, _ = register(manual_client)
    _subscribe(manual_client, token, "growth")
    resp = manual_client.post("/api/billing/cancel", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["subscription"]["cancel_at_period_end"] is True


def test_downgrade_to_free_plan_is_not_a_checkout(manual_client):
    token, _ = register(manual_client)
    resp = manual_client.post(
        "/api/billing/subscribe",
        json={"plan_id": "free"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


def test_member_cannot_buy_a_plan(manual_client, monkeypatch):
    token, user = register(manual_client, email="owner@member.test")
    _subscribe(manual_client, token, "starter")  # 3 seats, so the invite fits
    captured: list[str] = []
    monkeypatch.setattr(
        email_service,
        "invite",
        lambda *args, **kwargs: captured.append(kwargs["accept_url"]),
    )
    created = manual_client.post(
        "/api/team/invites",
        json={"email": "member@member.test", "role": "member"},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    raw = captured[0].split("token=")[1]
    accepted = manual_client.post(
        "/api/auth/accept-invite", json={"token": raw, "password": "password123"}
    )
    assert accepted.status_code == 200, accepted.text
    member_token = accepted.json()["token"]
    denied = manual_client.post(
        "/api/billing/subscribe",
        json={"plan_id": "starter"},
        headers=auth_headers(member_token),
    )
    assert denied.status_code == 403


# --- included minutes & wallet overage ---------------------------------------


def test_included_minutes_are_consumed_before_the_wallet(manual_client, session_factory):
    token, user = register(manual_client, email="meter@example.test")
    _subscribe(manual_client, token, "starter")
    org_id = user["org_id"]

    from app.models import Call

    now = utcnow()
    with session_factory() as db:
        # Shrink the allowance to 10 minutes so overage is reachable in a test.
        subscription = plans.active_subscription(db, org_id)
        assert subscription is not None
        subscription.included_minutes = 10
        db.commit()

        first = Call(
            org_id=org_id,
            kind="phone",
            status="completed",
            started_at=now,
            answered_at=now,
            duration_seconds=300.0,
        )
        db.add(first)
        db.commit()
        first_id = first.id

        assert billing.charge_call(db, first) is not None
        db.commit()
        covered = db.scalar(
            select(billing.CreditLedger).where(
                billing.CreditLedger.call_id == first_id,
                billing.CreditLedger.kind == "usage",
            )
        )
        assert covered is not None and covered.amount_paise == 0
        assert billing.balance_paise(db, org_id) == 3000

        second = Call(
            org_id=org_id,
            kind="phone",
            status="completed",
            started_at=now,
            answered_at=now,
            duration_seconds=500.0,
        )
        db.add(second)
        db.commit()
        assert billing.charge_call(db, second) is not None
        db.commit()
        overage = db.scalar(
            select(billing.CreditLedger).where(
                billing.CreditLedger.call_id == second.id,
                billing.CreditLedger.kind == "usage",
            )
        )
        # 600s allowance - 300s used = 300s included; 200s billable @ Rs 3/min.
        assert overage is not None and overage.amount_paise == -1000
        assert billing.balance_paise(db, org_id) == 2000

        # Re-running the same completion is a no-op (webhook duplication).
        assert billing.charge_call(db, second) is None


def test_plan_minutes_keep_dialing_with_an_empty_wallet(manual_client, session_factory):
    token, user = register(manual_client, email="dial@example.test")
    _subscribe(manual_client, token, "starter")
    org_id = user["org_id"]

    with session_factory() as db:
        assert billing.can_dial(db, org_id) is True
        org = db.get(billing.Organization, org_id)
        org.credit_balance_paise = 0
        db.commit()
        assert billing.can_dial(db, org_id) is True

        # A fully used plan leaves nothing to dial on.
        from app.models import Call

        now = utcnow()
        db.add(
            Call(
                org_id=org_id,
                kind="phone",
                status="completed",
                started_at=now,
                answered_at=now,
                duration_seconds=60_000.0,
            )
        )
        db.commit()
        assert billing.can_dial(db, org_id) is False


def test_playground_and_unanswered_calls_are_not_billed(manual_client, session_factory):
    token, user = register(manual_client, email="free@example.test")
    org_id = user["org_id"]
    from app.models import Call

    now = utcnow()
    with session_factory() as db:
        playground = Call(
            org_id=org_id,
            kind="playground",
            status="completed",
            started_at=now,
            answered_at=now,
            duration_seconds=120.0,
        )
        unanswered = Call(
            org_id=org_id,
            kind="phone",
            status="no_answer",
            started_at=now,
            duration_seconds=30.0,
        )
        db.add_all([playground, unanswered])
        db.commit()
        assert billing.charge_call(db, playground) is None
        assert billing.charge_call(db, unanswered) is None
        db.commit()
        assert billing.balance_paise(db, org_id) == 3000


# --- invoice numbering -------------------------------------------------------


def test_invoice_numbers_are_sequential_per_financial_year(session_factory):
    from app.models import Organization

    with session_factory() as db:
        org = Organization(name="Invoice Co", slug="invoice-co")
        db.add(org)
        db.commit()
        first = invoices.create_invoice(
            db, org, description="Starter plan", total_paise=299_000
        )
        second = invoices.create_invoice(
            db, org, description="Top-up", total_paise=18_000
        )
        assert second.number.endswith("0002")
        assert first.number != second.number
        assert first.number.split("/")[1] == invoices.financial_year(utcnow())
        db.rollback()


# --- team & seats ------------------------------------------------------------


def test_team_invite_accept_and_role_rules(manual_client, monkeypatch):
    token, _ = register(manual_client, org_name="Team Co", email="owner@team.test")
    _subscribe(manual_client, token, "starter")  # 3 seats

    captured: list[str] = []
    monkeypatch.setattr(
        email_service,
        "invite",
        lambda *args, **kwargs: captured.append(kwargs["accept_url"]),
    )
    created = manual_client.post(
        "/api/team/invites",
        json={"email": "new@team.test", "role": "member"},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    assert captured and "token=" in captured[0]

    team = manual_client.get("/api/team", headers=auth_headers(token)).json()
    assert team["seats_used"] == 2  # owner + pending invite
    assert team["seats_limit"] == 3

    raw = captured[0].split("token=")[1]
    accepted = manual_client.post(
        "/api/auth/accept-invite", json={"token": raw, "password": "password123"}
    )
    assert accepted.status_code == 200, accepted.text
    member_token = accepted.json()["token"]
    assert accepted.json()["user"]["role"] == "member"

    # Members cannot invite; the owner can promote the member to admin.
    forbidden = manual_client.post(
        "/api/team/invites",
        json={"email": "third@team.test", "role": "member"},
        headers=auth_headers(member_token),
    )
    assert forbidden.status_code == 403
    member_id = accepted.json()["user"]["id"]
    promoted = manual_client.patch(
        f"/api/team/members/{member_id}",
        json={"role": "admin"},
        headers=auth_headers(token),
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"


def test_seat_limit_blocks_the_fourth_member(manual_client, monkeypatch):
    token, _ = register(manual_client, org_name="Small Co", email="owner@small.test")
    _subscribe(manual_client, token, "starter")  # 3 seats
    monkeypatch.setattr(email_service, "invite", lambda *args, **kwargs: None)

    for address in ("a@small.test", "b@small.test"):
        resp = manual_client.post(
            "/api/team/invites",
            json={"email": address, "role": "member"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text

    overflow = manual_client.post(
        "/api/team/invites",
        json={"email": "c@small.test", "role": "member"},
        headers=auth_headers(token),
    )
    assert overflow.status_code == 403
    assert "team seats" in overflow.json()["detail"]


def test_free_plan_agent_limit(manual_client):
    token, _ = register(manual_client, email="agents@example.test")
    for index in range(3):
        ok = manual_client.post(
            "/api/agents",
            json={"name": f"Agent {index}"},
            headers=auth_headers(token),
        )
        assert ok.status_code == 201, ok.text
    blocked = manual_client.post(
        "/api/agents", json={"name": "Agent 4"}, headers=auth_headers(token)
    )
    assert blocked.status_code == 403
    assert "active agents" in blocked.json()["detail"]


# --- password reset ----------------------------------------------------------


def test_password_reset_flow(manual_client, monkeypatch):
    register(manual_client, email="forgetful@example.test", password="oldpassword1")
    captured: list[str] = []
    monkeypatch.setattr(
        email_service,
        "password_reset",
        lambda *args, **kwargs: captured.append(kwargs["reset_url"]),
    )

    anonymous = manual_client.post(
        "/api/auth/forgot-password", json={"email": "forgetful@example.test"}
    )
    assert anonymous.status_code == 200
    assert anonymous.json() == {"status": "sent"}
    # Unknown addresses get the same answer (no account enumeration).
    ghost = manual_client.post(
        "/api/auth/forgot-password", json={"email": "ghost@example.test"}
    )
    assert ghost.json() == {"status": "sent"}
    assert len(captured) == 1

    raw = captured[0].split("token=")[1]
    weak = manual_client.post(
        "/api/auth/reset-password", json={"token": raw, "password": "short"}
    )
    assert weak.status_code == 422
    changed = manual_client.post(
        "/api/auth/reset-password", json={"token": raw, "password": "newpassword1"}
    )
    assert changed.status_code == 200
    reused = manual_client.post(
        "/api/auth/reset-password", json={"token": raw, "password": "anotherpass1"}
    )
    assert reused.status_code == 400

    old_login = manual_client.post(
        "/api/auth/login",
        json={"email": "forgetful@example.test", "password": "oldpassword1"},
    )
    assert old_login.status_code == 401
    new_login = manual_client.post(
        "/api/auth/login",
        json={"email": "forgetful@example.test", "password": "newpassword1"},
    )
    assert new_login.status_code == 200


# --- platform admin ----------------------------------------------------------


def test_platform_admin_is_guarded_by_email(platform_client):
    boss_token, boss = register(platform_client, email="boss@example.test")
    assert boss["is_platform_admin"] is True
    other_token, other = register(platform_client, org_name="Other", email="other@example.test")
    assert other["is_platform_admin"] is False

    assert platform_client.get(
        "/api/platform/summary", headers=auth_headers(boss_token)
    ).status_code == 200
    assert platform_client.get(
        "/api/platform/summary", headers=auth_headers(other_token)
    ).status_code == 403
    assert platform_client.get(
        "/api/platform/orgs", headers=auth_headers(other_token)
    ).status_code == 403


def test_platform_credit_adjustment_and_enterprise_assignment(platform_client):
    boss_token, boss = register(platform_client, email="boss@example.test")

    listed = platform_client.get(
        "/api/platform/orgs", headers=auth_headers(boss_token)
    )
    assert listed.status_code == 200
    assert len(listed.json()["orgs"]) == 1

    adjusted = platform_client.post(
        f"/api/platform/orgs/{boss['org_id']}/credits",
        json={"amount_paise": 50_000, "description": "NEFT settlement"},
        headers=auth_headers(boss_token),
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["balance_after_paise"] == 53_000

    assigned = platform_client.post(
        f"/api/platform/orgs/{boss['org_id']}/plan",
        json={
            "plan_id": "enterprise",
            "months": 12,
            "included_minutes": 30_000,
            "price_paise": 7_500_000,
        },
        headers=auth_headers(boss_token),
    )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    assert body["subscription"]["included_minutes"] == 30_000
    assert body["invoice"]["total_paise"] == 7_500_000

    summary = platform_client.get("/api/billing", headers=auth_headers(boss_token))
    assert summary.json()["plan"]["id"] == "enterprise"
    start = body["subscription"]["period_start"]
    end = body["subscription"]["period_end"]
    assert end > start
