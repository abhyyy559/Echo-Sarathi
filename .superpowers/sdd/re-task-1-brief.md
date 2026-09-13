# RE Task 1 Brief — Upgrade the RE preset to verification + quotation-callback

Source: `docs/superpowers/plans/2026-09-06-real-estate-agent.md` (Task 1, plan lines 35-130).

**Goal (plan):** Upgrade the shipped real-estate preset into the full verification→quotation-callback agent from the design spec, and prove it end-to-end with an automated dry-run gate.

## Global Constraints (bind this task — exact values verbatim from the plan)

- Type hints required in all Python test code.
- Never hardcode API keys — no credentials in this plan (no new `.env` entries).
- Config-only: no backend, voice-agent, or frontend code changes. No latency tuning, no concurrency changes, no new providers.
- Never fabricate a structured-field value on low confidence — the confirm loop records only caller-confirmed values (FR-12).
- Every call domain stays a config/preset file — never a code branch.
- Backend tests run from `backend/` with `.\.venv\Scripts\python.exe -m pytest tests/<file>.py -q`.
- TDD every task: failing test, minimal implementation, green, commit. One task = one commit, staged files only.
- Validator rules (`backend/domain_config_schema.py`): `system_prompt` min 10 chars; `question_flow` min 1 step, numbered sequentially from 1; each extraction field needs `type` ∈ {string, date, boolean, number}, `description`, `validation` ∈ {required, optional}, `confidence_threshold` 0.0–1.0; `disclosure_script` min 10 chars; `escalation_rules` min 1 with `action` ∈ {transfer, flag, end_call}; `voice_settings.language`/`stt_language` ∈ {en, te, hi}.

## Machine notes (read before starting)

- Repo root is your working directory. The backend venv is `backend\.venv\Scripts\python.exe` (bare `python` is NOT on PATH). Run backend tests with workdir `backend/`.
- Shell is Windows PowerShell 5.1: no `&&` chaining (use `; if ($?) { ... }`), quote paths with spaces.
- Commit ONLY the two files this task names (`git add` those exact paths). The working tree contains unrelated uncommitted work — do not touch it.
- The plan file's `system_prompt` line exceeds display truncation — do NOT retype the JSON. Extract it mechanically (Step 3). Reference model: `domain-configs/presets/lead-verification.json`.

## Task text

### Task 1: Upgrade the RE preset to verification + quotation-callback

**Files:**
- Modify: `domain-configs/presets/real-estate-lead-qualification.json`
- Test: `backend/tests/test_agents.py` (extend RE assertions)

**Interfaces:**
- Consumes: `validate_agent_version_payload` (enforced by `GET /api/agents/presets` — a malformed file fails the endpoint test loudly).
- Produces: upgraded preset served by the presets endpoint; Task 2 builds an agent version from `version_payload`.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_agents.py`, replace the existing `test_real_estate_preset_has_qualification_schema` body with:

```python
def test_real_estate_preset_has_qualification_schema(client):
    token, _user = register(client)
    presets = client.get("/api/agents/presets", headers=auth_headers(token)).json()
    payload = next(p for p in presets if p["preset_id"] == "real-estate-lead-qualification")["version_payload"]
    assert set(payload["extraction_schema"]) >= {
        "enquiry_confirmed", "still_interested", "property_type", "budget_band",
        "locality_preference", "possession_timeline", "quotation_callback_slot",
        "visit_date_preference", "call_outcome", "escalation_needed",
    }
    assert len(payload["question_flow"]) == 6
    prompt = payload["system_prompt"].lower()
    assert "repeat" in prompt and "confirmation" in prompt and "quotation" in prompt
```

(Keep the preset-id set assertion from P1 Task 6 unchanged.)

- [ ] **Step 2: Run test to verify it fails**

Run (workdir `backend/`): `.\.venv\Scripts\python.exe -m pytest tests/test_agents.py -q`
Expected: FAIL — extraction-schema set mismatch (old 7-field schema) and `len(question_flow) == 5`, not 6.

- [ ] **Step 3: Rewrite the preset payload**

The exact new file content lives in the plan file (`docs/superpowers/plans/2026-09-06-real-estate-agent.md`, 1-indexed lines 76-112, inside the ```json fence opening at line 75). Do NOT retype it — extract it mechanically:

```powershell
$lines = Get-Content -LiteralPath "docs\superpowers\plans\2026-09-06-real-estate-agent.md"
$lines[75..111] | Set-Content -LiteralPath "domain-configs\presets\real-estate-lead-qualification.json"
```

(0-indexed slice `75..111` = 1-indexed lines 76-112, fence content only.)

Then verify JSON parses and has the expected shape:

```powershell
.\backend\.venv\Scripts\python.exe -c "import json; d=json.load(open('domain-configs/presets/real-estate-lead-qualification.json', encoding='utf-8')); p=d['version_payload']; print(d['preset_id'], len(p['question_flow']), len(p['extraction_schema']))"
```

Expected output: `real-estate-lead-qualification 6 10`

If the slice boundaries are off (parse fails or counts mismatch), read the plan around lines 71-115 to re-locate the fence and adjust — do not hand-write the JSON.

Content rules the extracted file must satisfy (verify by reading the extracted file if the endpoint test fails):
- `quotation_callback_slot` is `validation: "optional"` deliberately (schema has no conditional-required; refuses/invalid calls must not flag a missing slot). The REQUIRED-when-callback rule lives in its description + the confirm loop — the enforcement point.
- Steps sequential 1-6; thresholds 0.8 required / 0.7 optional / 0.9 escalation.
- Only mapped tokens (`[Company Name]`, `[Lead Name]`, `[Agent Name]`) in spoken regions; UTF-8, no BOM, no trailing commas.

- [ ] **Step 4: Run test to verify it passes**

Run (workdir `backend/`): `.\.venv\Scripts\python.exe -m pytest tests/test_agents.py -q`
Expected: all pass (the presets endpoint runs `validate_agent_version_payload` on the new file — a malformed file fails here, not silently).

- [ ] **Step 5: Commit**

```bash
git add domain-configs/presets/real-estate-lead-qualification.json backend/tests/test_agents.py
git commit -m "feat: upgrade RE preset to verification plus quotation-callback agent"
```
