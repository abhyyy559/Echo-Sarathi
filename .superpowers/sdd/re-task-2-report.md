# RE Task 2 Report — Sample RE leads + automated dry-run gate

## Status: DONE (controller ruling applied; committed 840b6af)

## What I implemented
- Step 1 (done): created `backend/tests/test_real_estate_dry_run.py` with the brief's exact content (3 tests: mapped-tokens, render-with-real-names, dry-run structural gate).
- Step 3 (done): created `sample_real_estate_contacts.csv` at repo root with the brief's exact content (4 rows, trailing newline).
- Steps 4–5 (NOT done): suite is not green, so per TDD and the brief's "commit only when green" discipline I created **no commit**. Both new files remain uncommitted in the working tree.

## What I tested and test results
- `.\.venv\Scripts\python.exe -m pytest tests/test_real_estate_dry_run.py -v` (workdir `backend/`): **2 passed, 1 failed**.
  - PASS `test_preset_spoken_regions_use_only_mapped_tokens`
  - PASS `test_real_estate_dry_run_structural_gate`
  - FAIL `test_preset_renders_with_real_names` — `AssertionError: unsubstituted tokens in rendered prompt: {'[REQUIRED]'}`
- `.\.venv\Scripts\python.exe -m pytest tests/test_real_estate_dry_run.py tests/test_agents.py -q` (workdir `backend/`): **16 passed, 1 failed** (same single failure; all 14 `test_agents.py` tests pass). Re-run after CSV creation: identical result.

## TDD Evidence
- RED (command): `.\.venv\Scripts\python.exe -m pytest tests/test_real_estate_dry_run.py tests/test_agents.py -q` from `backend/` — output `1 failed, 16 passed`; failure is `test_preset_renders_with_real_names` with `unsubstituted tokens in rendered prompt: {'[REQUIRED]'}`. This RED was recorded **before** creating the CSV (Step 2) and is genuine TDD RED, but it is NOT the RED the brief predicted.
- GREEN (command): same command after Step 3 — output `1 failed, 16 passed`. **No GREEN achieved.**

## Root-cause analysis (why GREEN is impossible as specified)
- The brief (Step 2) predicts: "FAIL on the new file (at minimum the gate test …; token/render tests pass against Task 1 content)". Actual: the **gate test passes** and the **render test fails**.
- Cause: Task 1's preset (`domain-configs/presets/real-estate-lead-qualification.json`, commit `4de0238`) marks 6 extraction-schema fields `validation: "required"` (enquiry_confirmed, still_interested, property_type, budget_band, locality_preference, call_outcome). The pre-existing renderer `backend/app/routers/playground.py:504-506` appends a literal `" [REQUIRED]"` marker per required field. The brief's render test asserts zero `[...]` tokens remain in the rendered prompt, so it cannot pass against this preset.
- None of the three possible fixes fits the task constraints: (a) changing the renderer violates "Config-only: no backend … code changes"; (b) changing the Task 1 preset means editing/committing a file outside the two named files (and weakens Task 1's committed design); (c) changing the test means deviating from the brief's "exactly the content below". The sample CSV is unrelated to the failure, so Step 3→4 can never turn the suite green.

## Files changed (uncommitted)
- `backend/tests/test_real_estate_dry_run.py` (new, exact brief content)
- `sample_real_estate_contacts.csv` (new, exact brief content)

## Self-review findings
- Both files match the brief byte-for-byte to the best of my verification (test file copied verbatim incl. docstring/imports; CSV has 5 lines + trailing newline).
- I did not touch the unrelated uncommitted work in the tree and created no commit, since committing a red suite would violate TDD discipline.
- YAGNI/discipline: no code changes made, no new `.env` entries, no guessing at a fix.

## Issues / concerns — decision needed
1. **How to resolve the `[REQUIRED]` conflict?** Options: (i) amend the brief's render test to allow the `[REQUIRED]` marker (e.g. subtract it from `leftovers`); (ii) change the renderer to use a non-bracket marker (code change, contradicts "config-only"); (iii) drop `validation: "required"` from the Task 1 preset (design change to committed work). My recommendation is (i), but that is the plan owner's call.
2. Note the brief's Step 2 expectation is inverted vs. reality (gate passes, render fails) — the plan's assumption "token/render tests pass against Task 1 content" is factually wrong for the render test, so the plan may need a small correction at lines ~134-326 of `docs/superpowers/plans/2026-09-06-real-estate-agent.md`.

## Addendum � controller ruling (option i) and GREEN
- Ruling: `[REQUIRED]` is pre-existing platform behavior (`_render_text_system_prompt` marks required schema fields for the model), not a placeholder leak. Amended the final assertion of `test_preset_renders_with_real_names` exactly as directed: `assert leftovers <= {"[REQUIRED]"}` with the two-line explanatory comment. No other file touched.
- TDD Evidence GREEN (command, workdir `backend/`): `.\.venv\Scripts\python.exe -m pytest tests/test_real_estate_dry_run.py tests/test_agents.py -q` � output `17 passed, 32 warnings in 12.06s`.
- Step 5 commit: `git add sample_real_estate_contacts.csv backend/tests/test_real_estate_dry_run.py` then `git commit -m "feat: RE sample leads and automated dry-run gate"` ? `840b6af`. `git show --stat HEAD` confirms exactly 2 files (test 143 lines, CSV 5 lines); unrelated working-tree work untouched.
- Self-review: amendment matches the controller text verbatim; staged paths exact; full TDD arc recorded (RED `1 failed, 16 passed` ? GREEN `17 passed` ? commit).
