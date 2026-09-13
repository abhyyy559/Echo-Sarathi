# RE Task 1 Report — Upgrade the RE preset to verification + quotation-callback

## What you implemented
- `backend/tests/test_agents.py`: replaced the body of
  `test_real_estate_preset_has_qualification_schema` with the brief's exact
  10-field / 6-step / prompt-keyword assertions (verbatim from the brief).
  The preset-id set assertion in `test_list_presets_returns_valid_payloads`
  was left unchanged.
- `domain-configs/presets/real-estate-lead-qualification.json`: replaced the
  whole file by mechanical extraction from the plan
  (`docs/superpowers/plans/2026-09-06-real-estate-agent.md`, PowerShell slice
  `$lines[75..111]`). No hand-typed JSON. Result: 6-step question flow,
  10-field extraction schema (incl. `enquiry_confirmed`, `still_interested`,
  `property_type`, `quotation_callback_slot`), confirm-loop system prompt.
- Config-only: no backend / voice-agent / frontend code changes, no new
  `.env` entries, no credentials.

## What you tested and test results
- RED: `test_real_estate_preset_has_qualification_schema` failed against the
  old preset (schema-set mismatch on the 4 new fields), as expected.
- Shape check: preset parses as JSON → `real-estate-lead-qualification 6 10`.
- Content-rule check: steps `[1,2,3,4,5,6]` sequential; `quotation_callback_slot`
  is `optional` (deliberate per brief); spoken-region tokens are exactly
  `[Agent Name]`, `[Company Name]`, `[Lead Name]`; prompt contains
  repeat/confirmation/quotation; no BOM.
- GREEN: full `tests/test_agents.py` → **14 passed**.

## TDD Evidence
- RED command (workdir `backend/`):
  `.\.venv\Scripts\python.exe -m pytest tests/test_agents.py::test_real_estate_preset_has_qualification_schema -q`
- RED output (failing assertion):
  `AssertionError: assert {'budget_band...imeline', ...} >= {'budget_band...imeline', ...}`
  `Extra items in the right set: 'quotation_callback_slot' 'still_interested' 'property_type' 'enquiry_confirmed'`
  `1 failed` — expected: old 7-field schema lacks the 4 new fields; old flow has 5 steps, not 6.
- GREEN command (workdir `backend/`):
  `.\.venv\Scripts\python.exe -m pytest tests/test_agents.py -q`
- GREEN output: `14 passed, 29 warnings in 11.47s`
  (warnings are pre-existing: starlette `httpx` deprecation + test JWT key-length; unrelated to this task).

## Files changed
- `domain-configs/presets/real-estate-lead-qualification.json` (rewritten via mechanical extraction)
- `backend/tests/test_agents.py` (one test body replaced)

## Self-review findings
- Completeness: all 5 brief steps done (failing test → fail confirmed →
  mechanical extraction → shape/content verified → green → commit of the two
  named files only).
- Quality: test body matches the brief verbatim; preset-id set assertion
  untouched; `git show --name-only HEAD` confirms exactly the two brief-named
  files in the commit; unrelated working-tree work left unstaged/untouched.
- Discipline/YAGNI: config + test only; no code, latency, provider, or auth changes.
- Observation (not a concern): `property_type` is `required` with threshold
  0.7 while the brief's shorthand says "0.8 required" — this is verbatim plan
  content from the mechanical extraction, so the plan is authoritative and the
  file is correct as extracted.

## Any issues or concerns
- None. No blockers, no ambiguity encountered; slice boundaries from the
  brief worked on the first try (parse OK, counts 6/10 on first extraction).
