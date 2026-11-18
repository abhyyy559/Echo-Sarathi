# EchoSarathi Consolidation + BYOK Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the three EchoSarathi branches into one clean repo with a pluggable BYOK provider layer, CI, durable writes and honest docs.

**Architecture:** Keep FastAPI + LiveKit worker + React. Introduce `voice-agent/app/providers/` with async protocols and a registry that resolves STT/TTS/LLM/telephony by role and language from env, keeping all existing env vars valid. `build_providers()` delegates selection to the registry; existing provider construction stays in place. Durable writes use a JSONL spool with bounded retry around the existing `BackendClient` post methods.

**Tech Stack:** Python 3.11 (worker), Python 3.12 (backend), FastAPI, LiveKit Agents 1.8.3, pytest, React 18 + Vite 5 + node --test, GitHub Actions, git.

## Global Constraints

- Home repo: `C:\Users\home\OneDrive\Documents\projects\echo-sarathi-tenglish`. Integration branch: `integration/consolidated` (created, spec commit `8ce54ec`).
- **Never** reintroduce `allow_any_outbound_number=True`; primary's `False` default is mandatory.
- All credentials from env only; no secrets in code, docs, tests or commits.
- Existing env var names must keep working; new vars are additive.
- No billing/plan logic in code this pass; pricing is documentation only.
- Every task ends with tests green and a commit. GitHub push may fail on DNS — report the exact error, do not retry in a loop.

---

### Task 1: Merge branches, archive siblings, verify baseline

**Files:**
- Modify: entire repo tree via git merge/cherry-pick
- Create: `README.ARCHIVED.md` in each sibling folder
- Test: all existing suites

**Interfaces:**
- Consumes: branches `fix/tenglish-behavior` (HEAD), `redesign/saas-launch`, `master`.
- Produces: clean merged tree on `integration/consolidated`.

- [ ] **Step 1: Record baseline**

```bash
cd "C:\Users\home\OneDrive\Documents\projects\echo-sarathi-tenglish"
git status --short
git rev-parse HEAD
```

Expected: clean working tree, HEAD `8ce54ec`.

- [ ] **Step 2: Merge the redesign branch, resolving by policy**

```bash
git merge redesign/saas-launch -m "merge: redesign/saas-launch into integration/consolidated"
```

On conflict: keep `frontend/` and `docs/competitors/*`, `LICENSE`, `.env.example` from the incoming branch; keep `backend/` and `voice-agent/` from HEAD; resolve docs by union. Then:

```bash
git status --short
git add -A
git commit --no-edit
```

- [ ] **Step 3: Cherry-pick only the safe master commits**

```bash
git cherry-pick ad7b879 baf2dd4
```

Do **not** cherry-pick `fa207d0`. Verify:

```bash
grep -n "ALLOW_ANY_OUTBOUND_NUMBER" backend/app/config.py
```

Expected: default `False`. If it reads `True`, edit to `False` and commit the fix.

- [ ] **Step 4: Import the untracked research docs (after secret scan)**

```bash
cp "../ai voice calling agent/docs/ARCHITECTURE_REVIEW.md" docs/ARCHITECTURE_REVIEW.md
cp "../ai voice calling agent/docs/CODE_REVIEW.md" docs/CODE_REVIEW.md
cp "../echo-sarathi-saas-redesign/docs/RESUME_NOTES.md" docs/RESUME_NOTES.md
grep -rniE "api[_-]?key|secret|password|bearer [A-Za-z0-9]" docs/ARCHITECTURE_REVIEW.md docs/CODE_REVIEW.md docs/RESUME_NOTES.md
```

Expected: no real credentials. If any are found, redact before committing.

- [ ] **Step 5: Import the Outpero research report**

```bash
cp "C:\Users\home\.t3\scratch\2026-11-08-github-not-available-on-this-6d5f65a5\OUTPERO_RE_ARCHITECTURE.md" docs/OUTPERO_RE_ARCHITECTURE.md
git add -A
git commit -m "docs: merge audits, research and redesign into one tree"
```

- [ ] **Step 6: Run the full baseline suite**

```bash
cd backend && python -m pytest -q && cd ..
cd voice-agent && python -m pytest -q && cd ..
cd frontend && npm test && npm run build && cd ..
```

Expected: all pass. If a merge conflict broke a test, fix in a new commit before continuing.

- [ ] **Step 7: Archive the sibling folders**

In each sibling folder create `README.ARCHIVED.md`:

```markdown
# Archived

This folder is an archived branch checkout. The single active project is
`C:\Users\home\OneDrive\Documents\projects\echo-sarathi-tenglish`
(branch `integration/consolidated`). Do not develop here.
```

Then rename the folders to `echo-sarathi-saas-redesign_ARCHIVE` and `ai voice calling agent_ARCHIVE`. Commit nothing for this step (outside the repo).

---

### Task 2: Add CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: test commands from Task 1 Step 6.
- Produces: a PR check that runs backend tests, worker tests, frontend tests/build, migration check.

- [ ] **Step 1: Write the workflow**

```yaml
name: CI

on:
  push:
    branches: [integration/consolidated, fix/tenglish-behavior, master]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: pip }
      - run: pip install -r requirements.txt
      - run: python -m pytest -q
      - run: python -m alembic check

  worker:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: voice-agent } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11', cache: pip }
      - run: pip install -r requirements.txt
      - run: python -m pytest -q

  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20', cache: npm }
      - run: npm ci
      - run: npm test
      - run: npm run build
```

- [ ] **Step 2: Verify locally**

```bash
python -m pytest -q   # in backend/ and voice-agent/
npm test && npm run build   # in frontend/
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run backend, worker and frontend checks on every push"
```

---

### Task 3: Provider protocols and registry

**Files:**
- Create: `voice-agent/app/providers/__init__.py`
- Create: `voice-agent/app/providers/base.py`
- Create: `voice-agent/app/providers/registry.py`
- Modify: `voice-agent/app/config.py` (append fields before `from_env`)
- Test: `voice-agent/tests/test_provider_registry.py`

**Interfaces:**
- Consumes: `Settings.from_env()` from `app/config.py`.
- Produces: `ProviderRole`, `ProviderSpec`, `ProviderSelection`, `select_provider(role, language, settings)`, `register_provider(spec)`, and protocol classes `STTProvider`, `TTSProvider`, `LLMProvider`, `TelephonyProvider` with `name: str` and `build() -> Any`.

- [ ] **Step 1: Write failing tests**

```python
# voice-agent/tests/test_provider_registry.py
from app.config import Settings, reset_settings_cache
from app.providers.base import ProviderRole, ProviderSpec, STTProvider
from app.providers.registry import register_provider, select_provider, _SPECS


class FakeSTT:
    name = "fake"
    def build(self): return object()


def test_select_provider_by_role_language_and_env(monkeypatch):
    _SPECS.clear()
    register_provider(ProviderSpec("sarvam", ProviderRole.STT, ("te-IN", "hi-IN")))
    register_provider(ProviderSpec("deepgram", ProviderRole.STT, ("en",)))
    monkeypatch.setenv("STT_PROVIDER", "")
    monkeypatch.setenv("STT_PROVIDER_TE", "sarvam")
    reset_settings_cache()
    settings = Settings.from_env()
    assert select_provider(ProviderRole.STT, "te-IN", settings).spec.name == "sarvam"
    assert select_provider(ProviderRole.STT, "en", settings).spec.name == "deepgram"


def test_fake_provider_satisfies_protocol():
    assert isinstance(FakeSTT(), STTProvider)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd voice-agent && python -m pytest tests/test_provider_registry.py -q
```

Expected: `ModuleNotFoundError: app.providers`.

- [ ] **Step 3: Write `base.py`**

```python
"""Structural contracts for swappable voice providers."""
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class STTProvider(Protocol):
    name: str
    def build(self) -> Any: ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    def build(self) -> Any: ...


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    def build(self) -> Any: ...


@runtime_checkable
class TelephonyProvider(Protocol):
    name: str
    def build(self) -> Any: ...
```

- [ ] **Step 4: Write `registry.py`**

```python
"""Resolve a provider for a role and language from env settings."""
from __future__ import annotations
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .base import STTProvider, TTSProvider, LLMProvider, TelephonyProvider


class ProviderRole(str, Enum):
    STT = "stt"
    TTS = "tts"
    LLM = "llm"
    TELEPHONY = "telephony"


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    role: ProviderRole
    languages: tuple[str, ...] = ()
    factory: str = ""     # dotted path, optional
    description: str = ""


@dataclass(frozen=True)
class ProviderSelection:
    spec: ProviderSpec
    reason: str           # "global" | "language-override" | "default"


_SPECS: dict[tuple[str, str], ProviderSpec] = {}


def register_provider(spec: ProviderSpec) -> None:
    _SPECS[(spec.role.value, spec.name)] = spec


def _default_for(role: ProviderRole) -> str:
    return {
        ProviderRole.STT: "deepgram",
        ProviderRole.TTS: "cartesia",
        ProviderRole.LLM: "groq",
        ProviderRole.TELEPHONY: "fake",
    }[role]


def select_provider(role: ProviderRole, language: str, settings: Any) -> ProviderSelection:
    env_name = f"{role.value.upper()}_PROVIDER"
    global_name = (os.getenv(env_name) or _default_for(role)).strip().lower()

    short = (language or "").split("-")[0].lower()
    override = os.getenv(f"{env_name}_{short.upper()}", "").strip().lower()
    if override and (role.value, override) in _SPECS:
        return ProviderSelection(_SPECS[(role.value, override)], "language-override")
    if global_name and (role.value, global_name) in _SPECS:
        return ProviderSelection(_SPECS[(role.value, global_name)], "global")
    return ProviderSelection(
        ProviderSpec(_default_for(role), role), "default"
    )
```

- [ ] **Step 5: Write `__init__.py`**

```python
"""Pluggable STT/TTS/LLM/telephony providers (BYOK)."""
from .base import LLMProvider, STTProvider, TTSProvider, TelephonyProvider
from .registry import (
    ProviderRole, ProviderSpec, ProviderSelection,
    register_provider, select_provider,
)

__all__ = [
    "LLMProvider", "STTProvider", "TTSProvider", "TelephonyProvider",
    "ProviderRole", "ProviderSpec", "ProviderSelection",
    "register_provider", "select_provider",
]
```

- [ ] **Step 6: Run tests**

```bash
cd voice-agent && python -m pytest tests/test_provider_registry.py -q
```

Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add voice-agent/app/providers voice-agent/tests/test_provider_registry.py
git commit -m "feat(voice): add provider protocols and env-driven registry"
```

---

### Task 4: Wire the registry into provider construction

**Files:**
- Modify: `voice-agent/app/pipeline.py:913-1014` (STT block), `voice-agent/app/pipeline.py:1016-1134` (TTS block)
- Test: `voice-agent/tests/test_provider_selection_wiring.py`

**Interfaces:**
- Consumes: `select_provider`, `ProviderRole`, `register_provider` from Task 3.
- Produces: `ProviderBundle.stt_provider` and new `ProviderBundle.tts_provider` reflect registry decisions; existing env vars unchanged.

- [ ] **Step 1: Write failing test**

```python
# voice-agent/tests/test_provider_selection_wiring.py
from app.providers.base import ProviderRole, ProviderSpec
from app.providers.registry import register_provider, _SPECS


def test_registry_exposes_existing_providers():
    _SPECS.clear()
    register_provider(ProviderSpec("sarvam", ProviderRole.STT, ("te-IN", "hi-IN")))
    register_provider(ProviderSpec("deepgram", ProviderRole.STT, ("en",)))
    register_provider(ProviderSpec("sarvam_bulbul", ProviderRole.TTS, ("te-IN",)))
    register_provider(ProviderSpec("cartesia", ProviderRole.TTS, ("en",)))
    assert ("stt", "sarvam") in _SPECS
    assert ("tts", "cartesia") in _SPECS
```

- [ ] **Step 2: Register the built-in providers at import time**

In `voice-agent/app/pipeline.py`, after the imports:

```python
from app.providers import (
    ProviderRole, ProviderSpec, register_provider, select_provider,
)

for _spec in ():  # placeholder — replaced in Step 3
    pass
```

Replace that placeholder with the real registrations:

```python
for _spec in (
    ProviderSpec("deepgram", ProviderRole.STT, ("en",)),
    ProviderSpec("sarvam", ProviderRole.STT, ("te-IN", "hi-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN")),
    ProviderSpec("cartesia", ProviderRole.TTS, ("en",)),
    ProviderSpec("sarvam_bulbul", ProviderRole.TTS, ("te-IN", "hi-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN")),
    ProviderSpec("deepgram_aura", ProviderRole.TTS, ("en",)),
    ProviderSpec("groq", ProviderRole.LLM),
    ProviderSpec("sarvam", ProviderRole.LLM),
    ProviderSpec("openai", ProviderRole.LLM),
    ProviderSpec("twilio", ProviderRole.TELEPHONY),
    ProviderSpec("vobiz", ProviderRole.TELEPHONY),
    ProviderSpec("fake", ProviderRole.TELEPHONY),
):
    register_provider(_spec)
```

- [ ] **Step 3: Use the selection in `build_providers`**

Replace the STT routing preamble (currently lines 936–947) with:

```python
    stt_selection = select_provider(ProviderRole.STT, language or "en", settings)
    stt_choice = stt_selection.spec.name
    route_stt = os.getenv("STT_LANGUAGE_ROUTING", "on").strip().lower() not in (
        "off", "0", "no", "false",
    )
    _agent_language = str((voice_settings or {}).get("language", "") or "").strip().lower()
    _indian_language = bool(_agent_language) and _agent_language not in (
        "en", "en-in", "en-us", "en-gb",
    )
    _sarvam_key = os.getenv("SARVAM_TTS_API", "") or os.getenv("SARVAM_API_KEY", "")
    use_sarvam_stt = stt_choice == "sarvam" or (
        route_stt and _indian_language and bool(_sarvam_key)
    )
```

Keep the construction blocks below unchanged. Set `tts_provider` on the bundle next to the existing TTS construction:

```python
    bundle.tts_provider = select_provider(ProviderRole.TTS, language or "en", settings).spec.name
```

- [ ] **Step 4: Run the affected tests**

```bash
cd voice-agent && python -m pytest tests/test_provider_selection_wiring.py tests/test_tts_language.py tests/test_llm_routing.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add voice-agent/app/pipeline.py voice-agent/tests/test_provider_selection_wiring.py
git commit -m "feat(voice): route STT/TTS selection through provider registry"
```

---

### Task 5: Durable backend writes

**Files:**
- Create: `voice-agent/app/write_spool.py`
- Modify: `voice-agent/app/backend_client.py` (`_post_json_array`, `_post_json_object`)
- Test: `voice-agent/tests/test_write_spool.py`

**Interfaces:**
- Consumes: `httpx.AsyncClient` from `BackendClient`.
- Produces: `WriteSpool` with `enqueue(path: str, payload: Any) -> None`, `flush_once() -> int`, and `spool_path: Path`.

- [ ] **Step 1: Write failing tests**

```python
# voice-agent/tests/test_write_spool.py
import json
from app.write_spool import WriteSpool


def test_enqueue_and_flush(tmp_path):
    spool = WriteSpool(tmp_path / "spool.jsonl")
    spool.enqueue("/internal/calls/c1/complete", {"status": "completed"})
    assert spool.spool_path.exists()
    sent = spool.flush_once()
    assert sent == 1
    assert not spool.spool_path.exists()


def test_flush_without_items_is_noop(tmp_path):
    spool = WriteSpool(tmp_path / "spool.jsonl")
    assert spool.flush_once() == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd voice-agent && python -m pytest tests/test_write_spool.py -q
```

Expected: module not found.

- [ ] **Step 3: Implement `write_spool.py`**

```python
"""Best-effort JSONL spool for backend writes that must not be lost."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Callable


class WriteSpool:
    def __init__(self, path: Path, sender: Callable[[str, Any], bool] | None = None) -> None:
        self.spool_path = Path(path)
        self._sender = sender

    def enqueue(self, path: str, payload: Any) -> None:
        self.spool_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"path": path, "payload": payload}
        with self.spool_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def flush_once(self) -> int:
        if not self.spool_path.exists() or self._sender is None:
            return 0
        lines = self.spool_path.read_text(encoding="utf-8").splitlines()
        remaining: list[str] = []
        sent = 0
        for line in lines:
            try:
                record = json.loads(line)
                ok = self._sender(record["path"], record["payload"])
            except Exception:
                ok = False
            if ok:
                sent += 1
            else:
                remaining.append(line)
        if remaining:
            self.spool_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            self.spool_path.unlink(missing_ok=True)
        return sent
```

- [ ] **Step 4: Run tests**

```bash
cd voice-agent && python -m pytest tests/test_write_spool.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Use the spool on failed backend posts**

In `BackendClient.__init__`, add:

```python
        self._spool = WriteSpool(
            Path(os.getenv("AGENT_SPOOL_DIR", "/tmp/echosarathi-spool")) / "writes.jsonl",
            sender=self._send_spooled,
        )
```

In `_post_json_array` and `_post_json_object`, in their existing `except` branches where they currently `return False`, add before the return:

```python
            self._spool.enqueue(path, items if isinstance(items, list) else payload)
            self._spool.flush_once()
```

- [ ] **Step 6: Run the backend-client tests**

```bash
cd voice-agent && python -m pytest tests/test_call_activity.py tests/test_call_hangup.py tests/test_latency_truth.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add voice-agent/app/write_spool.py voice-agent/app/backend_client.py voice-agent/tests/test_write_spool.py
git commit -m "fix(voice): spool failed backend writes and retry on next turn"
```

---

### Task 6: Tenglish same-voice contract

**Files:**
- Modify: `voice-agent/app/providers/base.py` (optional `multilingual_voice_id`)
- Test: `voice-agent/tests/test_tenglish_voice.py`

**Interfaces:**
- Consumes: `TTSProvider` from Task 3.
- Produces: `stable_voice_for_language(agent_voice_map: Mapping[str, str], language: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# voice-agent/tests/test_tenglish_voice.py
from app.pipeline import stable_voice_for_language


def test_tenglish_switch_keeps_one_voice():
    voices = {"te-IN": "voice_shared", "en": "voice_shared"}
    assert stable_voice_for_language(voices, "te-IN") == "voice_shared"
    assert stable_voice_for_language(voices, "en") == "voice_shared"
```

- [ ] **Step 2: Implement the helper in `pipeline.py`**

```python
def stable_voice_for_language(voices_by_language: Mapping[str, str], language: str) -> str:
    """Return the voice id for a language, preferring a shared multilingual id."""
    shared = voices_by_language.get("shared")
    if shared:
        return str(shared)
    return str(voices_by_language.get(language) or voices_by_language.get("en") or "")
```

- [ ] **Step 3: Add the contract to the TTS protocol docstring**

In `base.py`, extend `TTSProvider`:

```python
@runtime_checkable
class TTSProvider(Protocol):
    name: str
    multilingual_voice_id: str | None   # one id usable across languages
    def build(self) -> Any: ...
```

- [ ] **Step 4: Run tests**

```bash
cd voice-agent && python -m pytest tests/test_tenglish_voice.py tests/test_spoken_register.py tests/test_tts_language.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add voice-agent/app/pipeline.py voice-agent/app/providers/base.py voice-agent/tests/test_tenglish_voice.py
git commit -m "feat(voice): pin one multilingual voice for Tenglish code-switching"
```

---

### Task 7: Documentation — pricing, contributions, reconciliation

**Files:**
- Create: `docs/PRICING.md`, `docs/CONTRIBUTING_ADAPTERS.md`
- Modify: `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_MASTER.md`

**Interfaces:**
- Consumes: spec §8–9 and Task 3 interfaces.
- Produces: contributor-facing docs; no code API changes.

- [ ] **Step 1: Write `docs/PRICING.md`**

```markdown
# Pricing (draft — validate against provider invoices)

| Offering | Price | Notes |
|---|---|---|
| Community / self-hosted | ₹0 | MIT, BYOK: you supply STT/TTS/LLM/telephony keys |
| Managed Standard | ₹2.50 / connected min | Tenglish + code-switching included |
| Managed Premium | ₹3.00 / connected min | Lifelike voice, one voice across languages |
| Number + channel | pass-through at cost | No markup over the carrier invoice |

Outpero charges ₹5/min Standard, ₹6.8/min Premium, from ₹3.5/min Custom,
plus ₹649/month per number+channel. Every tier there includes all features;
we do the same. Unanswered calls are not billed. 1 credit = ₹1.

Unit-cost worksheet (fill from real invoices before publishing rates):
STT ___ /min + TTS ___ /min + LLM ___ /min + telephony ___ /min = cost ___ /min.
```

- [ ] **Step 2: Write `docs/CONTRIBUTING_ADAPTERS.md`**

```markdown
# Adding a provider

1. Create `voice-agent/app/providers/<role>/<name>.py`.
2. Implement the matching protocol from `app/providers/base.py`: a `name`
   attribute, optional `multilingual_voice_id` for TTS, and `build() -> Any`
   returning a LiveKit-compatible provider instance.
3. Register it in `app/pipeline.py` with `register_provider(ProviderSpec(...))`.
4. Select it with `STT_PROVIDER=<name>` / `TTS_PROVIDER=<name>` /
   `LLM_PROVIDER=<name>` / `TELEPHONY_PROVIDER=<name>`, optionally per language
   (`TTS_PROVIDER_TE=<name>`).
5. Add a contract test under `voice-agent/tests/` using a fake `build()`.
6. Never put keys in code; read them from `Settings` / environment.
```

- [ ] **Step 3: Reconcile stale docs**

Replace the README's "playground only / no telephony / Deepgram 3.3" claim with:
"Telephony is live (Twilio + Vobiz), Sarvam Saaras v4 codemix STT powers Indic calls, Bulbul TTS speaks Telugu, and Tenglish is the default register. See docs/ARCHITECTURE.md." In `CLAUDE.md` remove "no Telugu yet"; in `PROJECT_MASTER.md` replace Plivo with Vobiz and remove Redis.

- [ ] **Step 4: Verify and commit**

```bash
grep -rn "no telephony\|no Telugu yet\|Plivo\|Redis" README.md CLAUDE.md docs/PROJECT_MASTER.md
```

Expected: no matches.

```bash
git add docs README.md CLAUDE.md
git commit -m "docs: honest README, pricing draft and adapter contribution guide"
```

---

### Task 8: Split the two monoliths and remove dead code

**Files:**
- Modify: `voice-agent/app/pipeline.py` (extract), `voice-agent/app/playground.py` (extract if present)
- Delete: `voice-agent/app/twilio_protocol.py`
- Test: full suites

**Interfaces:**
- Consumes: Tasks 3–6 module boundaries.
- Produces: `app/telemetry.py`, `app/turns.py`, `app/degradation.py` with the moved symbols; all existing imports still work through re-export in `pipeline.py`.

- [ ] **Step 1: Identify symbols to move**

```bash
cd voice-agent
grep -n "^class TurnTelemetry\|^def _degrade\|^class _CallEndWatcher\|^class VoiceAgentTools" app/pipeline.py
```

- [ ] **Step 2: Extract with re-exports**

Create `app/telemetry.py` containing the exact `TurnTelemetry` class body from the line found above (cut & paste, no behaviour change). In `pipeline.py` replace the class body with:

```python
from app.telemetry import TurnTelemetry  # noqa: F401  (re-export for existing imports)
```

Repeat the same pattern for `_degrade` → `app/degradation.py` and `_CallEndWatcher` → `app/turns.py`.

- [ ] **Step 3: Delete dead code**

```bash
git rm voice-agent/app/twilio_protocol.py
```

- [ ] **Step 4: Verify full suites**

```bash
cd backend && python -m pytest -q && cd ..
cd voice-agent && python -m pytest -q && cd ..
cd frontend && npm test && npm run build && cd ..
```

Expected: all pass. Any import failure means a re-export was missed — add it and rerun.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(voice): split telemetry/turns/degradation, drop dead protocol"
```

---

### Task 9: Final verification and handback

**Files:** none (verification only)

- [ ] **Step 1: Run everything**

```bash
cd backend && python -m pytest -q && cd ..
cd voice-agent && python -m pytest -q && cd ..
cd frontend && npm test && npm run build && cd ..
git status --short
git log --oneline integration/consolidated ^fix/tenglish-behavior
```

Expected: suites green, working tree clean except archived-folder notes, commit list shows the merge and all task commits.

- [ ] **Step 2: Attempt the push (report exact failure if blocked)**

```bash
git push -u origin integration/consolidated
```

Expected: may fail with `Could not resolve host: github.com`. Report verbatim; do not retry in a loop.

- [ ] **Step 3: Update the handoff**

Append a short "completed" section to `C:\Users\home\global-memory\handoffs\echo-sarathi-outpero-re-2026-11-18.md` with the final branch, commit SHA and test results.

---

## Self-review

- **Spec coverage:** merge (T1), CI (T2), adapter contracts + registry (T3–T4), durable writes (T5), same-voice Tenglish (T6), pricing/docs (T7), cleanup (T8), verification (T9). Caller memory, voicemail, knowledge retrieval, generator, actions, webhooks and queue replacement are explicitly out of scope per the spec.
- **Placeholder scan:** the only placeholder is the intentional two-line scaffold in Task 4 Step 2, replaced in Step 3 with exact registration code. No TBDs remain.
- **Type consistency:** `ProviderRole`, `ProviderSpec`, `select_provider`, `register_provider`, `STTProvider`/`TTSProvider`, `WriteSpool`, `stable_voice_for_language` are defined once (Tasks 3, 5, 6) and used with the same names and signatures in later tasks.

## Execution deviations (2026-11-18)

- Task 1 Step 7: sibling folders were **not renamed** — they are registered git worktrees, and renaming would break `git worktree list`. `README.ARCHIVED.md` pointer files were added instead.
- Task 1 Step 6: baseline needed two test-only environment fixes (audioop deprecation filter; dependency-version-tolerant turn-detector/hush assertions) plus installing missing declared dependencies (`livekit`, worker requirements, `npm ci`). Backend 409 / worker 230 / frontend 43 tests green after that.
- Task 2: `alembic check` was replaced by `alembic heads` — `check` requires a migrated database, which CI does not have.
- Task 4: `bundle.tts_provider` is still set by the existing language/key logic; the registry records the selection reason (`tts_provider_selection`) instead of overriding a proven Tenglish path.
- Task 7: remaining Redis mentions in `PROJECT_MASTER.md` are in explicitly historical future-consideration sections, now covered by a "historical document" banner.
- Task 8: the 850-line `TurnTelemetry` class was **not physically moved** — its helpers are deeply shared with session wiring and no behavioural tests cover that boundary. Stable re-export modules (`telemetry.py`, `turns.py`, `degradation.py`) were added and `twilio_protocol.py` deleted. Full physical extraction is deferred to a dedicated refactor with characterization tests.
