# RE Task 2 Brief — Sample RE leads + automated dry-run gate

Source: `docs/superpowers/plans/2026-09-06-real-estate-agent.md` (Task 2, plan lines 134-326).

**Goal (plan):** Upgrade the shipped real-estate preset into the full verification→quotation-callback agent from the design spec, and prove it end-to-end with an automated dry-run gate.

## Global Constraints (bind this task — exact values verbatim from the plan)

- Type hints required in all Python test code.
- Never hardcode API keys — no credentials in this plan (no new `.env` entries).
- Config-only: no backend, voice-agent, or frontend code changes. No latency tuning, no concurrency changes, no new providers.
- Never fabricate a structured-field value on low confidence — the gate asserts structural persistence, not content.
- Every call domain stays a config/preset file — never a code branch.
- Backend tests run from `backend/` with `.\.venv\Scripts\python.exe -m pytest tests/<file>.py -q`.
- TDD every task: failing test, minimal implementation, green, commit. One task = one commit, staged files only.

## Machine notes (read before starting)

- Repo root is your working directory. The backend venv is `backend\.venv\Scripts\python.exe` (bare `python` is NOT on PATH). Run backend tests with workdir `backend/`.
- Shell is Windows PowerShell 5.1: no `&&` chaining (use `; if ($?) { ... }`), quote paths with spaces.
- Commit ONLY the two files this task names (`git add` those exact paths). The working tree contains unrelated uncommitted work — do not touch it.
- Task 1 (upgraded preset, commit `4de0238`) is the foundation — the gate test builds an agent version from its `version_payload` via the API.
- Patterns reused verbatim from P1 Task 8: `groq_client`/`script`/`chat`/`tool_call` imported from `test_playground_text`; ORM campaign/contact seeding; 8-message-style script accounting (here 5 Groq calls per contact: opening chat + record tool + follow-up chat + end_call tool + spare chat).

## Task text

### Task 2: Sample RE leads + automated dry-run gate

**Files:**
- Create: `sample_real_estate_contacts.csv` (repo root)
- Test: `backend/tests/test_real_estate_dry_run.py` (new)

**Interfaces:**
- Consumes: Task 1 (upgraded preset via `GET /api/agents/presets`); P1 `POST /api/playground/campaigns/{id}/dry-run`, `_render_text_system_prompt` (backend router).
- Produces: nothing downstream — this task is the verification gate. Manual follow-up (user roleplay + real dry-run in the deployed UI) is outside this plan.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_real_estate_dry_run.py` with exactly the content below. Top-of-file imports:

```python
"""Real-estate agent gate: preset tokens, prompt rendering, dry-run structure."""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from conftest import auth_headers, register
from test_playground_text import chat, groq_client, script, tool_call

_PRESET = Path(__file__).resolve().parents[2] / "domain-configs" / "presets" / "real-estate-lead-qualification.json"

# Tokens the maps resolve (backend build_token_map + voice map).
_MAPPED_TOKENS = {
    "[Institution Name]", "[Company Name]", "[Student Name]", "[Lead Name]",
    "[Parent/Guardian Name]", "[Agent Name]", "[Expected Return Date]",
}


def _payload() -> dict[str, Any]:
    return json.loads(_PRESET.read_text(encoding="utf-8"))["version_payload"]


def test_preset_spoken_regions_use_only_mapped_tokens() -> None:
    payload = _payload()
    spoken = "\n".join(
        [
            payload["disclosure_script"],
            payload["system_prompt"],
            *[step["question"] for step in payload["question_flow"]],
        ]
    )
    tokens = set(re.findall(r"\[[^\]]*\]", spoken))
    assert tokens, "expected at least the Company/Lead/Agent tokens"
    assert tokens <= _MAPPED_TOKENS, f"unmapped spoken tokens: {tokens - _MAPPED_TOKENS}"


def test_preset_renders_with_real_names() -> None:
    from app.routers.playground import _render_text_system_prompt

    payload = _payload()
    config = SimpleNamespace(
        disclosure_script=payload["disclosure_script"],
        system_prompt=payload["system_prompt"],
        company_context={},
        question_flow=payload["question_flow"],
        extraction_schema=payload["extraction_schema"],
    )
    contact = {"lead_name": "Riya Sharma", "city": "Hyderabad", "budget_band": "80 lakhs"}
    prompt = _render_text_system_prompt(config, contact=contact, institution="Acme Realty")
    assert "Riya Sharma" in prompt
    assert "Acme Realty" in prompt
    assert "Hyderabad" in prompt
    assert "[Lead Name]" not in prompt
    assert "[Company Name]" not in prompt
    leftovers = set(re.findall(r"\[[^\]]*\]", prompt))
    # [REQUIRED] is a platform marker the renderer adds for required fields,
    # not a placeholder leak — it is the only bracket token permitted here.
    assert leftovers <= {"[REQUIRED]"}, f"unsubstituted tokens in rendered prompt: {leftovers}"


def test_real_estate_dry_run_structural_gate(groq_client, session_factory):
    from sqlalchemy import select

    from app.models import Call, Campaign, Contact

    client = groq_client
    token, user = register(client)
    payload = _payload()
    agent = client.post(
        "/api/agents", json={"name": "RE Gate Agent", "description": ""},
        headers=auth_headers(token),
    )
    assert agent.status_code == 201, agent.text
    version = client.post(
        f"/api/agents/{agent.json()['id']}/versions", json=payload,
        headers=auth_headers(token),
    )
    assert version.status_code in (200, 201), version.text
    version_id = version.json()["id"]

    with session_factory() as db:
        campaign = Campaign(
            name="RE Gate", org_id=user["org_id"],
            agent_version_id=version_id, status="draft",
        )
        db.add(campaign)
        db.flush()
        for name, phone, custom in [
            ("L1", "+919812345611", {"lead_name": "Riya Sharma", "city": "Hyderabad"}),
            ("L2", "+919812345612", {"lead_name": "Arjun Rao", "city": "Bengaluru"}),
            ("L3", "+919812345613", {"lead_name": "Meera Iyer", "city": "Chennai"}),
        ]:
            db.add(Contact(
                campaign_id=campaign.id, name=name, phone=phone,
                status="pending_review", custom_fields=custom,
            ))
        db.commit()
        campaign_id = campaign.id

    # Personas answer positionally; the gate asserts STRUCTURE (persistence,
    # markup absence, schema membership), not content. Script accounting: each
    # contact consumes opening chat + record tool + follow-up chat + end_call
    # tool + spare chat = 5 Groq calls (round-robin personas never end early).
    script(
        chat("Hello, disclosure line. Am I speaking with Riya?"),
        tool_call("record_extracted_field", {"field_name": "budget_band", "value": "80 lakhs", "confidence": 0.9}),
        chat("Thanks, noted."),
        tool_call("end_call", {"summary": "done 1"}),
        chat("Goodbye."),
        chat("Hello, disclosure line. Am I speaking with Arjun?"),
        tool_call("record_extracted_field", {"field_name": "locality_preference", "value": "Madhapur", "confidence": 0.85}),
        chat("Thanks, noted."),
        tool_call("end_call", {"summary": "done 2"}),
        chat("Goodbye."),
        chat("Hello, disclosure line. Am I speaking with Meera?"),
        tool_call("record_extracted_field", {"field_name": "property_type", "value": "2BHK", "confidence": 0.8}),
        chat("Thanks, noted."),
        tool_call("end_call", {"summary": "done 3"}),
        chat("Goodbye."),
    )
    resp = client.post(
        f"/api/playground/campaigns/{campaign_id}/dry-run",
        json={},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["contacts_run"] == 3
    assert report["results"][0]["extracted_fields"][0]["field_name"] == "budget_band"
    assert all(r["status"] == "completed" for r in report["results"])
    schema_keys = set(payload["extraction_schema"])
    with session_factory() as db:
        for result in report["results"]:
            for turn in result["transcript"]:
                assert "[" not in turn["text"] and "]" not in turn["text"]
                assert "<tool_call>" not in turn["text"]
            for field in result["extracted_fields"]:
                assert field["field_name"] in schema_keys
        rows = db.scalars(select(Call).where(Call.campaign_id == campaign_id)).all()
        assert len(rows) == 3 and all(c.kind == "dry-run" for c in rows)
```

- [ ] **Step 2: Run tests to verify they fail**

Run (workdir `backend/`): `.\.venv\Scripts\python.exe -m pytest tests/test_real_estate_dry_run.py tests/test_agents.py -q`
Expected: FAIL on the new file (at minimum the gate test — no dry-run coverage for the RE version yet; token/render tests pass against Task 1 content and guard regressions).

- [ ] **Step 3: Create the sample CSV**

Create `sample_real_estate_contacts.csv` (repo root) with exactly this content (headers mirror `sample_campaign_contacts.csv` conventions; numbers use the +91981234561x sandbox range, distinct from the absentee sample):

```csv
name,phone,lead_name,city,property_interest,budget_band
Riya Sharma,+919812345611,Riya Sharma,Hyderabad,2BHK apartment,60-80 lakhs
Arjun Rao,+919812345612,Arjun Rao,Bengaluru,3BHK apartment,1-1.3 crore
Meera Iyer,+919812345613,Meera Iyer,Chennai,Residential plot,40-60 lakhs
Karan Mehta,+919812345614,Karan Mehta,Pune,2BHK apartment,70-90 lakhs
```

No BOM, LF or CRLF line endings, trailing newline at end of file.

- [ ] **Step 4: Run tests to verify they pass**

Run (workdir `backend/`): `.\.venv\Scripts\python.exe -m pytest tests/test_real_estate_dry_run.py tests/test_agents.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sample_real_estate_contacts.csv backend/tests/test_real_estate_dry_run.py
git commit -m "feat: RE sample leads and automated dry-run gate"
```
