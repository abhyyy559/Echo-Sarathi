"""Google Sign-In tests.

Google's token verification is stubbed — the real check fetches Google's
rotating signing certs over the network. Everything after verification
(account linking, org creation, registration gating, JWT issuance) runs for
real, against the same database the other auth tests use.
"""
from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import Organization, User
from app.services.billing import TRIAL_CREDITS_PAISE
from app.services.google_auth import GoogleTokenError
from conftest import auth_headers, make_settings, register


def google_claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "sub": "google-sub-1",
        "email": "newuser@example.test",
        "email_verified": True,
        "name": "New User",
    }
    claims.update(overrides)
    return claims


@pytest.fixture()
def google_client(session_factory: Any) -> Iterator[TestClient]:
    application = create_app(make_settings(google_client_id="test-client-id"))
    application.state.session_factory = session_factory
    with TestClient(application) as test_client:
        yield test_client


def stub_google(
    monkeypatch: pytest.MonkeyPatch,
    claims: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    def fake_verify(credential: str, client_id: str) -> dict[str, Any]:
        assert client_id == "test-client-id"
        if error is not None:
            raise error
        assert claims is not None
        return claims

    monkeypatch.setattr("app.routers.auth.verify_google_credential", fake_verify)


def google_login(client: TestClient):
    return client.post(
        "/api/auth/google", json={"credential": "fake-credential-value"}
    )


# --- sign-up ---------------------------------------------------------------


def test_google_signup_creates_org_owner_and_trial(
    google_client, monkeypatch, session_factory
):
    stub_google(monkeypatch, google_claims())

    resp = google_login(google_client)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token"]
    assert data["user"]["role"] == "owner"
    assert data["user"]["email"] == "newuser@example.test"

    me = google_client.get("/api/auth/me", headers=auth_headers(data["token"]))
    assert me.status_code == 200
    assert me.json()["org_id"] == data["user"]["org_id"]

    with session_factory() as db:
        org = db.get(Organization, data["user"]["org_id"])
        user = db.scalar(select(User).where(User.email == "newuser@example.test"))
        assert org.name == "New User"
        assert org.credit_balance_paise == TRIAL_CREDITS_PAISE
        assert user.google_sub == "google-sub-1"
        assert user.password_hash is None


# --- linking an existing password account ----------------------------------


def test_google_links_existing_password_account(google_client, monkeypatch, session_factory):
    _, existing = register(google_client, email="owner@example.test")
    stub_google(
        monkeypatch,
        google_claims(sub="google-sub-link", email="owner@example.test"),
    )

    resp = google_login(google_client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["org_id"] == existing["org_id"]

    with session_factory() as db:
        assert db.scalar(select(func.count(User.id))) == 1
        user = db.scalar(select(User).where(User.email == "owner@example.test"))
        assert user.google_sub == "google-sub-link"

    # Both sign-in paths keep working after the link.
    assert google_login(google_client).status_code == 200
    pwd = google_client.post(
        "/api/auth/login",
        json={"email": "owner@example.test", "password": "password123"},
    )
    assert pwd.status_code == 200, pwd.text


def test_google_refuses_a_second_identity_on_a_linked_email(google_client, monkeypatch):
    register(google_client, email="owner@example.test")
    stub_google(
        monkeypatch, google_claims(sub="google-sub-a", email="owner@example.test")
    )
    assert google_login(google_client).status_code == 200

    stub_google(
        monkeypatch, google_claims(sub="google-sub-b", email="owner@example.test")
    )
    assert google_login(google_client).status_code == 409


# --- policy / failure paths ------------------------------------------------


def test_google_disabled_without_client_id(client):
    resp = client.post("/api/auth/google", json={"credential": "x" * 40})
    assert resp.status_code == 503


def test_invalid_google_credential_rejected(google_client, monkeypatch):
    stub_google(monkeypatch, error=GoogleTokenError("bad token"))
    assert google_login(google_client).status_code == 401


def test_google_signup_blocked_when_registration_closed(session_factory, monkeypatch):
    application = create_app(
        make_settings(
            google_client_id="test-client-id", allow_public_registration=False
        )
    )
    application.state.session_factory = session_factory
    with TestClient(application) as closed_client:
        stub_google(monkeypatch, google_claims())
        assert google_login(closed_client).status_code == 403

        # An existing account still signs in with Google while sign-up is off.
        # Seed it directly: public registration is exactly what is disabled.
        from app.auth import hash_password

        with session_factory() as db:
            org = Organization(name="Existing Org", slug="existing-org")
            db.add(org)
            db.flush()
            db.add(
                User(
                    org_id=org.id,
                    email="newuser@example.test",
                    password_hash=hash_password("password123"),
                    role="owner",
                )
            )
            db.commit()
        assert google_login(closed_client).status_code == 200


def test_password_login_rejected_for_google_only_user(google_client, monkeypatch):
    stub_google(monkeypatch, google_claims())
    assert google_login(google_client).status_code == 200

    resp = google_client.post(
        "/api/auth/login",
        json={"email": "newuser@example.test", "password": "anything123"},
    )
    assert resp.status_code == 401


def test_verification_requires_a_verified_email(monkeypatch):
    from app.services import google_auth

    monkeypatch.setattr(
        google_auth.id_token,
        "verify_oauth2_token",
        lambda *args, **kwargs: {
            "sub": "google-sub-1",
            "email": "unverified@example.test",
            "email_verified": False,
        },
    )
    with pytest.raises(GoogleTokenError):
        google_auth.verify_google_credential("credential", "test-client-id")
