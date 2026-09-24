"""Agents & immutable versions tests (Lane A).

Contract §4: CRUD for agents, immutable version rows validated with
domain_config_schema rules, and strict org isolation (cross-org => 404).
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

from conftest import auth_headers, register

_ABSENT_STUDENT = Path(__file__).resolve().parents[2] / "domain-configs" / "absent-student.json"


def version_payload(**overrides: Any) -> dict[str, Any]:
    """A valid AgentVersion payload derived from the shipped domain config."""
    config = json.loads(_ABSENT_STUDENT.read_text(encoding="utf-8-sig"))
    payload: dict[str, Any] = {
        "system_prompt": config["system_prompt"],
        "company_context": {"institution": "Demo University"},
        "question_flow": config["question_flow"],
        "extraction_schema": config["extraction_schema"],
        "disclosure_script": config["mandatory_disclosure"],
        "escalation_rules": config["escalation_rules"],
        "voice_settings": {"voice_id": "demo-voice", "speed": 1.0},
    }
    payload.update(overrides)
    return payload


def _create_agent(client: Any, token: str, name: str | None = None) -> dict[str, Any]:
    name = name or f"agent-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/agents",
        json={"name": name, "description": "test agent"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- role presets ("default prompts") --------------------------------------------


def test_list_presets_returns_valid_payloads(client):
    token, _user = register(client)
    resp = client.get("/api/agents/presets", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    presets = resp.json()
    ids = {p["preset_id"] for p in presets}
    # Only the attendance preset ships after single-agent cleanup.
    assert ids == {"absent-student-followup"}
    for preset in presets:
        assert preset["name"]
        payload = preset["version_payload"]
        # Each preset is a complete, saveable AgentVersion payload.
        assert payload["system_prompt"]
        assert payload["question_flow"]
        assert payload["extraction_schema"]
        assert payload["disclosure_script"]
        assert payload["escalation_rules"]


def test_absent_student_preset_has_attendance_schema(client):
    token, _user = register(client)
    presets = client.get("/api/agents/presets", headers=auth_headers(token)).json()
    payload = next(p for p in presets if p["preset_id"] == "absent-student-followup")["version_payload"]
    assert set(payload["extraction_schema"]) >= {
        "reason_for_absence", "expected_return_date", "is_sick_leave",
    }
    assert len(payload["question_flow"]) == 4
    prompt = payload["system_prompt"].lower()
    assert "absence" in prompt


def test_preset_payload_saves_as_agent_version(client):
    """End-to-end contract: pick a preset, create an agent, save it as v1."""
    token, _user = register(client)
    presets = client.get(
        "/api/agents/presets", headers=auth_headers(token)
    ).json()
    attendance = next(p for p in presets if p["preset_id"] == "absent-student-followup")

    agent = _create_agent(client, token, name="My Attendance Caller")
    resp = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=attendance["version_payload"],
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["version"] == 1
    assert "absence" in body["system_prompt"].lower()


def test_list_presets_requires_auth(client):
    assert client.get("/api/agents/presets").status_code in (401, 403)


# --- agent CRUD ----------------------------------------------------------------
# --- agent CRUD ----------------------------------------------------------------


def test_create_agent_returns_draft(client):
    token, user = register(client)
    resp = client.post(
        "/api/agents",
        json={"name": "Absent Student Follow-up", "description": "calls parents"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    assert body["name"] == "Absent Student Follow-up"
    assert body["status"] == "draft"
    assert body["current_version_id"] is None
    assert body["org_id"] == user["org_id"]


def test_list_agents_is_org_scoped_and_excludes_archived(client):
    token_a, _ = register(client, org_name="Org A", email="a@example.test")
    token_b, _ = register(client, org_name="Org B", email="b@example.test")
    agent = _create_agent(client, token_a)

    listed_b = client.get("/api/agents", headers=auth_headers(token_b))
    assert listed_b.status_code == 200
    assert listed_b.json() == [], "fresh org must see zero agents"

    listed_a = client.get("/api/agents", headers=auth_headers(token_a))
    assert [row["id"] for row in listed_a.json()] == [agent["id"]]

    deleted = client.delete(f"/api/agents/{agent['id']}", headers=auth_headers(token_a))
    assert deleted.status_code in (200, 204)
    listed_after = client.get("/api/agents", headers=auth_headers(token_a))
    assert listed_after.json() == [], "archived agents must be hidden from the list"


def test_patch_updates_meta_only(client):
    token, _ = register(client)
    agent = _create_agent(client, token)
    version_resp = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=version_payload(),
        headers=auth_headers(token),
    )
    assert version_resp.status_code in (200, 201), version_resp.text

    patched = client.patch(
        f"/api/agents/{agent['id']}",
        json={"name": "Renamed", "description": "new desc"},
        headers=auth_headers(token),
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "Renamed"
    assert body["description"] == "new desc"
    assert body["current_version_id"] is not None, "PATCH meta must not reset versions"


def test_get_agent_detail_cross_org_is_404_key_test(client):
    """THE tenancy guarantee: org B touching org A's agent sees 404, never 403."""
    token_a, _ = register(client, org_name="Org A", email="a@example.test")
    token_b, _ = register(client, org_name="Org B", email="b@example.test")
    agent = _create_agent(client, token_a)

    own = client.get(f"/api/agents/{agent['id']}", headers=auth_headers(token_a))
    assert own.status_code == 200, own.text

    foreign = client.get(f"/api/agents/{agent['id']}", headers=auth_headers(token_b))
    assert foreign.status_code == 404, (
        f"cross-org access must be 404 (no existence leak), got {foreign.status_code}"
    )


def test_agents_require_bearer_token(client):
    assert client.get("/api/agents").status_code == 401
    assert client.post("/api/agents", json={"name": "x"}).status_code == 401


# --- versions ------------------------------------------------------------------


def test_version_roundtrip_and_current_pointer(client):
    token, _ = register(client)
    agent = _create_agent(client, token)

    v1_resp = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=version_payload(),
        headers=auth_headers(token),
    )
    assert v1_resp.status_code in (200, 201), v1_resp.text
    v1 = v1_resp.json()
    assert v1["version"] == 1
    assert v1["agent_id"] == agent["id"]

    v2_resp = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=version_payload(system_prompt="Updated persona prompt for alumni outreach calls."),
        headers=auth_headers(token),
    )
    assert v2_resp.status_code in (200, 201), v2_resp.text
    v2 = v2_resp.json()
    assert v2["version"] == 2

    detail = client.get(f"/api/agents/{agent['id']}", headers=auth_headers(token))
    assert detail.json()["current_version_id"] == v2["id"], "pointer must advance"

    history = client.get(
        f"/api/agents/{agent['id']}/versions", headers=auth_headers(token)
    )
    assert history.status_code == 200
    rows = history.json()
    assert sorted(row["version"] for row in rows) == [1, 2]

    # Immutability: fetching v1 after creating v2 returns identical content.
    v1_refetched = client.get(f"/api/agent-versions/{v1['id']}", headers=auth_headers(token))
    assert v1_refetched.status_code == 200
    fetched = v1_refetched.json()
    for key, original in v1.items():
        if key in {"created_at", "updated_at"}:
            continue
        assert fetched[key] == original, f"immutable v1 field '{key}' mutated"


def test_version_validation_errors_name_fields(client):
    token, _ = register(client)
    agent = _create_agent(client, token)

    missing_disclosure = version_payload()
    missing_disclosure.pop("disclosure_script")
    resp = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=missing_disclosure,
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert "disclosure" in resp.text.lower()

    empty_flow = version_payload(question_flow=[])
    resp = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=empty_flow,
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert "question_flow" in resp.text.lower()

    bad_confidence = version_payload()
    bad_confidence["extraction_schema"]["reason_for_absence"]["confidence_threshold"] = 1.5
    resp = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=bad_confidence,
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    lowered = resp.text.lower()
    assert "confidence" in lowered or "extraction_schema" in lowered

    non_sequential = version_payload()
    non_sequential["question_flow"][1]["step"] = 3
    resp = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=non_sequential,
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert "sequential" in resp.text.lower()


def test_foreign_agent_version_access_is_404(client):
    token_a, _ = register(client, org_name="Org A", email="a@example.test")
    token_b, _ = register(client, org_name="Org B", email="b@example.test")
    agent = _create_agent(client, token_a)
    version = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=version_payload(),
        headers=auth_headers(token_a),
    ).json()

    foreign = client.get(f"/api/agent-versions/{version['id']}", headers=auth_headers(token_b))
    assert foreign.status_code == 404


def test_member_cannot_delete_agent_but_owner_can(client, session_factory):
    from app.auth import hash_password
    from app.models import User

    token, user = register(client)
    agent = _create_agent(client, token)

    # Create a member of the same org directly, then log in as them.
    with session_factory() as db:
        db.add(
            User(
                org_id=user["org_id"],
                email=f"member-{uuid.uuid4().hex[:6]}@example.test",
                password_hash=hash_password("memberpass123"),
                role="member",
            )
        )
        db.commit()
        member_email = (
            db.query(User)
            .filter(User.org_id == user["org_id"], User.role == "member")
            .order_by(User.id.desc())
            .first()
            .email
        )

    member_login = client.post(
        "/api/auth/login", json={"email": member_email, "password": "memberpass123"}
    )
    assert member_login.status_code == 200, member_login.text
    member_token = member_login.json()["token"]

    forbidden = client.delete(
        f"/api/agents/{agent['id']}", headers=auth_headers(member_token)
    )
    assert forbidden.status_code == 403, "members must not delete agents"
    still_there = client.get(f"/api/agents/{agent['id']}", headers=auth_headers(token))
    assert still_there.status_code == 200

    allowed = client.delete(f"/api/agents/{agent['id']}", headers=auth_headers(token))
    assert allowed.status_code in (200, 204)


def test_archived_agent_versions_still_queryable(client):
    token, _ = register(client)
    agent = _create_agent(client, token)
    version = client.post(
        f"/api/agents/{agent['id']}/versions",
        json=version_payload(),
        headers=auth_headers(token),
    ).json()

    assert (
        client.delete(f"/api/agents/{agent['id']}", headers=auth_headers(token)).status_code
        in (200, 204)
    )
    history = client.get(f"/api/agents/{agent['id']}/versions", headers=auth_headers(token))
    assert history.status_code == 200, "archived agent history stays queryable"
    fetched = client.get(
        f"/api/agent-versions/{version['id']}", headers=auth_headers(token)
    )
    assert fetched.status_code == 200
