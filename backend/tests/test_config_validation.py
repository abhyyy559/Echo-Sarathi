"""Lane E — config validation tests.

Layer 1 (runs today): the legacy validator ``domain_config_schema.DomainConfig``
already shipped in ``backend/`` — invalid extraction schemas, empty question
flows and missing disclosure scripts must be rejected with field-level error
messages; ``domain-configs/absent-student.json`` must pass.

Layer 2 (skips until Lane A merges): POST /api/agents/{id}/versions must
return 422 with per-field messages for the same violations, and accept a
payload built from absent-student.json in the frozen contract shape.
"""
from __future__ import annotations

import copy
from typing import Any

import pydantic
import pytest

from _qa_contract import (
    api,
    build_test_client,
    build_version_payload,
    create_agent,
    expect_merged,
    import_app,
    load_absent_student_config,
    register_org,
)

_VALIDATOR: Any = None


def _load_validator() -> Any:
    global _VALIDATOR
    if _VALIDATOR is None:
        import domain_config_schema  # type: ignore[import-not-found]

        _VALIDATOR = domain_config_schema
    return _VALIDATOR


def _valid_config() -> dict[str, Any]:
    return load_absent_student_config()


def _errors(exc: Any) -> list[tuple[tuple[int, ...], str]]:
    return [(tuple(err.get("loc", ())), str(err.get("msg", ""))) for err in exc.errors()]


def test_valid_absent_student_config_passes() -> None:
    schema = _load_validator()
    parsed = schema.validate_domain_config(_valid_config())
    assert parsed.domain_id == "absent-student"
    assert len(parsed.question_flow) == 3  # v2: tightened for the 2-minute call budget
    assert "reason_for_absence" in parsed.extraction_schema
    assert "needs_human_help" in parsed.extraction_schema


def test_invalid_extraction_field_type_rejected_with_field_message() -> None:
    schema = _load_validator()
    config = _valid_config()
    config["extraction_schema"]["bad_field"] = {
        "type": "integer",
        "description": "unsupported type",
        "validation": "optional",
        "confidence_threshold": 0.7,
    }
    with pytest.raises(pydantic.ValidationError) as excinfo:
        schema.validate_domain_config(config)
    locs = [loc for loc, _msg in _errors(excinfo.value)]
    assert any("extraction_schema" in map(str, loc) or "bad_field" in map(str, loc) for loc in locs), (
        f"error should name the offending extraction field, got {locs}"
    )


def test_confidence_threshold_out_of_range_rejected() -> None:
    schema = _load_validator()
    config = _valid_config()
    config["extraction_schema"]["reason_for_absence"]["confidence_threshold"] = 1.5
    with pytest.raises(pydantic.ValidationError) as excinfo:
        schema.validate_domain_config(config)
    flat = " | ".join(f"{loc} {msg}" for loc, msg in _errors(excinfo.value))
    assert "confidence" in flat.lower(), f"error should mention confidence_threshold, got: {flat}"


def test_empty_question_flow_rejected() -> None:
    schema = _load_validator()
    config = _valid_config()
    config["question_flow"] = []
    with pytest.raises(pydantic.ValidationError) as excinfo:
        schema.validate_domain_config(config)
    locs = [loc for loc, _msg in _errors(excinfo.value)]
    assert any("question_flow" in map(str, loc) for loc in locs), (
        f"error should locate question_flow, got {locs}"
    )


def test_non_sequential_question_steps_rejected() -> None:
    schema = _load_validator()
    config = _valid_config()
    config["question_flow"][1]["step"] = 3
    with pytest.raises(pydantic.ValidationError) as excinfo:
        schema.validate_domain_config(config)
    flat = " | ".join(msg for _loc, msg in _errors(excinfo.value))
    assert "sequential" in flat.lower(), f"error should explain step ordering rule, got: {flat}"


def test_missing_disclosure_script_rejected() -> None:
    schema = _load_validator()
    config = _valid_config()
    config.pop("mandatory_disclosure", None)
    config.pop("disclosure_script", None)
    with pytest.raises(pydantic.ValidationError) as excinfo:
        schema.validate_domain_config(config)
    all_loc_names = [str(part) for loc, _msg in _errors(excinfo.value) for part in loc]
    assert any("disclosure" in name for name in all_loc_names), (
        f"missing disclosure must be reported by field name, got {all_loc_names}"
    )


# --------------------------------------------------------------------------
# Layer 2 — HTTP contract on Lane A's agents router (skips until merged)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def http_env() -> Any:
    app, why_app = import_app()
    if app is None:
        pytest.skip(f"[Lane A] backend app not merged yet: {why_app}")
    client, why_client = build_test_client(app)
    if client is None:
        pytest.skip(f"[Lane A] test harness unavailable: {why_client}")
    with client as entered:
        owner, why_org = register_org(
            entered, org_name="Validation Org", email="validator@example.com"
        )
        owner = expect_merged(owner, f"registration broken: {why_org}")
        agent, why_agent = create_agent(entered, owner["token"], "validation-agent")
        agent = expect_merged(agent, f"agent creation unavailable: {why_agent}")
        yield {"client": entered, "token": owner["token"], "agent_id": agent["id"]}


def _post_version(env: dict[str, Any], payload: dict[str, Any]) -> Any:
    return api(
        env["client"],
        "POST",
        f"/api/agents/{env['agent_id']}/versions",
        token=env["token"],
        json=payload,
    )


def test_api_accepts_valid_absent_student_payload(http_env: dict[str, Any]) -> None:
    resp = _post_version(http_env, build_version_payload(load_absent_student_config()))
    assert resp.status_code in (200, 201), (
        f"valid absent-student payload rejected: {resp.status_code} {resp.text[:400]}"
    )
    body = resp.json()
    assert body.get("id") is not None or body.get("version_id") is not None, (
        f"version response missing id: {str(body)[:300]}"
    )


def test_api_missing_disclosure_script_is_422_naming_the_field(
    http_env: dict[str, Any],
) -> None:
    payload = build_version_payload(load_absent_student_config())
    payload.pop("disclosure_script")
    resp = _post_version(http_env, payload)
    assert resp.status_code == 422, (
        f"missing disclosure_script must be 422, got {resp.status_code}: {resp.text[:300]}"
    )
    assert "disclosure" in resp.text.lower(), (
        f"422 detail should name the disclosure field: {resp.text[:500]}"
    )


def test_api_empty_question_flow_is_422_naming_the_field(http_env: dict[str, Any]) -> None:
    payload = build_version_payload(load_absent_student_config())
    payload["question_flow"] = []
    resp = _post_version(http_env, payload)
    assert resp.status_code == 422, (
        f"empty question_flow must be 422, got {resp.status_code}: {resp.text[:300]}"
    )
    assert "question_flow" in resp.text.lower(), (
        f"422 detail should name question_flow: {resp.text[:500]}"
    )


def test_api_invalid_extraction_schema_is_422_with_field_message(
    http_env: dict[str, Any],
) -> None:
    payload = build_version_payload(load_absent_student_config())
    broken = copy.deepcopy(payload["extraction_schema"])
    broken["reason_for_absence"]["confidence_threshold"] = 1.5
    payload["extraction_schema"] = broken
    resp = _post_version(http_env, payload)
    assert resp.status_code == 422, (
        f"out-of-range confidence must be 422, got {resp.status_code}: {resp.text[:300]}"
    )
    detail = resp.text.lower()
    assert "confidence" in detail or "extraction_schema" in detail, (
        f"422 detail should point at the extraction field: {resp.text[:500]}"
    )
