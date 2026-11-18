# Consolidation + pluggable BYOK voice stack — design spec

*Date: 2026-11-18. Status: approved for implementation. Owner decision: single home = `echo-sarathi-tenglish`; product shape = adapters inside the current app.*

## 1. Context and goals

Outpero is a published Indian AI-telecalling SaaS: streaming ASR → VAD/endpointing → LLM with tool calls → streaming TTS → telephony, 0.8–1.3 s average latency, one voice across Telugu↔English code-switching, concurrency sold as "channels", ₹5/min Standard / ₹6.8/min Premium / from ₹3.5/min Custom, plus ₹649/month per number+channel. It publishes no model names.

EchoSarathi already implements most of this shape (LiveKit Agents worker, Sarvam Saaras v4 `codemix` STT, Bulbul Indic TTS, Groq/Sarvam LLM fallback chain, Twilio + Vobiz telephony, immutable `AgentVersion`, multi-tenant billing). Its three local folders are clones of one origin on divergent branches, and its README is stale.

Goals:
1. **One project**: merge the three branches into one coherent repo with full history.
2. **Clean codebase**: reorganise front end, back end, pipeline and docs along architectural seams.
3. **Open-source BYOK core**: anyone can add/replace STT, TTS, LLM and telephony providers.
4. **Tenglish-first**: code-switching is a first-class, tested capability.
5. **Adapt the Outpero gaps** into the app, with a written implementation plan.
6. **Quotation below Outpero**: ₹0 self-hosted, ₹2.50/min Standard, ₹3.00/min Premium — documented in `docs/PRICING.md` only (no billing logic added in this pass).

## 2. Merge strategy (exact)

Base branch: `integration/consolidated` from `fix/tenglish-behavior` @ `6e6bc04`.

| Source | Action | Rationale |
|---|---|---|
| `redesign/saas-launch` @ `deb869b` | `git merge` — keep its frontend redesign, MIT `LICENSE`, `.env.example` secret scrub, competitor research; keep primary backend/pipeline on conflict | UI and licensing are its value |
| `master` @ `fa207d0` | cherry-pick `ad7b879` (deploy docs) and `baf2dd4` (scratch cleanup); **skip `fa207d0`** (sets `allow_any_outbound_number=True`) | Keep the safe outbound default from primary |
| Untracked audit docs from `ai voice calling agent/docs/` (`ARCHITECTURE_REVIEW.md`, `CODE_REVIEW.md`) and `echo-sarathi-saas-redesign/docs/RESUME_NOTES.md` | scan for secrets → copy into `docs/` | Reuse as gap checklist, no code merge |
| Sibling folders | add `README.ARCHIVED.md` pointing to primary; rename folders with `_ARCHIVE` suffix | Single source of truth |

Conflict policy: frontend from redesign; backend, voice pipeline and prompting from primary; docs unioned and reconciled. After merge, run all suites before committing the merge resolution.

## 3. Target layout

```
docs/
  ARCHITECTURE.md                     (primary, reconciled)
  OUTPERO_RE_ARCHITECTURE.md          (research report, imported)
  PRICING.md                          (quotation + unit-cost worksheet)
  CONTRIBUTING_ADAPTERS.md            (how to write a provider)
  ARCHITECTURE_REVIEW.md, CODE_REVIEW.md, RESUME_NOTES.md
  superpowers/specs/2026-11-18-consolidation-and-byok-design.md
backend/            FastAPI routers/services/models, Alembic, tests (layout preserved)
voice-agent/
  agent.py
  app/pipeline.py                     orchestration only
  app/providers/
    base.py                           Protocol definitions
    registry.py                       config → provider, cache, health, fallback
    stt/{sarvam,deepgram,...}.py
    tts/{sarvam_bulbul,cartesia,deepgram_aura}.py
    llm/{fallback_chain,groq,sarvam,...}.py
    telephony/{twilio,vobiz,fake}.py
  app/prompting.py                    single renderer
  app/telemetry.py, turns.py, degradation.py, tools.py, config.py, backend_client.py
  tests/
frontend/           redesign UI + livekit-client
domain-configs/     presets (seeds for an Employee Store)
infra/              compose + deploy configs
.github/workflows/ci.yml
```

## 4. Provider adapter contract

Four async protocols in `app/providers/base.py`:

- `STTProvider`: `stream(audio, language, hints) -> AsyncIterator[TranscriptEvent]`
- `TTSProvider`: `synthesize(text, voice, language) -> AsyncIterator[bytes]`; optional `multilingual_voice_id`
- `LLMProvider`: `complete(messages, tools) -> AsyncIterator[TokenEvent]`
- `TelephonyProvider`: `answer(), dial(), play(), hangup(), on_media()`

`registry.py` reads env/YAML: `STT_PROVIDER`, `TTS_PROVIDER`, `LLM_PROVIDER`, `TELEPHONY_PROVIDER`, plus per-language overrides (`TTS_PROVIDER_TE=sarvam_bulbul`, `STT_PROVIDER_TE=sarvam`). Existing env vars remain valid (backwards compatibility). Providers are instantiated lazily and cached; every turn records `provider_id` in telemetry.

`FallbackLLM` is generalised into a provider-agnostic fallback chain used for all four roles. On provider failure: next candidate → if all fail, existing `_degrade()` speaks the apology line and posts `status=error`. No mid-audio splicing.

Community contribution: add a module under `providers/<role>/`, implement the protocol, add a contract test, register in `registry.py`; documented in `CONTRIBUTING_ADAPTERS.md`.

## 5. Tenglish / same-voice guarantee

- Keep Sarvam `mode=codemix` for Indic; keep the existing Tenglish prompt rules (English root + Telugu suffix, respect register, no Sanskrit synonyms).
- The TTS contract exposes `multilingual_voice_id`; an agent can pin one voice id used for both Telugu and English segments.
- Acceptance test: a Telugu utterance containing an embedded English token produces a stable voice id across the switch (no provider/voice swap mid-call).

## 6. Cleanup scope

Split only the two monoliths along the seams in §3 (`pipeline.py` ~3.4k lines, `playground.py` ~3.5k lines), and merge the duplicate prompt renderer into `prompting.py` with parity tests. Delete the dormant `twilio_protocol.py`. Reconcile stale docs (README, PROJECT_MASTER, CLAUDE) with shipped telephony, Vobiz not Plivo, no Redis, Telugu live. No unrelated refactors.

## 7. CI and verification

`.github/workflows/ci.yml`: backend pytest (386 defs), worker pytest (229 defs), frontend node tests (17 defs), frontend build, Alembic migration check. Add provider contract tests, a Tenglish code-switch E2E and the same-voice assertion.

Local verification before handback: all suites green, build clean, migrations current, `git status` understood. Commits stay local if GitHub DNS remains unavailable; report the exact failure.

## 8. Gaps adapted from Outpero (tracked in `docs/OUTPERO_RE_ARCHITECTURE.md` §4)

Phase 1: CI, durable backend writes (spool + bounded retry), docs truth, compliance guardrails (keep `allow_any_outbound_number=False`, DLT/KYC, DNC, recording notice).
Phase 2: same-voice Tenglish, caller memory, voicemail/outcome classification, knowledge chunk retrieval.
Phase 3: "describe your employee" generator, action toggles, webhooks + HMAC, recording retention, real queue + autoscale, and the cheap wins (strictness dial, ambient beds, two-speed publishing, 3-version rollback, lifecycle states, Employee Store).

**This spec's implementation scope:** the merge, archiving, file reorganisation, CI workflow, provider registry + at least two adapters per role (existing providers wrapped, not rewritten), durable backend writes (spool + bounded retry), the safe outbound guardrails, stale-doc reconciliation, the pricing/contribution docs, and the Tenglish same-voice test. Caller memory, voicemail/outcome classification, knowledge retrieval, the employee generator, actions, webhooks and queue replacement stay in Phase 2–3 of the roadmap and are not part of this implementation pass.

## 9. Non-goals

- No new hosted billing/plan logic in this pass; pricing is documentation only.
- No speech models are trained; providers are plugged in, not replaced.
- No telephony carrier migration; Twilio + Vobiz stay.

## 10. Acceptance criteria

1. One branch contains all three branches' useful work; each old folder archived with a pointer.
2. `pytest` backend + worker and frontend tests pass; build passes; CI workflow exists.
3. Providers can be swapped by env config and by a new adapter module; documented with a contract test.
4. Telugu↔English code-switch test passes with one stable voice.
5. `docs/PRICING.md`, `CONTRIBUTING_ADAPTERS.md`, reconciled docs and the imported research report exist.
6. All changes committed locally; push failure (if any) reported explicitly.
