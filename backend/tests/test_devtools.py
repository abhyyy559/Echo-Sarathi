"""Dev-tools endpoints (dev-only, removed in production) + internal token gate.

- GET /api/health — presence booleans only, never key values
- GET /api/dev/status — calling hours, limits, alembic revision (auth required)
"""
from __future__ import annotations

from typing import Any

from conftest import auth_headers, register


def test_health_reports_presence_booleans(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["db"] is True  # sqlite in-memory answers SELECT 1
    assert isinstance(body["redis"], bool)
    assert body["voice_agent"] == "unknown"  # no registry this phase

    providers = body["providers"]
    assert set(providers.keys()) == {
        "deepgram",
        "cartesia",
        "groq",
        "openai",
        "twilio",
        "plivo",
        "livekit",
    }
    assert all(isinstance(v, bool) for v in providers.values())
    assert providers["twilio"] is False, "test settings configure no twilio creds"
    assert providers["livekit"] is True, "test settings configure devkey/devsecret"
    # Presence only — the response must never contain any key material.
    assert "devsecret" not in resp.text and "sk-" not in resp.text


def test_health_reports_redis_down_without_crashing(app, session_factory):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from conftest import make_settings

    fresh = create_app(make_settings(redis_url="redis://localhost:59999/0"))
    fresh.state.session_factory = session_factory
    with TestClient(fresh) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["redis"] is False


def test_dev_status_requires_auth(client):
    assert client.get("/api/dev/status").status_code == 401


def test_dev_status_reports_config_and_alembic(client):
    token, _user = register(client)
    resp = client.get("/api/dev/status", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["calling_hours"]["start"] == 9
    assert body["calling_hours"]["end"] == 21
    assert body["calling_hours"]["timezone"] == "Asia/Kolkata"
    assert isinstance(body["calling_hours"]["within_hours_now"], bool)

    assert body["limits"]["cps"] == 1.0
    assert body["limits"]["concurrency"] == 10
    assert body["limits"]["retry_max_attempts"] == 3

    assert body["dialer_enabled"] is False
    assert body["environment"] == "development"
    assert "alembic" in body
    assert set(body["alembic"].keys()) == {"db_revision", "table_present"}


def test_internal_agent_config_serves_version_payload(client):
    import json as _json

    token, _ = register(client)
    agent = client.post(
        "/api/agents",
        json={"name": "Internal Agent", "description": ""},
        headers=auth_headers(token),
    ).json()
    from test_agents import version_payload

    version = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=version_payload(),
        headers=auth_headers(token),
    ).json()

    served = client.get(
        "/internal/agent-config",
        params={"version_id": version["id"]},
        headers={"X-Internal-Token": "test_internal_token"},
    )
    assert served.status_code == 200, served.text
    config = served.json()
    assert config["version_id"] == version["id"]
    assert config["system_prompt"] == version["system_prompt"]
    assert config["disclosure_script"] == version["disclosure_script"]
    assert len(config["question_flow"]) == len(version["question_flow"])
    assert _json.dumps(config["extraction_schema"]) == _json.dumps(
        version["extraction_schema"]
    )


def test_internal_agent_config_unknown_version_404(client):
    resp = client.get(
        "/internal/agent-config",
        params={"version_id": 424242},
        headers={"X-Internal-Token": "test_internal_token"},
    )
    assert resp.status_code == 404


def test_internal_requires_token_everywhere(client):
    assert (
        client.get("/internal/agent-config", params={"version_id": 1}).status_code == 401
    )
    assert (
        client.get(
            "/internal/calls/1/context", headers={"X-Internal-Token": "nope"}
        ).status_code
        == 401
    )
