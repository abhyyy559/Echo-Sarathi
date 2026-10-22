"""GET /api/analytics/usage — per-key provider quota for the dashboard card.

The card answers one question: which key/limit gets exhausted first. Rows are
seeded directly through the ORM (the worker's ingest path is covered by
``POST /internal/usage`` in the same file).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.timeutil import utcnow
from tests.conftest import auth_headers, register


def _seed_snapshot(
    db,  # noqa: ANN001 - session factory
    *,
    provider: str,
    key_id: str,
    metric: str,
    value: float,
    model: str = "",
    timestamp=None,
) -> None:
    from app.models import UsageSnapshot

    db.add(
        UsageSnapshot(
            provider=provider,
            key_id=key_id,
            model=model,
            metric=metric,
            value=value,
            timestamp=timestamp or utcnow(),
        )
    )


def test_usage_requires_auth(client: TestClient) -> None:
    assert client.get("/api/analytics/usage").status_code == 401


def test_usage_empty_states_are_explicit(client: TestClient) -> None:
    token, _user = register(client, org_name="Usage Empty Org")
    resp = client.get("/api/analytics/usage", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["keys"] == []
    assert data["alerts"] == []
    assert data["sarvam"]["characters"] == 0.0
    assert data["sarvam"]["cost_inr"] == 0.0


def test_usage_reports_worst_key_first_with_headline(
    client: TestClient, session_factory
) -> None:
    token, _user = register(client, org_name="Usage Org")
    with session_factory() as db:
        # Shared org TPM bucket, per-key request counters — the real Groq shape.
        _seed_snapshot(
            db, provider="groq", key_id="gsk_...aaaa", model="qwen/qwen3.8-27b",
            metric="limit_tokens", value=8000,
        )
        _seed_snapshot(
            db, provider="groq", key_id="gsk_...aaaa", model="qwen/qwen3.8-27b",
            metric="remaining_tokens", value=400,  # 5% -> critical
        )
        _seed_snapshot(
            db, provider="groq", key_id="gsk_...bbbb", model="qwen/qwen3.8-27b",
            metric="limit_tokens", value=8000,
        )
        _seed_snapshot(
            db, provider="groq", key_id="gsk_...bbbb", model="qwen/qwen3.8-27b",
            metric="remaining_tokens", value=6000,  # 75% -> ok
        )
        db.commit()

    resp = client.get("/api/analytics/usage", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert [k["key_id"] for k in data["keys"]] == ["gsk_...aaaa", "gsk_...bbbb"]
    worst, best = data["keys"]
    assert worst["status"] == "critical"
    assert "5% left" in worst["headline"]
    assert worst["remaining_fraction"] == 0.05
    assert best["status"] == "ok"

    assert len(data["alerts"]) == 1
    assert data["alerts"][0]["level"] == "critical"
    assert data["alerts"][0]["key_id"] == "gsk_...aaaa"


def test_usage_reports_zero_remaining_as_exhausted(
    client: TestClient, session_factory
) -> None:
    token, _user = register(client, org_name="Exhausted Org")
    with session_factory() as db:
        _seed_snapshot(
            db, provider="groq", key_id="gsk_...dead", metric="limit_requests", value=1000
        )
        _seed_snapshot(
            db, provider="groq", key_id="gsk_...dead", metric="remaining_requests", value=0
        )
        db.commit()

    data = client.get("/api/analytics/usage", headers=auth_headers(token)).json()
    assert data["keys"][0]["status"] == "critical"
    assert "exhausted" in data["keys"][0]["headline"]


def test_usage_without_limit_is_unknown_not_fake_healthy(
    client: TestClient, session_factory
) -> None:
    """Deepgram reports volume, not a remaining budget: the card must say so
    rather than showing a green 'healthy' badge it cannot justify."""
    token, _user = register(client, org_name="Volume Org")
    with session_factory() as db:
        _seed_snapshot(
            db, provider="deepgram", key_id="sk-...dddd", model="nova-3",
            metric="usage_requests", value=421,
        )
        db.commit()

    data = client.get("/api/analytics/usage", headers=auth_headers(token)).json()
    assert data["keys"][0]["status"] == "unknown"
    assert data["keys"][0]["remaining_fraction"] is None
    assert data["alerts"] == []


def test_usage_summarizes_sarvam_characters_and_hides_them_from_keys(
    client: TestClient, session_factory
) -> None:
    token, _user = register(client, org_name="Sarvam Org")
    with session_factory() as db:
        _seed_snapshot(
            db, provider="sarvam", key_id="", model="bulbul:v3",
            metric="characters", value=2500,
        )
        _seed_snapshot(
            db, provider="sarvam", key_id="", model="bulbul:v3",
            metric="characters", value=1500,
        )
        db.commit()

    data = client.get("/api/analytics/usage", headers=auth_headers(token)).json()
    # Cumulative characters are a cost metric, not a key quota: they must not
    # appear as a "key" with an invented remaining budget.
    assert data["keys"] == []
    assert data["sarvam"]["characters"] == 4000.0
    # 4000 chars * (30 INR / 10000) = 12.0 INR
    assert data["sarvam"]["cost_inr"] == 12.0
    assert data["sarvam"]["models"] == ["bulbul:v3"]


def test_internal_usage_ingest_masks_raw_keys(client: TestClient, session_factory) -> None:
    """The worker may send an unmasked key; the backend must store only the id."""
    resp = client.post(
        "/internal/usage",
        headers={"X-Internal-Token": "test_internal_token"},
        json={
            "snapshots": [
                {
                    "provider": "groq",
                    "key_id": "gsk_1234567890abcdef",
                    "model": "qwen/qwen3.8-27b",
                    "metric": "remaining_tokens",
                    "value": 1234,
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["written"] == 1

    with session_factory() as db:
        from app.models import UsageSnapshot

        rows = db.query(UsageSnapshot).all()
    assert len(rows) == 1
    assert rows[0].key_id == "gsk_...cdef"
    assert "1234567890" not in rows[0].key_id


def test_dev_usage_refresh_never_raises_without_admin_keys(
    client: TestClient, session_factory
) -> None:
    """No Deepgram project id / Cartesia admin key configured: the refresh is a
    no-op, not a 500. The dashboard button must always be safe to press."""
    token, _user = register(client, org_name="Refresh Org")
    resp = client.post("/api/dev/usage/refresh", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["written"] == 0
    assert body["deepgram_configured"] is False
    assert body["cartesia_configured"] is False