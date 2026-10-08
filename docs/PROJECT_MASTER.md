# VocalIQ - Project Master Document

> **Single source of truth.** All standalone markdown files (PRD, status, log,
> research, architecture, guides, specs) are consolidated below and removed from
> the repo. Use the bookmarks to jump. Git history preserves every original.
>
> Untouched by design: README_SETUP.md, voice-agent/README.md, CLAUDE.md,
> .claude/agents/*, .claude/commands/*. Companion: GENESIS_EIR_ANSWERS.md.

---

## Table of Contents

1. [Product Requirements (PRD)](#1-product-requirements-prd)
2. [Current Status Snapshot](#2-current-status-snapshot)
3. [Project Log - Timeline](#3-project-log--timeline)
4. [Original Vision Brief](#4-original-vision-brief)
5. [Market & Vendor Research - India](#5-market--vendor-research--india)
6. [EchoSarathi Final Architecture (CONFIDENTIAL)](#6-echosarathi-final-architecture-confidential)
7. [Research: Multilingual Telugu Stack](#7-research-multilingual-telugu-stack)
8. [Research: Telephony Alternatives](#8-research-telephony-alternatives)
9. [Cost-Cutter Overhaul Approach](#9-cost-cutter-overhaul-approach)
10. [Build History - Specs & Plans Index](#10-build-history--specs--plans-index)
11. [User Guide (Beginner Path)](#11-user-guide-beginner-path)
12. [Run Book - Commands](#12-run-book--commands)

---

# 1. Product Requirements (PRD)

> Consolidated from source file: PRD.md

# Product Requirements Document — AI Voice Calling Agent (India, English-first)

Status: Draft for build kickoff · Owner: [your name] · Last updated: 2026-08-15
Companion doc: `AI_Voice_Calling_Agent_India_Research.md` (market/vendor research this PRD is built on)

## 1. Problem & goal

Build a real-time AI voice calling platform that places outbound phone calls and conducts natural, low-latency conversations — not a basic IVR bot. Phase 1 ships English only. The platform must be **domain-independent**: the first proven use case is a college calling students who were absent and asking why, but the architecture must not hardcode that use case.

**Non-goals for Phase 1:** Telugu/multilingual support, authentication/authorization, human-agent handoff/live transfer, production-scale hardening, and self-hosting the voice infra (use managed LiveKit Cloud or Pipecat Cloud first).

## 2. Users

- **Administrator** — uploads a contact list, reviews it, launches a calling campaign, monitors call status, reads transcripts/summaries, exports results. No technical skill assumed.
- **Call recipient** — a person answering the phone. Never sees the admin UI. Must hear a clear AI-disclosure at call start (regulatory requirement, see §8).

## 3. Locked architecture decisions

These are **decided**, not open questions — do not re-litigate them without a documented reason. Rationale is in the research doc.

| Decision | Choice | Why (one line) |
|---|---|---|
| Voice pipeline architecture | **Cascaded** (STT → LLM with tool-calling → TTS), not speech-to-speech | Structured field extraction needs an auditable text layer and reliable tool-calling |
| Real-time orchestration | **LiveKit Agents** (fallback: Pipecat) | Solves session concurrency, WebRTC/SIP, turn-taking, barge-in as first-class primitives — don't rebuild this |
| Telephony (India) | **Plivo** for prototype (fallback: Exotel for compliance-handled option) | Cheapest, LiveKit/Pipecat-native, fast DID provisioning; avoid Twilio for India-domestic economics |
| STT (English) | **Deepgram** (Flux model for built-in turn detection; Nova-3 as fallback) | Purpose-built for voice agents, lowest end-of-speech latency |
| TTS (English) | **Cartesia Sonic** | Lowest time-to-first-audio of any mainstream provider |
| LLM | **Fast/cheap model by default** (Groq-hosted Llama 3.3-class or GPT-4o-mini-class), with deterministic escalation rules for ambiguous turns — not a large model on every turn | Latency + cost; the task is intent classification/slot-filling, not deep reasoning |
| Backend | **FastAPI** (Python) | Same language as the voice pipeline (LiveKit Agents/Pipecat are Python) |
| Database | **PostgreSQL** | Relational, reporting-heavy workload; no need for a vector DB at this stage |
| Session/queue state | **Redis** | Call session state + outbound dialer rate-limiting queue |
| Frontend | **React** admin dashboard | Standard, matches contractor/agent availability |
| Hosting region | **India (Mumbai)** cloud region | DPDP data-localization alignment |
| Telugu stack (Phase 2, not now) | **Sarvam AI** (Saaras v3 STT, Bulbul V3 TTS) | Only India-first vendor with real Telugu code-switching support — do not try to stretch the English stack to Telugu |

## 4. Functional requirements

### 4.1 Admin web app
- FR-1: Upload a CSV/XLSX contact list with configurable column mapping (name, phone, ID, custom fields).
- FR-2: Review/edit the parsed contact list before launching a campaign; flag rows with invalid phone numbers.
- FR-3: Define a **campaign** = contact list + a **call domain config** (see 4.3) + schedule window (must respect the 9 AM–9 PM calling-hours rule, see §8).
- FR-4: Launch, pause, and cancel a campaign.
- FR-5: Live campaign dashboard: per-contact status (queued / calling / answered / no-answer / busy / failed / completed), running counts.
- FR-6: Per-call detail view: transcript, AI-generated structured summary, audio recording link, duration, timestamps.
- FR-7: Export campaign results as CSV/XLSX with all structured fields plus status/duration/transcript-link columns.

### 4.2 Voice agent (real-time call handling)
- FR-8: Place outbound calls via the telephony provider; handle answered/no-answer/busy/failed states.
- FR-9: Conduct a conversation per the active call domain config: ask configured questions, listen, handle interruptions/barge-in, detect end-of-turn, hold context across turns.
- FR-10: Extract structured fields via LLM tool-calling per the call domain config's schema (e.g., `reason_for_absence`, `expected_return_date`).
- FR-11: Disclose at call start that the caller is speaking with an automated system (regulatory requirement).
- FR-12: Escalate to a defined fallback (end call gracefully, flag for human follow-up) when the LLM's confidence is low or the extraction schema can't be filled after N attempts — never fabricate a value.
- FR-13: Record the call (subject to consent/compliance rules in §8), generate a transcript and a structured summary, and write all of it to the database before marking the call complete.

### 4.3 Call domain config (this is what makes the platform domain-independent)
A domain config is a versioned JSON/YAML file, not code, containing: the question flow (ordered, with allowed branching), the structured-field extraction schema (name, type, required/optional), the disclosure/consent script, escalation rules, and a system-prompt template. The "absent student" use case is the first config, not a hardcoded flow. **Acceptance test for this requirement: adding a second call-domain use case must require zero changes to the voice-pipeline or backend code — only a new config file.**

### 4.4 Outbound campaign dialer
- FR-14: Rate-limit outbound call placement to the telephony provider's CPS/concurrency limit (configurable).
- FR-15: Retry policy for no-answer/busy (configurable max attempts, backoff).
- FR-16: Independent conversation state per concurrent call — no shared mutable state between calls.

## 5. Non-functional requirements

- NFR-1 (Latency): median end-of-caller-speech-to-start-of-agent-speech ≤ 900ms; P95 ≤ 1.5s. Instrument and log this per call from day one — it's a target to tune against, not a one-time check.
- NFR-2 (Concurrency): Phase 0/1 target = 10 concurrent calls without degradation. Design so raising this later is a config/infra change, not a rewrite (see LiveKit Agents choice above).
- NFR-3 (Reliability): a crashed/dropped call must not corrupt campaign state; partial call data (whatever was captured before the drop) must still be saved.
- NFR-4 (Auditability): every structured-field extraction must be traceable to the transcript turn(s) it came from.
- NFR-5 (Compliance): see §8 — DLT registration, consent capture, disclosure, data retention/deletion are launch-blocking, not post-launch hardening.
- NFR-6 (Cost visibility): log per-call cost (telephony + STT + LLM + TTS) so the admin dashboard can eventually show cost-per-campaign.

## 6. Data model (starting point — refine in `backend-agent`)

- `contacts` (id, campaign_id, name, phone, external_id, custom_fields jsonb, status)
- `campaigns` (id, name, domain_config_id, schedule_window, status, created_at)
- `domain_configs` (id, name, version, question_flow jsonb, extraction_schema jsonb, disclosure_script, escalation_rules jsonb)
- `calls` (id, contact_id, campaign_id, provider_call_id, status, started_at, ended_at, duration_seconds, recording_url)
- `call_events` (id, call_id, event_type, payload jsonb, timestamp) — raw provider webhook log
- `transcripts` (id, call_id, turn_index, speaker, text, timestamp)
- `extracted_fields` (id, call_id, field_name, field_value, source_turn_index, confidence)
- `consent_records` (id, contact_id or phone, consent_type, captured_at, source)

## 7. System architecture (text form)

```
Admin (browser) ──> Frontend (React) ──> Backend API (FastAPI)
                                              │
                          ┌───────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
                     Postgres            Redis (session/     Outbound dialer
                  (contacts, calls,       queue state)         (rate-limited
                  transcripts, etc.)                            worker)
                                                                    │
                                                                    ▼
                                                          Telephony provider
                                                          (Plivo/Exotel)
                                                                    │
                                                                    ▼
                                                    Voice pipeline (LiveKit Agents)
                                                    STT (Deepgram) → LLM (tool-calling)
                                                    → TTS (Cartesia) → back to caller
                                                                    │
                                                                    ▼
                                                   Writes transcript/extracted fields
                                                   back to Postgres via Backend API
```

## 8. Compliance requirements (launch-blocking — do not defer)

- DLT Principal Entity registration and correct number-series classification before any real (non-test-number) outbound calling. The classification for "institutional/administrative call to an existing student" is a genuine gray area — confirm with the DLT-registration provider or counsel before the first real campaign (see research doc §10).
- Consent capture: build a consent flag into the contact/enrollment data model (`consent_records` table above) — do not call anyone without a recorded consent basis.
- Mandatory AI self-disclosure at the start of every call (FR-11).
- Calling-hours restriction: 9 AM–9 PM local time, enforced by the campaign scheduler, not left to the admin to remember.
- Data localization: audio/transcripts processed and stored in India (hosting decision in §3 already reflects this); verify each third-party API (STT/TTS/LLM provider) processes data in-region or document the exception.
- Defined retention period for recordings/transcripts with an automated deletion job — do not keep everything indefinitely by default.

## 9. Success metrics (Phase 0/1)

- ≥ 90% of test calls connect successfully (telephony reliability).
- Median turn-taking latency ≤ 900ms measured across ≥ 50 real test calls (not scripted demo calls).
- ≥ 85% of structured-field extractions match a human reviewer's read of the same transcript (accuracy check, run manually on a sample each sprint).
- False-interruption rate (agent talks over the caller) ≤ 10% on a 20-call real-conversation test set.
- Zero calls placed without a recorded consent basis.

## 10. Milestones

- **M0 — Scaffold**: repo structure, docker-compose local dev, all provider accounts created (Plivo/Exotel, Deepgram, Cartesia, LLM/Groq), `.env` wired, empty end-to-end call (agent says one line, hangs up) working on a real phone.
- **M1 — Single domain config, single call**: full "absent student" question flow working on one outbound test call, transcript + extraction + export working end-to-end.
- **M2 — Campaign dialer**: CSV upload → review → launch → concurrent calls (target 10) → live dashboard → export.
- **M3 — Compliance gate**: DLT registered, consent flow live, disclosure script live, retention job live. **This gates any real (non-test-number) campaign.**
- **M4 — Hardening**: latency/turn-detection tuning against real call recordings, eval harness, cost logging.
- **M5 (Phase 2, separate PRD)**: Telugu via Sarvam.

## 11. Open questions to resolve during build (not blocking scaffold)
- Exact DLT number-series classification for the education use case (needs provider/legal confirmation).
- Which LLM provider hosts the "fast/cheap" model in production (Groq vs. an OpenAI/Anthropic small model) — prototype both, decide on measured latency/accuracy on your own call audio, not vendor benchmarks alone.
- Recording retention period (needs an institutional policy decision, not just a technical default).

---

# 2. Current Status Snapshot

> Consolidated from source file: PROJECT_STATUS.md

# Project Status — AI Voice Calling Agent ("VocalIQ")

Last updated: 2026-08-25 · Phase: **1 COMPLETE (closed out)** · See `git log` for head.

---

## 1. What works TODAY (all verified end-to-end)

| Capability | Proof |
|---|---|
| Multi-tenant orgs + JWT auth, per-org isolation | 77 backend tests green |
| Agent builder (6-step wizard → immutable versions) | Adding a use case = new version, zero code |
| **Voice playground**: mic → Deepgram STT → Groq LLM (tool-calling) → Cartesia TTS on LiveKit; agent speaks first; live captions | E2E harness PASS |
| **Text playground** (typed testing) | Live curl verified incl. extraction |
| Field extraction in both modes | voice: 3 fields @0.8–0.9 conf; text: 2 fields |
| Personalization inputs per contact | `sample_campaign_contacts.csv` ships `student_name/parent_name/class_section` columns for prompt injection |
| Campaign import w/ auto column-mapping, 9–9 IST guardrails, transcripts, export | UI flow complete |
| Analytics overview + Vapi-style dark UI (sidebar shell, agent workspace split-view, call history table) | `/api/analytics/summary` live |
| Voice & model pickers per agent (8 Cartesia presets + LLM choice) | persisted via `voice_settings` |
| Anti-noise interruption hardening | stricter VAD (0.6 threshold), min_interruption 350ms, resume_false_interruption |
| Dev Tools console (health, provider checklist, full endpoint catalog) | footer "Dev" link, hidden in prod builds |

## 2. Latency — measured vs targets (your last session)

| Metric | Your avg | Target | Diagnosis / next fix |
|---|---|---|---|
| STT final | 1671ms (p95 2674) | ≤900 | Dominated by end-of-speech detection silence + Deepgram finalization. Next: tune Deepgram `endpointing`, consider nova-2 streaming config, and measure `transcription_delay` separately from EOU delay |
| LLM first token | 1393ms (p95 2867) | ≤400 | qwen+no-reasoning median is ~260–900ms; p95 spike = Groq free-tier variance/cold calls. Next: Groq Dev tier + keep tool-loop to 1 step (`max_tool_steps=1`) |
| TTS first audio | 126ms | ✅ | Cartesia is fine |
| **End-to-end** | 2739ms (p95 3707) | ≤1500 | Sum of above; STT is the biggest lever |

Also noted from transcript: the demo agent addressed a non-parent as parent ("your child") because seeded config lacks the verify-step + personalized context wiring — see P0-2.

## 3. Pending — P0 (this phase)

- [x] **P0-1 STT latency**: DONE — Deepgram `endpointing_ms=200` shipped (commit `7d28763`); EOU vs transcription delay split logged in turn_latency. Fresh live measurement still owed at next test-call session.
- [x] **P0-2 Personalized opening**: DONE end-to-end (commit `6b24f86`) — contact fields persist on calls.context, packed into room/token metadata, CALLER CONTEXT prompt section + verify-relationship rule in voice + text modes, migration 0003.
- [x] **P0-3 Strict-guardrails block** in every prompt: refuse off-topic questions ("Who is India's PM?"), never disclose other students' data, wrap up fast (calls cost money), offer human handoff when caller drifts or demands more help
- [x] **P0-4 Caption lag in audio mode**: publish partial transcripts (not just finals) over the data channel
- [ ] **P0-5 Groq Dev tier** (owner action) to remove p95 spikes + TPM 429s

## 4. Pending — P1

- [ ] Parallel outbound calling demo (3–4 simultaneous) — BLOCKED on owner: Twilio keys/tunnel; dialer concurrency already built
- [x] Cost dashboard: org-scoped GET /api/analytics/costs + "Est. Spend" card on Overview ($/min constants in analytics.PRICING_USD_PER_MINUTE — update per invoice)
- [x] Export v2 columns: call status/duration/extracted fields/custom fields + E2E Latency column (shipped commit `0d3087f`)
- [x] Landing page motion pass: scroll-reveal + glassmorphism accents, prefers-reduced-motion safe (public mic demo intentionally deferred — new auth surface)
- [x] Frontend container healthcheck IPv6 false-negative fix

## 5. Phase 2 roadmap (agreed, not started)

1. **Telugu + Indian regional languages** via Sarvam (Saaras STT / Bulbul TTS) — separate pipeline profile per language
2. **Bring-your-own providers**: org-level settings page where users paste their own STT/TTS/LLM API keys (Deepgram/Cartesia/Groq/OpenAI/Sarvam/ElevenLabs…) — runtime resolves per-org provider chain; positions product as fully open-source, vendor-neutral alternative to ₹2–12/min incumbents
3. Phone-number purchasing flows per org (Plivo/Exotel re-evaluation for India domestic)
4. Human-agent live transfer
5. Auth hardening (SSO, roles granularity), production hosting (Mumbai region), DLT registration workflow assistant

## 6. Skills note

- `ui-ux-pro-max` skill IS installed locally and informed the current dark design tokens.
- An "Apple-design" replica skill does not exist in this environment's registry; Apple HIG principles (generous whitespace, depth via layering not borders, restrained accent color) should guide the next frontend polish pass manually.
- All developer tools are visible at **footer → "Dev"** in dev builds (endpoint catalog = full feature surface). In production builds they are compiled out by design.

## 7. File-cleanup candidates — AWAITING OWNER APPROVAL (nothing deleted)

| File(s) | Purpose | Recommendation |
|---|---|---|
| `uvicorn_out.log` / `uvicorn_err.log` / `worker_out.log` / `worker_err.log` / `livekit_out.log` / `livekit_err.log` | runtime debug logs from local bring-up | delete + gitignore `*.log` |
| `caller.wav` / `caller2.wav` | E2E harness fixtures (regenerable) | keep (small, used by tests) |
| `frontend/dist/*` | committed build artifact | remove from git, add dist/ to .gitignore |
| `backend/models.py` + `backend/main.py` + `backend/twilio.py` (repo-root legacy stubs duplicating `backend/app/*`) | pre-refactor shims kept for compose compat | review then delete shims after compose path check |
| `test_validate.py` | early manual validator | delete after confirming unused |

Reply with which rows to delete and I'll execute.

## 8. Run book (quick)

```
docker compose -f infra/docker-compose.yml up -d --build   # everything
# app :3000 · API :8000/docs · LiveKit :7880
login: demo@example.com / demo1234
E2E test: voice-agent\.venv\Scripts\python.exe scripts\e2e_caller.py --wav caller.wav --wav2 caller2.wav --hold 60
```

## Update 2026-08-25
- [x] P0-3 guardrails block live in all prompts
- [x] P0-4 partial captions streaming (final:false on partials)
- [x] P1 healthcheck IPv6 fix (frontend now healthy)
- [x] Cleanup executed per approval (logs, dist untracked, test_validate.py removed; .gitignore hardened)
- [ ] Still open this phase: P0-1 STT endpointing tuning, P0-2 personalized opening + parent-verify wiring, P0-5 Groq Dev tier (owner), P1 cost dashboard + export v2 + landing motion pass; parallel-calls demo waits on Twilio keys.

## Update 2026-08-25 (closeout #2)

- [x] P0-1/P0-2 marked done (were committed in `7d28763` / `6b24f86`; doc lagged)
- [x] P1 cost dashboard shipped: `/api/analytics/costs` + Overview "Est. Spend" card (81 backend tests green, vite build clean)
- [x] P1 landing motion pass shipped (`useReveal` hook + CSS reveal layer, zero deps, reduced-motion safe)
- [x] Final review fix: reveal moved to keyframe animation so `.land-step-card` hover transitions survive (`e8792b6`)
- [ ] Owner-blocked: P0-5 Groq Dev tier, Twilio keys for parallel-calls demo
- [ ] Queued next: external tool bindings (calendar / appointment booking via agent tool-calling) — design pass pending; Phase 2 roadmap starts in a few days

## Update 2026-08-25 (BETA v1 cut)

- [x] **Clean-slate demo tenant** (`7c69848`): `seed_demo.py` now creates ONLY the demo org + login (`demo@example.com` / `demo1234`) + starter agent from absent-student.json. No campaigns, no fake contacts, no calls — testers see honest empty states.
- [x] **Purge path for existing DBs**: `python scripts/seed_demo.py --purge-sample-data` wipes all demo-org campaigns/contacts/calls (transcripts/events/fields cascade); agents + users preserved. Run once against any DB that still carries old demo data.
- [x] Verification: 83/83 backend tests.
- [ ] Beta v1 = this head. v2 candidates after tester feedback: SaaS-level UI redesign of all pages (ui-ux-pro-max pass), calendar/appointment tool bindings for agents.



---

# 3. Project Log - Timeline

> Consolidated from source file: PROJECT_LOG.md

# Project Log

## 2026-08-23

- Created `absent-student.json` in `domain-configs` directory.
- Created `schema.json` in `domain-configs` directory.
- Created `domain_config_schema.py` in `backend` directory.

---

# AI Voice Calling Agent Project Log

## Project Overview
- **Objective**: Build a domain-independent AI voice calling platform for India (English-first).
- **Phase**: Phase 0 - Scaffolding (Milestone M0 completed).
- **Next Milestone**: M1 - Single domain config, single call.
- **Tech Stack**: FastAPI, LiveKit Agents, Twilio, Deepgram, Cartesia, PostgreSQL, Redis.

## Current Progress (2026-08-23)

### Completed Tasks (M0 - Scaffolding)
1. **Repo Structure & Setup**
   - Created directory structure: `/backend`, `/voice-agent`, `/frontend`, `/domain-configs`, `/infra`.
   - Generated `.env.example` with all required environment variables.
   - Configured `.gitignore` for Python/Node.js development.

2. **Infrastructure**
   - Docker Compose setup for Postgres, Redis, and services.

3. **Backend (FastAPI)**
   - SQLAlchemy models for PRD entities (`contacts`, `campaigns`, `calls`, etc.).
   - Basic `main.py` with DB session setup.
   - Alembic migration script for initial schema.

4. **Voice Pipeline (LiveKit Agents)**
   - Agent connects to "test-room" and speaks TTS line via Cartesia.
   - Docker-ready with `Dockerfile` and `requirements.txt`.

5. **Telephony (Twilio - migrated from Plivo)**
   - Webhook endpoint and API route for outbound test calls.
   - Voice-agent integration for call audio handling.
   - Twilio trial account created, test call placed successfully.

### Completed Tasks (M1 - Single Domain Config & Call Pipeline) - IN PROGRESS
1. **Domain Configuration System** ✅
   - Created `domain-configs/absent-student.json` - First use case: "Absent Student Follow-up"
   - Created `backend/domain_config_schema.py` - Pydantic validator for domain configs
   - Includes: system_prompt, mandatory AI disclosure (FR-11), question_flow, extraction_schema, escalation_rules, fallback_responses

### Next Immediate Steps
1. **Task 2**: Build cascaded STT-LLM-TTS pipeline in LiveKit Agents service
   - Integrate Deepgram STT
   - Integrate Groq/OpenAI LLM with function calling for extraction
   - Integrate Cartesia TTS
   - Load domain config at runtime
   - Handle end-of-turn detection and barge-in

2. **Task 3**: Implement backend call session & extraction API endpoints
   - Domain-config CRUD endpoints
   - Single-call trigger endpoint
   - Twilio webhook integration with database recording
   - Call event, transcript, and extraction field recording

3. **Task 4**: Implement campaign dialer with Redis queue and rate limiting
   - Redis-backed queue
   - CPS rate-limiting
   - Concurrency control
   - Calling-hours enforcement (9AM-9PM IST)
   - Retry logic

4. **Task 5**: Build React frontend admin dashboard
   - Contact upload (CSV/XLSX)
   - Campaign creation/launch
   - Test call trigger
   - Live campaign status view
   - Call transcript/extracted fields viewer
   - CSV export

## Time Estimates
- **Total Project Duration**: 6-8 weeks (from scaffold start).
- **Time Remaining**: ~5-7 weeks (after M0 completion).
- **M1 Estimate**: 1-2 weeks (single-call workflow).

## Troubleshooting & Notes
- **Docker/Docker Compose**: Ensure Docker Desktop is installed and running. Use `docker compose up` (without hyphen) if using Docker 20.0+.
- **LiveKit Agent**: Ensure LiveKit server is running and accessible.
- **Twilio Integration**: Requires valid test phone number. User provided: `+919391470646`
- **Database**: Run migrations after Docker setup (`alembic upgrade head`).

## Preview & Artifacts
- **Docker Compose**: `infra/docker-compose.yml`.
- **Backend Code**: `backend/models.py`, `backend/main.py`, `backend/twilio.py`, `backend/domain_config_schema.py`.
- **Voice Agent**: `voice-agent/agent.py`, `voice-agent/twilio_media.py`.
- **Domain Configs**: `domain-configs/absent-student.json`.
- **Telephony**: `backend/twilio.py`.

## User Actions Needed
- ✅ **Test phone number** provided: `+919391470646`
- ✅ **Twilio trial account created** with Gmail (`abhyyy559@gmail.com`)
- ✅ **Test call placed** from Twilio trial number `+17372508034` → `+919391470646` (status: queued)
- ✅ **Telephony code refactored to Twilio** (replaced Plivo integration)
- **Next**:
  1. **Add Twilio credentials** to `.env` (SID, Auth Token, Phone Number)
  2. **Add Deepgram API Key** to `.env`
  3. **Add Cartesia API Key** to `.env`
  4. **Add Groq API Key** to `.env`
  5. **Add LiveKit credentials** to `.env`
  6. **Start services** via Docker Compose: `docker compose -f infra/docker-compose.yml up --build`
  7. **Place test call** via Twilio Console or API

---

## Telephony Provider Change (2026-08-15)
- **From**: Plivo (requires corporate email - blocked)
- **To**: Twilio (accepts personal Gmail, $15 trial credit, India numbers available)
- **Status**:
  - Twilio trial call successfully placed via Console (call SID: `CA63cbe92c0a74513f880bd7b52f45f2a7`)
  - Backend and voice-agent refactored to use Twilio SDK
  - Docker Compose ready for local testing

## Domain Config Architecture (NEW - 2026-08-23)
Per user requirements: The platform is **domain-independent**. Users can:
1. **Configure agents** via web UI (system prompt, question flow, extraction schema, escalation rules)
2. **Test agents** in-browser via simulated calls
3. **Launch campaigns** with contact lists
4. **Use cases**: Sales, lead qualification, surveys, appointment reminders, debt collection, absent student follow-up, etc.

The `domain-configs/` directory holds versioned JSON configs. The `backend/domain_config_schema.py` validates them. The voice agent loads configs at runtime - no code changes needed for new use cases.

---

## Enterprise Platform Lanes Merged + Real-Key Local Stack (2026-08-24)
- **Merged**: all enterprise-platform lanes (auth/tenancy, agents + immutable versions, in-browser playground, campaigns, dev tools) into `master`; frontend design language extended across auth/wizard/playground/dev-tools screens.
- **Real-key local stack (no Docker) brought up**:
  - LiveKit server binary vendored at `tools/livekit/livekit-server.exe`, running on :7880 with devkey credentials from root `.env`.
  - FastAPI backend on :8000 against SQLite (`backend/voice_agent.db`), voice-agent worker registered with LiveKit (logs: `worker_out.log`), React app on :3000.
  - New one-command launcher: `scripts/dev-local.ps1` (idempotent — skips anything already listening; polls `/api/health`; PS 5.1 compatible).
- **Campaign-launch 422 fixed**: root cause was NOT a request/body mismatch — `POST /api/campaigns/{id}/launch` takes no body and the 422s were the endpoint's own guards firing after a post-midnight-IST test click (calling window is 09:00–21:00 IST). Frontend now pre-checks the IST window + empty roster, disables Launch with a plain-English banner, and translates server guard details to friendly messages. Contract pinned by new tests in `backend/tests/test_campaign_launch.py`.
- **Docs**: beginner-friendly golden-path guide added at **`docs/USER_GUIDE.md`**.
- **Known limitations**:
  - Redis is absent locally → dialer queue features degraded (no distributed rate-limiting / queue backpressure).
  - Twilio integration dormant pending owner go-signal (code present, credentials not wired for outbound).
  - `OPENAI_API_KEY` is a placeholder in `.env` — Groq (`llama-3.3-70b-versatile`) is the LLM actually used.

---

**Log Format**: This file will be updated after each major conversation/milestone with:
- Clear task completion status.
- Technical decisions made.
- Troubleshooting steps.
- Time estimates and progress tracking.
- User actions required.

**Last Updated**: 2026-08-24 by Claude Code.
## 2026-08-24 - Phase Complete (Web)
- E2E PASS both modes: Voice (mic->STT->LLM->TTS->captions->DB) and Text (typed turns).
- Extraction live in both modes (call 36 voice: 3 fields @0.8-0.9 conf; call 33 text: 2 fields).
- Latency: qwen3.6 reasoning-off (~262ms TTFT vs 756ms), VAD-only turns (-4s stall), endpointing 350/1500ms; per-turn metrics persisting.
- Docker compose = single source of truth (env_file ../.env); native scripts retained.
- Known minors: Groq free-tier TPM 429 on rapid text turns; frontend container healthcheck IPv6 false-negative (serves fine); heuristic extractor occasionally misses fragmented STT finals (LLM tool-call path covers it).
- Pending owner actions: GitHub repo URL to push; real Twilio creds + 'go twilio' for phone phase.

---

## 2026-08-25 — Phase 1 closeout (cost dashboard + landing polish)

- **Cost dashboard**: backend `GET /api/analytics/costs` (org-scoped, monthly buckets, flat $/min pricing consts) + "Est. Spend" stat card on Overview. Rates are estimates — update `PRICING_USD_PER_MINUTE` per provider invoices.
- **Landing motion**: `useReveal` IntersectionObserver hook, staggered step-card reveals, glassmorphism accents; fully disabled under `prefers-reduced-motion`.
- **Verification**: 81/81 backend tests, `vite build` clean.
- **Still owner-blocked**: Groq Dev tier (P0-5), Twilio keys/tunnel (parallel-calls demo).
- Design spec: `docs/superpowers/specs/2026-08-25-phase1-finish-design.md`.
- Queued next: external tool bindings (calendar/appointment booking via agent tool-calling).


---

# 4. Original Vision Brief

> Consolidated from source file: docs/AI voice calling agent.md

# Project initial prompt-1

I am building an AI Voice Calling Agent as a serious project and I want you to act as a **senior voice-AI architect, telecom engineer, AI systems engineer and product strategist**.

Do not assume that the technologies or providers I mention are the best. I want an **independent second opinion** based on current information available on the internet. Research the current ecosystem where necessary and challenge weak assumptions.

## **PROJECT**

We are building a highly natural, real-time AI voice calling platform.

The initial version will focus **only on English**. Once the English voice experience reaches a very high level of quality, we will expand it to **Telugu**, and eventually support multiple Indian and international languages.

The goal is not simply to make an AI that can place a phone call.

The goal is to build a voice agent that feels as close to a natural human phone conversation as technically possible.

The agent should be able to:

* Make outbound phone calls.  
* Conduct natural conversations.  
* Listen continuously and understand the caller's response.  
* Handle interruptions naturally.  
* Stop speaking when the person interrupts.  
* Detect when the person has finished speaking.  
* Handle pauses, hesitation and incomplete sentences.  
* Maintain conversation context.  
* Respond quickly enough that the conversation does not feel robotic.  
* Collect structured information from the conversation.  
* Determine the outcome of the call.  
* Generate a transcript.  
* Generate a structured summary/result.  
* Track the status of every call.  
* Handle multiple calls concurrently.  
* Maintain an independent conversation state for every active call.

The system should eventually be **domain-independent** rather than being designed only for sales or lead qualification.

For example, one use case could be a college contacting absent students.

An administrator could upload a list of students containing information such as:

* Name  
* Phone number  
* Student ID  
* Other relevant information

The system would call the students individually and ask why they were absent.

After the campaign, the platform should provide results such as:

* Answered  
* Not answered  
* Busy  
* Failed  
* Reason for absence  
* Expected return/date  
* Other relevant information  
* Call duration  
* Transcript  
* AI-generated summary

The administrator should be able to export the final structured results, for example as an Excel/CSV file.

## **EXPECTED USER FLOW**

### **Administrator**

Website

↓

Upload CSV/Excel containing contacts

↓

Review contacts

↓

Start calling campaign

↓

System initiates calls

↓

AI conducts conversations

↓

Calls are independently tracked

↓

Transcripts and structured information are generated

↓

Administrator views campaign results

↓

Administrator exports results

Authentication and authorization are **not required during the initial development/prototype phase**. They will be added when moving toward production.

## **TELEPHONY REQUIREMENT**

The system needs to make real phone calls using a **proper Indian telephone number**.

We do not want the initial system to depend on an international number because the project will be demonstrated in India and calls should appear legitimate and trustworthy to recipients.

We need to understand the best current options for:

* Indian virtual numbers  
* Cloud telephony  
* Programmable voice  
* SIP  
* Voice APIs  
* Real-time bidirectional audio  
* Outbound calling  
* Call status tracking  
* Concurrent calls  
* Caller ID  
* Number provisioning  
* KYC requirements  
* DLT/regulatory requirements  
* Pricing  
* Number rental  
* Per-minute calling costs  
* Concurrency limits  
* API/WebSocket support  
* Academic/student access if available

Do not assume that a normal SIM/eSIM is the correct architecture. Evaluate **SIM/eSIM, virtual numbers, cloud telephony, SIP providers and other approaches** and explain which is actually appropriate for this project.

## **MOST IMPORTANT REQUIREMENT: VOICE QUALITY**

The primary differentiator of this project should be **conversation quality**, not merely the ability to make calls.

The agent should not feel like:

"User speaks → AI waits → AI thinks → AI speaks."

We want a natural conversation with:

* Very low perceived latency  
* Natural turn-taking  
* Natural pauses  
* Fast response generation  
* Reliable interruption handling  
* Barge-in support  
* Accurate speech recognition  
* Natural speech synthesis  
* Appropriate pacing  
* Natural sentence endings  
* Context awareness  
* Robust handling of hesitation  
* Robust handling of background noise  
* Ability to handle different accents  
* Ability to handle people speaking quickly or slowly  
* Ability to recover gracefully when speech recognition is uncertain

The final system should feel like an actual person is participating in the conversation rather than an obvious automated IVR system.

## **MULTILINGUAL ROADMAP**

Phase 1:

**English**

Phase 2:

**Telugu**

Phase 3:

**Telugu \+ English code-switching / Tanglish**

Phase 4:

**Multiple Indian languages**

Phase 5:

Other languages if technically and commercially justified.

Telugu is expected to be significantly more challenging because conversational Telugu requires good pronunciation, natural sentence rhythm, regional variation, code-switching, names, numbers and colloquial speech.

Do not assume that an English architecture will automatically produce high-quality Telugu.

We want to understand what must change between the English and Telugu versions.

## **RESEARCH QUESTIONS**

I want you to independently investigate the entire problem and answer the following.

### **1\. Telephony**

What are the best current options for building an AI voice calling system in India?

Compare the major relevant providers and approaches rather than giving only two options.

Compare:

* Indian virtual numbers  
* Cloud telephony providers  
* CPaaS providers  
* SIP providers  
* Programmable voice APIs  
* Real-time voice-AI-specific platforms  
* SIM/eSIM-based approaches

Explain the advantages, disadvantages, pricing model, Indian number availability, KYC, DLT requirements, API quality, WebSocket/audio streaming capabilities and concurrency.

### **2\. Real-time voice architecture**

What are the critical components required to make a genuinely high-quality real-time voice agent?

Explain the important concepts without assuming a specific vendor:

* Telephony  
* Audio streaming  
* STT  
* VAD  
* Endpoint detection  
* Turn-taking  
* Barge-in/interruption handling  
* Conversation orchestration  
* LLM  
* TTS  
* Audio buffering  
* Streaming  
* Latency management  
* Session management  
* Memory  
* Tool calling  
* Call state  
* WebSockets/SIP/RTP where relevant

Identify which components have the largest effect on perceived human quality.

### **3\. Latency**

What latency targets should we aim for?

Explain the complete latency pipeline from:

User stops speaking

→ speech detection

→ STT

→ reasoning

→ response generation

→ TTS

→ audio playback

Identify where latency normally occurs and how high-quality systems reduce perceived latency.

### **4\. Interruption and turn-taking**

This is one of the most important requirements.

Explain how high-quality voice agents handle:

* User interrupting the AI  
* AI stopping immediately  
* User pausing while thinking  
* User speaking in incomplete sentences  
* Simultaneous speech  
* Background speech  
* False interruption detection  
* Long pauses  
* Agent deciding when to respond

Explain what technologies and architectural patterns are normally used.

### **5\. Voice quality**

Research the current best approaches for achieving highly natural speech.

Compare current TTS approaches based on:

* Naturalness  
* Latency  
* Streaming  
* Emotional expression  
* Pronunciation  
* Conversational quality  
* English performance  
* Indian accent performance  
* Telugu capability  
* Cost

Do not assume open-source models are automatically better or cheaper.

### **6\. STT quality**

Compare the best current speech recognition approaches for conversational phone audio.

Consider:

* English  
* Indian accents  
* Telephone audio  
* Background noise  
* Streaming  
* Latency  
* Accuracy  
* Telugu  
* Code-switching

### **7\. LLM strategy**

Determine whether a voice agent actually needs a large reasoning model.

Compare:

* Small/fast models  
* Large models  
* Local models  
* Cloud models  
* Hybrid architectures  
* Multiple-model architectures

Explain where intelligence is actually required and where deterministic logic is preferable.

### **8\. Cost**

Estimate the realistic cost per minute of operating the system.

Break down:

* Indian telephone number  
* Telephony  
* STT  
* LLM  
* TTS  
* Infrastructure  
* Storage  
* Recording  
* Transcription  
* Other relevant costs

Give approximate costs for:

* 100 calls/month  
* 1,000 calls/month  
* 10,000 calls/month  
* 100,000 calls/month

Also compare the cost with traditional human calling.

### **9\. Scalability**

Explain how the system should handle:

* 1 concurrent call  
* 10 concurrent calls  
* 100 concurrent calls  
* 1,000 concurrent calls

Identify the technical bottlenecks and provider limitations.

### **10\. Indian telecom/legal considerations**

Research the current Indian requirements for AI-generated outbound phone calls.

Specifically investigate:

* KYC  
* DLT  
* Caller ID  
* Consent  
* Promotional vs transactional calls  
* Recording  
* Privacy  
* Data protection  
* Automated calling restrictions  
* Number provisioning  
* Institutional/college use cases

Do not make legal assumptions. Use current authoritative sources wherever possible.

### **11\. English → Telugu transition**

Explain what will need to change when moving from English to Telugu.

Investigate:

* Telugu STT  
* Telugu TTS  
* Telugu pronunciation  
* Regional dialects  
* Code-switching  
* Tanglish  
* Names  
* Numbers  
* Locations  
* Colloquial speech  
* Conversational Telugu

Identify the biggest technical gaps in the current ecosystem.

### **12\. Competitive landscape**

Research current companies/products that are doing high-quality AI phone conversations.

Do not only list them.

Analyze what appears to differentiate the strongest systems in:

* Latency  
* Voice quality  
* Interruption handling  
* Turn-taking  
* Indian languages  
* Telugu  
* Telephony infrastructure  
* Cost  
* Developer flexibility

Do not assume that a company's marketing claims represent its actual technical advantage.

### **13\. Critical risks**

Identify the biggest reasons this project could fail.

I specifically want you to challenge the project on:

* Robotic voice  
* High latency  
* Poor interruption handling  
* Bad turn detection  
* Hallucinations  
* Incorrect information extraction  
* Telephone audio degradation  
* Poor Indian accent recognition  
* Telugu quality  
* High per-minute costs  
* Telecom restrictions  
* Provider lock-in  
* Concurrency limitations  
* Unreliable call connections  
* Poor scalability  
* Privacy/security issues

### **14\. Recommended technology strategy**

Only AFTER independently researching all of the above, recommend:

1. Best telephony provider(s)  
2. Best Indian number approach  
3. Best STT approach  
4. Best TTS approach  
5. Best LLM strategy  
6. Best real-time communication architecture  
7. Best backend architecture  
8. Best database  
9. Best deployment approach  
10. Best development roadmap

Give multiple alternatives where appropriate.

Do not recommend a technology merely because it is popular.

## **IMPORTANT**

I am not asking you to immediately build the system.

I am currently trying to understand the **complete technical and commercial landscape** before development begins.

I want a research-grade answer based on current information.

Use current web sources wherever possible, especially official provider documentation and pricing pages.

Clearly distinguish between:

* Verified facts  
* Provider claims  
* Your technical inference  
* Your recommendation

Most importantly, **challenge my assumptions instead of agreeing with them**.

The final objective is to build an English voice calling agent whose conversation quality is significantly better than a typical basic AI calling implementation, and then use the lessons from the English system to build a highly natural Telugu and eventually multilingual voice agent.

# GLM 5.2 approch

1\. Telephony: The Indian Landscape  
Challenging Assumption: Do not assume that a normal SIM/eSIM is the correct architecture.  
Verdict: A SIM/eSIM (even via gateways like Truphone or Twilio Mobile) is entirely the wrong approach for automated outbound calling in India. It lacks scalability, programmatic control, and violates TRAI's commercial usage guidelines for automated bulk calling.

Verified Facts & Provider Comparison (India):

Twilio (Global CPaaS):  
Pros: Best developer experience, excellent WebSocket/Media Streams API for real-time bidirectional audio.  
Cons: Indian numbers are difficult to provision (requires heavy KYC). Often routes calls via US/UK servers, introducing 150-300ms network latency before audio processing even begins.  
Pricing: \~$0.013/min outbound to India. Number rental \~$1.15/mo.  
Exotel / Kaleyra / Ozonetel (Indian CPaaS):  
Pros: Deeply integrated with Indian telecom (Jio, Airtel, Vi). Excellent DLT compliance dashboards. Local data centers \= low network latency.  
Cons: Their core APIs are built for legacy IVR, not real-time AI. Many do not offer true bidirectional WebSocket streaming; they use POST APIs to trigger pre-recorded audio or basic dynamic TTS.  
Pricing: \~₹0.80 \- ₹1.50/min. Number rental \~₹200-₹300/mo.  
Plivo / Sinch:  
Pros: Sinch (via Voice API) and Plivo offer decent SIP trunking and WebSocket support. Plivo has good Indian coverage.  
Cons: Still require strict DLT registration.  
Voice-AI Specific Platforms (Vapi, Retell AI, Bland AI):  
Pros: Out-of-the-box orchestration of STT, LLM, TTS, and telephony. You can bring your own Twilio/Plivo numbers.  
Cons: High markup on usage (\~$0.10 \- $0.15/min). May not fully support Indian DLT routing natively.  
Recommendation for Telephony: Do not build your own SIP/PBX infrastructure initially. Use Twilio Media Streams (bringing your own Indian virtual number via a local CPaaS provider that supports SIP forwarding, or using Twilio's Indian mobile numbers if you qualify). Alternatively, Exotel recently launched real-time WebSocket APIs—verify their latency. If you want ultimate control, rent an Indian SIP trunk from a local provider and bridge it to your application using FreeSWITCH or Asterisk.

2\. Real-time Voice Architecture  
To achieve "human-like" quality, you cannot use a sequential pipeline (Record \-\> STT \-\> LLM \-\> TTS \-\> Play). You must use a Streaming Event-Driven Architecture.

Critical Components:

Telephony Bridge: Connects PSTN to your server via WebSocket (RTP/Opus audio).  
Audio Streaming: Must use 16kHz, 16-bit linear PCM. Phone lines are narrowband (8kHz mu-law), but upsampling to 16kHz gives STT models better accuracy.  
VAD (Voice Activity Detection): WebRTC VAD or Silero VAD. Runs locally on the audio stream to detect speech presence.  
Endpoint Detection: The hardest part. Determines when the user finished speaking. Relies on VAD silence thresholds \+ LLM intent parsing.  
Turn-taking / Barge-in Orchestrator: A central state machine that tracks who is "holding the floor." If the AI is speaking and VAD detects user audio, it sends a "kill signal" to the TTS audio buffer.  
Streaming STT: Continuously transcribes audio chunks.  
LLM: Generates tokens in a stream.  
Streaming TTS: Converts incoming LLM tokens to audio chunks before the LLM finishes generating the full sentence.  
Largest Effect on Perceived Quality: VAD/Endpoint detection and Barge-in orchestration. A highly intelligent LLM with poor endpoint detection feels like a walkie-talkie conversation.

3\. Latency  
Human conversational latency (the gap between one person finishing and the other starting) is typically 200-400ms. Anything over 800ms feels like a delay.

Pipeline Breakdown & Targets:

Network Audio Transport (Telephony → Server): 40-80ms (Use AWS Mumbai ap-south-1 or local Indian DC).  
VAD & Endpointing: 100-300ms (Requires waiting for silence to ensure the user actually stopped).  
STT Processing: 100-200ms (Streaming STT returns text as soon as audio stops).  
LLM Time-to-First-Token (TTFT): 150-300ms (Crucial. Must use fast inference providers).  
TTS Time-to-First-Audio (TTFA): 100-200ms.  
Audio Transport back to PSTN: 40-80ms.  
Total Target: \~550ms \- 1.1s.  
How to reduce perceived latency further:

Speculative Execution: While the user is speaking, run an intent classifier on the partial transcripts. If the user is clearly saying "Yes", pre-generate the next logical response before the user even finishes.  
Chunked TTS: Send TTS requests sentence-by-sentence, or even clause-by-clause.  
Backchanneling: If endpointing takes longer than 1s, inject a quick "Hmm", "Right", or "I see" to fill the dead air.  
4\. Interruption and Turn-taking  
Challenging Assumption: The system should stop speaking when the person interrupts.  
Architectural reality: If you simply cut the audio upon hearing any voice, background noise, TV sounds, or the caller's own echo will constantly interrupt the AI, ruining the experience.

How High-Quality Systems Handle This:

Echo Cancellation: Hard on PSTN, but necessary.  
Energy Thresholds \+ VAD: Background noise has different acoustic signatures than directed speech.  
Semantic Barge-in: Instead of just VAD, use a fast STT model to transcribe the interrupting audio. If it detects words (not just noise), send the kill signal to the TTS buffer.  
Handling Pauses/Hesitation: If the user pauses, STT yields a partial transcript. The LLM classifies: "Is this a complete thought?" If no, the orchestrator waits. If the pause exceeds 2 seconds, the AI can use a "floor-holding" phrase: "Take your time."  
5\. Voice Quality (TTS)  
Challenging Assumption: Open-source models are automatically better or cheaper.  
Verdict: False. Open-source models (like Bark, VITS, XTTS) require heavy GPU provisioning. At 100 concurrent calls, the cost of hosting real-time TTS GPUs often exceeds API costs, and latency is generally worse.

Current Best Approaches:

ElevenLabs: Best naturalness and emotion. Conversational latency is \~400ms. English is unmatched. Has Telugu support, but pronunciation of complex Telugu words/names can be Anglicized. Cost: \~$0.30/1000 chars.  
Cartesia (Sonic): Insanely fast (TTFA \< 100ms). Excellent for conversational English. Highly recommended for low-latency barge-in. Cost: \~$0.10/1000 chars.  
PlayHT (Play3): Low latency, good cloning, decent Indian accents.  
Google Cloud TTS / Azure TTS: Extremely reliable, excellent Telugu voices (specifically trained on native speakers). But sounds more "robotic" than ElevenLabs in conversational English.  
6\. STT Quality  
For phone audio (8kHz), you must use models trained on telephone datasets.

Deepgram (Nova-2): The industry standard for speed and accuracy. Excellent on noisy audio. Strong Indian English accents. Latency \< 150ms. Cost: \~$0.0043/min.  
AssemblyAI: Highly accurate, great semantic features (sentiment, speaker diarization), but slightly higher latency than Deepgram.  
Google Speech-to-Text: Best for Telugu. Their multilingual models handle code-switching (Tanglish) natively better than Deepgram currently does.  
OpenAI Whisper (API): Too slow for real-time barge-in. High hallucination rate on silence/noise.  
7\. LLM Strategy  
Challenging Assumption: A voice agent actually needs a large reasoning model.  
Verdict: False. GPT-4o, Claude 3.5 Sonnet, or o1 are overkill for a phone call. Their high TTFT (Time to First Token) ruins the conversation, and their reasoning capabilities lead to over-explaining.

The Strategy:

Core Dialogue Model: Use a fast, highly capable model. Llama 3.1 8B (via Groq or self-hosted), GPT-4o-mini, or Claude 3 Haiku. These have TTFT of \< 200ms.  
Tool Calling / Function Calling: Use the LLM only to extract structured data and determine conversation state (e.g., absence\_reason\_captured: true).  
Deterministic Logic: For things like "Please spell your student ID," use deterministic string matching, not LLM parsing.  
Hybrid Architecture: Use a fast classifier model to determine intent, and route the conversation. Only escalate to a heavier model if complex reasoning is strictly required (rare in outbound transactional calls).  
8\. Cost Analysis  
Per-Minute Breakdown (English):

Telephony (India): ₹1.00 ($0.012)  
STT (Deepgram): ₹0.35 ($0.004)  
LLM (GPT-4o-mini / Llama 8B): ₹0.30 ($0.004)  
TTS (ElevenLabs/Cartesia): ₹0.50 ($0.006)  
Infrastructure/WebSockets: ₹0.20 ($0.002)  
Total per minute: \~₹2.35 ($0.028)  
Monthly Estimates (Assuming 3-min avg call duration):

100 calls/month (300 mins): \~₹705  
1,000 calls/month (3,000 mins): \~₹7,050  
10,000 calls/month (30,000 mins): \~₹70,500  
100,000 calls/month (300,000 mins): \~₹590,000 (volume discounts apply)  
Comparison to Human: A human BPO worker in India costs \~₹15,000 \- ₹25,000/month plus overhead. A human can make \~50-80 calls a day. AI can make 10,000s a day. The ROI of AI is massive at scale.

9\. Scalability  
1 Concurrent Call: Can run on a single mid-tier VM.  
10 Concurrent Calls: Needs a dedicated WebSocket server \+ external API integrations.  
100 Concurrent Calls: Requires load-balanced WebSocket nodes. Deepgram/ElevenLabs handle concurrency easily. LLM API concurrency limits become the bottleneck here.  
1,000 Concurrent Calls: Requires a microservices architecture. State management (Redis) is critical. SIP trunking concurrency limits (telephony provider) will require enterprise tier negotiations.  
Bottlenecks: LLM rate limits (tokens per minute) and TTS concurrency limits.

10\. Indian Telecom/Legal Considerations  
Verified Facts (TRAI Regulations):

DLT (Distributed Ledger Technology): Mandatory in India. You must register your business, get a Header ID (Sender ID), and register the content template of your calls. Critical: AI conversational scripts are hard to template because the exact words change. You must register a generalized transactional template.  
Promotional vs. Transactional: You cannot use promotional routes for automated calls without strict consent mechanisms. College absence calling is arguably transactional (service/relationship based), which allows calling any time between 10 AM and 9 PM.  
AI Disclosure: While specific AI calling laws are evolving, TRAI mandates that automated calls must not mislead. Using a human-sounding AI without disclosing it's an assistant is a legal gray area that is currently being scrutinized. Proceed with caution.  
Caller ID: Must display the registered Indian virtual number.  
11\. English → Telugu Transition  
Challenging Assumption: An English architecture will automatically produce high-quality Telugu.  
Verdict: Completely false. Moving to Telugu breaks standard STT/TTS pipelines.

What must change:

Code-Switching (Tanglish): Users will say "Nenu illa unnanu, fever vastundi." (I am at home, getting a fever). Deepgram struggles with this natively. You must use Google Speech-to-Text with automatic language detection or multilingual models.  
TTS: ElevenLabs Telugu often sounds like a foreigner reading Telugu phonetically. You must evaluate Azure Neural TTS (which has specifically trained Telugu voices like Shruti) or Bhashini (Indian government initiative) for natural Telugu.  
Pronunciation: Telugu names (e.g., "D. Venkateshwarlu") and places will be butchered by standard TTS. You need custom pronunciation dictionaries (lexicons).  
Grammar/Syntax: Telugu is Subject-Object-Verb. The LLM might generate English syntax translated to Telugu, which sounds robotic. The system prompt must enforce native Telugu syntax.  
12\. Competitive Landscape  
Current Leaders:

Vapi.ai: Excellent orchestration. Fast, handles barge-in well. Highly developer-focused.  
Skit.ai (Indian Company): Very strong in Indian context, debt collection, and multilingual support. They use custom acoustic models rather than just off-the-shelf APIs, giving them an edge in noisy Indian phone networks.  
Retell AI: Great turn-taking models. They invested heavily in custom endpointing algorithms.  
Gnani.ai (Indian): Strong local STT/TTS models built for Indian languages.  
Differentiators: The strongest systems do not rely on standard OpenAI/Deepgram integrations. They build custom endpointing models trained on conversational data, and they use semantic barge-in rather than acoustic barge-in.

13\. Critical Risks (Challenging the Project)  
Bad Turn Detection: The project assumes the system can tell when a person finishes speaking. Over Indian mobile networks with high background noise, VAD will either cut users off constantly or hang in dead silence. Mitigation: Build a custom dual-model endpointer (VAD \+ fast LLM to validate if the sentence is complete).  
Telephony Lock-in: If you build directly on Exotel's specific API, you cannot scale globally or switch providers if quality drops. Mitigation: Abstract the telephony layer. Use SIP/WebRTC bridges.  
LLM Hallucination on Data Extraction: If the AI calls a student, and the student says "I will come on Monday," the LLM might extract "Next Monday" or hallucinate a date. Mitigation: Use strict JSON schemas and Tool Calling (Function Calling). Do not rely on free-text summarization for the final exported CSV.  
DLT Blocking: TRAI is aggressive. If recipients mark your AI calls as spam, your virtual number will be blocked within days. Mitigation: Ensure the AI clearly states the purpose of the call within the first 3 seconds.  
14\. Recommended Technology Strategy  
Based on the independent research above, here is the optimal path forward:

1\. Telephony Provider:

Prototype: Twilio (for rapid WebSocket Media Streams dev) OR Exotel (if Indian number DLT is the immediate priority).  
Scale: Rent an Indian SIP trunk from a local provider (e.g., Jio/Airtel enterprise) and bridge via FreeSWITCH.  
2\. STT:

English: Deepgram (Nova-2 conversational model). Unbeatable speed.  
Telugu/Tanglish: Google Speech-to-Text (V1 API with auto\_decoding and multilingual config).  
3\. TTS:

English: Cartesia Sonic (for lowest latency) or ElevenLabs (for best naturalness).  
Telugu: Microsoft Azure Neural TTS (Telugu voices are far superior to ElevenLabs for native pronunciation).  
4\. LLM:

Llama 3.1 8B (served via Groq for ultra-fast TTFT) or GPT-4o-mini. Keep prompts incredibly short. Use JSON tool calling for data extraction.  
5\. Real-time Architecture:

Do not build polling loops. Use an event-driven WebSocket orchestrator. As audio streams in, push it to STT. As STT yields text, push to a state machine. If state \== "user\_turn\_complete", stream prompt to LLM. Stream LLM tokens to TTS. Stream TTS chunks back to the WebSocket.  
Implement a "barge-in" event bus: if VAD triggers during "ai\_speaking" state, send a kill signal to the TTS stream.  
6\. Backend Architecture:

Node.js or Go for the real-time WebSocket layer (critical for I/O concurrency).  
Python/FastAPI for the LLM/STT integration and business logic.  
Redis for ephemeral call state (who is speaking, current prompt context).  
Celery/RabbitMQ for background tasks (transcription, summary generation, CSV export).  
7\. Database:

PostgreSQL for relational data (Campaigns, Contacts, Call Logs, Results).  
8\. Deployment:

AWS Mumbai (ap-south-1). This is non-negotiable for latency. Hosting in US/EU will add 250ms+ of network latency, ruining the human feel.  
9\. Development Roadmap:

Phase 1 (Weeks 1-3): Text-to-Speech conversational loop in terminal. Master the VAD, STT, and TTS pipeline before touching telephony. Aim for \<800ms latency.  
Phase 2 (Weeks 4-6): Integrate Twilio/Exotel WebSocket. Handle real PSTN audio (mu-law to PCM conversion). Implement barge-in.  
Phase 3 (Weeks 7-8): Implement the LLM state machine, tool calling for student data extraction, and campaign management DB.  
Phase 4: Begin Telugu evaluation. Swap Deepgram for Google STT, ElevenLabs for Azure. Evaluate code-switching failure rates.

# k3 approch

# 1\. Telephony: Best Current Options for AI Voice Calling in India

## The Core Architectural Decision: SIM/eSIM vs. Cloud Telephony vs. SIP

Your assumption that a "proper Indian telephone number" requires evaluating SIM/eSIM is worth challenging. For a scalable AI voice platform, a physical SIM or eSIM is almost never the correct architecture. Here is why:  
Table

| Approach | What It Is | Pros | Cons | Verdict |
| :---- | :---- | :---- | :---- | :---- |
| Physical SIM / eSIM | Consumer mobile SIM in a GSM gateway or Android device | Very low per-minute cost; no KYC beyond normal SIM | Illegal/gray-area for commercial bulk calling; no API control; no concurrent calls; TRAI considers this "gray traffic"; no call recording consent automation; device failure \= downtime; no CLI management | Inappropriate |
| Cloud Telephony (CPaaS) | Exotel, Ozonetel, Knowlarity, Plivo, Twilio | Full API control; WebSocket/RTP streaming; DLT compliance support; concurrent scaling; legitimate CLI | Higher per-minute cost; KYC required; monthly commitments | Correct for prototypes and mid-scale |
| Direct SIP Trunk | Direct carrier relationship with Airtel Business, Jio Business, Tata | Lowest per-minute cost at scale; best latency; full control | You become your own CPaaS; need SBC config, codec negotiation, DLT plumbing, telecom engineer | Correct at 20L+ minutes/month |
| Hybrid | Direct SIP for volume \+ CPaaS for overflow/failover | Cost optimization \+ operational safety | Complexity | Correct for mature scale |

Verified fact: Direct SIP trunking with Airtel/Jio/Tata at 20 lakh+ minutes/month drops outbound rates to ₹0.60–₹1.20/min versus ₹0.80–₹1.80 through aggregators.  
Technical inference: For your prototype and early production (under \~10,000 calls/month), a CPaaS provider is the only rational choice. A SIM-based approach would require you to build hardware redundancy, call rotation to avoid carrier spam flags, and manual DND scrubbing — all of which a CPaaS handles.

## Provider Comparison for India (2026)

Table

| Provider | India Focus | Outbound ₹/min | DID Provisioning | DLT Support | WebSocket/RTP Streaming | Best For |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| Exotel | Very high | ₹0.80–1.00 | 2–5 days | Strongest operational support | AgentStream (\<50ms) | India-native voice AI; DLT hand-holding |
| Ozonetel | Very high | Competitive | 3–7 days | Strong | Yes | Contact-center workflows; unlimited minute plans |
| Knowlarity | High | Competitive | 2–5 days | Strong | Yes | Mid-market with compliance needs |
| Plivo | Moderate | ₹0.80–1.20 | 24–48 hours | Competent | Yes | Developer-led; global expansion later |
| Twilio | Low in India | ₹1.20–1.50 | 24–48 hours | Thinnest | Yes | Global-first teams; weak India-specific compliance |
| Direct SIP (Airtel/Jio) | N/A | ₹0.60–1.20 | Weeks | You handle it | Raw SIP/RTP | 20L+ minutes/month with telecom engineer |

Verified fact: Exotel's pricing is typically ₹0.80–1.00 for outbound and ₹0.30–0.50 for inbound, with AgentStream providing \<50ms media latency for AI streaming.  
Verified fact: Plivo and Twilio provision new Indian DIDs in 24–48 hours versus 2–7 business days for India-native providers.  
Challenge to your assumption: Twilio is not the best choice for India despite its global popularity. Its India DLT support is the thinnest among major providers, and its India outbound rates are 20–50% higher than Exotel/Plivo. If you start with Twilio because "it's what everyone uses," you will pay a premium and struggle with TRAI compliance.

## KYC, DLT, and Regulatory Requirements

DLT Registration (for SMS): If your system sends any SMS (appointment reminders, OTPs, consent confirmations), you must register on a TRAI-approved DLT platform. This is a three-phase process: Entity Registration → Sender ID Registration → Template Registration. Cost: ₹5,000 \+ GST for entity registration; ₹50,000 \+ GST for telemarketer delivery function.  
For voice calls specifically: The DLT framework is primarily SMS-oriented, but TRAI's TCCCPR regulations and the new Digital Consent Registry apply to voice communications as well. You must:

* Register as a telemarketer if making outbound commercial calls  
* Scrub against DND (Do Not Disturb) lists  
* Maintain call logs for 1 year  
* Implement recording disclosure  
* Restrict calling hours (typically 9 AM – 9 PM for marketing; 9 AM – 7 PM for BFSI)

Critical 2026 update: TRAI has introduced mandatory AI disclosure for AI-generated voice calls. Your agent must clearly state at the beginning of the call that it is AI-powered, the purpose, company identification, and how to opt out. Penalties for non-compliance reach up to ₹10 lakh, with repeat offenders facing disconnection and blacklisting.  
Number series restrictions:

* 140 series: Strictly for marketing/promotional calls  
* 160 series: Reserved for transactional/service calls from regulated entities (RBI, SEBI, IRDAI, PFRDA)  
* Cross-selling during service calls on 160 series is prohibited

For your college absentee use case: This is arguably a transactional/service call (educational institution contacting enrolled students about attendance). You may qualify for 160-series numbers or standard DIDs, but you still need explicit consent or a legitimate educational relationship. Do not assume "we're a college" exempts you from consent requirements.  
---

# 2\. Real-Time Voice Architecture

The architecture is a cascaded pipeline with intelligent orchestration, not a single model. Here are the critical components and their quality impact:

## Component Breakdown

Table

| Component | Function | Quality Impact | Typical Latency |
| :---- | :---- | :---- | :---- |
| Telephony | PSTN/SIP connectivity, audio capture | Medium — 8kHz μ-law degrades audio | 20–100ms network |
| VAD (Voice Activity Detection) | Detects if human is speaking | Critical — bad VAD \= false interruptions or delayed responses | Runs continuously |
| STT (Speech-to-Text) | Converts speech to text | Critical — errors cascade to LLM | 50–300ms (streaming) |
| Endpoint Detection | Decides when user has finished speaking | Critical — hardest problem in voice AI | 100–400ms |
| LLM | Reasoning, response generation | High — but latency matters more than size | 100–500ms TTFT |
| TTS (Text-to-Speech) | Converts response to audio | Critical — dominant cost and perceived quality | 40–200ms TTFB |
| Turn-Taking Orchestrator | Coordinates who speaks when | Critical — defines "naturalness" | Orchestration layer |
| Barge-In Handler | Stops AI when user interrupts | Critical — worst failure mode is talking over user | \<100ms stop time |
| Session Manager | Maintains call state, context, memory | High — prevents repetition, maintains flow | N/A |
| Tool Calling | Extracts structured data, triggers actions | Medium — latency spikes if synchronous | 100–500ms |

## The Streaming Principle

The single most important architectural concept: Every stage must stream into the next without waiting for completion.

* STT emits partial transcripts every \~50ms  
* LLM streams tokens as they generate  
* TTS streams audio chunks before the full response exists  
* Endpoint detection uses a small neural model updating probability dozens of times per second

Technical inference: A non-streaming architecture adds 2–4 seconds of perceived latency. A streaming architecture can achieve \~600ms end-to-end.

## What Actually Differentiates Production-Grade Systems

In 2026, the raw STT/LLM/TTS components are commoditized. What separates "demo" from "production-grade" is:

1. Endpoint detection quality — A naive timeout (e.g., 1.5s silence) destroys naturalness. Humans pause mid-sentence, say "um," and breathe. The 2026 answer is a trained conversational endpoint model.  
2. Barge-in recovery — When interrupted, the system must stop TTS within 100ms, discard the remaining planned response, and start a fresh STT stream without losing context.  
3. VAD tuning — Semantic VAD (understanding meaningful speech vs. background noise) outperforms energy-based VAD.  
4. Turn-taking model — A dedicated small model that decides when the human has finished, considering prosody, semantics, and conversational history.

---

# 3\. Latency Targets

## The Complete Latency Pipeline

Table

| Stage | Target | Where Latency Hides | Optimization |
| :---- | :---- | :---- | :---- |
| Network round-trip | 20–80ms | Physical distance to server | Edge deployment (Mumbai/Bangalore) |
| VAD detection | 10–50ms | Energy vs. semantic detection | Use semantic VAD (neural) |
| Endpoint detection | 100–300ms | Conservative timeouts | Train/fine-tune endpoint model on conversational data |
| STT | 50–200ms | Waiting for complete utterance | Streaming STT with partial transcripts |
| LLM TTFT | 100–400ms | Large model inference time | Use small/fast model; streaming; speculative decoding |
| TTS TTFB | 40–200ms | First audio chunk generation | Streaming TTS; optimize for speed |
| Audio playback | 20–50ms | Buffering | Minimal buffering; WebRTC if possible |
| TOTAL | \<700ms |  |  |

Verified fact: Under \~700ms end-to-end response time is the threshold where conversation feels human. Above that, callers interrupt, repeat themselves, and hang up.  
Where latency actually occurs: Most latency hides in turn-taking decisions and LLM time-to-first-token, not STT or TTS. A typical budget: network 50ms, VAD/turn-taking 200ms, LLM TTFT 250ms, TTS first audio 100ms. STT runs largely in parallel with speech.

## How High-Quality Systems Reduce Perceived Latency

1. Predictive TTS: Start generating audio for high-probability responses before the LLM finishes.  
2. Filler audio: Inject "um," "hmm," or "let me check" while tools run.  
3. Progressive responses: Speak the first clause while generating the rest.  
4. Edge deployment: Run VAD/STT/endpoint models in Mumbai/Bangalore, not US-East.  
5. Speculative execution: Pre-generate likely follow-up responses.

---

# 4\. Interruption and Turn-Taking

This is the most technically difficult requirement and the primary differentiator between robotic and natural systems.

## Handling Specific Scenarios

Table

| Scenario | Technique | Common Failure |
| :---- | :---- | :---- |
| User interrupts AI | Barge-in detection → immediate TTS stop → flush buffer → new STT stream | TTS continues for 500ms+; stale response plays |
| AI stopping immediately | \<100ms TTS cancellation; discard unplayed audio chunks | Partial word cutoff sounds robotic |
| User pausing while thinking | Semantic endpoint model distinguishes "thinking pause" from "finished" | Naive timeout cuts off user or delays response |
| Incomplete sentences | LLM trained on conversational repair; ask clarifying questions | AI treats incomplete input as complete |
| Simultaneous speech | Crosstalk detection; defer to user; mark overlapping audio | Both speakers continue; chaos |
| Background speech | Directional/noise-robust VAD; spectral subtraction | False trigger from TV/radio |
| False interruption detection | Hysteresis in barge-in threshold; confirm with 200ms lookahead | AI stops for every cough |
| Long pauses | Progressive "are you there?" prompts; comfort noise | Dead silence feels abandoned |
| Agent decides when to respond | Turn-taking probability model combining acoustic \+ lexical \+ conversational features | Always responds too fast or too slow |

## Architectural Patterns

The 2026 standard pattern: A small neural turn-taking model (often \~100M parameters) runs on the audio stream, outputting a probability of "user has finished" dozens of times per second. This model is trained on real conversational telephone audio.  
Barge-in implementation: The system maintains two audio streams:

1. Agent output stream (TTS → telephony)  
2. User input stream (telephony → VAD → STT)

When VAD detects user speech during agent output, a barge-in event fires. The orchestrator must:

1. Send TTS stop signal (\<50ms)  
2. Flush remaining TTS buffer  
3. Reset STT stream (or maintain separate context)  
4. Start new inference turn

Technical inference: Poor barge-in handling is the \#1 reason users perceive voice AI as "robotic." A system that talks over the user for even 300ms feels fundamentally broken.  
---

# 5\. Voice Quality (TTS)

## Current TTS Comparison (2026)

Table

| Provider | Model | Naturalness | Latency (TTFB) | Streaming | Indian Accent | Telugu | Cost/1M chars | Best For |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| ElevenLabs | v3 / Flash v2.5 | Excellent (\#4 ELO) | \~100ms | Yes | Good (English) | Limited | \~$100 | Premium English; voice cloning |
| Cartesia | Sonic-3 / Sonic-3.5 | Very good | \~40–90ms | Yes | Moderate | No | \~$39 | Ultra-low latency |
| Inworld | TTS-2 / TTS 1.5 Max | Excellent (\#1–2 ELO) | \~120–155ms | Yes | Good | No | \~$12.50–35 | Expressive realtime; steerable |
| Google | Gemini 3.1 Flash TTS | Excellent (\#2 ELO) | Variable | Yes | Good | Good | \~$36.60 | Multilingual; Indian languages |
| Deepgram | Aura-2 | Good | \~313ms | Yes | Moderate | No | \~$13.50 | Integrated stack; cost |
| VoisLabs | Default | Good (Indian languages) | Moderate | Batch+Stream | Good | Native-quality | \~₹8.3/min | Indian languages primary |
| DesiVocal | Default | Moderate | Moderate | Yes | Good | Yes | \~₹399/mo | Indian-built; INR billing |
| OpenAI | gpt-4o-mini-tts | Good | Moderate | Yes | Moderate | No | Bundled | OpenAI ecosystem |

Verified fact: Inworld TTS 1.5 Max ranks \#1 on Artificial Analysis Speech Arena ELO (1,208), followed by Google Gemini 3.1 Flash TTS (1,206), with ElevenLabs v3 at \#4 (1,178).  
Verified fact: For Indian languages specifically, VoisLabs and Narakeet lead. VoisLabs offers native Telugu voices, English→Telugu transliteration, and code-mixed ("Tanglish") handling. ElevenLabs and Murf are over-indexed for this market at their current price points.

## Challenge to Your Assumption

Do not assume open-source TTS is better or cheaper. Open-source models like Coqui TTS, Piper, or XTTS require significant GPU infrastructure, voice cloning data, and tuning to sound natural. For a small team, the engineering cost exceeds API costs. Commercial APIs also update models continuously — a hidden operational cost of self-hosting.  
For English: ElevenLabs, Inworld, and Google Gemini Flash TTS are the top tier. Cartesia wins on raw latency but sacrifices some expressiveness.  
For Telugu: This is where the ecosystem gaps appear. ElevenLabs has Telugu voices but quality is described as "limited" for conversational use. VoisLabs and DesiVocal are specifically built for Indian languages. Google Cloud TTS has Telugu support but conversational naturalness is questionable. The biggest gap: No major realtime TTS provider offers truly natural, conversational Telugu with emotional range and code-switching.  
---

# 6\. STT Quality

## Comparison for Conversational Phone Audio

Table

| Provider | Model | English WER | Phone Audio WER | Indian Accent | Telugu | Streaming Latency | Cost/min | Best For |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| Deepgram | Nova-3 | \~5.26% (batch) | 21.8% (CallHome) | Good | Poor | \<300ms | $0.0043 | Real-time voice agents; speed |
| Deepgram | Flux | N/A | 15.58% (realtime) | Good | Poor | \<300ms | $0.0065 | Conversational agents |
| AssemblyAI | Universal-3.5 Pro | \~7.0% (aggregate) | \~23.4% | Good | No | \~300ms | $0.0035 | Max accuracy; post-processing |
| Whisper (OpenAI) | Large-v3 | \~8–12% real-world | \~26.4% | Good | \~21–28% | 1–5s (batch) | Free (self-host) / $0.006 | Multilingual; Indian languages |
| Google | Chirp 2 | \~3–4% clean | \~7–10% noisy | Very good | Good | \~350ms | $0.006 | Indian languages |
| ElevenLabs | Scribe v2 | Good | Good | Good | Unknown | Realtime | $0.0065 | Integrated with ElevenLabs TTS |

Verified fact: On conversational phone audio (CallHome benchmark), Deepgram Nova-3 achieves 21.8% WER versus Whisper's 26.4% and AssemblyAI's 23.4%. Even the best engine misses roughly 1 word in 5 on phone audio.  
Verified fact: Whisper Large-v3 achieves \~21.5% WER on Hindi FLEURS benchmark. Telugu WER on Whisper (from academic research) is approximately 20.3–26.7% depending on model size and prompting.  
Critical finding for Indian accents: The Voice of India benchmark found that best-performing models scored 5–6% WER on Indo-Aryan languages (Hindi, Bengali) but 15–20% on Dravidian languages (Tamil, Telugu, Malayalam).  
Challenge to your assumption: Deepgram is the dominant choice for English voice agents due to speed and cost, but its multilingual accuracy is significantly worse than alternatives. For Telugu, Google Cloud STT and Whisper are better starting points, though all options have substantial quality gaps for conversational Telugu.

## Code-Switching (Tanglish)

This is a major unsolved problem. When speakers switch between Telugu and English mid-sentence:

* Deepgram Nova-3 Multilingual achieves 12.22% WER on code-switching audio  
* AssemblyAI Universal-3.5 Pro achieves 7.69% WER on code-switching  
* Whisper handles Hinglish/Tanglish better than most commercial APIs due to its diverse training data, but still struggles with mid-sentence switches

Technical inference: For Phase 3 (Telugu \+ English code-switching), you will likely need a custom solution or significant prompt engineering. No off-the-shelf API handles Tanglish conversationally at production quality.  
---

# 7\. LLM Strategy

## Do You Need a Large Reasoning Model?

Short answer: No, not for most turns.  
A voice agent does not need frontier-level reasoning for every response. The LLM's job in a voice conversation is:

1. Understand intent (classification)  
2. Maintain context (short-term memory)  
3. Generate natural, concise responses (not essays)  
4. Decide when to call tools (structured extraction)  
5. Handle edge cases (escalation, clarification)

## Model Architecture Options

Table

| Architecture | Description | Latency | Cost | When to Use |
| :---- | :---- | :---- | :---- | :---- |
| Small fast model (3B–9B) | Gemma 4 26B, Qwen3, Mistral Small | Very low | Very low | 90% of turns; routine conversation |
| Medium model (20B–70B) | GPT-4.1, Claude Sonnet, Gemini Flash | Low | Moderate | Complex reasoning; multi-step extraction |
| Large model (400B+) | GPT-5.5, Claude Opus, Gemini Pro | Higher | High | Escalation only; edge cases |
| Hybrid routing | Small model handles routine; large model handles complex | Optimized | Optimized | Recommended architecture |
| Speech-to-speech native | GPT-Realtime 2.1, Gemini Live | Low | Very high ($0.09/min) | When single-vendor simplicity matters |

Verified fact: A small open model like Gemma 4 26B costs under $0.0002/min in LLM tokens, while GPT-5.5 at $5 input/$30 output per 1M tokens adds \~$0.015/min — more than an entire cascaded stack with a small model.  
Recommendation: Use a hybrid routing architecture. Route 90% of turns to a fast, cheap small model (Gemma 4, Qwen3, or Mistral Small). Escalate to a larger model only for:

* Ambiguous intent classification  
* Complex structured extraction  
* Sentiment analysis requiring nuance  
* Tool call failures

This reduces both latency and cost by 80%+ without sacrificing quality.

## Deterministic Logic vs. LLM

Not everything needs an LLM:

* Call status tracking (answered, busy, failed) → Deterministic telephony webhook  
* DND scrubbing → Deterministic API call  
* Simple information collection (name, date) → Can use deterministic grammar \+ LLM validation  
* Transcript generation → Deterministic STT output

Use LLMs for language understanding and generation only. Everything else should be deterministic code.  
---

# 8\. Cost Estimation

## Component Cost Breakdown (India, per conversation minute)

Table

| Component | Low-Cost Option | Mid-Range | Premium | Notes |
| :---- | :---- | :---- | :---- | :---- |
| Telephony (India outbound) | ₹0.60 (direct SIP) | ₹0.90 (Exotel/Plivo) | ₹1.50 (Twilio) | Dominant cost at scale |
| STT | $0.0036 (Deepgram Nova-2) | $0.0043 (Deepgram Nova-3) | $0.0075 (AssemblyAI) | Billed per audio minute |
| LLM | $0.0002 (small open model) | $0.002 (GPT-4.1) | $0.015 (GPT-5.5) | Token-based; history matters |
| TTS | $0.003 (Deepgram Aura-2) | $0.005 (Cartesia) | $0.010 (ElevenLabs) | Dominant API cost |
| Orchestration | $0 (DIY) | $0.03 (SigmaMind) | $0.055 (Retell) | Platform fee if used |
| Storage/Recording | $0.001 | $0.002 | $0.005 | S3/Cloudflare R2 |
| Infrastructure | $0.001 | $0.002 | $0.005 | Compute, load balancers |

Verified fact: TTS dominates every cascaded stack at 70–73% of raw component cost. The LLM is under 4% if using a small open model.

## Total Cost Per Minute (All-In)

Table

| Scenario | Cost/Min | Notes |
| :---- | :---- | :---- |
| DIY low-cost stack | \~$0.007–0.015 | Deepgram \+ Gemma 4 \+ Deepgram Aura \+ direct SIP |
| DIY mid-range stack | \~$0.025–0.040 | Deepgram \+ GPT-4.1 \+ Cartesia \+ Exotel |
| DIY premium stack | \~$0.060–0.090 | AssemblyAI \+ GPT-4.1 \+ ElevenLabs \+ Exotel |
| Managed platform (Bland) | \~$0.09–0.14 | All-inclusive; cheapest managed option |
| Managed platform (Retell) | \~$0.13–0.31 | Component-based; transparent |
| Managed platform (Vapi) | \~$0.12–0.25 | $0.05 platform \+ provider costs |
| Speech-to-speech (OpenAI) | \~$0.09 | GPT-Realtime 2.1; single vendor |

## Monthly Cost at Scale (assuming 3 min avg call duration)

Table

| Volume | DIY Low | DIY Mid | Managed (Retell) | Human Agent Equivalent |
| :---- | :---- | :---- | :---- | :---- |
| 100 calls/mo (300 min) | \~$2–5 | \~$8–12 | \~$40–90 | \~$150–300 |
| 1,000 calls/mo (3,000 min) | \~$20–45 | \~$75–120 | \~$400–900 | \~$1,500–3,000 |
| 10,000 calls/mo (30,000 min) | \~$200–450 | \~$750–1,200 | \~$4,000–9,000 | \~$15,000–30,000 |
| 100,000 calls/mo (300,000 min) | \~$2,000–4,500 | \~$7,500–12,000 | \~$40,000–90,000 | \~$150,000–300,000 |

Challenge to your assumption: Human calling in India costs $5–16 per agent hour offshore. At 3-minute calls, a human agent handles \~20 calls/hour \= $0.25–0.80 per call minute in labor alone, plus infrastructure, management, and turnover costs. AI voice agents at $0.07–0.15/min are already cost-competitive, but the gap narrows at lower volumes where human agents can multitask.  
Hidden costs not in the table:

* Barge-in waste: 10–30% extra TTS cost from poor interruption handling  
* LLM history growth: 30-minute calls can 2–3× LLM token costs  
* Minimum commitments: Deepgram Growth requires $4K+/year; ElevenLabs tiers have unused quota waste  
* DLT registration and compliance ongoing costs

---

# 9\. Scalability

## Scaling Scenarios

Table

| Concurrent Calls | Architecture | Bottlenecks | Provider Limits |
| :---- | :---- | :---- | :---- |
| 1 | Single WebSocket thread; local dev | None | N/A |
| 10 | Single server; async event loop | LLM rate limits; TTS concurrency | Most APIs handle 10 easily |
| 100 | Load-balanced workers; Redis for state | Telephony trunk capacity; STT socket limits; LLM TPM | Exotel/Plivo: negotiate CC; Deepgram: concurrency tiers |
| 1,000 | Kubernetes cluster; dedicated SBC; multi-region | Telephony trunk saturation; TTS throughput; database writes | Requires direct SIP or enterprise CPaaS; custom infrastructure |
| 10,000 | Multi-region auto-scaling; direct carrier relationships; edge compute | Carrier-grade routing; regulatory limits; cost explosion | Requires direct Airtel/Jio relationships; dedicated infrastructure |

Technical inference: The primary bottleneck at 100+ concurrent calls is telephony trunk capacity, not AI components. A CPaaS provider will enforce a concurrent-call ceiling. At 1,000 concurrent calls, you need either:

1. Enterprise CPaaS with burst allowances  
2. Direct SIP trunking with multiple carriers  
3. A hybrid approach (primary \+ overflow carriers)

Database consideration: At 100+ concurrent calls, your database must handle high write throughput for call state updates. Use Redis for hot session state (sub-millisecond latency) and PostgreSQL or ClickHouse for persistent call records and transcripts.  
---

# 10\. Indian Telecom/Legal Considerations

## Current Regulatory Framework (2026)

### TRAI TCCCPR Amendment (February 2026\)

Verified fact: TRAI's February 2026 amendment introduced:

1. Mandatory AI disclosure at call opening  
2. Digital Consent Registry — real-time verification before dialing  
3. 140/160 series number segregation — marketing vs. service  
4. Penalties up to ₹10 lakh for violations; repeat offenders face 1-year disconnection and blacklisting

### Specific Requirements for Your Use Case (College Absentee Calling)

Table

| Requirement | Status | Action Needed |
| :---- | :---- | :---- |
| KYC | Mandatory | Business PAN, GST, address proof |
| DLT Registration | Mandatory if any SMS | Entity \+ Header \+ Template registration |
| Telemarketer Registration | Likely required | Register as principal entity with TRAI |
| Consent | Required | Students must have consented to contact (enrollment forms) |
| DND Scrubbing | Mandatory | Scrub against National DND registry |
| AI Disclosure | Mandatory (2026) | Script must disclose AI nature |
| Recording Disclosure | Mandatory | Announce "this call is recorded" |
| Calling Hours | Restricted | 9 AM – 9 PM for most; 9 AM – 7 PM for BFSI |
| Call Log Retention | 1 year | Maintain records |
| Data Protection | DPDPA 2023 applies | Consent withdrawal mechanism; data minimization |

Critical challenge: Your "college absentee" use case sits in a gray area. Is it transactional (educational institution contacting enrolled students about attendance) or commercial (if any survey/data collection beyond immediate academic need)? If transactional, you may use standard DIDs. If commercial/marketing, you need 140-series numbers and explicit consent.  
Do not assume institutional use exempts you. TRAI's regulations apply to all automated calling. The "educational" exemption is narrower than most assume.

### Academic/Student Access

Most providers (Twilio, Exotel, Plivo) offer startup credits but not specific academic discounts for telephony. You can typically get:

* Exotel: 7-day trial with ₹500 credits  
* Twilio: $15–50 trial credit  
* Plivo: Trial credits on request

For significant volume, negotiate as a startup rather than an academic project.  
---

# 11\. English → Telugu Transition

## What Must Change

Table

| Component | English Approach | Telugu Requirement | Gap Severity |
| :---- | :---- | :---- | :---- |
| STT | Deepgram Nova-3 or Whisper | Google Cloud STT or Whisper; custom fine-tuning likely needed | Critical — 15–20% WER on Dravidian languages vs. 5–6% on Indo-Aryan |
| TTS | ElevenLabs/Cartesia/Inworld | VoisLabs, DesiVocal, or Google Cloud | Critical — No premium realtime Telugu TTS exists |
| Endpoint Detection | English-trained models | Needs Telugu acoustic/prosodic training | High — Pauses, fillers, and turn cues differ |
| LLM Prompting | English system prompts | Telugu prompts; code-switching handling | High — Tanglish is not well-handled by any API |
| Pronunciation | Standard English phonemes | Telugu retroflexes, vowel length, sandhi | Critical — Names, places, numbers often mispronounced |
| Regional Dialects | Minor accent variation | Telangana vs. Andhra dialects; regional vocabulary | High — Models trained on standard Telugu |
| Code-Switching | Occasional loanwords | Heavy Tanglish (Telugu \+ English mid-sentence) | Critical — Major unsolved problem |
| Numbers | Standard English number TTS | Telugu number system; lakhs/crores; ordinal forms | Moderate — TTS often falls back to English numerals |
| Names | Standard pronunciation | Telugu names with Sanskrit/Telugu origin; honorifics | High — Critical for your absentee use case |

## The Biggest Technical Gaps

1. Conversational Telugu TTS: Current TTS for Telugu is either robotic (Google Cloud) or not realtime (VoisLabs is batch/streaming hybrid). There is no ElevenLabs-quality Telugu voice that streams with \<200ms latency.  
2. Telugu STT on Phone Audio: Whisper achieves \~20–27% WER on Telugu. On 8kHz phone audio with background noise, this degrades to potentially 30–40% — borderline unusable for information extraction.  
3. Code-Switching: No production API handles Telugu-English code-switching reliably. AssemblyAI's 7.69% WER on code-switching is for major European languages, not Tanglish.  
4. Colloquial Speech: Telugu conversational fillers ("ante," "emito," "inkenti"), discourse markers, and informal grammar are poorly represented in training data.

Recommendation: Do not attempt Telugu until your English system has:

* Proven interruption handling  
* Proven structured extraction accuracy \>90%  
* Proven endpoint detection quality  
* A clear path to custom model fine-tuning

---

# 12\. Competitive Landscape

## Major Players (2026)

Table

| Company | Differentiation | Latency | Voice Quality | Indian Languages | Telephony | Cost | Developer Flex |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| Inworld AI | \#1 TTS quality; model-agnostic (220+ LLMs); expressive steering | Sub-200ms | Excellent | 15 GA; 90+ experimental | BYO | Low (cascaded) | High |
| Retell AI | Native telephony; enterprise compliance; structured dialog | \~600ms | Very good | Moderate | Built-in | $0.13–0.31/min | Moderate |
| Vapi | Provider-agnostic orchestration; 14+ providers | Variable | Good (depends on providers) | Depends on providers | BYO | $0.05 \+ providers | High |
| Bland AI | Cheapest at scale; outbound-native; campaign management | Good | Good (below premium) | Limited | Built-in | $0.09–0.14/min | Low |
| Cartesia | Ultra-low latency TTS (\~40ms TTFB); full stack (Sonic \+ Ink \+ Line) | \~40ms TTFB | Very good | 42+ languages | Built-in | $0.06 \+ telephony | Moderate |
| ElevenLabs | Broadest language coverage; voice cloning; ConvAI platform | Sub-100ms | Excellent | 70+ languages | Built-in | Higher | Moderate |
| Bolna AI | Indian/South Asian market focus; INR pricing | Good | Moderate | Indian languages | India-native | $0.05–0.07/min | Moderate |
| OpenAI | Unified ecosystem; Realtime API; SIP connectivity | Low | Good (not premium) | 57+ languages | Built-in | $0.09/min | Low (lock-in) |
| Deepgram | Integrated speech stack; Voice Agent API; turn detection | Low | Good (Aura-2) | 36+ languages | Built-in | $0.05–0.16/min | Moderate |

Verified fact: Bland AI is optimized for high-volume outbound at \~$0.09/minute all-in, making it 30–50% cheaper than Vapi or Retell at scale. Voice quality sits below Vapi/ElevenLabs-based platforms.  
Verified fact: Bolna AI specifically targets Indian/South Asian language markets at $0.05–0.07/min.

## What Differentiates the Strongest Systems

The strongest systems (Inworld, Retell, top-tier custom stacks) differentiate on:

1. Endpoint model quality — Not raw TTS latency, but when to speak  
2. Barge-in recovery speed — \<100ms TTS cancellation  
3. Expressive voice control — Natural pauses, breathing, emotional range  
4. Turn-taking orchestration — Not just fast components, but correct sequencing

Marketing claims vs. reality: Many platforms claim "human-like conversations." In practice, most implementations still feel robotic because:

* They use naive timeout-based endpoint detection  
* They don't handle barge-in gracefully  
* They use cheap TTS that sounds "good enough" in demos but grating over 10+ minutes  
* They don't vary prosody based on conversational context

---

# 13\. Critical Risks

Table

| Risk | Likelihood | Impact | Mitigation |
| :---- | :---- | :---- | :---- |
| Robotic voice | Medium | High | Invest in premium TTS (ElevenLabs/Inworld); use expressive steering; avoid cheap bundled voices |
| High latency | High | High | Edge deploy in India; use small LLM for 90% of turns; optimize turn-taking model |
| Poor interruption handling | High | Critical | This is the \#1 failure mode. Test barge-in aggressively. Budget 10–30% TTS waste. |
| Bad turn detection | High | High | Do not use naive timeouts. Use semantic endpoint detection. |
| Hallucinations | Medium | High | Use deterministic logic for extraction; LLM only for conversation; validation layers |
| Incorrect information extraction | Medium | High | Multi-pass extraction; validation prompts; human review for critical fields |
| Telephone audio degradation | Certain | Medium | 8kHz μ-law is unavoidable; train/test on phone audio specifically; use noise-robust STT |
| Poor Indian accent recognition | Medium | High | Test Deepgram vs. Whisper vs. Google on your target accent; consider fine-tuning |
| Telugu quality | Certain | Critical | No production-ready conversational Telugu stack exists. This is a research project, not a config change. |
| High per-minute costs | Medium | Medium | TTS dominates; negotiate committed tiers; use small LLM; direct SIP at scale |
| Telecom restrictions | Medium | Critical | TRAI can shut down campaigns in 24 hours. Full compliance from day one. |
| Provider lock-in | Medium | Medium | Use modular architecture (Vapi-style or DIY); avoid speech-to-speech native models |
| Concurrency limitations | Medium | High | Negotiate burst allowances; plan for direct SIP at 1000+ concurrent |
| Unreliable connections | Medium | Medium | Multi-carrier failover; retry logic; call quality monitoring |
| Poor scalability | Low | High | Stateless design; Redis for session state; horizontal scaling |
| Privacy/security | Medium | High | DPDPA compliance; encryption; minimal data retention; consent audit trail |

Biggest risk to project success: The combination of poor interruption handling \+ high latency \+ robotic voice creates a death spiral where users hang up immediately. You can have perfect information extraction, but if the conversation feels robotic, nobody will stay on the line long enough to extract anything.  
Second biggest risk: TRAI compliance. A single DND violation or missing AI disclosure can result in number blacklisting, which kills your entire operation.  
---

# 14\. Recommended Technology Strategy

Based on independent research, here are my recommendations. I provide alternatives where appropriate.

## 1\. Best Telephony Provider(s)

Primary recommendation: Exotel

* Best India-native DLT compliance support  
* AgentStream for \<50ms media latency  
* Competitive ₹0.80–1.00/min outbound  
* Strong operational support for Indian regulations

Alternative: Plivo

* Better for globally-minded teams  
* Faster DID provisioning (24–48 hours)  
* Good API quality  
* Slightly weaker India compliance support

Avoid: Twilio for India-specific deployment

* Thinnest DLT support  
* Highest India outbound rates  
* Better suited for global expansion later

At scale (\>20L min/month): Direct SIP with Airtel Business or Jio Business, using Exotel/Plivo as CPaaS layer for API convenience.

## 2\. Best Indian Number Approach

* Start with standard DID numbers from Exotel (not toll-free)  
* Ensure DLT entity registration is complete before any outbound calling  
* Implement AI disclosure in opening script from day one  
* For your college use case, position as transactional/service calls with proper consent documentation  
* Do not use 140-series unless explicitly marketing; standard DIDs or 160-series (if eligible) are appropriate

## 3\. Best STT Approach

Phase 1 (English): Deepgram Nova-3 or Flux

* Fastest streaming latency (\<300ms)  
* Best phone-audio WER among realtime APIs (21.8% on CallHome)  
* Cheapest commercial option ($0.0043/min)  
* Built-in keyterm prompting for names/student IDs

Alternative: Google Cloud STT Chirp 2 if Indian accent recognition proves problematic with Deepgram.  
Phase 2+ (Telugu): Google Cloud STT or fine-tuned Whisper. Deepgram's multilingual accuracy is significantly worse for Dravidian languages.

## 4\. Best TTS Approach

Phase 1 (English): ElevenLabs v3 or Inworld TTS-2

* Highest naturalness and expressiveness  
* Sub-200ms TTFB  
* Good Indian English accent support

Budget alternative: Cartesia Sonic-3.5 (\~40ms TTFB) if latency is absolute priority over expressiveness.  
Phase 2+ (Telugu): This is the hardest gap. Options:

* VoisLabs for batch/pre-recorded Telugu content  
* Google Cloud TTS for basic Telugu (robotic but functional)  
* Custom fine-tuned model (significant research investment)  
* Hybrid: English TTS for English words, Telugu TTS for Telugu words (complex orchestration)

## 5\. Best LLM Strategy

Hybrid routing architecture:

* 90% of turns: Small fast model (Gemma 4 26B, Qwen3 8B, or Mistral Small)  
  * Latency: \<100ms TTFT  
  * Cost: negligible  
  * Handles: routine conversation, simple extraction, status updates  
* 10% of turns: Escalate to GPT-4.1 or Claude Sonnet  
  * Complex ambiguity resolution  
  * Sentiment analysis  
  * Multi-step reasoning  
* Routing decision: Use a lightweight classifier or the small model's confidence score

Avoid: Using GPT-5.5 or Claude Opus for every turn. The cost is 50–100× higher with minimal quality benefit for routine conversation.

## 6\. Best Real-Time Communication Architecture

DIY cascaded pipeline over managed platform for maximum quality control:  
plain  
Telephony (Exotel)   
  → WebSocket/RTP audio stream  
  → VAD \+ Endpoint Detection (semantic, neural)  
  → Streaming STT (Deepgram)  
  → Turn-taking orchestrator  
  → LLM Router (small → large)  
  → Streaming TTS (ElevenLabs/Cartesia)  
  → Audio playback (minimal buffer)  
Key architectural decisions:

* Use WebSockets for full-duplex audio streaming  
* Run semantic VAD (not energy-based)  
* Implement dedicated endpoint detection model  
* Stream everything — no stage waits for previous to finish  
* Maintain separate audio contexts for barge-in recovery  
* Deploy in Mumbai or Bangalore (not US-East)

## 7\. Best Backend Architecture

* Language: Python (FastAPI/Starlette) or Node.js — both have excellent WebSocket support  
* Session state: Redis (hot state, sub-ms latency)  
* Persistent storage: PostgreSQL (call records, transcripts) \+ ClickHouse or BigQuery (analytics)  
* Queue: Redis Streams or RabbitMQ for async processing  
* Orchestration: Custom orchestrator (not a managed platform) — you need control over turn-taking

## 8\. Best Database

* Redis: Call session state, active WebSocket mappings, rate limiting  
* PostgreSQL: User data, campaign configurations, call outcomes, transcripts  
* Object storage (S3/R2): Call recordings, audio artifacts

## 9\. Best Deployment Approach

* Cloud: AWS Mumbai (ap-south-1) or GCP Mumbai (asia-south1)  
* Containerization: Docker \+ Kubernetes for horizontal scaling  
* Edge: Run VAD/STT/endpoint models on edge nodes; LLM/TTS can be API calls  
* Monitoring: Prometheus \+ Grafana for latency percentiles; custom dashboards for barge-in rate, endpoint accuracy, turn-taking latency

## 10\. Best Development Roadmap

Table

| Phase | Duration | Goal | Key Deliverable |
| :---- | :---- | :---- | :---- |
| Phase 0 | 2–3 weeks | Architecture validation | Single-call prototype with Exotel \+ Deepgram \+ GPT-4.1 \+ ElevenLabs |
| Phase 1a | 4–6 weeks | English MVP | Working outbound campaign; basic interruption; structured extraction; transcript |
| Phase 1b | 4–6 weeks | English quality | Semantic endpoint detection; barge-in \<100ms; expressive TTS; \<700ms E2E latency |
| Phase 1c | 4–6 weeks | English scale | 10+ concurrent calls; campaign dashboard; CSV export; basic analytics |
| Phase 2 | 8–12 weeks | Telugu research | Evaluate Telugu STT (Google, Whisper); evaluate Telugu TTS (VoisLabs, Google); build Tanglish test set |
| Phase 3 | 12–16 weeks | Telugu MVP | Basic Telugu conversation; code-switching handling; custom pronunciation |
| Phase 4 | Ongoing | Multilingual | Expand to Hindi, Tamil based on Telugu learnings |

Critical milestone before Phase 2: Your English system must achieve \>90% structured extraction accuracy and \<5% hang-up rate due to robotic feel. If you can't make English feel natural, Telugu will be impossible.  
---

## Final Challenge to Your Core Assumptions

1. "We need a proper Indian number" → Correct, but SIM/eSIM is the wrong approach. Cloud telephony with a DID is the only scalable, legal approach.  
2. "English architecture will automatically produce Telugu" → Dangerously wrong. Telugu requires fundamentally different STT, TTS, endpoint detection, and LLM prompting. Budget 3–4× the English effort.  
3. "Open-source is cheaper" → Not necessarily true. When you factor in GPU costs, engineering time, and ongoing maintenance, commercial APIs are often cheaper for small teams.  
4. "We need a large LLM" → Wrong. A small model with smart routing outperforms a large model on latency, cost, and often user experience.  
5. "The hardest part is making the call" → Wrong. The hardest part is making the conversation feel natural. Telephony is a solved problem; turn-taking is not.  
6. "We can add compliance later" → Catastrophically wrong. TRAI's 2026 regulations can shut you down in 24 hours. Compliance must be in the MVP.

This project is technically feasible and commercially viable, but the path to genuinely natural conversation is steeper than most assume. Start with English, optimize for \<700ms latency and flawless interruption handling, and treat Telugu as a Phase 2 research project with significant custom engineering requirements.

# deepseek approch

# **Independent Research & Architecture Review: AI Voice Calling Platform for India**

Date context: My training data runs through approximately mid-2025. I cannot browse the live web, and the current date in your environment is August 2026\. Where facts may have shifted (pricing, specific Telugu model quality, regulatory changes), I explicitly flag uncertainty. Everything below distinguishes verified fact, provider claim, technical inference, and my recommendation.

---

## **TL;DR / Executive Summary**

1. Do not build the telephony layer from scratch. The highest-leverage decision is to use an Indian CPaaS provider (Exotel or Ozonetel) for Indian DIDs and outbound calling, and either (a) use a managed AI-voice orchestration layer (Vapi, Retell, Sarvam AI) or (b) build your own orchestration on top of Pipecat/LiveKit with best-in-class pluggable STT/TTS. Building your own SIP media server is a distraction.  
2. The quality differentiator is turn-taking and interruption handling, not the LLM. Most "robotic" AI callers fail because of poor VAD/endpointing and slow TTS, not because the LLM is slow. Invest engineering effort there first.  
3. Indian number provisioning is the biggest regulatory/operational friction. Expect KYC, DLT registration, and consent documentation. An individual developer or student cannot easily get a production Indian DID. Partner with a registered entity or use a CPaaS that handles DLT on your behalf.  
4. For English first: Use a streaming STT (Deepgram or Google), a fast LLM (Gemini 2.0 Flash or GPT-4o-mini class), and a streaming TTS (OpenAI TTS, Azure en-IN, or ElevenLabs if budget allows). Target total user-stops-speaking-to-AI-audio-starts under 700ms.  
5. For Telugu later: Do not assume the same pipeline works. You will likely need Sarvam AI or [Gnani.ai](https://gnani.ai/) for STT/TTS because they are Telugu-first and handle code-switching. Realistic Telugu quality depends on these Indian vendors, and you should pilot them in Phase 2 before committing to a single architecture.  
6. Cost per minute: Realistic ₹3–₹15 (USD $0.04–$0.18) depending on TTS choice and scale. This is cheaper than a human telecaller on a per-minute basis, but the comparison is misleading—AI quality still trails humans in difficult conversations.  
7. Biggest risks: KYC/DLT friction, Google Dialer spam-flagging, Telugu TTS naturalness, and user experience of interruptions feeling "too sensitive" or "too stubborn."

---

## **1\. Telephony Options in India**

### **1.1 The Core Distinction: Who carries the call vs. who processes the audio**

You need three things:

* Number (DID): an Indian phone number to call from.  
* Call control API: ability to dial, track status, bridge audio.  
* Real-time audio access: ability to get bidirectional raw audio (typically 8 kHz μ-law PCM for PSTN) into your AI pipeline via WebSocket, SIP/RTP, or proprietary media streams.

The providers below differ primarily in which of the three they actually give you in India.

### **1.2 Comparison of major approaches**

| Provider / Approach | Indian DIDs | Outbound India | Real-time audio to AI | KYC/DLT burden | Concurrency | Notes |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| Exotel (Indian CPaaS) | Yes | Yes, strong | WebSocket audio streaming available via "Exotel AI" / "Talk to AI" | Medium — entity KYC; DLT handled | High (hundreds) | Strong India play. Good API. Enterprise-focused. |
| Ozonetel (Kookoo) | Yes | Yes | WebSocket streaming available | Medium | High | Well-documented. More developer-friendly than Exotel historically. |
| Kaleyra (Tata Communications) | Yes | Yes | Media streams available | Medium | Very high | Enterprise. Acquired by Tata in 2024\. Strong on CPaaS but AI-orchestration is less turnkey. |
| Twilio | Limited in India (inbound DIDs discontinued for new accounts; outbound via regulatory bundle) | Yes, via partner carriers | Yes (Media Streams over WebSocket) | High for India numbers; easier via Twilio's global number pool, but those aren't Indian | High | Media Streams are the gold standard for AI integrations, but Indian DID acquisition is painful. |
| Plivo | Yes (Indian DID available) | Yes | Limited AI-specific media stream | Medium | Medium | Solid CPaaS, cheaper than Twilio. AI integrations less turnkey. |
| Sarvam AI (Voice Agent platform) | Partners with Indian telephony | Yes | Fully managed voice pipeline | Medium (they handle much) | Depends on plan | Telugu-first AI voice agents. Strong for Indian languages. Less "bring-your-own-model" flexibility in early versions. |
| [Gnani.ai](https://gnani.ai/) | Partners with carriers | Yes | Managed voice AI | Medium | High | Indian enterprise voice AI. Telugu STT/TTS strong. |
| SIP trunk providers (e.g., Tata, Airtel, enterprise SIP) | Yes | Yes | You must build media server (FreeSWITCH) | High | Very high | Full control, but you own media routing, NAT, codecs, RTP. This is a multi-week engineering effort. |
| SIM/eSIM approach | Uses mobile phone number | Yes, via modem/gateway | Raw audio if you build the modem interface | Very low (just a SIM) | Very low (per SIM) | Not scalable. A SIM can realistically handle 1–3 concurrent calls with poor quality. Using a 4G/5G modem in a server is fragile. |

### **1.3 SIM/eSIM vs. virtual numbers vs. SIP — what's actually appropriate?**

Technical inference (strong): A normal SIM/eSIM in a phone or USB modem is not appropriate for a calling platform. Limitations:

* Mobile network operators often block or degrade concurrent voice calls on consumer SIMs. A standard SIM supports at most 2–4 simultaneous voice calls, and call quality over a relayed modem is poor.  
* You'd be building your own GSM stack, which is a massive detour from the actual value (conversation quality).  
* Caller ID would be a personal mobile number, which looks legitimate but doesn't scale and creates personal liability.

Recommendation: Use cloud telephony with Indian DIDs via a CPaaS. This gives you proper concurrency, call control, and regulatory compliance without the fragile hardware path.

### **1.4 The "AI-voice-agent platform" shortcut**

Providers like Vapi, Retell AI, LiveKit, and Bolna abstract the entire telephony+AI pipeline. They each have different India coverage:

* Vapi: Works with Twilio/Telnyx/Exotel; Indian DID support depends on the underlying provider. Vapi handles WebSocket audio, VAD, STT/TTS plugin, LLM orchestration, and structured data extraction. Fast to start.  
* Retell AI: Strong turn-detection model. Telephony via Twilio/Vonage/SIP. Indian DIDs possible via Plivo/Exotel connector.  
* LiveKit: Open-source WebRTC/agents framework. You bring your own telephony via SIP; stronger for building custom pipelines.

Key inference: If your goal is to get a high-quality English demo fast, using a managed orchestrator (Vapi/Retell) with an Indian CPaaS for numbers is the pragmatic path. If you need deep control over turn-taking (which you said is a differentiator), you may eventually build your own orchestrator, but do not start there.

---

## **2\. Real-Time Voice Architecture: Critical Components**

### **2.1 The pipeline**

`text`

`User speaks`  
   `↓`  
`PSTN → Provider (SIP/RTP) → Audio stream (WebSocket/PCM)`  
   `↓`  
`VAD / Endpoint detection`  
   `↓`  
`Streaming STT (interim hypotheses)`  
   `↓`  
`Conversation orchestrator (state machine + LLM)`  
   `↓`  
`TTS (streaming first-chunk)`  
   `↓`

`Audio back into provider`

### **2.2 Component-by-component analysis**

| Component | Role | Impact on perceived quality | Notes |
| :---- | :---- | :---- | :---- |
| VAD (Voice Activity Detection) | Detect whether there is speech energy in the audio | Very high | Bad VAD causes either clipped speech or long silences. Use adaptive thresholds, not fixed energy. |
| Endpoint detection | Decide when the user has finished their turn | Extremely high | This is the \#1 source of "robotic" feel. Pure silence threshold fails for hesitation. Need semantic-aware endpointing. |
| STT (Streaming) | Convert speech to text, emit interim results | High | Use interim results to start LLM pre-warming. Accuracy of Indian English matters. |
| Turn-taking model | Decide who speaks when | Extremely high | Should incorporate VAD, syntax, semantics, and user speaking style. Some vendors (Retell) sell this as a service. |
| Barge-in / interruption | Stop TTS when user starts speaking | Very high | Must stop within \~50–150ms of user speech onset. Full-duplex audio is mandatory. |
| LLM | Generate response, track state, extract entities | Medium (for quality) | A slow LLM adds latency; a wrong LLM fails extraction. But the LLM is rarely the quality bottleneck if chosen correctly. |
| TTS (Streaming) | Produce speech from text | Very high | First-audio latency matters most. Naturalness, pacing, and sentence endings matter for trust. |
| Session memory | Maintain context, slots, user intent | Medium | Use Redis for ephemeral state \+ Postgres for results. Keep context window tight. |
| Tool/function calling | Query knowledge base, validate data, update DB | Medium | Keep tools fast; avoid synchronous API calls that block the turn. |
| Call state machine | Track dialing, ringing, in-progress, completed | Medium | Finite-state machine, not ad-hoc code. |

### **2.3 Largest perceived-quality levers (my inference)**

1. Endpoint detection quality — decides whether the AI waits awkwardly or interrupts too early.  
2. TTS first-audio latency and naturalness — the most audible difference.  
3. Barge-in sensitivity — too sensitive \= AI stops at coughs; too stubborn \= feels like IVR.  
4. STT accuracy on Indian English — mis-recognition cascades into wrong responses.  
5. LLM speed — less important than people think if you pre-warm with interim STT.

---

## **3\. Latency Targets and Pipeline Analysis**

### **3.1 What humans perceive**

* Human turn-taking gap in phone conversations: \~150–400ms.  
* Below \~500ms total system response feels "good"; below \~700ms is acceptable; above \~1000ms feels robotic.

### **3.2 Complete latency chain (user stops speaking → AI audio starts)**

| Stage | Typical (naive) | Optimized | How to optimize |
| :---- | :---- | :---- | :---- |
| User stops speaking → VAD detects silence | 150–300ms | 50–150ms | Shorter silence threshold, adaptive VAD, or semantic endpointer |
| VAD → STT final hypothesis | 200–500ms | 100–300ms (interim) | Use interim hypotheses; don't wait for full final |
| STT → LLM prompt | 0–50ms | 0 | Pre-assemble prompt |
| LLM → first response token | 300–2000ms | 200–500ms | Use fast model (Gemini Flash, GPT-4o-mini), streaming |
| LLM → TTS first audio | 100–500ms | 30–150ms | Streaming TTS; first-chunk synthesis |
| TTS audio → user's ear | 20–100ms (PSTN jitter) | 20–100ms | Provider-dependent |
| Total | 770–3450ms | 400–1200ms |  |

### **3.3 Where naive systems fail**

Verified fact: The single biggest mistake is waiting for STT final result before calling the LLM. Final results are delayed by the trailing silence detector. High-quality systems use interim STT hypotheses to begin generating a response, then revise if the final hypothesis changes.

Technical inference: Another major source of latency is using a non-streaming TTS. Requesting the entire audio file from TTS before playback starts adds 500ms–2s. Streaming TTS with chunked synthesis is mandatory.

### **3.4 Practical target (my recommendation)**

* English demo: Total user-stops-speaking → AI audio starts: 600–800ms.  
* English production: 500–700ms.  
* Telugu: Expect \+100–200ms due to STT/TTS maturity, at least initially.

---

## **4\. Interruption and Turn-Taking**

### **4.1 Why this is the \#1 hard problem**

Turn-taking is about predicting intent, not just detecting sound. Humans use syntax, prosody, and semantics to know when the other person has yielded the floor. A purely energy-based VAD cannot do this.

### **4.2 The sub-problems**

| Problem | Naive approach | Better approach |
| :---- | :---- | :---- |
| User interrupting AI | Stop TTS when VAD detects user speech | Full-duplex audio; stop TTS within 50–150ms; do not stop on single-frame noise |
| User pauses while thinking | Treat as end of turn | Use longer silence threshold \+ semantic endpointer that checks if the utterance is a complete thought |
| Incomplete sentences | Respond immediately | Wait for syntactic completion or timeout; let LLM decide if the user trails off |
| Simultaneous speech | Just stop TTS | Consider both audio streams; if AI has almost finished a sentence, let it complete; if early in utterance, stop |
| Background speech / TV | Stop TTS and get confused | Use robust VAD \+ speaker separation; require sustained energy above threshold for N ms |
| False interruption (cough, uh) | Stop TTS | Require sustained user speech (e.g., 100ms) before interrupting; re-synthesize TTS from cut point |
| Long pauses | Timeout and prompt user | Adaptive timeouts; AI can say "Are you still there?" rather than restarting the whole turn |
| Agent deciding when to respond | Fixed silence threshold | Semantic turn-taking: use an LLM or dedicated model to judge if the user's utterance is complete |

### **4.3 Architectural patterns used by high-quality systems**

1. Full-duplex audio — The system listens while speaking. This is non-negotiable. (Twilio Media Streams, Exotel WebSocket, Pipecat, LiveKit all support this.)  
2. Continuous VAD with hysteresis — A short "debounce" window prevents false triggers. Example: user speech must exceed threshold for 80–120ms before AI stops TTS.  
3. Semantic endpointing — A small classifier (or the main LLM) decides "is the user done?" based on the content of the interim transcript, not just silence. Retell AI's turn-detection model does this; you can also prompt the LLM: "Is this utterance complete? Answer only YES/NO."  
4. TTS cut-point recovery — When interrupted, remember the last word boundary; resume from a natural sentence boundary rather than replaying the whole response.  
5. Interrupt patience parameter — Different contexts need different sensitivity. A college absence call should be more patient than a sales call. Expose this as a tunable parameter.

### **4.4 My recommendation**

Do not rely solely on a vendor's default turn detection. Even if you use Vapi/Retell, test with real Indian English audio containing hesitation, code-switching, and background noise and tune:

* Silence threshold (e.g., 400–600ms for Indian English)  
* Interrupt activation time (e.g., 100–150ms of sustained user speech)  
* Semantic endpointing on/off

This tuning is where your project will win or lose.

---

## **5\. TTS Landscape (2024–2025 snapshot, flag for 2026 changes)**

| TTS | Naturalness | Streaming | First-audio latency | English Indian accent | Telugu | Cost (indicative) | Verdict |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| ElevenLabs | Very high | Yes | \~200–400ms | Good en-IN voices | Yes, but quality uncertain for conversational Telugu | \~$0.30/1k chars (Turbo) | Best naturalness, highest cost. Use for English demo if budget allows. |
| OpenAI TTS (tts-1 / GPT-4o-mini-tts) | High | Yes | \~100–300ms | Good | Telugu supported, mixed quality | \~$15/1M chars | Best price/quality for English. Good first choice. |
| Azure Neural TTS | Good | Yes | \~100–300ms | Excellent en-IN voices (Neerja, Arjun) | te-IN (Shruti, Mohan) decent | \~$16/1M chars | Solid, reliable, good Indian English. Slightly less "warm" than ElevenLabs/OpenAI. |
| Google Cloud TTS | Good | Yes | \~100–300ms | Good en-IN | te-IN available | \~$16/1M chars | Similar to Azure. |
| Cartesia (Sonic) | High | Yes | Very low (\<150ms) | Good | Telugu growing | Tiered | Very low latency, strong for real-time. Check Telugu maturity in 2026\. |
| Sarvam AI TTS | Good (Telugu-first) | Yes | Low | Good | Strong Telugu | Per-char, India pricing | Best Telugu option as of my knowledge. English is decent but not best-in-class. |
| [Gnani.ai](https://gnani.ai/) TTS | Good | Yes | Low | Good | Strong Telugu | Enterprise pricing | Solid Indian language option. |
| Open-source (VITS, XTTS v2, Kokoro, etc.) | Variable | Some | Variable | Variable | Poor Telugu mostly | Compute cost | Not recommended for Telugu initially. XTTS v2 can be fine-tuned but engineering cost high. |

### **5.1 Key inferences**

* For English Phase 1: OpenAI TTS or Azure en-IN give the best cost/quality tradeoff. ElevenLabs is noticeably more natural but 20x more expensive per character. The difference matters when you scale.  
* For Telugu Phase 2: The gap between open/global providers and Sarvam/Gnani is significant. Plan to switch TTS vendor for Telugu rather than assuming ElevenLabs/OpenAI will handle conversational Telugu well.  
* Indian English accents: Azure en-IN voices are specifically trained on Indian English. OpenAI TTS handles Indian English well but is less India-specific. Test both with your actual scripts.

---

## **6\. STT Landscape (2024–2025 snapshot)**

| STT | Streaming | Indian English | Telugu | Code-switching | Latency | Cost (indicative) |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| Deepgram (Nova-3) | Yes | Very good | Yes (but quality varies) | Some | Very low | \~$0.0059/min |
| Google Cloud STT | Yes | Good | Good (te-IN) | Some | Low | \~$0.016/min |
| Azure STT | Yes | Very good (en-IN) | Good (te-IN) | Some | Low | \~$0.015/min |
| AssemblyAI (Universal) | Yes | Good | Yes | Moderate | Low | \~$0.0025/min |
| OpenAI Whisper (API) | Batch (chunking needed) | Very good | Good | Some | Higher | \~$0.006/min |
| Sarvam AI STT | Yes | Good | Best Telugu | Strong code-switching | Low | India pricing, competitive |
| [Gnani.ai](https://gnani.ai/) STT | Yes | Good | Strong Telugu | Strong | Low | Enterprise |
| Nvidia Canary (open) | Yes (with setup) | Good | Good | Moderate | Depends on GPU | Compute cost |

### **6.1 Key inferences**

* For English Phase 1: Deepgram or Google STT are the safe choices. Deepgram is cheaper and lower-latency; Google is very accurate on Indian English. Both stream well.  
* For Telugu Phase 2: Sarvam AI or [Gnani.ai](https://gnani.ai/) are the realistic best options. Their models are trained on Indian telephone speech and handle code-switching better than the global providers. Pilot Sarvam in Phase 1 for English-to-Telugu comparison.  
* Telephone audio (8kHz) degrades STT accuracy for all systems. Ask your telephony provider for 16kHz audio passthrough if possible. If not, choose an STT that explicitly trains on telephony audio (Deepgram, Google, Sarvam, Gnani).

---

## **7\. LLM Strategy**

### **7.1 Do you need a large reasoning model?**

No. This is one of your assumptions I want to challenge.

A voice agent for structured calls (absence follow-up, lead qualification, appointment scheduling) is not a task that requires deep reasoning. The LLM needs to:

* Understand conversational intent from noisy STT output  
* Decide what to say next from a constrained set of behaviors  
* Extract structured entities (name, reason, return date)  
* Stay within policy boundaries (don't promise things, don't hallucinate)

These are achievable with small, fast models.

### **7.2 Model comparison**

| Model class | Latency | Cost | Strengths | Weaknesses |
| :---- | :---- | :---- | :---- | :---- |
| Large reasoning (o1/o3, Sonnet 3.7+) | 1–5s first token | High | Complex reasoning, long-horizon tasks | Massive latency, expensive, overkill for calls |
| Large general (GPT-4o, Claude Opus) | 300–800ms | Medium-high | Good quality, strong tool use | Still overkill for most call flows |
| Small/fast (Gemini 2.0 Flash, GPT-4o-mini, Llama 3.1 8B on Groq) | 100–500ms | Low | Low latency, cheap, sufficient for slot-filling and conversational control | May struggle with very complex user queries |
| Local (Llama 3.x 8B, Qwen 2.5 7B) | 100–500ms (with GPU) | Very low marginal | Privacy, low cost at scale | DevOps burden, lower quality than cloud fast models |
| Deterministic logic | 0ms | Zero | Perfect for validation, formatting, state transitions | Cannot handle open-ended natural language |

### **7.3 Hybrid architecture (my recommendation)**

`text`

`Call flow:`  
`1. Deterministic state machine handles dial, greeting, retry, hangup`  
`2. LLM (small/fast) handles natural language:`  
   `- Understand user utterance`  
   `- Decide intent (e.g., "gives reason", "asks question", "wants to reschedule")`  
   `- Extract entities (name, reason, date)`  
   `- Generate the next response`  
`3. Deterministic validators check the LLM's extraction:`  
   `- Is the reason in an allowed enum? If not, ask LLM to re-classify`  
   `- Is the date valid? If not, ask again`

`4. Structured output is stored via a separate, deterministic Pydantic schema`

This reduces hallucination risk and speeds up extraction.

### **7.4 The hallucination challenge**

Technical inference (high confidence): LLMs will hallucinate names, numbers, and commitments in a voice call unless you constrain them. Mitigations:

* Use JSON-schema / function-calling output rather than free text for structured data.  
* Validate numbers against known formats (phone, dates).  
* Keep a "ground truth" list of allowed entities in the system prompt (e.g., student name must match the CSV record).  
* Use a separate small LLM call to verify extracted facts.

---

## **8\. Cost Analysis**

### **8.1 Per-minute cost breakdown (English, moderate quality)**

| Component | Cost basis | ₹/min (approx) | $/min |
| :---- | :---- | :---- | :---- |
| Telephony (Indian outbound, mobile) | ₹0.30–₹1.00/min at moderate volume | ₹0.30–₹1.00 | $0.004–$0.012 |
| Number rental | ₹500–₹2000/month amortized | ₹0.01–₹0.05 | negligible |
| STT | Deepgram \~₹0.50/min; Google \~₹1.30/min | ₹0.40–₹1.30 | $0.005–$0.016 |
| LLM | Gemini Flash / GPT-4o-mini: 2–5k in \+ 0.5–1k out tokens/min | ₹0.20–₹1.00 | $0.002–$0.012 |
| TTS (OpenAI/Azure) | \~₹1.30/1k chars; AI speaks \~400 chars/min | ₹0.50–₹0.80 | $0.006–$0.010 |
| TTS (ElevenLabs) | \~₹25/1k chars | ₹10–₹15 | $0.12–$0.18 |
| Infra \+ storage \+ DB | Redis, Postgres, compute, S3 per call | ₹0.10–₹0.50 | $0.001–$0.006 |
| Total (budget TTS) |  | ₹1.51–₹4.65 | $0.018–$0.056 |
| Total (premium TTS) |  | ₹11–₹18.65 | $0.13–$0.22 |

### **8.2 Scale estimates**

Assumptions: average call duration 2 minutes; average connect rate 50–60% for outbound.

| Monthly calls | Minutes (connected) | Cost (budget) | Cost (premium) |
| :---- | :---- | :---- | :---- |
| 100 | \~200 | ₹300–₹930 | ₹2,200–₹3,730 |
| 1,000 | \~2,000 | ₹3,020–₹9,300 | ₹22,000–₹37,300 |
| 10,000 | \~20,000 | ₹30,200–₹93,000 | ₹2.2L–₹3.7L |
| 100,000 | \~200,000 | ₹3.0L–₹9.3L | ₹22L–₹37L |

### **8.3 vs. human calling**

A human telecaller in India costs ₹15,000–₹25,000/month. At 160 working hours/month and 60% talk time, that's \~5,760 minutes → ₹2.6–₹4.3/min. But a human can handle only 1 call at a time, needs breaks, training, and supervision.

My inference: AI is cost-competitive at scale, especially with budget TTS. But the quality gap matters more than cost for your project's stated goal. Do not optimize for cost first; optimize for quality, then reduce cost.

---

## **9\. Scalability**

### **9.1 Concurrency bottlenecks**

| Scale | Bottleneck | Solutions |
| :---- | :---- | :---- |
| 1 call | Development comfort | Manual testing |
| 10 calls | Single-threaded orchestration, provider API rate limits | Horizontal orchestration workers, use async I/O (Python asyncio, Node.js) |
| 100 calls | STT/TTS API rate limits; LLM concurrency; audio websocket management | Use streaming providers with high rate limits; provision more API keys; use connection pooling |
| 1000 calls | Telephony provider concurrency caps; SIP trunk capacity; CPU for media processing | Multi-provider telephony; dedicated SIP trunk; use managed media servers (Asterisk/FreeSWITCH cluster) |

### **9.2 Architecture for scale**

* Stateless orchestration workers that consume a queue of "call sessions." Each active call is a WebSocket connection held by a worker.  
* Redis for session state (transcript buffer, slot values, conversation history).  
* PostgreSQL for final results, campaign state, exports.  
* Queue (RabbitMQ/Kafka or Redis streams) for call commands: dial, hangup, retry.  
* Media server only if you're doing SIP directly; if using CPaaS WebSocket, you skip this entirely.

Technical inference: For 1,000 concurrent calls, the cost of compute alone is manageable, but provider rate limits for STT/TTS/LLM will be the real constraint. You will need enterprise quotas with Deepgram/Google/OpenAI and possibly multiple API keys. Also, Indian CPaaS providers have per-account concurrency caps that may require negotiation.

---

## **10\. Indian Telecom/Legal Considerations**

### **10.1 KYC for Indian DIDs**

Verified fact (as of 2025, likely unchanged 2026): To obtain a virtual Indian number (DID) for outbound calling, you must complete KYC. Requirements typically:

* Registered entity (company, LLP, partnership, sole proprietorship) — or individual KYC with some providers (harder)  
* PAN card of entity/individual  
* Address proof  
* GST certificate if entity  
* Authorized signatory documentation

Technical inference: An individual student developer will struggle. The pragmatic path is:

1. Partner with the college/institution as the KYC entity, or  
2. Use a provider's sandbox/shared number for development (limited), or  
3. Use a reseller that handles KYC on your behalf (many CPaaS resellers exist, but trust is an issue).

### **10.2 DLT (Distributed Ledger Technology) registration**

Verified fact: TRAI's TCCCPR 2018 (amended) requires commercial communicators to register on DLT platforms (operated by Jio, Airtel, Vi, BSNL). This applies to SMS and voice commercial communications. Requirements:

* Entity registration on the DLT portals  
* Header registration (for SMS) — for voice, this maps to caller ID registration  
* Content template registration (for voice: call scripts/intent templates may need approval)  
* Consent management: consent from recipients must be captured and logged  
* Penalties for non-compliance, including number disconnection

Technical inference: The category matters:

* Transactional calls (related to an existing relationship, e.g., college notifying its own student about absence) have lighter consent requirements than promotional calls.  
* A college calling its enrolled student about attendance is likely transactional, but the college should still have the student's consent (e.g., via admission forms) and maintain records.  
* Some CPaaS providers (Exotel, Ozonetel) handle DLT registration as part of onboarding. Use them.

### **10.3 Recording and privacy**

Verified fact: Indian law (IT Act, Indian Telegraph Act) requires that if you record calls, you must inform the other party and/or obtain consent. A standard practice is to play a short announcement: "This call is being recorded for quality and training purposes."

Technical inference (strong): You should do this for your prototype too. It reduces legal risk and sets user expectations. The DPDP Act 2023 (Digital Personal Data Protection Act) is in effect with rules being finalized; it requires consent for processing personal data, data minimization, and breach notification. This applies to storing transcripts, names, phone numbers, etc.

### **10.4 Automated calling restrictions**

Verified fact (as of 2025): India does not have a blanket ban on automated outbound calls like the US TCPA. However:

* TRAI's DND registry allows users to opt out of promotional calls.  
* Since 2024, Google Dialer on Android flags suspected spam numbers. Many shared cloud-telephony numbers get flagged, which destroys trust.  
* TRAI has been increasingly concerned about AI voice calls; there were discussions in 2024–2025 about mandating disclosure of AI callers ("I am an AI assistant").  
* In late 2024, Airtel and Jio launched their own AI voice services, so the direction is toward more AI calls, not fewer, but with disclosure expectations.

My recommendation: For the college absence use case:

1. Ensure the college has student consent (admission form).  
2. Classify as transactional, not promotional.  
3. Disclose AI nature at the start ("This is an AI assistant from \[College\] calling regarding your attendance.").  
4. Play a recording notice.  
5. Use a dedicated Indian DID with clean reputation, not a shared pool number.

---

## **11\. English → Telugu Transition**

### **11.1 What changes**

| Component | English Phase 1 | Telugu Phase 2 | What breaks |
| :---- | :---- | :---- | :---- |
| STT | Deepgram/Google en-IN works well | Sarvam/Gnani preferred | Global STT struggles with casual Telugu; code-switching is the killer |
| TTS | OpenAI/Azure/ElevenLabs | Sarvam/Gnani strongly preferred | Global TTS often has unnatural Telugu prosody; names and numbers garbled |
| LLM prompt | English system prompt | Telugu system prompt \+ transliteration policies | Hallucination risk higher; need Telugu-native constraint validation |
| Entity extraction | English NER works | Indian names/places/dates in Telugu are hard; use Telugu-specific validators | Date/time formats, student names in Telugu script |
| Turn-taking | Tuned for English prosody | Telugu has different pause patterns; retune VAD/endpointing | English tuning won't transfer |
| Code-switching | Minor | Major — Telugu speakers mix English words (Tanglish/Tenglish) | STT must handle both scripts in same utterance |
| Phone audio | 8kHz degrades less | 8kHz degrades Telugu more because of retroflex and aspirated sounds | Telugu recognition on PSTN is measurably worse |
| Locale handling | Simple | Andhra vs Telangana dialects, formal vs colloquial register | Regional variation in greetings, pronouns, verb endings |

### **11.2 Biggest Telugu technical gaps (my inference, 2025 knowledge)**

1. Conversational Telugu TTS — Global providers have Telugu, but it's often news-reading register, not conversational. Sarvam/Gnani are better but still maturing for "natural human phone conversation" quality.  
2. Code-switching STT — Very few models handle "I am going to college, na? Actually, sir, nenu absent ayyi...". Sarvam is the strongest I know of.  
3. Telugu entity extraction — Extracting dates ("repu", "nellu", "varam"), names, and locations from colloquial Telugu requires Indian-specific training data.  
4. Phone audio degradation — Telugu has retroflex consonants (ట, ఠ, డ, ఢ, ణ) and aspirated stops that are poorly represented at 8kHz. Demand 16kHz audio from your telephony provider.

### **11.3 Phase 2 recommendation**

Run a Telugu pilot early. Do not assume the English architecture transfers. In Phase 1 (English), already sign up for Sarvam AI's sandbox and test a small Telugu script. This will reveal:

* Whether your telephony provider can deliver 16kHz audio for Telugu  
* Whether Sarvam's STT handles your target dialect  
* Whether the TTS is acceptable to native Telugu speakers

Budget this pilot as a separate line item.

---

## **12\. Competitive Landscape**

### **12.1 Who's doing high-quality AI phone conversations (as of 2025\)**

| Player | Focus | Strengths | Weaknesses |
| :---- | :---- | :---- | :---- |
| Retell AI | Developer platform, real-time AI voice agents | Strong turn-detection model, low latency, telephony integration, good dev UX | Less India-specific; Indian number support depends on underlying providers |
| Vapi | Developer platform | Large ecosystem, flexible "bring your own" STT/LLM/TTS, telephony handled | More configuration burden; India quality depends on providers |
| ElevenLabs Conversational AI | Voice agent platform | Top-tier TTS, brand, naturalness | Costly; less telephony depth in India; Telugu uncertain |
| OpenAI Realtime API | Voice-native API | Multimodal speech-to-speech, low-latency, high quality English | Expensive; telephony is DIY; Telugu uncertain; compliance burden on you |
| Google Gemini Live API | Voice-native API | Fast, good multilingual, competitive pricing | Telephony is DIY; developer docs evolving; Telugu quality unclear |
| Sarvam AI | Indian voice agents, Telugu-first | Best Telugu STT/TTS, India telephony partnerships, code-switching | Smaller ecosystem, less global tooling; English not as polished as global players |
| [Gnani.ai](https://gnani.ai/) | Indian enterprise voice AI | Strong Indian language models, enterprise trust, regulated industries | Less developer-friendly, more sales-led |
| LiveKit \+ Pipecat (open source) | Infrastructure | Maximum control, WebRTC/SIP, real-time agents | You assemble everything; no turnkey India telephony; engineering-heavy |
| Twilio \+ Voice Intelligence | CPaaS \+ AI add-ons | Mature telephony, Media Streams, developer trust | Indian DID friction; AI add-ons less flexible than dedicated platforms |
| Cisco/Genesys/AWS Connect | Enterprise contact center | Scale, compliance, integration | Not for a startup prototype; cost and complexity |

### **12.2 What differentiates the strongest systems (my analysis)**

1. Turn-detection model quality — Retell's biggest moat is their endpointer. This is where most DIY systems fail.  
2. TTS naturalness \+ latency — ElevenLabs's voice quality is a real differentiator; Cartesia's low latency is too.  
3. Indian language support — Sarvam and Gnani own Telugu for now. Global players are behind in code-switched Indian speech.  
4. Telephony partnership depth — Exotel/Ozonetel have the Indian carrier relationships; a US-based platform (Vapi/Retell) without a local partner will struggle with Indian DIDs.  
5. Developer flexibility — Vapi and LiveKit allow swapping STT/LLM/TTS; closed platforms (Sarvam, Gnani) don't, but deliver quicker for Indian languages.

### **12.3 My inference about the 2026 landscape**

By mid-2026, expect:

* OpenAI Realtime API and Gemini Live API to have more telephony partners, but India DID support still gated by local KYC.  
* Sarvam/Gnani expanding English quality, but still Telugu-first.  
* More hybrid platforms (e.g., Vapi \+ Sarvam connectors) emerging.  
* TRAI rules on AI call disclosure possibly formalized.

---

## **13\. Critical Risks (Challenging Your Project)**

### **13.1 Top risks ranked by severity**

| Risk | Likelihood | Impact | Mitigation |
| :---- | :---- | :---- | :---- |
| KYC/DLT friction prevents you from getting an Indian DID | High | Project-stopper | Partner with the college entity; use Exotel/Ozonetel who handle DLT; start this immediately |
| Google Dialer flags your number as spam | Medium-High | Trust destroyed | Dedicated DID, keep call volumes moderate per day, disclose AI identity, avoid repeated short calls |
| Robotic feel due to endpoint detection | High | Quality fails | Invest heavily in turn-taking tuning; consider Retell's endpointer or semantic endpointing |
| Telugu TTS quality is not human-natural | Medium-High | Phase 2 fails | Pilot Sarvam/Gnani early; budget for model fine-tuning or hybrid TTS |
| STT mis-recognizes Indian English on 8kHz telephone audio | Medium | Data extraction wrong | Use telephony-trained STT; request 16kHz audio; use deterministic validators |
| TTS cost blows budget at scale | Medium | Commercial failure | Start with OpenAI/Azure TTS; reserve ElevenLabs for demo only |
| LLM hallucination during information extraction | Medium | Wrong results, reputation damage | Use function-calling/JSON schema \+ deterministic validators; log and audit |
| Provider lock-in | Medium | Flexibility loss | Abstract STT/TTS/LLM behind interfaces; keep telephony provider swappable |
| Concurrency limits on STT/TTS/LLM APIs | Low-Medium | Scale ceiling | Provision multiple keys, negotiate enterprise quotas |
| Privacy/DPDP violation | Medium | Legal risk | Anonymize after export; store transcripts with consent; implement data minimization |
| Telephony audio degradation | Medium | Quality fails | Test with real PSTN calls; ask provider for 16kHz passthrough |
| User hangs up on AI | High (practical) | Campaign fails | Short, clear scripts; disclose AI; offer opt-out |

### **13.2 Three assumptions I want to challenge**

1. "Authentication and authorization are not required initially." — True for your web dashboard, but false for telephony. Indian number KYC/DLT is mandatory regardless of your dashboard. Do not defer this.  
2. "English first, Telugu later is a smooth transition." — The English architecture will not automatically transfer. The gap between English and conversational Telugu in STT/TTS/entity-extraction is large. Treat Telugu as a separate project with its own pilot.  
3. "We should build the whole pipeline ourselves for differentiation." — Your stated differentiator is conversation quality, not infrastructure. Building your own SIP/media server is weeks of work that does not improve conversation quality. Use proven platforms for telephony and audio transport; focus your engineering on turn-taking, prompt design, extraction validation, and language quality.

---

## **14\. Recommended Technology Strategy**

### **14.1 Guiding principles**

1. Highest conversation quality per engineering hour.  
2. Indian telephony credibility (DID, DLT, spam-free).  
3. Switchable components (STT/TTS/LLM) to avoid lock-in.  
4. Phase 2 Telugu readiness.

### **14.2 Recommendations**

#### A. Telephony provider(s)

Primary: Exotel or Ozonetel (Indian CPaaS with WebSocket streaming and DLT assistance).

* Both offer Indian DIDs, outbound dialing, and real-time audio streaming suitable for AI integration.  
* Exotel's "Exotel AI" suite is more mature for voice agents; Ozonetel is more developer-friendly.  
* Choose based on: WebSocket audio format, pricing, concurrency, and whether they can provide 16kHz audio.

Alternative: Plivo (cheaper, Indian DID available) if you want a global CPaaS.

Avoid for initial phase: Twilio (Indian DID friction), SIP direct (engineering burden), SIM-based (unscalable).

#### B. Indian number approach

* Use a dedicated Indian mobile DID from your CPaaS.  
* Complete KYC through the college or a registered entity.  
* Ask the CPaaS to handle DLT registration for transactional calls.  
* Disclose AI identity in the greeting.

#### C. STT

* English Phase 1: Deepgram (low cost, low latency) or Google STT (high accuracy for Indian English). Test both with your actual audio.  
* Telugu Phase 2: Sarvam AI STT (Telugu-first, code-switching) or [Gnani.ai](https://gnani.ai/).

#### D. TTS

* English Phase 1: OpenAI TTS (tts-1 or gpt-4o-mini-tts) for cost/quality; Azure en-IN (Neerja/Arjun) if you prefer stronger Indian English; ElevenLabs only for investor demos.  
* Telugu Phase 2: Sarvam AI TTS or [Gnani.ai](https://gnani.ai/) TTS. Do not rely on global providers for Telugu.

#### E. LLM strategy

* Primary: Gemini 2.0 Flash or GPT-4o-mini (fast, cheap, streaming, function-calling).  
* Fallback: Groq-hosted Llama 3.x 70B for low-latency open-source option.  
* Deterministic layer: Python/Pydantic validators for entity extraction, date parsing, and state transitions. The LLM generates natural language; validation is deterministic.

#### F. Real-time communication architecture

Option 1 (recommended for speed): Use Vapi or Retell AI as the orchestration layer. Configure your chosen STT/TTS/LLM. Connect to your Indian CPaaS for DIDs. Focus on prompt design and turn-tuning.

Option 2 (recommended for control): Build orchestration on Pipecat (Python) or LiveKit Agents. Connect to CPaaS WebSocket. Implement your own VAD/endpointing with semantic checks. This is more work but gives you full control over turn-taking and interruption.

Option 3 (not recommended initially): Build everything on FreeSWITCH \+ custom media server.

#### G. Backend architecture

* Language: Python (FastAPI) or TypeScript (Node.js). Python preferred for AI ecosystem.  
* Orchestrator: Async service per active call (Pipecat actor model, or FastAPI \+ asyncio WebSockets).  
* Queue: Redis Streams or RabbitMQ for call commands.  
* Session state: Redis (with TTL) for live call context.  
* Database: PostgreSQL for campaigns, contacts, results, transcripts.  
* Object storage: S3-compatible (AWS S3 or MinIO) for audio recordings and full transcripts.  
* Export: Generate Excel/CSV via backend job; use `openpyxl` or similar.

#### H. Best deployment approach

* Containerize services (Docker).  
* Deploy orchestration workers on AWS/GCP/Azure (or an Indian cloud provider like E2E/Netmagic for data residency).  
* Use managed Redis and Postgres for low ops overhead.  
* For high concurrency, auto-scale workers horizontally.

#### I. Development roadmap

Phase 0 (2–4 weeks): Telephony setup.

* Choose CPaaS, complete KYC, get Indian DID, test outbound call.  
* Set up WebSocket audio streaming and record a sample call.

Phase 1 (4–6 weeks): English MVP.

* Build orchestrator with Vapi/Retell or Pipecat.  
* Integrate STT (Deepgram/Google), LLM (Gemini Flash/GPT-4o-mini), TTS (OpenAI/Azure).  
* Tune turn-taking: silence threshold, interrupt sensitivity, semantic endpointing.  
* Build campaign flow (CSV upload, call scheduling, result storage).  
* Run a 100-call pilot with the college use case.  
* Measure: latency, transcription accuracy, extraction accuracy, user experience.

Phase 2 (4–6 weeks): Telugu pilot.

* Swap STT/TTS to Sarvam/Gnani.  
* Rewrite prompts and scripts in Telugu.  
* Test with native Telugu speakers (both Andhra and Telangana dialects).  
* Implement code-switching handling.  
* Decide whether to keep unified architecture or fork language pipelines.

Phase 3 (ongoing): Productionization.

* Add authentication/authorization to the dashboard.  
* Add DPDP compliance features (consent logs, data export, anonymization).  
* Scale concurrency, negotiate enterprise API quotas.  
* Build multi-campaign management, retry logic, reporting dashboard.

---

## **Summary of Where I Challenge Your Assumptions**

| Your assumption | My challenge |
| :---- | :---- |
| "Authentication not required initially" | Telephony KYC/DLT is mandatory regardless. Do not defer it. |
| "English architecture will transfer to Telugu" | It will not. Telugu needs separate STT/TTS vendors and tuning. Plan a separate pilot. |
| "Building everything ourselves gives better differentiation" | Your differentiation is conversation quality, not infrastructure. Use proven platforms for telephony and audio transport; invest in turn-taking and language quality. |
| "Need a large LLM for intelligence" | No. Small/fast models with deterministic validation are better for structured calls. |
| "Open-source TTS/STT is cheaper/better" | For Telugu, open-source is worse. Indian vendors (Sarvam/Gnani) are the realistic best. |
| "SIM/eSIM could work" | Not scalable, not appropriate for concurrent calling. |

---

Final note: My information reflects the world as of approximately May 2025\. Before you commit, verify current pricing, provider capabilities (especially Telugu STT/TTS quality and Indian DID availability), and Indian regulatory changes (TRAI AI voice disclosure rules may have evolved in 2026). The architecture and strategy above are designed to be robust to those changes—the key decisions (Indian CPaaS for telephony, managed orchestrator, pluggable STT/TTS/LLM, deterministic extraction layer) do not change if a specific vendor's pricing shifts.

# GPT approch

---

# **1\. Executive verdict**

### **Recommended architecture**

                   ADMIN WEB APP  
                         │  
                  CSV / Excel Upload  
                         │  
                         ▼  
                Campaign Orchestrator  
                         │  
                ┌────────┴────────┐  
                │                 │  
             Queue           Call State DB  
                │                 │  
                ▼                 │  
         Indian Telephony          │  
            Exotel                │  
                │                 │  
        PSTN / Mobile Network      │  
                │                 │  
                ▼                 │  
        WebSocket Audio Stream     │  
                │                 │  
                ▼                 │  
        ┌─────────────────────┐   │  
        │   Voice Runtime     │   │  
        │      Pipecat        │   │  
        └─────────┬───────────┘   │  
                  │  
        ┌─────────┼─────────┐  
        ▼         ▼         ▼  
       STT       LLM       TTS  
        │         │         │  
        │         │         │  
   Deepgram /  Fast LLM   Cartesia /  
   Sarvam      \+ tools    Sarvam  
        │         │         │  
        └─────────┼─────────┘  
                  │  
                  ▼  
            Audio Stream  
                  │  
                  ▼  
               Exotel  
                  │  
                  ▼  
               Person

### **My first-choice stack**

| Layer | Recommendation | Why |
| ----- | ----- | ----- |
| Indian telephony | **Exotel** | Strong India positioning \+ real-time bidirectional streaming |
| Voice runtime | **Pipecat** | Open, modular, provider-independent |
| STT English | **Deepgram Flux/Nova-3** | Excellent real-time voice-agent tooling |
| STT India/Telugu | **Sarvam Saaras** | Much stronger India-language positioning |
| TTS English | **Cartesia Sonic / ElevenLabs Flash** | Excellent real-time quality |
| TTS Telugu | **Sarvam Bulbul V3** | India/Telugu focus |
| LLM | **Fast model first**, large model selectively | Voice does not need maximum reasoning everywhere |
| Database | **PostgreSQL** | Call/campaign/state data is relational |
| Queue | **Redis \+ BullMQ** initially | Simple campaign scheduling/concurrency control |
| Backend | **Python/FastAPI** for voice runtime \+ Node/Next.js if preferred for dashboard | Python ecosystem fits Pipecat |
| Deployment | Docker \+ AWS/GCP/Azure/Indian-region infrastructure where appropriate | predictable scaling |
| Storage | S3-compatible object storage | recordings/transcripts |
| Observability | OpenTelemetry \+ structured call events | voice debugging requires timelines |

Exotel explicitly supports bidirectional WebSocket streaming for conversational bots, and its current documentation describes outbound calls, call status callbacks, recording, and direct WebSocket audio streaming.

Sarvam itself now documents an Exotel \+ Pipecat \+ Sarvam architecture for Indian-language voice agents, including Telugu, which is interesting because it validates the general architectural direction independently of our recommendation.

---

# **2\. First assumption I would challenge**

Your biggest potentially dangerous assumption is:

> "We need an Indian virtual number, therefore we should find an Indian equivalent of Twilio."

Not quite.

The **telephony provider is not the voice AI platform**.

You should deliberately separate:

Telephony  
    ↓  
Audio transport  
    ↓  
Voice orchestration  
    ↓  
STT  
    ↓  
LLM  
    ↓  
TTS

That separation is extremely important.

If you use a platform like Retell/Vapi for everything, you gain speed but lose control.

If you build everything yourself from raw SIP/RTP, you gain control but inherit a ridiculous amount of telecom engineering.

The sweet spot is:

> **Buy the telecom infrastructure. Build the intelligence layer.**

---

# **3\. Indian telephony landscape**

## **Tier 1: Exotel**

[Exotel](https://exotel.com/?utm_source=chatgpt.com)

### **Why I rank it \#1 for this project**

Exotel is unusually well aligned with what you need:

* Indian telephony  
* Indian numbers  
* outbound calls  
* call status  
* recording  
* WebSocket streaming  
* bidirectional audio  
* Voicebot integration  
* SIP  
* enterprise telecom infrastructure

Its Voicebot Applet supports two-way audio over WebSocket, specifically for conversational bots.

It also supports an API flow where your application initiates an outbound call, Exotel connects the call, and the AI bot receives audio through WebSocket.

### **Important technical detail**

Exotel's documented streaming format includes:

* 8 kHz mono PCM  
* WebSocket  
* JSON events  
* media chunks  
* DTMF  
* call start/stop events

It also supports higher sample rates through its streaming configuration.

That is exactly the type of interface we want.

### **Weakness**

Pricing isn't as transparently exposed as Plivo/Twilio.

You'll likely have to deal with:

* KYC  
* business documentation  
* account approval  
* commercial negotiation  
* concurrency/throughput discussions

For a serious production system, that's not necessarily bad.

For a random student wanting to call 500 people tomorrow, it is considerably less amusing.

---

# **4\. Plivo**

[Plivo](https://www.plivo.com/?utm_source=chatgpt.com)

Plivo is technically very interesting.

Current India pricing lists:

* outbound local calls: **₹0.60/min**  
* local number: **₹250/month**  
* browser/SIP: ₹0.34/min  
* local number requirements include **Certificate of Incorporation \+ GST**.

More importantly, Plivo supports:

* bidirectional WebSocket streaming  
* 8 kHz / 16 kHz PCM  
* μ-law  
* noise cancellation  
* status callbacks  
* audio playback back into the call  
* interruption/clear-audio events.

That's excellent for a voice runtime.

### **But**

The documentation's current India number requirements are a problem for a student prototype if you don't have an eligible business entity.

So:

**Technically:** excellent.

**For your India-first prototype:** probably \#2 behind Exotel.

---

# **5\. Twilio**

[Twilio](https://www.twilio.com/?utm_source=chatgpt.com)

Twilio remains one of the strongest programmable telecom platforms globally.

But India changes the equation.

Twilio's current India guidelines explicitly state that outbound calls to Indian PSTN numbers can only be made from **international, non-Indian numbers**.

That directly conflicts with one of your requirements:

> calls should appear legitimate/trustworthy with an Indian number.

Therefore:

### **Twilio is excellent globally.**

### **Twilio is not my recommended primary Indian PSTN layer for this project.**

Its India voice pricing currently lists approximately:

* $0.0496/min to Indian mobiles  
* $0.0699/min to Indian local numbers

and it doesn't offer Indian voice-enabled numbers in the same way you need.

So don't build the architecture around Twilio merely because every tutorial on the internet does.

---

# **6\. Knowlarity**

[Knowlarity](https://www.knowlarity.com/?utm_source=chatgpt.com)

Knowlarity is a serious Indian cloud-telephony player.

Current published pricing includes:

* ₹1,999/month inbound contact center  
* ₹2,999/month inbound \+ outbound contact center  
* ₹1,499 to ₹1,999/agent/month for WebRTC offerings  
* outbound pricing depending on product  
* automatic outbound dialer/OBD offerings.

### **Problem**

It is much more contact-center-oriented than developer-oriented.

For your project, I prefer a platform exposing clean real-time media primitives.

**Verdict:**

Good enterprise telephony option.

Not my first choice for building an experimental voice-AI runtime.

---

# **7\. Ozonetel**

[Ozonetel](https://ozonetel.com/?utm_source=chatgpt.com)

Worth considering for Indian production deployments.

It is especially relevant once you become:

* enterprise-facing  
* contact-center-heavy  
* campaign-heavy  
* compliance-heavy

ElevenLabs currently offers an Ozonetel integration specifically for real-time AI agents handling Indian inbound/outbound calls.

That is a useful signal that Ozonetel is viable for AI voice infrastructure.

But again, for your **developer-controlled prototype**, Exotel is cleaner.

---

# **8\. Indian telecom recommendation**

My ranking:

| Provider | India PSTN | Streaming | AI friendliness | Developer control | Recommendation |
| ----- | ----- | ----- | ----- | ----- | ----- |
| **Exotel** | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **\#1** |
| **Plivo** | ★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | \#2 |
| **Ozonetel** | ★★★★★ | ★★★★ | ★★★★ | ★★★ | \#3 |
| **Knowlarity** | ★★★★★ | ★★★ | ★★★ | ★★★ | \#4 |
| **Twilio** | ★★ for your use case | ★★★★★ | ★★★★★ | ★★★★★ | Avoid as primary India PSTN |
| SIM/eSIM | ★★★ | ★ | ★ | ★ | Don't use |

---

# **9\. Why SIM/eSIM is the wrong architecture**

Don't build this around:

SIM card  
 ↓  
Android phone  
 ↓  
GSM audio  
 ↓  
AI

It sounds clever.

It is actually technical debt wearing a clever hat.

Problems:

* unreliable call control  
* difficult concurrency  
* limited automation  
* carrier restrictions  
* hardware dependency  
* poor observability  
* difficult scaling  
* difficult number management  
* difficult compliance  
* no clean media API

For one experimental call, fine.

For a platform, absolutely not.

---

# **10\. The telecom regulatory problem is bigger than you think**

This deserves special attention.

TRAI's current framework explicitly addresses **auto-dialer and robo-calls**.

The 2025 regulatory changes distinguish:

* promotional voice calls  
* service calls  
* transactional calls  
* auto-dialer/robocalls

and establish specific numbering approaches. TRAI's material says promotional auto-dialer/robocalls are associated with the **140 series**, while service/transactional voice calls are associated with **1600 or another allotted series**.

TRAI also defines a robocall as a call using artificial or prerecorded voice to interactively deliver a voice message without human involvement on the calling side.

This matters enormously.

Your college absence example is **not automatically equivalent to telemarketing**, but you cannot casually assume:

> "It's educational, therefore regulations don't apply."

The actual classification depends on:

* sender  
* purpose  
* recipient relationship  
* consent  
* communication category  
* provider implementation

And TRAI continues to update the framework. A 2026 consultation on further amendments was closed in April 2026\.

### **Even more important**

TRAI is now institutionalizing **AI/ML-based UCC detection** across operators.

So building something that behaves like:

10,000 calls  
\+  
random 10-digit caller ID  
\+  
automatic script  
\+  
no consent

is an excellent way to discover that telecom operators have opinions.

Very strong opinions.

---

# **11\. DLT and consent**

TRAI's current guidance says commercial communications operate through registered headers and distinguishes promotional from service communications.

Therefore, before production outbound campaigns, your architecture needs a **compliance layer**, not just a dialer.

I would create:

Campaign  
 ├── purpose  
 ├── communication\_type  
 ├── consent\_source  
 ├── consent\_timestamp  
 ├── recipient  
 ├── provider  
 ├── caller\_id  
 ├── script\_version  
 ├── recording\_policy  
 └── retention\_policy

This becomes extremely important later.

---

# **12\. Privacy and data protection**

Your system potentially stores:

* phone number  
* name  
* student ID  
* absence reason  
* recordings  
* transcripts  
* summaries  
* timestamps  
* potentially sensitive personal information

India's DPDP Rules were formally notified in November 2025, with phased commencement.

The government's published material describes the framework as operationalized with an 18-month phased compliance timeline.

Therefore, even during the prototype phase, architect for:

* encryption  
* deletion  
* retention periods  
* access controls  
* audit logs  
* consent records  
* data minimization

Don't build a database containing five years of voice recordings because "storage is cheap."

Cheap storage has a remarkable ability to become expensive evidence.

---

# **13\. Real-time voice architecture**

This is where your actual competitive advantage will come from.

A good system isn't:

STT → LLM → TTS

That's the kindergarten diagram.

A serious architecture is:

            TELEPHONY  
                 │  
                 ▼  
          AUDIO INGESTION  
                 │  
                 ▼  
          ┌─────────────┐  
          │ Audio Buffer│  
          └──────┬──────┘  
                 │  
          ┌──────▼──────┐  
          │     VAD     │  
          └──────┬──────┘  
                 │  
       ┌─────────▼─────────┐  
       │ Endpoint / Turn   │  
       │ Detection Engine  │  
       └─────────┬─────────┘  
                 │  
                 ▼  
                STT  
                 │  
                 ▼  
       Partial Transcript  
                 │  
                 ▼  
       Conversation State  
                 │  
          ┌──────▼──────┐  
          │ LLM / Policy│  
          └──────┬──────┘  
                 │  
         Streaming Tokens  
                 │  
                 ▼  
                TTS  
                 │  
           Audio Chunks  
                 │  
          ┌──────▼──────┐  
          │ Audio Queue │  
          └──────┬──────┘  
                 │  
          INTERRUPTION?  
           /           \\  
         YES            NO  
          │              │  
       CLEAR           PLAY  
       AUDIO

This is much closer to what you actually need.

---

# **14\. VAD is not endpoint detection**

This distinction is critical.

### **VAD**

Answers:

> "Is someone speaking?"

### **Endpoint detection**

Answers:

> "Has this person finished their turn?"

Those are not the same problem.

Example:

> "I was absent because... um... my..."

A naive VAD system may decide:

speech stopped  
→ respond

Human conversation does not.

The person is still thinking.

You need a turn detector that understands:

* silence duration  
* partial transcript  
* syntax  
* semantic incompleteness  
* speech prosody  
* conversation context

This is one reason Deepgram's current Flux model is interesting. It is specifically positioned for conversational speech recognition with turn detection and interruption handling.

---

# **15\. Barge-in**

This is probably the **single most visible quality feature**.

Suppose AI says:

> "So your expected return date is..."

User:

> "No, actually..."

The AI must stop.

Immediately.

Not:

> "So your expected return date is... No, actually..."

That is the classic AI phone-bot embarrassment.

Your pipeline should have:

Incoming audio  
      ↓  
VAD  
      ↓  
Barge-in detector  
      ↓  
CLEAR TTS BUFFER  
      ↓  
STOP PLAYBACK  
      ↓  
LISTEN

Plivo exposes explicit mechanisms for clearing buffered audio, and Exotel's voice-streaming architecture is designed for bidirectional conversational media.

---

# **16\. Latency targets**

Don't obsess over raw API latency.

Measure:

> **End of user's speech → first audible AI response**

That's the metric the human experiences.

I'd establish these internal targets:

| Metric | Target |
| ----- | ----- |
| Barge-in stop | \<150 ms |
| STT first partial | \<200 ms |
| End-of-turn detection | \~200–400 ms |
| LLM first token | \<200–400 ms |
| TTS first audio | \<200–300 ms |
| First audible response | **\~400–800 ms** |
| Excellent p95 | **\<1.2 s** |
| \>2 sec | Feels noticeably robotic |

These are engineering targets, not guarantees from vendors.

The biggest trick is **parallelism**.

Don't wait for:

complete STT  
→ complete LLM  
→ complete TTS

Instead:

partial STT  
    ↓  
LLM begins reasoning  
    ↓  
first useful phrase  
    ↓  
TTS begins  
    ↓  
audio starts  
---

# **17\. Streaming is not optional**

TTS should produce:

"Yes, I understand..."

before the complete answer exists.

Then:

"Yes, I understand... you were absent because..."

continues streaming.

ElevenLabs documents WebSocket TTS specifically for real-time text input and says its Flash models have roughly 75 ms model inference latency under representative conditions, while warning that real end-to-end latency will be higher.

Sarvam's Bulbul V3 currently advertises sub-250 ms first-byte streaming and 8 kHz telephony optimization.

---

# **18\. STT recommendation**

## **English**

### **\#1 Deepgram**

[Deepgram](https://deepgram.com/?utm_source=chatgpt.com)

Deepgram's current Flux model is explicitly aimed at conversational voice agents and includes turn detection/interruption handling. Nova-3 is positioned for noisy, multilingual and crosstalk-heavy audio.

Current published prices are roughly:

* Nova-3 monolingual: \~$0.0048/min  
* Nova-3 multilingual: \~$0.0058/min  
* Flux English: \~$0.0065/min  
* Flux multilingual: \~$0.0078/min.

That's extremely cheap relative to the overall voice stack.

### **\#2 Sarvam**

[Sarvam AI](https://www.sarvam.ai/?utm_source=chatgpt.com)

Sarvam is far more interesting once Indian languages enter the picture.

Current Saaras V3 supports 22 Indian languages \+ English and supports:

* real-time streaming  
* code mixing  
* Telugu  
* Indian English  
* word timestamps  
* speaker diarization.

Its published API pricing is ₹30/hour, or roughly **₹0.50/minute**.

### **My strategy**

Don't choose one STT permanently.

Build:

STTProvider  
    ├── DeepgramSTT  
    ├── SarvamSTT  
    └── GoogleSTT

Then benchmark them against **your actual calls**.

---

# **19\. TTS recommendation**

This is more nuanced.

## **English**

### **Cartesia**

[Cartesia](https://www.cartesia.ai/?utm_source=chatgpt.com)

Very strong candidate for low-latency English voice.

### **ElevenLabs**

[ElevenLabs](https://elevenlabs.io/?utm_source=chatgpt.com)

Still one of the strongest choices for expressive English.

Its Flash/Turbo API is currently priced around $0.05/1,000 characters, with multilingual models around $0.10/1,000 characters.

Its WebSocket streaming API is specifically designed for real-time generation.

---

# **20\. Telugu changes the equation**

This is where your roadmap is correct.

Don't assume:

Great English voice  
      ↓  
same model  
      ↓  
Great Telugu

That assumption is wrong.

Telugu needs:

* pronunciation  
* Telugu phonetics  
* regional variation  
* names  
* numbers  
* locations  
* code-switching  
* Tanglish  
* colloquial speech  
* speech rhythm

Sarvam is currently one of the most strategically interesting options here because Bulbul V3 explicitly supports Telugu and Indian-language voice generation, with code-switching and telephony optimization.

Sarvam's current documentation also lists Telugu as a supported STT language and supports mixed-language recognition.

### **Therefore:**

**English:**

Deepgram → fast LLM → Cartesia/ElevenLabs

**Telugu:**

Sarvam STT → fast LLM → Sarvam TTS

And the rest of the orchestration remains unchanged.

That's exactly why the provider abstraction matters.

---

# **21\. LLM strategy**

You do **not** need the largest reasoning model for every sentence.

A phone conversation has a very different computational profile from an agent doing software engineering.

Most turns are:

"Yes."  
"Okay."  
"I understand."  
"What date?"  
"Tuesday."  
"Can you repeat that?"

Using an enormous reasoning model for that is like hiring a constitutional lawyer to decide whether you want tea.

### **Use three layers**

                Voice Agent  
                     │  
          ┌──────────┼──────────┐  
          │          │          │  
      Deterministic  Fast LLM   Heavy LLM  
         Logic

### **Deterministic**

Use code for:

* call state  
* retries  
* validation  
* date parsing  
* phone numbers  
* campaign scheduling  
* termination conditions  
* structured extraction  
* compliance  
* tool permissions

### **Fast LLM**

Use for:

* normal conversation  
* paraphrasing  
* intent recognition  
* contextual responses  
* natural follow-ups

### **Strong LLM**

Use only when needed:

* ambiguous reasoning  
* complicated user requests  
* knowledge-intensive tasks  
* difficult tool planning

---

# **22\. Native speech-to-speech vs cascaded pipeline**

This is an important decision.

There are two architectures.

### **Cascaded**

Audio  
 ↓  
STT  
 ↓  
LLM  
 ↓  
TTS  
 ↓  
Audio

### **Native realtime model**

Audio  
 ↓  
Realtime multimodal model  
 ↓  
Audio

Google's Gemini Live API currently supports bidirectional real-time audio with native audio output over WebSockets.

Google's current Gemini pricing also exposes native-audio realtime models.

OpenAI also has a Realtime API for real-time audio interaction.

### **Native speech-to-speech advantage**

Potentially:

* lower latency  
* more natural turn-taking  
* better prosody  
* less pipeline overhead

### **Cascaded advantage**

You can independently control:

* STT  
* turn detection  
* LLM  
* TTS  
* transcript  
* structured extraction  
* language  
* provider  
* debugging

### **For your project**

I choose **cascaded first**.

Why?

Because your project isn't merely:

> "Make a cool voice demo."

It's:

> "Build an AI calling platform."

You need observability.

---

# **23\. Pipecat is the right abstraction**

[Pipecat](https://github.com/pipecat-ai/pipecat?utm_source=chatgpt.com)

Pipecat already supports real-time voice pipelines and WebSocket telephony transports.

Its architecture allows:

Telephony  
    ↓  
Transport  
    ↓  
VAD  
    ↓  
STT  
    ↓  
LLM  
    ↓  
TTS

with interchangeable providers.

Its current quickstart uses:

* Deepgram  
* OpenAI  
* Cartesia

and reports sub-second full-round-trip behavior in its sample architecture.

More importantly, Sarvam has an existing Pipecat integration and Exotel example.

That combination is unusually attractive for your India → Telugu roadmap.

---

# **24\. Why I don't recommend Vapi as the core**

[Vapi](https://vapi.ai/?utm_source=chatgpt.com)

Vapi is genuinely useful.

Current pricing is approximately:

**$0.05/minute platform fee**

plus provider costs passed through at cost.

That's attractive.

But you're trying to learn/build the underlying architecture.

Vapi gives you:

telephony  
\+  
STT  
\+  
LLM  
\+  
TTS  
\+  
orchestration

conveniently.

The downside is that your actual differentiator becomes:

> "We configured Vapi well."

That's not enough for the serious platform you're describing.

### **Use Vapi for:**

* rapid experiments  
* benchmarking  
* reference implementation  
* proving product-market fit

### **Don't make it your architectural foundation.**

---

# **25\. Retell is stronger, but same strategic problem**

[Retell AI](https://www.retellai.com/?utm_source=chatgpt.com)

Retell is probably one of the best turnkey choices for high-quality voice agents.

Current pricing is approximately:

**$0.07–$0.31/minute**

depending on configuration. It includes a voice runtime, analytics, APIs, simulation, and 20 concurrent calls on the pay-as-you-go plan.

It supports a wide range of models and voices, including GPT, Claude, Gemini, Cartesia and ElevenLabs.

### **This is actually a very good product.**

But:

**You are trying to build the underlying product.**

So I'd use Retell as a **benchmark**.

Build the same conversation on:

Retell  
vs  
your Pipecat stack

Then measure:

* response latency  
* barge-in  
* WER  
* completion rate  
* human rating  
* cost

If your system can't beat it, you learn exactly where you're weak.

That's far more useful than blindly choosing one.

---

# **26\. Competitive landscape**

The serious ecosystem currently includes:

### **Infrastructure/platform**

* [Exotel](https://exotel.com/?utm_source=chatgpt.com)  
* [Plivo](https://www.plivo.com/?utm_source=chatgpt.com)  
* [Twilio](https://www.twilio.com/?utm_source=chatgpt.com)  
* [Ozonetel](https://ozonetel.com/?utm_source=chatgpt.com)  
* [Knowlarity](https://www.knowlarity.com/?utm_source=chatgpt.com)

### **Voice AI platforms**

* [Retell AI](https://www.retellai.com/?utm_source=chatgpt.com)  
* [Vapi](https://vapi.ai/?utm_source=chatgpt.com)  
* [ElevenLabs](https://elevenlabs.io/?utm_source=chatgpt.com)  
* [LiveKit](https://livekit.io/?utm_source=chatgpt.com)  
* [Pipecat](https://github.com/pipecat-ai/pipecat?utm_source=chatgpt.com)

### **India-focused AI**

* [Sarvam AI](https://www.sarvam.ai/?utm_source=chatgpt.com)  
* Haptik  
* Yellow.ai  
* Skit.ai  
* Kore.ai  
* Ozonetel

The strongest Indian enterprise players increasingly differentiate on **telephony reliability, compliance, multilingual support, and concurrency**, not merely the LLM. This is also reflected in current Indian enterprise voice-AI positioning from Exotel and Haptik.

---

# **27\. Cost model**

Let's use a realistic prototype assumption:

### **Average call**

**5 minutes**

Then:

| Calls | Minutes |
| ----- | ----- |
| 100 | 500 |
| 1,000 | 5,000 |
| 10,000 | 50,000 |
| 100,000 | 500,000 |

Now approximate the AI layer.

### **STT**

Sarvam:

₹30/hour

≈ **₹0.50/minute**.

Deepgram is dramatically cheaper on published raw STT pricing, but the correct choice depends on accuracy and Indian-language performance.

### **TTS**

Sarvam Bulbul V3:

₹30/10,000 characters.

A five-minute conversation might produce around 600–1,000 assistant words depending on speaking behavior, so TTS cost can remain relatively low.

### **LLM**

For a normal short phone conversation, the LLM is unlikely to dominate cost if you use an efficient model and aggressively manage context.

### **Infrastructure**

At prototype scale:

Probably negligible compared with telecom \+ AI usage.

At 100k concurrent-scale minutes, infrastructure and observability become real costs.

---

# **28\. Practical prototype cost estimate**

For an India-first cascaded system, I would initially budget approximately:

### **₹1.5–₹3.5 per connected minute**

for the AI \+ telecom stack, depending heavily on:

* telephony provider  
* STT  
* TTS  
* LLM  
* call duration  
* recording  
* infrastructure

This is an **engineering estimate**, not a vendor quote.

At 5-minute average calls:

| Calls/month | Minutes | Approx operating cost |
| ----- | ----- | ----- |
| 100 | 500 | ₹750–₹1,750 |
| 1,000 | 5,000 | ₹7,500–₹17,500 |
| 10,000 | 50,000 | ₹75k–₹1.75L |
| 100,000 | 500,000 | ₹7.5L–₹17.5L |

Then optimize.

The raw numbers will change substantially once you negotiate Indian telecom pricing and choose exact model combinations.

---

# **29\. Why your average call duration matters enormously**

If you allow an AI agent to talk forever:

"Okay..."  
"Right..."  
"Yes..."  
"So..."  
"Let me understand..."

you burn money.

Your agent should have:

* objective  
* state  
* maximum duration  
* maximum turns  
* completion criteria  
* early termination  
* voicemail detection  
* silence timeout

For the absence example:

1\. Identify student  
2\. Confirm identity  
3\. Ask absence reason  
4\. Ask expected return  
5\. Ask whether support is required  
6\. Confirm  
7\. End

That's it.

Don't let the model discover philosophy halfway through the call.

---

# **30\. Campaign architecture**

The campaign system should not directly call people from the web request.

Use a queue.

Admin  
 │  
 ▼  
Campaign  
 │  
 ▼  
Contacts  
 │  
 ▼  
Redis Queue  
 │  
 ├── Worker 1  
 ├── Worker 2  
 ├── Worker 3  
 ├── Worker 4  
 └── Worker N

Each worker:

reserve contact  
      ↓  
check compliance  
      ↓  
initiate call  
      ↓  
track call SID  
      ↓  
start voice session  
      ↓  
store events  
      ↓  
finalize result  
---

# **31\. Call state machine**

Don't let the LLM own call state.

Use deterministic state.

CREATED  
   ↓  
QUEUED  
   ↓  
DIALING  
   ↓  
RINGING  
   ↓  
ANSWERED  
   ↓  
AI\_ACTIVE  
   ├── HUMAN\_TRANSFER  
   ├── COMPLETED  
   ├── USER\_HANGUP  
   ├── AI\_HANGUP  
   ├── TIMEOUT  
   └── ERROR

DIALING  
   ├── BUSY  
   ├── NO\_ANSWER  
   └── FAILED

This gives you reliable reporting.

---

# **32\. Structured extraction**

Never depend on the final LLM summary to reconstruct everything.

Maintain structured state during the conversation.

Example:

{  
  "student\_id": "STU1024",  
  "answered": true,  
  "absence\_reason": "fever",  
  "expected\_return\_date": "2026-08-15",  
  "needs\_support": false,  
  "confidence": 0.91,  
  "call\_duration\_seconds": 182  
}

The LLM can propose values.

Your application validates them.

For example:

LLM says:  
"return date \= next Friday"

        ↓

deterministic date resolver

        ↓

2026-08-21

This is far safer.

---

# **33\. Don't let the LLM control everything**

The architecture should be:

LLM \= intelligence  
Code \= authority

The LLM can say:

> "The student says they will return Monday."

Your code determines:

* what Monday means  
* whether it is a valid date  
* whether it falls within allowed range  
* whether the field is complete

This principle becomes increasingly important in high-stakes voice systems.

Recent research into voice agents for Indian populations is also moving toward combining LLMs with deterministic validation and flow control rather than allowing the model to control the entire process.

---

# **34\. Concurrency**

Your system should have two separate concurrency limits.

### **Telephony concurrency**

How many calls can Exotel place?

### **AI concurrency**

How many voice sessions can your infrastructure process?

They are not the same.

At:

### **1 call**

Nothing interesting happens.

### **10 calls**

You discover bugs.

### **100 calls**

You discover architecture.

### **1,000 calls**

You discover telecom.

At 1,000 concurrent calls, you need:

* multiple workers  
* connection pools  
* queue partitioning  
* autoscaling  
* provider CPS management  
* Redis  
* backpressure  
* WebSocket lifecycle management  
* CPU/memory monitoring  
* model rate-limit management  
* provider failover

---

# **35\. Don't scale the LLM blindly**

Imagine:

1,000 calls  
×  
one LLM request every 5 seconds

You suddenly have massive request throughput.

Instead:

1000 sessions  
     │  
     ▼  
fast model  
     │  
     ├── most requests  
     │  
     └── heavy model only when necessary

This dramatically reduces cost and rate-limit pressure.

---

# **36\. Database**

Use PostgreSQL.

Not MongoDB for this core data.

Your entities naturally look like:

organizations  
campaigns  
contacts  
calls  
call\_events  
conversation\_turns  
transcripts  
extractions  
recordings  
providers  
agents  
agent\_versions

Example:

campaign  
   │  
   ├── contacts  
   │       │  
   │       └── calls  
   │              │  
   │              ├── events  
   │              ├── transcript  
   │              ├── extraction  
   │              └── recording

This is relational data.

Postgres wins.

---

# **37\. Frontend**

Your initial dashboard can be:

Next.js  
\+  
TypeScript  
\+  
Tailwind  
\+  
PostgreSQL

Pages:

/dashboard

/campaigns  
/campaigns/:id

/campaigns/:id/contacts

/calls/:id

/analytics

/settings

Campaign page:

Campaign: Student Absence

Total:       1,000  
Answered:      721  
No Answer:     183  
Busy:           61  
Failed:         35

Avg duration: 2m 41s

Completion: 78.4%

Then export:

CSV  
XLSX  
JSON  
---

# **38\. The voice session object**

Every active call needs an isolated session.

VoiceSession(  
    call\_id,  
    campaign\_id,  
    contact\_id,  
    language,  
    state,  
    conversation\_history,  
    extracted\_fields,  
    audio\_buffers,  
    provider\_metadata  
)

Never put active call state into global process memory.

Because:

Call A  
Call B  
Call C

must never accidentally share:

"Okay, your fever..."

with another person.

That would be a spectacularly bad demo.

---

# **39\. English → Telugu migration**

The beautiful part is that most of your system doesn't change.

### **Doesn't change**

Campaign engine  
Call state  
Database  
Dashboard  
Queue  
Telephony  
Analytics  
Structured extraction  
Tool system  
Observability

### **Changes**

STT  
TTS  
Language detection  
Prompting  
Pronunciation  
Evaluation dataset  
Turn-taking tuning  
Normalization  
Names  
Numbers

So your architecture should have:

LanguageProfile(  
    language="en-IN",  
    stt\_provider="deepgram",  
    tts\_provider="cartesia",  
    normalization="english"  
)

and:

LanguageProfile(  
    language="te-IN",  
    stt\_provider="sarvam",  
    tts\_provider="sarvam",  
    normalization="telugu"  
)

Same agent.

Different speech stack.

---

# **40\. Telugu should be tested separately**

Build a Telugu evaluation dataset.

Not:

> "It sounds good to me."

That's worthless.

Create \~500–2,000 representative utterances:

"నాకు జ్వరం వచ్చింది"

"నిన్న కాలేజీకి రాలేకపోయాను"

"రేపు వస్తాను"

"నాకు ఖచ్చితంగా తెలియదు"

"అది సోమవారం అనుకుంటా"

"ఫోన్ సరిగ్గా వినిపించడం లేదు"

Then add:

### **Code-switching**

"నాకు fever ఉంది"

### **Tanglish**

"Naku fever vachindi"

### **Names**

"నా పేరు శ్రీనివాస్"

### **Numbers**

"రెండు రోజులు"  
"twenty second"  
"22nd"

### **Regional variation**

Telangana Telugu ≠ Andhra Telugu ≠ formal Telugu.

That's where your eventual moat could actually emerge.

---

# **41\. Your real competitive advantage**

It will **not** be:

> "We use GPT."

Everyone uses GPT.

It will not be:

> "We use AI."

Congratulations, the year is 2026\.

Your moat could become:

Indian telephony  
\+  
low-latency orchestration  
\+  
excellent interruption handling  
\+  
Indian accent STT  
\+  
Telugu conversational data  
\+  
structured workflows  
\+  
reliability  
\+  
evaluation infrastructure

Especially:

### **Your evaluation dataset.**

If you collect thousands of real-world anonymized conversational examples and systematically measure:

* WER  
* latency  
* interruption success  
* turn errors  
* hallucination rate  
* extraction accuracy  
* task completion  
* human naturalness rating

you start developing something genuinely difficult to copy.

---

# **42\. Voice quality benchmark**

Build a score out of 100\.

### **Naturalness: 20**

Does it sound human?

### **Latency: 20**

Does it respond quickly?

### **Turn-taking: 15**

Does it know when to speak?

### **Barge-in: 15**

Does it stop immediately?

### **STT accuracy: 10**

Does it understand correctly?

### **Task completion: 10**

Did it accomplish the goal?

### **Extraction accuracy: 5**

Did it record structured data correctly?

### **Recovery: 5**

Can it recover from misunderstandings?

Then:

Human baseline  
Retell  
Vapi  
Your system

Run the same conversations.

Now you're engineering instead of vibes-based benchmarking.

---

# **43\. Biggest project risks**

Here is where I'd be most worried.

## **Risk \#1: Robotic turn-taking**

**Probability: very high**

Most voice agents fail here before they fail at intelligence.

---

## **Risk \#2: Latency**

**Probability: high**

A brilliant model with 2-second response latency feels stupid.

---

## **Risk \#3: Telecom restrictions**

**Probability: high**

Especially outbound campaigns.

---

## **Risk \#4: Number provisioning**

**Probability: medium-high**

A student prototype may not have all documentation required for production numbers.

---

## **Risk \#5: Telugu quality**

**Probability: high**

English performance tells you almost nothing about Telugu conversational quality.

---

## **Risk \#6: Provider lock-in**

**Probability: very high**

If your business logic is embedded inside Retell/Vapi/etc., migration becomes painful.

---

## **Risk \#7: LLM hallucinations**

**Probability: high**

Especially when the agent is asked something outside its allowed scope.

---

## **Risk \#8: Bad extraction**

**Probability: medium**

The conversation may sound perfect while the database gets the wrong date.

That's worse than an obvious failure because it silently corrupts your results.

---

## **Risk \#9: Cost explosion**

**Probability: medium**

Especially if calls become long and model selection is careless.

---

# **44\. My final provider strategy**

## **Telephony**

### **Primary**

**Exotel**

### **Secondary**

**Plivo**

### **Enterprise alternative**

**Ozonetel**

### **Benchmark/global**

**Twilio**

---

# **45\. STT**

### **English**

**Deepgram Flux / Nova-3**

### **Indian English / Telugu**

**Sarvam Saaras**

### **Backup**

Google Speech / another provider

Don't hard-code one vendor.

---

# **46\. TTS**

### **English**

Test:

1. Cartesia  
2. ElevenLabs Flash  
3. OpenAI  
4. Google

### **Telugu**

Start with:

**Sarvam Bulbul V3**

Sarvam currently advertises 35+ voices across 11 Indian languages, including Telugu, with streaming and telephony-oriented output.

---

# **47\. LLM**

### **Default**

Fast model.

### **Heavy reasoning**

Only when required.

### **Architecture**

LLM interface  
    │  
    ├── OpenAI  
    ├── Gemini  
    ├── Anthropic  
    └── local model

Don't let the LLM provider become your platform.

---

# **48\. Voice orchestration**

### **Pipecat**

This is my strongest architectural recommendation.

Not because it is trendy.

Because it gives you the thing you actually need:

> control over the pipeline without having to implement the entire media-processing stack from scratch.

Pipecat explicitly supports WebSocket telephony transports and provider components.

---

# **49\. Alternative architecture**

There is another viable route:

Exotel  
   ↓  
ElevenLabs Agents  
   ↓  
LLM \+ TTS \+ STT \+ orchestration

ElevenLabs now has direct Exotel integration using WebSocket and positions it specifically for Indian contact centers.

This could give you a much faster proof of concept.

### **But I would use it as:**

**Benchmark / rapid MVP**

rather than:

**core architecture**

because you want control over the speech stack and Telugu migration.

---

# **50\. Recommended development roadmap**

## **Phase 0: Telephony proof**

**1–3 days**

Goal:

Browser/API  
 ↓  
Exotel  
 ↓  
Indian phone

Verify:

* number  
* KYC  
* outbound call  
* caller ID  
* call status  
* WebSocket  
* audio

Do not touch AI yet.

---

## **Phase 1: Audio pipeline**

**3–5 days**

Build:

Exotel  
 ↓  
WebSocket  
 ↓  
Pipecat  
 ↓  
VAD  
 ↓  
STT  
 ↓  
TTS  
 ↓  
Exotel

Goal:

> caller speaks → AI repeats/answers

---

## **Phase 2: Real conversation**

**5–10 days**

Add:

* LLM  
* streaming  
* context  
* interruption  
* endpoint detection  
* silence handling

---

## **Phase 3: Structured workflow**

**3–7 days**

Add:

Campaign  
 ↓  
Contact  
 ↓  
Call  
 ↓  
Extraction  
 ↓  
Result  
---

## **Phase 4: Dashboard**

**5–10 days**

Build:

* upload  
* contact preview  
* campaign start  
* live status  
* results  
* transcript  
* summary  
* export

---

## **Phase 5: Evaluation**

**1–2 weeks**

Create:

* latency benchmarks  
* WER benchmarks  
* interruption tests  
* extraction tests  
* human rating  
* failure dataset

This phase is more important than adding another 15 features.

---

## **Phase 6: Telugu**

Only after English is genuinely good.

Then:

Sarvam STT  
\+  
Sarvam TTS  
\+  
same runtime

Add:

* Telugu  
* Tanglish  
* code-switching  
* pronunciation dictionary  
* regional dialect tests

Sarvam's current speech stack already exposes Telugu, code-mixing, streaming and pronunciation-related capabilities, making it a strong candidate for this phase.

---

# **51\. The architecture I would actually build**

                   ┌──────────────────────┐  
                    │       Next.js        │  
                    │     Admin Dashboard  │  
                    └──────────┬───────────┘  
                               │  
                         REST / WebSocket  
                               │  
                    ┌──────────▼───────────┐  
                    │      FastAPI         │  
                    │   Control Plane      │  
                    └──────────┬───────────┘  
                               │  
             ┌─────────────────┼─────────────────┐  
             │                 │                 │  
             ▼                 ▼                 ▼  
         PostgreSQL          Redis            Object Store  
             │                 │                 │  
             │                 ▼                 │  
             │          Campaign Workers         │  
             │                 │                 │  
             │                 ▼                 │  
             │              Exotel               │  
             │                 │                 │  
             │          PSTN / Mobile            │  
             │                 │                 │  
             │                 ▼                 │  
             │         WebSocket Audio           │  
             │                 │                 │  
             │          ┌──────▼──────┐          │  
             │          │   Pipecat   │          │  
             │          │ Voice Engine│          │  
             │          └──────┬──────┘          │  
             │                 │                 │  
             │       ┌─────────┼─────────┐       │  
             │       ▼         ▼         ▼       │  
             │     Deepgram   LLM      Sarvam    │  
             │       │         │         │       │  
             │       └─────────┼─────────┘       │  
             │                 │                 │  
             │                 ▼                 │  
             │               TTS                 │  
             │                 │                 │  
             └─────────────────┼─────────────────┘  
                               │  
                               ▼  
                         Call Result  
---

# **52\. One important change to your original plan**

You described the system as domain-independent from the beginning.

I would **not** do that.

Build the runtime generically.

But build the **first agent around one narrow workflow**.

For example:

College absence verification

Why?

Because voice quality is difficult enough.

You don't need:

absence  
sales  
customer support  
appointments  
collections  
surveys  
lead qualification

simultaneously.

The platform should be generic.

The first agent should not be.

---

# **53\. The first MVP should therefore be**

### **"AI Student Absence Calling Agent"**

Input:

student\_id,name,phone  
ST001,Rahul,+91...  
ST002,Priya,+91...

Agent:

Hello Rahul, this is an automated call from XYZ College.

We noticed that you were absent today.

Could you tell me the reason?

Then:

Reason?  
Expected return?  
Need assistance?

Then:

Thank you. We have recorded that information.  
Have a good day.

Output:

student\_id  
name  
phone  
call\_status  
absence\_reason  
expected\_return  
support\_required  
duration  
confidence  
transcript  
summary

That gives you a complete vertical slice of the entire platform.

---

# **54\. Final stack decision**

If we were starting development **today**, my stack would be:

Frontend  
Next.js \+ TypeScript \+ Tailwind

Control API  
FastAPI

Voice Runtime  
Pipecat

Telephony  
Exotel

Queue  
Redis \+ BullMQ / Celery

Database  
PostgreSQL

Storage  
S3-compatible

English STT  
Deepgram Flux

English TTS  
Cartesia / ElevenLabs Flash

Indian/Telugu STT  
Sarvam Saaras

Telugu TTS  
Sarvam Bulbul V3

LLM  
Fast GPT/Gemini model  
\+  
strong model fallback

Observability  
OpenTelemetry

Deployment  
Docker  
\+  
AWS/GCP/Azure

CI/CD  
GitHub Actions

The most important architectural rule:

> **No provider-specific business logic inside the agent.**

Instead:

VoiceRuntime  
    ↓  
Provider Interfaces  
    ├── TelephonyProvider  
    ├── STTProvider  
    ├── TTSProvider  
    ├── LLMProvider  
    └── StorageProvider

That one decision will save you enormous pain when you move from English to Telugu.

---

# **55\. Bottom line**

Your original instinct to prioritize **conversation quality over simply making calls** is correct. The architecture should therefore optimize the things humans actually notice: response latency, turn-taking, barge-in, speech recognition, pacing and recovery.

But I would change the implementation philosophy:

### **Don't build:**

> "A Vapi/Retell clone."

### **Build:**

> **An India-first voice runtime that happens to use Exotel for telecom.**

The strongest initial combination is:

**Exotel \+ Pipecat \+ Deepgram \+ fast LLM \+ Cartesia/ElevenLabs**

and then:

**Exotel \+ Pipecat \+ Sarvam Saaras \+ fast LLM \+ Sarvam Bulbul V3**

for Telugu.

The biggest technical moat is not the LLM. It is the **real-time orchestration \+ evaluation \+ Indian-language speech quality \+ telecom reliability**.

And the biggest non-technical risk is not model quality. It is **Indian outbound-call compliance and number provisioning**. TRAI's current framework explicitly regulates auto-dialer/robocall behavior, commercial communication categories and numbering, while its 2026 work is increasing automated UCC detection.

So I would **not start by building the dashboard**.

I would start with the hardest proof:

Exotel Indian number  
        ↓  
real mobile call  
        ↓  
bidirectional audio  
        ↓  
Pipecat  
        ↓  
VAD \+ turn detection  
        ↓  
STT  
        ↓  
fast LLM  
        ↓  
streaming TTS  
        ↓  
barge-in  
        ↓  
human-quality conversation

If that loop feels genuinely good, everything else is engineering.

If that loop feels robotic, the dashboard is just a beautifully designed way to display failure.

# gemini 3.6 flash

## Critical Assumption Audit & Technical Reality Check

Before building a voice AI platform for the Indian telecommunications landscape, we must address three flawed architectural assumptions commonly held by engineering teams:

### Assumption 1: SIM Cards or Mobile GSM Gateways Can Scale Outbound AI Calling

* The Flaw: Utilizing physical SIM cards, eSIMs, or local GSM gateways (such as GoIP boxes) to route AI calls is unsuitable for production systems.  
*   
* The Reality: Commercial SIMs operate under strict Indian TRAI/DoT Fair Usage Policies (FUP). Automated calling over regular consumer SIMs triggers instant network-level fraud detection, leading to IMEI/SIM blocking and phone number blacklisting. Furthermore, local SIM gateways offer zero native WebSockets, poor audio quality (lacking direct digital PCM capture), and no scalable concurrency. You must use enterprise-grade Cloud Telephony or Programmable SIP Trunking.  
* 

### Assumption 2: An English Voice-AI Pipeline Can Effortlessly Adapt to Indian Languages

* The Flaw: Assuming that swapping an English STT/TTS engine with a Telugu STT/TTS engine on an existing pipeline will retain fluid, low-latency conversation quality.  
*   
* The Reality: Standard global models (OpenAI, Deepgram, ElevenLabs) degrade significantly on Indian telephonic audio (8kHz bandpass filtered), Indian proper nouns, regional dialects, and code-switching (Tanglish / Telugu-English). Indic languages require specific acoustic modeling, custom VAD tuning for longer conversational pauses, higher token density handling in LLMs, and localized TTS engines (e.g., Sarvam AI).  
* 

### Assumption 3: Turn-Based AI Architecture ("Listen $\\rightarrow$ Process $\\rightarrow$ Speak") can feel Human

* The Flaw: Relying on standard sequential API calls where the system waits for audio to complete before processing.  
*   
* The Reality: Human phone conversations operate on continuous, full-duplex feedback. A user says "uh-huh" or pauses to think. Sequential pipelines cause high perceived latency ($\>1.5\\text{s}$) or aggressive, unnatural interruptions. Achieving human conversation requires a full-duplex, streaming-first pipeline using bidirectional WebSockets or WebRTC/SIP, continuous energy/semantic VAD, and real-time audio frame manipulation.  
* 

## 1\. Telephony & Indian Telecom Options

To make legitimate outbound calls in India with proper Caller ID, low latency, and continuous real-time audio access, your system architecture must integrate directly with Indian Telecom Service Providers (TSPs) or compliant international CPaaS platforms.

### Architecture Options Comparison

| Option | Inbound/Outbound Audio Path | Indian CLI Support | Regulatory Compliance | Concurrency Capabilities | Real-Time Audio Streaming |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Indian Cloud Telephony (Exotel, Tata Tele, MyOperator) | HTTP Webhooks / WebSockets | High (Fixed Local / 140 / 160 Series) | High (Full TRAI/DLT Compliance) | High (Scalable via virtual channels) | Excellent (Exotel Voicebot Applet / Audio Streaming over WSS) |
| Global CPaaS with India POP (Plivo, Twilio India) | SIP Trunking / Bidirectional WSS | High (Must complete Indian Entity KYC) | High (Enforces TRAI DLT scrubbing) | Unlimited (Elastic SIP / Channel scaling) | Excellent (Direct WSS / Native LiveKit & Pipecat adapters) |
| Direct SIP Trunking (Tata Comms, Airtel Enterprise) | Pure SIP/RTP Protocol | Enterprise Direct CLI | Enterprise Legal Agreement Required | Very High (Dedicated Bandwidth E1/PRI/IP-SIP) | Raw RTP Audio (Requires custom SBC/RTP Media Gateway) |
| GSM Gateways / SIM Boxes | Analog/GSM to SIP | Single Mobile Number | Illegal / High Risk (Banned by TRAI for commercial transit) | Very Low (Limited by hardware ports & SIM locks) | Poor (A/D conversion distortion, high jitter) |

### Regulatory, KYC, and DLT Requirements in India

1. DLT (Distributed Ledger Technology) Registration: Every business placing commercial or automated voice calls in India must register as a Principal Entity on a telecom DLT portal (Jio, Airtel, Vodafone Idea, or Tata).  
2.   
3. 140 vs. 160 Number Series (TRAI Regulations):  
4. 

   * 140 Series: Mandatory prefix (+91-140-XXXXXXX) for Promotional/Telemarketing calls. Bypasses non-DND (Do Not Disturb) numbers only; blocked on DND numbers.  
   *   
   * 160 Series: Designated prefix (+91-160-XXXXXXX or 1600\) reserved exclusively for Service and Transactional calls (e.g., student attendance alerts, BFSI reminders, OTPs). Calls can reach DND-registered numbers provided explicit prior consent exists.  
   *   
5. KYC Documents Required for Provisioning: Certificate of Incorporation, GST Registration, Company PAN, Authorized Signatory LOA (Letter of Authorization), and proof of physical office in India.  
6. 

### Telecom Recommendation for Prototype vs. Production

* For Prototype: Use Plivo or Exotel. Both offer compliant Indian virtual numbers with direct Bidirectional WebSocket Audio Streaming (PCM 8kHz mono, Slinc/Base64). This bypasses the complexity of building custom Session Border Controllers (SBC) while keeping latency low ($\<100\\text{ms}$ telephonic transport).  
*   
* For High-Scale Production: Transition to Direct Enterprise Cloud SIP Trunking (Plivo / Tata Communications) connected directly to a self-hosted media server cluster (LiveKit SIP ingress/egress).  
* 

## 2\. Real-Time Voice Pipeline Architecture

To achieve a natural human-like voice conversation, you must avoid coarse turn-taking. The diagram below illustrates the continuous, event-driven streaming pipeline:

                         FULL-DUPLEX REAL-TIME AUDIO PIPELINE  
                            
Caller Phone  \<---\> Telephony Provider \<---\> WebSocket Bridge (PCM 8kHz Audio Streams)  
                        (Plivo / Exotel)               |  
                                                      v  
  \+-----------------------------------------------------------------------------------+  
  |                              AGENT ORCHESTRATION ENGINE                            |  
  |                                                                                   |  
  |  \+---------------------+      \+---------------------+      \+-------------------+  |  
  |  |  VAD & Endpointing  | \---\> |   Streaming STT     | \---\> | Dialogue Manager  |  |  
  |  | (Silero / TenSOFM)  |      |  (Deepgram / Sarvam)|      | & Tool Execution  |  |  
  |  \+---------------------+      \+---------------------+      \+-------------------+  |  
  |             |                                                        |            |  
  |             v Interrupt Event (Barge-In)                             v Text Stream|  
  |  \+--------------------------------------------------+      \+-------------------+  |  
  |  |      Audio Frame Buffer & Output Controller      | \<--- |   Streaming TTS   |  |  
  |  |      (Clears queue instantly upon barge-in)       |      |(Cartesia / Sarvam)|  |  
  |  \+--------------------------------------------------+      \+-------------------+  |  
  \+-----------------------------------------------------------------------------------+

### Key Architectural Components

1. Telephony Bridge & Audio Transcoder: Converts telephony audio streams (G.711 $\\mu$-law/A-law, 8kHz PCM) into standard WebSockets PCM chunks (typically 20ms–100ms frames).  
2.   
3. Dual-Layer Voice Activity Detection (VAD):  
4. 

   * Local Energy/Acoustic VAD: High-speed (e.g., Silero VAD, running in $\<10\\text{ms}$) running directly on incoming audio frames to detect instant vocal onset or interruption.  
   *   
   * Semantic/LLM VAD: Secondary analysis to determine if the user has reached a pause (thinking) versus a completed utterance (turn boundary).  
   *   
5. Streaming Speech-to-Text (STT): Maintains an open WebSocket connection, converting incoming chunks into interim transcriptions with sub-word timestamps and final transcriptions.  
6.   
7. Conversation Orchestration State Machine: Manages state transitions, session variables (student data, call status), tool execution, and prompt injection.  
8.   
9. Ultra-Low TTFT (Time-To-First-Token) LLM: Receives text context and streams output tokens immediately.  
10.   
11. Streaming Text-to-Speech (TTS): Processes token chunks, generates audio bytes (24kHz or 16kHz), and downsamples them to telephonic 8kHz PCM.  
12.   
13. Interruption-Aware Audio Playback Buffer: Holds audio frames being sent back over the WebSocket. If the VAD flags a barge-in event, it fires a clear\_buffer signal to instantly purge unplayed audio.  
14. 

## 3\. Latency Budget & Optimization Strategies

Human speech turn-taking typically occurs within a 200ms to 500ms window. In telephonic voice AI, a total round-trip response time exceeding 800ms creates an unnatural "walkie-talkie" cadence.

### System Latency Budget

$$\\text{Latency}\_{\\text{Total}} \= T\_{\\text{VAD}} \+ T\_{\\text{STT}} \+ T\_{\\text{LLM\\\_TTFT}} \+ T\_{\\text{TTS\\\_TTFB}} \+ T\_{\\text{Network\\\_Jitter}}$$

| Component | Target Latency (Optimal) | Realistic Latency (Standard Setup) | Optimization Strategy |
| :---- | :---- | :---- | :---- |
| VAD / Silence Detection | $100\\text{ms} \- 200\\text{ms}$ | $500\\text{ms}$ | Use sub-frame acoustic VAD \+ speculative execution instead of waiting for long trailing silence. |
| Streaming STT | $100\\text{ms} \- 150\\text{ms}$ | $300\\text{ms}$ | Use WebSocket streaming models (e.g., Deepgram Nova-2) with interim transcription enabled. |
| LLM Processing (TTFT) | $150\\text{ms} \- 250\\text{ms}$ | $600\\text{ms}$ | Deploy fast inference engines (Groq, vLLM) using small, tuned instruction models (Llama-3.1-8B, Claude 3.5 Haiku, Gemini 2.0 Flash). |
| TTS Processing (TTFB) | $100\\text{ms} \- 180\\text{ms}$ | $400\\text{ms}$ | Stream audio on sentence fragments or first 3–5 tokens (e.g., Cartesia Sonic, ElevenLabs Turbo v2.5). |
| Network & Telephony Buffer | $50\\text{ms} \- 80\\text{ms}$ | $150\\text{ms}$ | Pin application deployment region to target market (e.g., AWS ap-south-1 Mumbai). |
| Total Round-Trip Latency | $500\\text{ms} \- 860\\text{ms}$ | $1950\\text{ms}+$ | Sub-800ms feels conversational; $\>1.5\\text{s}$ breaks natural flow. |

### Latency Reduction Techniques

* Speculative LLM Execution: Start processing the LLM request when STT interim results reach high confidence ($\>90\\%$), even before final VAD endpointing fires. If the user continues speaking, cancel the speculative request.  
*   
* Early First-Sentence TTS Dispatch: Do not wait for the LLM to complete its entire response. Split output tokens by clause punctuation (commas, periods) and send the first 3–5 words immediately to the TTS engine.  
*   
* Filler Audio Injections: If tool calling or state lookup adds $\>400\\text{ms}$ latency, stream short, contextual audio fillers ("Let me check that...", "Hmm, one moment...") to hold the conversational turn without leaving dead silence.  
* 

## 4\. Interruption & Turn-Taking Architecture

Handling barge-in smoothly separates amateur voice implementations from enterprise-grade systems.

USER SPEAKS WHILE AI IS PRODUCING AUDIO  
\------------------------------------------------------------------------------------  
\[AI Speaking Stream\] \----\> \[Audio Output Buffer\] \----\> \[Caller Telephone\]  
                                   |  
\[Caller Microphone\] \---\> \[Acoustic VAD (Silero)\]  
                                   | (On Voice Onset Detected)  
                                   v  
                      \+-------------------------+  
                      |   PURGE / CLEAR SIGNAL  |  
                      \+-------------------------+  
                                   |  
               \+-------------------+-------------------+  
               |                                       |  
               v                                       v  
   \[Purge Local Audio Queue\]             \[Send WSS 'clear' Event to CPaaS\]  
               |                                       |  
               v                                       v  
    \[Cancel LLM Generation\]                \[Stop Telephony Playback Instantly\]  
\------------------------------------------------------------------------------------

### Interruption Scenarios & Mitigations

1. User Barges In mid-sentence:  
2. 

   * Acoustic VAD detects speech ($\>30\\text{ms}$ energy above threshold).  
   *   
   * Orchestrator sends an immediate clear event to the telephony provider (e.g., Plivo/Exotel WebSocket clear command).  
   *   
   * The audio queue is flushed, LLM output generation is aborted, and the STT engine prioritizes the new user speech input.  
   *   
3. False Interruptions (Background noise, coughing, brief "mm-hmm"):  
4. 

   * Mitigation: Implement a two-stage confirmation window. Soft interrupt: Pause audio playback for $150\\text{ms}$. If the user speech stops within $200\\text{ms}$ (a quick "okay" or cough), resume playback from the pause point. If speech continues, execute a hard clear.  
   *   
5. Mid-Utterance Thinking Pauses ("I was absent because... uh... my fever..."):  
6. 

   * Mitigation: Do not rely solely on static silence timers. Use dynamic endpointing: lengthen silence threshold ($800\\text{ms}$) when trailing words end with conjunctions or hesitation tokens ("because", "and", "uh"), and shorten it ($300\\text{ms}$) when sentence completion syntax is detected.  
   * 

## 5\. Voice Quality & Speech Synthesis (TTS) Strategy

| Provider / Model | Latency (TTFB) | Voice Naturalness | Streaming Support | Indian English Performance | Telugu Quality | Cost Profile |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| Cartesia Sonic | $\\approx 90\\text{ms} \- 120\\text{ms}$ | High | WebSocket / Chunked | Excellent | Limited / Beta | $\\$0.030 \- \\$0.060$ / 1k chars |
| ElevenLabs Turbo v2.5 | $\\approx 150\\text{ms} \- 250\\text{ms}$ | Industry Leading | WebSocket / Chunked | Excellent | Moderate | $\\$0.150 \- \\$0.300$ / 1k chars |
| Deepgram Aura | $\\approx 100\\text{ms} \- 140\\text{ms}$ | Moderate / Good | WebSocket | Good | Not Supported | $\\$0.015$ / 1k chars |
| Sarvam AI (Bulbul v2/v3) | $\\approx 200\\text{ms} \- 350\\text{ms}$ | High (Indic Native) | HTTP / WebSocket | Good | Best-in-Class (Native Pronunciation) | $\\mathbf{\\approx ₹15 \- ₹30}$ / 10k chars (\~$\\$0.018 \- \\$0.036$) |
| OpenAI Realtime Voice | $\\approx 250\\text{ms} \- 400\\text{ms}$ | High | Native WebSockets | Good | Moderate | $\\$0.060 \- \\$0.240$ / min (Speech-to-Speech) |

### Technical Verdict on TTS

* For English Phase: Cartesia Sonic or ElevenLabs Turbo v2.5 provide the optimal blend of sub-150ms Time-To-First-Audio-Byte (TTFB) and fluid conversational prosody.  
*   
* For Telugu Phase: Sarvam AI (Bulbul v3) is necessary. Global models produce unnatural pitch contours and mispronounce regional phonemes, names, and places in Telugu.  
* 

## 6\. Speech Recognition (STT) Strategy

Telephonic audio presents severe STT challenges: it is narrowband (sampled at 8kHz), compressed via lossy codecs (G.711 $\\mu$-law/A-law), and subjected to line noise and varying speaker volume.

### Speech-to-Text Benchmark Comparison

| STT Engine | Telephonic (8kHz) Accuracy | Indian Accent Handling | Code-Switching (Tanglish/Telugu-Eng) | Streaming Latency | Cost / Hour |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Deepgram Nova-2 / Nova-3 | High | High | Moderate (Trained on Indian audio) | $\<150\\text{ms}$ | $\\approx \\$0.25 \- \\$0.43$ |
| Sarvam STT | High | Native | Best-in-Class | $\\approx 200\\text{ms} \- 300\\text{ms}$ | ₹30 ($\\approx \\$0.36$) |
| OpenAI Whisper (Cloud / Local Flash) | Moderate (Needs upsampling) | Moderate | Moderate | $\>400\\text{ms}$ (Batch/Chunked) | $\\$0.36$ |
| AssemblyAI Conformer-2 | High | High | Low | $\\approx 250\\text{ms}$ | $\\$0.37$ |

### Telephonic Audio Noise Strategy

1. Audio Resampling & Conditioning: Upsample incoming 8kHz PCM to 16kHz before processing if the target STT requires 16kHz input. Apply a high-pass filter ($\<80\\text{Hz}$) to eliminate telephonic DC offset and line hum.  
2.   
3. Vocabulary Prompting / Keyterm Injection: Inject contextual domain keywords (e.g., student names, branch names like "Electronics", reason categories like "Fever", "Casual Leave") into the STT engine configuration to force accurate recognition of proper nouns.  
4. 

## 7\. LLM Reasoning & Dialogue Strategy

### End-to-End Speech-to-Speech (S2S) vs. Cascaded Pipeline

CASCADED PIPELINE (Recommended for Enterprise/Deterministic Control):  
\[Audio In\] \-\> \[STT\] \-\> \[Text Prompt \+ Guardrails\] \-\> \[LLM\] \-\> \[JSON/Tool Call State\] \-\> \[TTS\] \-\> \[Audio Out\]

END-TO-END SPEECH-TO-SPEECH (e.g., OpenAI Realtime / Gemini Live):  
\[Audio In\] \------------------------\> \[Multimodal Model\] \------------------------\> \[Audio Out\]

### Strategic Evaluation

* Speech-to-Speech (S2S) Models: Excellent natural expressiveness and low latency, but suffer from high costs ($\\approx \\$0.06 \- \\$0.30/\\text{min}$), hallucination risks, difficulty enforcing strict business logic (e.g., extracting precise student IDs), and limited support for direct Indian language telephony integration.  
*   
* Cascaded Hybrid Architecture (Recommended):  
* 

  * Orchestrator: High-speed deterministic state machine (Node.js/Python).  
  *   
  * LLM: Ultra-fast, instruction-tuned reasoning model (Groq Llama-3.1-8B, Gemini 2.0 Flash, or Claude 3.5 Haiku).  
  *   
  * Function Calling / Tool Execution: Structured output extraction (JSON) runs concurrently to extract intent ("Reason: Medical", "Return Date: 2026-08-16").  
  * 

## 8\. Unit Economics & Realistic Cost Model

### Per-Minute Operating Cost Breakdown (Production Enterprise Stack)

| Cost Center | Vendor / Solution | Per-Minute Cost (USD) | Per-Minute Cost (INR) |
| :---- | :---- | :---- | :---- |
| Telephony Transit & WSS | Plivo / Exotel (India Outbound \+ Streaming) | $\\$0.011$ | ₹0.94 |
| Streaming STT | Deepgram Nova-2 / Sarvam STT | $\\$0.005 \- \\$0.007$ | ₹0.42 \- ₹0.60 |
| LLM Reasoning | Gemini 2.0 Flash / Groq Llama-3.1-8B ($\\approx 1k$ tokens/min) | $\\$0.002 \- \\$0.004$ | ₹0.17 \- ₹0.34 |
| Streaming TTS | Cartesia / Sarvam Bulbul v3 ($\\approx 600$ chars/min) | $\\$0.003 \- \\$0.018$ | ₹0.25 \- ₹1.50 |
| Server Infra & Orchestration | AWS / Hetzner GPU/CPU Clusters | $\\$0.002$ | ₹0.17 |
| Total Estimated Cost / Min | Hybrid Enterprise AI Stack | $\\mathbf{\\$0.023 \- \\$0.042}$ | $\\mathbf{₹1.95 \- ₹3.55}$ / minute |

### Cost Comparison across Scaling Tiers

Human BPO Comparison in India: A human tele-caller in India costs approximately ₹4.00 to ₹8.00 per active conversational minute (factoring in salaries, office overhead, dialer software, and idle time). AI calling operates at ₹2.00 to ₹3.50 per minute, delivering 50%–70% cost savings alongside instantaneous horizontal concurrency.

| Campaign Volume | Total Estimated Minutes | AI Calling Platform Cost (INR) | Human Tele-Caller Cost (Est. ₹6/min) |
| :---- | :---- | :---- | :---- |
| 100 Calls (Avg 1.5 min/call) | 150 Mins | ₹375 \- ₹532 | ₹900 |
| 1,000 Calls | 1,500 Mins | ₹3,750 \- ₹5,325 | ₹9,000 |
| 10,000 Calls | 15,000 Mins | ₹37,500 \- ₹53,250 | ₹90,000 |
| 100,000 Calls | 150,000 Mins | ₹3,75,000 \- ₹5,32,500 | ₹9,000,000 |

## 9\. System Scalability & Throughput Architecture

Scaling to 1,000 concurrent active voice sessions requires a stateful, horizontally scalable architecture:

                               SYSTEM CONCURRENCY ARCHITECTURE  
                                  
\[ Campaign Trigger / CSV \] \---\> \[ Redis Queue / Celery Workers \]  
                                               |  
                                               v  
                        \+-----------------------------------------------+  
                        |          Orchestrator Cluster (Node/Go)       |  
                        |   (Stateless Audio Pipeline Controllers)      |  
                        \+-----------------------------------------------+  
                          /                    |                    \\  
                         v                     v                     v  
                \[Worker Session 1\]    \[Worker Session 2\]    \[Worker Session N\]  
                         |                     |                     |  
                \+-----------------------------------------------------------+  
                |           Distributed State & Event Storage               |  
                |   Redis Cluster (State) \<---\> PostgreSQL (Metadata/Logs)  |  
                \+-----------------------------------------------------------+

### Architectural Bottlenecks & Solutions by Scaling Tier

* 1 to 10 Concurrent Calls:  
* 

  * Single application server (Node.js/Python) maintaining WebSockets.  
  *   
  * Direct connections to third-party STT/TTS cloud APIs.  
  *   
* 10 to 100 Concurrent Calls:  
* 

  * Bottleneck: Node.js event-loop congestion caused by audio transcoding/buffering.  
  *   
  * Solution: Decouple audio streaming handlers from application logic. Use a lightweight state machine controller and manage active call states in Redis.  
  *   
* 100 to 1,000 Concurrent Calls:  
* 

  * Bottleneck: Third-party API rate limits (STT/TTS concurrency caps), telephony channel caps, and database write lock contention from stream events.  
  *   
  * Solution:  
  * 

    1. Negotiate explicit rate-limit increases (Concurrency limits $\>1,000$) with STT/TTS providers or deploy self-hosted STT/TTS containers on GPU clusters (e.g., vLLM \+ Triton Server).  
    2.   
    3. Utilize SIP Trunking with dynamic elastic channels rather than basic cloud REST APIs.  
    4.   
    5. Asynchronously push call transcripts and structured JSON results to a message queue (Kafka/RabbitMQ) for batch insertion into PostgreSQL.  
    6. 

## 10\. Regulatory & Compliance Framework in India

Navigating telecom compliance is critical for sustaining enterprise operations in India.

                          TRAI / DLT COMPLIANCE FLOWCHART  
                             
 \[ Enterprise Call Intent \]  
             |  
             \+---\> Is it Promotional / Sales?   
             |            |  
             |            \+---\> YES: Must use 140-Series Number Prefix  
             |                  Scrub list against NCPR (Do-Not-Call) Database  
             |  
             \+---\> Is it Transactional / Service (e.g., Attendance, Banking)?  
                          |  
                          \+---\> YES: Must use 160-Series Number Prefix  
                                Register Entity & Voice Script Templates on DLT Portal  
                                Explicit Prior Consent required on file

1. Digital Personal Data Protection Act (DPDPA 2023):  
2. 

   * Requires clear notice and consent mechanisms prior to processing personal data (student records, phone numbers).  
   *   
   * Call recordings and transcripts containing PII must be encrypted at rest (AES-256) and stored in in-region data centers within India.  
   *   
3. Call Recording Consent:  
4. 

   * Automated calls must begin with a clear, concise disclosure (e.g., "This is an automated AI system calling on behalf of ABC College. This call is recorded for record-keeping.").  
   *   
5. Automated Calling Time Windows:  
6. 

   * TRAI mandates commercial/promotional voice calls occur strictly between 09:00 AM and 09:00 PM IST. Transactional emergency calls are exempt but require compliant DLT template tagging.  
   * 

## 11\. Architectural Shift: English $\\rightarrow$ Telugu Transition

Adapting an AI voice system to Telugu involves more than simple translation. It requires adjusting the underlying acoustic, linguistic, and state management models.

              ENGLISH PIPELINE vs. TELUGU / TANGLISH PIPELINE

   ENGLISH PIPELINE:  
   \[8kHz Audio\] \-\> \[Deepgram Nova-2\] \-\> \[Llama-3-8B\] \-\> \[Cartesia TTS\] \-\> \[Audio Out\]

   TELUGU / TANGLISH PIPELINE:  
   \[8kHz Audio\] \-\> \[Sarvam STT / Indic VAD\] \-\> \[Language ID / Routing Layer\]  
                                                      |  
                                                      v  
   \[Audio Out\] \<- \[Sarvam Bulbul v3 TTS\] \<- \[Llama-3 \+ Telugu System Prompt\]

### Key Technical Differences

1. Acoustic & VAD Adjustments:  
2. 

   * Telugu conversational cadence features distinct vocal lengthenings and pitch inflection changes at sentence terminations (e.g., "Vasthunnara?" vs "Vasthunnaru").  
   *   
   * Standard VAD models tuned for English often misidentify vowel extensions in Telugu as silence or continued speech. VAD silence thresholds must be extended from $300\\text{ms}$ to $450\\text{ms} \- 500\\text{ms}$.  
   *   
3. Handling Code-Switching (Tanglish / Telugu \+ English):  
4. 

   * Native speakers frequently mix English words into Telugu conversation ("Nenu college ki fever valla raaleka poyanu").  
   *   
   * Generic STT models convert English words within Indic speech into phonetic non-words. You must employ a code-switching model (e.g., Sarvam STT) configured for mixed-script normalization.  
   *   
5. Phonetic Entity Extraction (Names, Numbers, Dates):  
6. 

   * LLM tokenizers often split Telugu script into numerous sub-word tokens, increasing token volume and inference latency by up to $3\\times$.  
   *   
   * Mitigation: System prompts should enforce ASCII/English output for structured data extraction (e.g., output dates as 2026-08-14 and reasons in normalized English categories) while streaming Telugu text responses to the TTS engine.  
   * 

## 12\. Competitive Landscape Analysis

| Provider / Platform | Core Differentiators | Platform Bottlenecks & Weaknesses | Indian Telephony Integration |
| :---- | :---- | :---- | :---- |
| Retell AI | Excellent low-latency orchestration, built-in turn-taking, developer-friendly Webhooks. | High markup on underlying STT/TTS; restricted customization for low-level audio buffering. | Good (Supports custom SIP Trunking / Plivo). |
| Vapi | Flexible, modular architecture; allows easy swapping of STT/LLM/TTS models. | Higher latency variations due to multiple API orchestrations; requires careful tuning. | High (Native SIP / WebSockets via Plivo & Twilio). |
| Bland AI | Native custom telephony infrastructure, built for high enterprise outbound volume. | Proprietary "black-box" model execution; limited control over exact VAD and turn-taking logic. | Moderate (Primarily optimized for US/EU PSTN). |
| Bolna.ai | Open-source platform built specifically for Indian voice AI workflows; native support for Indic TTS/STT. | Infrastructure requires active engineering maintenance at large scale. | Native (Pre-built integrations with Indian DLT, Vobiz, Exotel). |

## 13\. Critical Risks & Failure Modes Matrix

| Risk Factor | Root Cause | Impact | Mitigation Strategy |
| :---- | :---- | :---- | :---- |
| Robotic Latency Spikes | Sequential API processing, LLM cold starts, network jitter | High (Caller hangs up) | Implement speculative execution, streaming chunked TTS, and host orchestration in Mumbai (ap-south-1). |
| Barge-In Echo Loops | Telephony speaker output bleeds into microphone input | High (AI interrupts itself) | Enable strict echo cancellation (AEC) at the telephony level and enforce a $150\\text{ms}$ VAD grace period post-playback. |
| Hallucinated State Tracking | Unstructured LLM conversation drift | Medium (Corrupts reporting data) | Separate conversation generation from state tracking. Use deterministic state machines to update database values via structured tool calls. |
| DLT / Number Blocking | Calling non-consented numbers via incorrect number series | Fatal (Telecom blocking) | Secure 160-series numbers for transactional workflows, register principal entities on DLT, and maintain explicit opt-in records. |
| Poor Telugu Name Extraction | STT phonetically misinterpreting regional student names | Medium (Bad data export) | Pre-load CSV student lists into the LLM context prompt so entity recognition matches against known candidate names. |

## 14\. Recommended Master Technology Strategy

### Recommended Technology Stack

\+-----------------------------------------------------------------------------------+  
|                                PRODUCTION STACK                                   |  
|                                                                                   |  
|  \[ Telephony Layer \]       Plivo / Exotel SIP Trunking (160 Series Numbers)       |  
|  \[ Transport Protocol \]    Bidirectional WebSockets (PCM 8kHz / Slinc)             |  
|  \[ Framework Core \]        Pipecat / LiveKit Agents Engine (Python/Go)            |  
|  \[ VAD Engine \]            Silero VAD (Sub-10ms Acoustic Detection)               |  
|                                                                                   |  
|  \+-----------------------------------------------------------------------------+  |  
|  | \[ English Stack \]            \[ Telugu / Multilingual Stack \]                |  |  
|  | STT: Deepgram Nova-2         STT: Sarvam STT (Code-Switching Enabled)       |  |  
|  | LLM: Groq Llama-3.1-8B       LLM: Gemini 2.0 Flash / Claude 3.5 Haiku        |  |  
|  | TTS: Cartesia Sonic          TTS: Sarvam Bulbul v3                          |  |  
|  \+-----------------------------------------------------------------------------+  |  
|                                                                                   |  
|  \[ Application Backend \]   FastAPI / Node.js Microservices                        |  
|  \[ Cache & Session State \] Redis Cluster                                          |  
|  \[ Database & Analytics \]  PostgreSQL (JSONB Transcript & Call Result Storage)    |  
|  \[ Infrastructure Host \]   AWS India (ap-south-1 Mumbai)                          |  
\+-----------------------------------------------------------------------------------+

### Implementation Roadmap

PHASE 1: Core Architecture & English Prototype  
  │  
  ├── 1\. Deploy Pipecat/LiveKit Orchestrator on AWS Mumbai (ap-south-1)  
  ├── 2\. Provision Plivo/Exotel Indian Test Numbers with WebSockets  
  ├── 3\. Wire Pipeline: Silero VAD \-\> Deepgram STT \-\> Groq LLM \-\> Cartesia TTS  
  └── 4\. Build CSV Ingestion, Campaign Scheduler, and Structured Data Exporter

PHASE 2: Interruption Optimization & State Reliability  
  │  
  ├── 1\. Implement Dual-VAD and WebSocket frame purge signals  
  ├── 2\. Add Speculative Execution to reduce perceived turn latency to \<700ms  
  └── 3\. Implement Deterministic State Machine for Call Disposition (Answered, Busy, Reason)

PHASE 3: Telugu & Tanglish (Code-Switching) Integration  
  │  
  ├── 1\. Integrate Sarvam STT and Bulbul v3 TTS into the Pipeline  
  ├── 2\. Calibrate VAD Silence Windows (450ms) for Telugu Vocal Cadence  
  └── 3\. Train Prompt Layer for Entity Normalization (Converting spoken Telugu names/dates to English JSON)

PHASE 4: Enterprise Scale & Telecom Compliance  
  │  
  ├── 1\. Obtain DLT Registration & Provision 160-Series Number Blocks  
  ├── 2\. Scale Architecture with Redis Session Cache and Elastic SIP Trunking  
  └── 3\. Perform Load Testing up to 1,000 Concurrent Active Calls

## Architectural Synthesis

To realize your vision of an ultra-natural AI voice platform:

1. Avoid SIM Cards: Use Plivo or Exotel Cloud Telephony over WebSockets to ensure Indian compliance, full-duplex control, and scalability.  
2.   
3. Prioritize Latency: Choose high-performance components like Cartesia Sonic (English), Sarvam AI (Telugu), and Groq Llama-3.1 to keep total round-trip response time below $800\\text{ms}$.  
4.   
5. Control Interruption Logic: Build a full-duplex pipeline capable of instantly flushing stale audio buffers upon detecting user speech.  
6.   
7. Ensure Regulatory Compliance: Register your entity on the DLT portal and secure 160-series numbers for legitimate service and attendance calling.

# qwen 3.8 max

As a senior voice-AI architect and telecom engineer, I have evaluated your project requirements against the current Indian telecommunications landscape, real-time AI inference capabilities, and TRAI (Telecom Regulatory Authority of India) regulations.  
Your goal of building a "highly natural" voice agent is technically feasible today, but the Indian market presents unique regulatory and infrastructural hurdles that invalidate several standard "Western" voice-AI assumptions. Below is a research-grade, independent analysis of your project.

### 1\. Telephony: The Indian Reality

Challenge your assumption: Do not use SIM cards, eSIMs, or GSM Gateways (SIM farms) for this project.  
Using GSM gateways to route automated bulk calls bypasses standard interconnect charges and is classified as illegal telecom fraud by TRAI  
decoded.legal  
. It will result in immediate blocking of your hardware and severe legal penalties  
www.infobip.com  
.  
Best Options for India:

* Cloud Telephony (Aggregators): Providers like Exotel, Plivo, and Ozonetel are the standard for Indian Voice AI  
* caller.digital  
* . They provide DLT-compliant virtual numbers and handle the complex KYC required by Indian telecom operators (Jio, Airtel, Vi).  
* Programmable Voice APIs: Plivo offers excellent WebSocket-based "Audio Streaming" specifically designed for AI agents  
* plivo.com  
* . EnableX is another strong local contender with real-time raw audio WebSocket streaming  
* www.enablex.io  
* .  
* SIP Trunking: For high volume (10k+ calls/day), direct SIP trunks via Tata Tele or Jio Business offer the lowest per-minute rates (₹0.40–₹0.60/min) but require a Registered Telemarketer license and high upfront deposits.  
* Pricing & Routing: Twilio is generally too expensive for domestic Indian outbound calls (₹1.20–₹1.50/min)  
* exotel.com  
* . Local providers like Plivo or Exotel charge between ₹0.50 and ₹0.90 per minute for outbound mobile calls  
* caller.digital  
* ,  
* vobiz.ai  
* .

### 2\. Real-Time Voice Architecture

To achieve "human-like" quality, you must move away from standard request-response loops and adopt a Continuous Streaming Pipeline.

* Orchestration Frameworks: Do not build the pipeline from scratch. Use Pipecat (by Daily.co) or LiveKit Agents  
* www.cekura.ai  
* .  
  * *Pipecat* uses a pipeline architecture (VAD → STT → LLM → TTS) giving you granular control over barge-in logic and audio buffering  
  * thinnest.ai  
  * .  
  * *LiveKit* uses a "room" model based on WebRTC, which is superior if you plan to add multimodal features (video/avatar) later  
  * www.cekura.ai  
  * .  
* Audio Transport: You must stream raw PCM/Mulaw audio via WebSockets from the telephony provider to your media server.  
* State Management: Redis is required to maintain the independent state of thousands of concurrent calls, storing the conversation history and tool-call status for every active session.

### 3\. Latency Targets & Pipeline

In human conversation, a gap of \>1000ms feels "robotic." Your target for Time-To-First-Audio (TTFA) should be \< 600ms.  
The Latency Pipeline:

1. Endpointing (50ms): Detecting the user stopped speaking.  
2. STT Streaming (200ms): Transcribing audio *while* the user is speaking.  
3. LLM Inference (150ms): Generating the first token of the response.  
4. TTS Generation (100ms): Synthesizing the first audio chunk.  
5. Network/Playback (50ms): Sending audio back to the phone.

*Strategy:* You must use Streaming APIs for every component. Do not wait for the LLM to finish generating a full sentence before sending it to the TTS. Send chunks of 10-20 words as they are generated.

### 4\. Interruption and Turn-Taking (Barge-In)

This is the hardest engineering challenge.

* Acoustic Echo Cancellation (AEC): When the AI speaks, the user's phone mic might pick up the AI's voice. If your system doesn't filter this out, it will "hear itself" and interrupt itself.  
* Semantic Endpointing: Standard systems wait for 800ms of silence. High-end systems analyze the *transcript* to see if the user finished a thought. If the user pauses but the sentence is grammatically incomplete, the AI waits.  
* Cancel-and-Clear: When the user interrupts, the system must instantly drop the TTS buffer, cancel the LLM generation, and pass the new audio to the STT. Frameworks like Pipecat handle this "barge-in" logic natively  
* thinnest.ai  
* .

### 5\. Voice Quality (TTS)

For Indian English and eventual Telugu, naturalness is key.

* Cartesia (Sonic): Currently the latency leader (\~40ms TTFA)  
* deepgram.com  
* . It is optimized for real-time conversational AI and includes "fillers" (ums, ahs) that make it sound human.  
* ElevenLabs (Turbo v2.5 / Multilingual v2): The industry standard for emotional range and voice cloning. It supports Indian accents well and has a specific multilingual model that covers Telugu.  
* Avoid: Standard cloud TTS (AWS Polly, Google WaveNet) as they lack the "breathiness" and pacing variations of human speech.

### 6\. STT Quality for Telephony

* The Problem: Phone calls use 8kHz narrowband audio, which degrades quality.  
* The Solution: Deepgram Nova-3 or AssemblyAI Universal-1. Deepgram is specifically optimized for telephony audio and Indian accents, offering \<300ms latency  
* deepgram.com  
* ,  
* futureagi.substack.com  
* .  
* Whisper Warning: While OpenAI's Whisper is powerful, the Large-v3 model often struggles with 8kHz telephony compression and heavy Indian accents compared to specialized commercial models  
* www.hirefinn.ai  
* ,  
* novascribe.ai  
* .

### 7\. LLM Strategy

Challenge your assumption: You do *not* need a massive reasoning model for 90% of this project.

* The "College Absent" Use Case: This is a deterministic flow. You need a fast, low-latency model like Llama 3.1 70B (via Groq) or GPT-4o-mini. Groq offers inference speeds that are virtually instantaneous, which is critical for voice  
* blog.portaone.com  
* .  
* Architecture: Use a "Router" model. A fast model handles the conversation flow and turn-taking. Only route to a heavy model (Claude 3.5 Sonnet / GPT-4o) if the user asks a complex, out-of-domain question that requires deep reasoning.

### 8\. Cost Estimates (Per Minute)

Based on current API pricing  
softcery.com  
,  
inworld.ai  
,  
blog.portaone.com  
:

* Telephony (India): \~$0.012/min (₹1.00)  
* STT (Deepgram): \~$0.007/min  
* LLM (Groq/GPT-4o-mini): \~$0.005/min  
* TTS (Cartesia/ElevenLabs): \~$0.030/min  
* Total AI Cost: \~$0.054 per minute (approx. ₹4.50/min).

Scale Comparison:

* 1,000 calls (3 min avg) \= \~$162  
* 100,000 calls \= \~$16,200  
* *Human Alternative:* A human BPO agent in India costs approx. ₹15–₹25 per minute (fully loaded). AI is roughly 5x-8x cheaper and infinitely more scalable.

### 9\. Scalability Bottlenecks

* 1–10 Calls: Handled easily by a single Node.js/Python server.  
* 100 Calls: Requires load balancing and managing WebSocket file descriptors.  
* 1,000+ Calls: The bottleneck shifts to SIP Trunk Capacity and Media Server CPU. You will need a Kubernetes cluster (e.g., using LiveKit or Jitsi) to distribute the audio processing load across multiple nodes.

### 10\. Indian Legal & Telecom (Critical)

This is where most international projects fail in India.

* DLT Registration: Under TRAI regulations, every commercial/transactional call must be registered on a Distributed Ledger Technology (DLT) platform  
* thinnest.ai  
* . You must register as a "Principal Entity" (the College) and approve your "Headers" (Caller ID names) and "Teasers" (Call purpose templates).  
* Number Series: Promotional calls use the 140-series. Service/Transactional calls (like college attendance) use the 160-series or specific whitelisted headers  
* www.linkedin.com  
* .  
* AI Disclosure: Recent TRAI updates mandate that AI voice agents must disclose they are artificial if asked, or at the start of the call  
* qcall.ai  
* .  
* Penalties: Violating DND (Do Not Disturb) registries or DLT rules can attract penalties up to ₹50 Lakhs and disconnection of all telecom resources  
* conversailabs.com  
* .

### 11\. The English → Telugu Transition

Moving to Telugu is not just a "translation" task; it is a linguistic engineering challenge.

* Code-Switching (Telugish): Indian users rarely speak pure Telugu. They say, *"Nenu bus miss ayyindi, so late ga vasthanu."* Standard TTS/STT models fail here.  
* STT: You must switch to AI4Bharat's IndicConformer models, which are specifically trained on Indian code-mixed datasets and telephony audio  
* models.ai4bharat.org  
* ,  
* ai4bharat.iitm.ac.in  
* .  
* TTS: AI4Bharat’s IndicTTS and Indic-Parler-TTS offer the most natural Telugu prosody  
* github.com  
* ,  
* huggingface.co  
* . ElevenLabs Multilingual v2 is good but may struggle with specific regional slang unless you use phonetic prompting.

### 12\. Competitive Landscape Analysis

* Bland AI / Air AI: Proprietary, end-to-end platforms. Good for US markets, but they lack the deep integration with Indian DLT compliance and local SIP routing required for high connection rates in India.  
* Vapi / Retell AI: These are "orchestration layers." They allow you to plug in Twilio/Plivo and Deepgram. They are excellent for developer flexibility but require you to manage the Indian telecom compliance wrapper yourself.  
* Differentiation: The winning systems in India will be those that master Semantic Endpointing and DLT Compliance, not just those with the best voices.

### 13\. Critical Risks (The "Project Killers")

1. TRAI Blocking: If your DLT templates are not approved or you call DND numbers, your numbers will be blocked within 24 hours.  
2. Robotic Turn-Taking: If you use a fixed 800ms silence timeout, the AI will constantly interrupt people who are just thinking. You *must* implement semantic endpointing.  
3. Hallucinations: If the AI tells a student "You are expelled" because the LLM hallucinated, the liability falls on the college. You need strict "System Prompts" and "Tool Calling" constraints.  
4. Audio Degradation: 8kHz telephony audio \+ background noise (traffic/fans in India) will destroy standard Whisper models.

### 14\. Recommended Technology Strategy

Based on the research, here is the optimal stack for your prototype and MVP:

* Telephony: Plivo or Exotel. Use their WebSocket Audio Streaming APIs. Ensure your "Principal Entity" KYC is completed before writing code.  
* Orchestration Framework: Pipecat (Python). It gives you the lowest-level control over the VAD and Barge-in logic, which is essential for "natural" conversation.  
* STT: Deepgram Nova-3 (Telephony model, streaming).  
* LLM: Groq (Llama 3.1 70B). The inference speed is unmatched and critical for keeping latency under 600ms.  
* TTS: Cartesia Sonic (for lowest latency) or ElevenLabs Turbo v2.5 (for best naturalness).  
* Backend: Python (FastAPI) \+ Redis (State) \+ PostgreSQL (Campaign Data).  
* Deployment: Host your media servers in the AWS Mumbai (ap-south-1) region to minimize network latency to Indian telecom exchanges.

Final Advice: Do not start with Telugu. Spend 3 months perfecting the "Interruption/Barge-in" logic and the DLT compliance workflow in English. If the English version feels robotic, the Telugu version will be unlistenable due to the added complexity of code-mixing.

# claude approch

# **AI Voice Calling Agent — Independent Technical & Commercial Research (India, Aug 2026\)**

**How to read this:** Given the size of this brief, I'm not tagging every sentence. Instead: figures with a `(Source: ..., 2026)` note are things I found in current, dated sources — treat vendor blog numbers as *provider claims* unless I say "independent benchmark." Anything under a **"My take"** or **"Recommendation"** heading is my own inference/judgment, not a cited fact. I've flagged the places where I think your brief is making an assumption worth challenging.

---

## **0\. TL;DR — the four places I'd push back on the brief**

1. **Don't evaluate SIM/eSIM at all.** It's not a real option for this use case — no programmability, no legal outbound-calling compliance path, no concurrency, no audio streaming. The real decision is *which cloud telephony/CPaaS provider*, not telephony architecture type.  
2. **"Best latency" and "best voice quality" are not settled by picking one vendor.** The entire market has converged on a *cascaded* pipeline (STT → LLM → TTS) as the production default, specifically *because* your core requirement — structured data extraction ("why were you absent," "when will you return") — needs reliable tool-calling and auditable text at every stage. Speech-to-speech models (OpenAI Realtime, Gemini Live) are lower-latency in theory but worse at exactly the thing your admin-use-case needs most. This is the single biggest architectural decision in your brief, and I'd resolve it in the opposite direction of where "most natural conversation" intuition points.  
3. **Telugu is not a "harder version of English" — it's a different vendor stack.** None of the providers that are strong in English (Deepgram, Cartesia, ElevenLabs, AssemblyAI) have credible production Telugu. The market has a genuine India-first specialist (Sarvam AI) that is *purpose-built* for this, including Telugu-English code-switching. Plan for a stack swap, not a stack extension, in Phase 2\.  
4. **Cost math: "AI is cheaper than a human caller" is not obviously true in India at your scale.** In the US, human agents cost $35–50k/year, making AI's \~$0.05–0.25/min trivially cheaper. In India, a telecaller costs roughly ₹15,000–25,000/month and handles \~2,500–3,500 calls/month at \~3 min average — that's roughly ₹2–3.5/min *fully loaded*, which is in the same range as, or cheaper than, a well-run AI stack at low volume once you include Indian STT/TTS/LLM/telephony costs. AI's actual advantage for your use case is concurrency, 24/7 availability, consistency of data capture, and not needing to staff a calling team every semester — not raw per-minute cost. Sell it internally on that basis, not on "cheaper than a human."

---

## **1\. Telephony: the real decision is which CPaaS provider, not what "kind" of number**

### **Why SIM/eSIM is off the table**

A physical/eSIM-based approach (a phone connected to a modem/GSM gateway) has no API-level call control, no reliable concurrency beyond the number of physical SIMs you buy, no programmatic WebSocket/RTP audio access for STT/TTS integration, and critically, **no path to DLT compliance** — Indian carriers treat bulk automated calling from a personal-SIM-style number as spam and will silently block or throttle it (Source: multiple TRAI-compliance guides, 2026). This isn't a trade-off to weigh against cloud telephony; it simply doesn't do the job.

### **The real shortlist for India**

| Provider | India fit | Outbound rate (typical) | Number rental | Streaming for voice AI | DLT handling | Notes |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| **Exotel** | India/APAC-native, UL-VNO licensed telecom operator | \~₹0.80–1.00/min (Source: Exotel migration guide, 2026\) | Varies by plan | AgentStream — bidirectional WebSocket, 16-bit 8kHz PCM, \<20–50ms media latency (provider claim) | Strongest — handles DLT/DND as part of the platform (Source: caller.digital, 2026\) | Best "compliance handled for you" option; \~10–25% pricier than Plivo per-minute (Source: caller.digital, 2026\) |
| **Plivo** | Global CPaaS with strong India presence | Local outbound \~₹0.60/min (Source: awaaz.ai, 2026\) | \~₹250/month (Source: awaaz.ai, 2026\) | Native SIP trunking \+ audio streaming; explicitly integrates with LiveKit and Pipecat (Source: Plivo pricing page, 2026\) | Competent, self-managed DLT registration | Best "developer-first, cheapest to prototype on" option; 24–48hr Indian DID provisioning (Source: caller.digital, 2026\) |
| **Ozonetel** | India CCaaS \+ telephony | Unlimited-minute agent pricing on some plans (unusual model) | — | Yes | Strong | Leans more contact-center-suite than raw API; good if you eventually want agent-desktop/CCaaS features |
| **Knowlarity (Vonage)** | India-native | — | — | Yes | Strong | Similar profile to Exotel |
| **Twilio** | Global, weakest India economics | \~₹1.20–1.50/min outbound, \~₹0.50–0.80 inbound (Source: Exotel migration guide citing Twilio's own India pricing, 2026\) | — | Best-in-class docs, `<Stream>` verb, ConversationRelay | DLT is **self-managed with no platform tooling** (Source: frejun.com, 2026\) | 50–100% more expensive than India-native providers for India-domestic calls; best documentation ecosystem but that's not worth the premium here |
| **Bolna (open-source India-focused agent framework)** | India-specific, ships **Sarvam \+ Twilio-India defaults out of the box** (Source: thinnest.ai framework comparison, 2026\) | Depends on underlying telephony chosen | — | Built for exactly this stack | Handled at the framework level | Worth evaluating directly — it's the framework in this landscape closest to "built for an India \+ regional-language voice agent," see §12 |

**Reality check on the pricing figures above:** these numbers come from vendor blogs and comparison sites, not directly from a live quote. Treat them as *directionally correct, not contractual* — get an itemized INR quote from 2–3 providers before committing, since several sources explicitly warn that "quote only in USD" or vague per-minute figures are a red flag at contract stage (Source: frejun.com voice-api-india guide, 2026).

### **KYC / DLT / regulatory requirements (this is not optional paperwork — see §10 for the full legal picture)**

* Register as a **Principal Entity** on TRAI's DLT platform (PAN, GST, CIN, Aadhaar biometric auth required); one-time fee \~₹5,900 on the first TSP platform (Source: frejun.com TRAI guide, 2026).  
* Choose the correct number series: **140-series** for promotional/marketing calls, **1600-series** (was 160\) for BFSI/transactional service calls (Source: multiple TRAI-compliance guides, 2026). **Neither cleanly fits an educational-institution "why were you absent" call** — this is a genuine gray area (see §10). Get this classified correctly before your first campaign; carriers silently drop non-compliant calls rather than erroring (Source: autointerviewai.com, 2026).  
* Registration typically takes 5–10 business days when documentation is correct, longer if resubmission is needed (Source: multiple sources, 2026).

### **Recommendation**

Prototype on **Plivo** (cheapest, cleanest API, works directly with LiveKit/Pipecat, fast DID provisioning) or **Exotel** if you'd rather have DLT/compliance handled for you at a \~15–25% cost premium. Do **not** start with Twilio for India-domestic calling — its India economics are worse on every axis and its DLT tooling is weaker, and its main advantage (documentation quality) matters less once you're using LiveKit/Pipecat docs instead of Twilio's. Register DLT in parallel with prototyping — it's the long pole, and calls will silently fail without it once you leave a sandbox/test-number phase.

---

## **2\. Real-time voice architecture: the components, ranked by effect on perceived quality**

A production voice agent is a pipeline, not a model:

**Telephony (PSTN/SIP) → Audio streaming (WebSocket/RTP) → VAD → STT (streaming) → Turn/endpoint detection → LLM (streaming, with tool calling) → TTS (streaming) → Audio playback**, wrapped in session/state management that tracks conversation history, call status, and structured data extraction per call.

Ranked by how much each one actually affects whether a caller thinks they're talking to a human (my inference, based on the aggregate of what the sourced benchmarks measure and emphasize):

1. **Turn detection / endpointing** — this is the component every serious 2026 source calls "the least understood and most important" (Source: autointerviewai.com, 2026). Get this wrong and nothing else matters: the agent either talks over people or leaves robotic dead air.  
2. **TTS time-to-first-audio** — the single largest controllable contributor to perceived responsiveness (Source: codesota.com, burki.dev, 2026).  
3. **STT streaming latency \+ accuracy on telephone-quality (8kHz, noisy) audio** — most STT benchmarks are run on clean audio; production phone audio is materially harder (Source: sarvam.ai, gladia.io, 2026).  
4. **LLM time-to-first-token**, less so total generation time, since responses stream.  
5. **Barge-in / interruption handling** — technically straightforward (stop TTS playback, flush buffer) but the *policy* around it (is this a real interruption or a backchannel "mhm"?) is where quality is actually won or lost.

**My take:** most teams over-invest in "which LLM" and under-invest in turn detection and TTS latency tuning. For your project, I'd budget engineering time in the opposite proportion to where the brief's question list implies effort — turn-taking tuning and TTS provider selection will move the needle on "feels human" far more than LLM choice will.

---

## **3\. Latency: the pipeline and realistic targets**

**Human conversational turn-taking gap averages \~200ms** (Source: reactify-solutions.com citing production 2026 figures). No cascaded system fully matches this yet, but the target for "doesn't feel robotic" is generally cited as **under \~800ms** end-of-caller-speech to start-of-agent-speech, with a hard ceiling around 900ms–1.2s before callers perceive it as "the AI is thinking" (Source: retellai.com, autointerviewai.com, 2026).

Realistic 2026 component budget for a well-tuned cascaded pipeline (my synthesis of the sourced benchmarks in §5–§7, not a single vendor's number):

| Stage | Typical range (2026, tuned) |
| ----- | ----- |
| VAD / end-of-turn detection | \~200–300ms (Silero VAD baseline; semantic/prosody turn detectors add \~20ms but cut false-cutoffs) (Source: reactify-solutions.com, livekit docs, 2026\) |
| STT first-partial / streaming | 100–300ms (Deepgram Nova-3/Flux, AssemblyAI Universal-Streaming) (Source: assemblyai.com, futureagi.com, 2026\) |
| LLM time-to-first-token | 200–300ms on a fast small model via Groq; 300–600ms+ on a standard hosted frontier model (Source: neuraplus-ai, reactify-solutions.com, 2026\) |
| TTS time-to-first-audio | 40–90ms (Cartesia Sonic) to 75–300ms (ElevenLabs, depending on model tier) (Source: multiple TTS comparisons, 2026\) |
| Network/orchestration overhead | 50–200ms depending on region pinning (Source: reactify-solutions.com, 2026\) |
| **Realistic end-to-end (tuned, cascaded)** | **\~600–900ms median**, matching what Retell/Vapi/LiveKit teams report in independent 2026 tests (Source: techsy.io head-to-head test, tested.media, 2026\) |

**My take:** don't chase sub-500ms as a Phase-1 target — even the best-funded commercial platforms (Retell, Vapi) sit at 500–900ms median in independent testing, with P95 regularly exceeding 1.5s under load (Source: techsy.io, 2026). A more useful Phase-1 goal is "consistent 700–900ms with no P95 tail above \~1.5s," because *consistency* matters more to perceived quality than best-case latency (Source: retellai.com, 2026).

---

## **4\. Interruption & turn-taking**

The 2026 production pattern has three layers, and this is worth building deliberately rather than treating as a VAD afterthought:

1. **VAD (Voice Activity Detection)** — continuous per-frame confidence that incoming audio contains a voice. Silero VAD is the open-source default used across LiveKit, Pipecat, and most managed platforms.  
2. **Endpointing** — deciding *when* the user's turn has actually ended. Pure silence-threshold endpointing (typically 700–1000ms of silence) is the baseline but can't distinguish a genuine pause from someone still thinking mid-sentence (Source: autointerviewai.com, 2026).  
3. **Semantic/prosody turn detection** — the 2026 upgrade path: models that read pitch drop, rising intonation, and semantic completeness of the partial transcript to distinguish "done talking" from "thinking pause" from "backchannel" (uh-huh/mhm). LiveKit's Turn Detector v1 reports a **9.9% false-cutoff rate at a 300ms latency budget** in their own testing (Source: livekit/autointerviewai.com, 2026\) — an independently-reproducible number worth validating on your own audio before trusting it wholesale. Deepgram's **Flux** model folds end-of-turn detection directly into the STT model, claiming under 300ms median with no external VAD needed (Source: coval.ai, 2026 — vendor claim).

For interruption handling specifically: when the caller speaks while the agent is talking, the system needs to distinguish a genuine interruption ("actually, wait—") from background noise or a backchannel, then immediately stop TTS playback and discard unplayed audio if it's genuine. This is largely a solved engineering pattern in LiveKit Agents and Pipecat (both ship "adaptive interruption handling" and "false interruption" guards out of the box per their docs) — I would not try to build this from scratch.

**My take:** For your college-absence use case specifically, students will frequently pause mid-explanation ("I was... um... I had a family thing"). A silence-only endpointer will cut them off. Budget explicit tuning time for endpointing thresholds against real Indian-English and Telugu speech patterns — this is exactly the kind of thing that reads fine in a demo and breaks on real calls.

---

## **5\. Voice quality (TTS) — don't assume open-source is cheaper or better**

| Provider | Time-to-first-audio | Strength | Weakness | Telugu? |
| ----- | ----- | ----- | ----- | ----- |
| **Cartesia Sonic** | \~40–90ms (Source: multiple 2026 comparisons) | Latency leader; State Space Model architecture, not transformer-based | Voice character/emotional range slightly behind ElevenLabs; latency *spread* is wider than ElevenLabs (Source: forasoft.com, 2026\) | No |
| **ElevenLabs (Flash v2.5 / Turbo)** | \~75–300ms depending on model tier | Best voice realism/emotional expressiveness, cloning, broadest language count (32+) | Slower than Cartesia on the fast path; the highest-quality models (Multilingual v2) are 500–800ms — too slow for real-time turns | Limited — general multilingual, not Telugu-specialist |
| **Deepgram Aura-2** | \~90ms tuned | Bundled into Deepgram's Voice Agent API (single WebSocket for STT+LLM+TTS) | Newer, less proven on voice character | No |
| **Sarvam Bulbul V3** | Sub-250ms first-byte via WebSocket (provider claim, sarvam.ai 2026\) | **Purpose-built for Telugu and 10 other Indian languages** — vowel harmony, Tenglish code-switching, Indian name/number pronunciation, top-ranked in a Josh Talks blind study of 20k+ votes (provider-cited study) | Not competitive for pure-English use vs. Cartesia/ElevenLabs | **Yes — this is the answer to your Telugu TTS question** |

**My take on "open-source vs. paid":** the brief specifically asks not to assume open-source is automatically cheaper/better, and the evidence supports that skepticism — self-hosted open-weight TTS (e.g., Kokoro) is genuinely cheaper at very high volume but requires you to own GPU infrastructure, and for a project whose *entire differentiator is voice quality*, that's the wrong place to cut corners in Phase 1\. Rent a top-tier API until conversation quality is proven, then reconsider self-hosting purely as a cost optimization once volume justifies it.

**Recommendation:** Cartesia Sonic for English (latency-critical outbound calls, where every hundred milliseconds compounds into "feels robotic"). Sarvam Bulbul V3 for Telugu — there isn't a credible alternative with comparable Telugu-specific tuning (code-switching, prosody, name pronunciation) among the global providers.

---

## **6\. Speech recognition (STT) — telephone audio is the hard case, and vendor benchmarks mostly don't test it**

Independent 2026 benchmarking (Hamming.ai, 4M+ production calls) found **AssemblyAI's Universal-3 Pro Streaming faster *and* more accurate than Deepgram Nova-3** on real production call audio — 307ms P50 latency / 8.14% WER vs. Deepgram's 516ms / 9.87% (Source: assemblyai.com citing Hamming.ai, 2026 — note this is AssemblyAI's own blog citing a third-party benchmark, so treat the framing with mild skepticism even though the underlying benchmark is independent). Deepgram's counter is **Flux**, a model purpose-built for voice agents that folds end-of-turn detection into the STT step itself and posts the lowest end-of-speech latency as of mid-2026 (Source: coval.ai, futureagi.com, 2026).

Word error rate has genuinely plateaued among the top players on *clean* audio — Deepgram Nova-3, AssemblyAI Universal-3 Pro, OpenAI gpt-4o-transcribe, ElevenLabs Scribe v2, and Microsoft's MAI-Transcribe-1 all sit within 1–2 percentage points of each other on standard benchmarks (Source: coval.ai, 2026). **The real competitive surface has moved to streaming latency, end-of-turn detection, and multilingual/code-switching depth** — which is exactly where the India/Telugu question becomes decisive.

For Telugu (and Indian accents generally), **Sarvam's Saaras v3** is the standout: trained on 1M+ hours of real Indian audio specifically (not adapted from an English-first model), explicitly built for 8kHz noisy telephony audio rather than clean studio recordings, with native code-mixing/diarization support and \<150ms time-to-first-token (provider claim, sarvam.ai 2026). **Gnani.ai** is the enterprise alternative — 14M+ hours of Indian telephony training data, \#1 on 8 of 9 Indian languages on the "Kathbath Noisy" benchmark (provider claim), but it's an enterprise-only, custom-pricing platform rather than a self-serve API, which matters for a bootstrapped project.

**Recommendation:** Deepgram (Flux, for the built-in turn detection) or AssemblyAI for English. Sarvam Saaras v3 for Telugu — same reasoning as TTS above.

---

## **7\. LLM strategy — this is where I'd most directly challenge the brief's framing**

### **Does this need a large reasoning model? Mostly no.**

The actual reasoning load per turn in your use case (understand "I was absent because my grandmother was in the hospital," extract a reason, decide the next question, detect when the conversation is complete) is not a hard reasoning problem — it's closer to structured intent classification \+ slot-filling with natural-language wrapping. This is squarely in "small/fast model" territory, not "frontier reasoning model" territory.

**Groq's LPU-hosted open models** deliver genuinely large latency wins here: Llama 3.3 70B running at \~276+ tokens/sec on Groq vs. \~40–80 tokens/sec for GPT-4o on OpenAI's standard API (Source: apiscout.dev, 2026), and independent testing puts full voice-pipeline latency (STT \+ LLM \+ TTS) at \~330ms using Groq vs. \~880ms using an H100-hosted equivalent (Source: neuraplus-ai.github.io, 2026 — this is a third-party benchmark site, treat the exact numbers as illustrative rather than guaranteed on your traffic). Cost follows the same pattern: Groq's Llama 3.1 8B is $0.05/million input tokens; GPT-4o-mini is $0.15/$0.60 per million input/output (Source: baytechconsulting.com, aipricing.guru, 2026).

**Where you *do* want more model capability:** edge cases — an ambiguous or emotionally loaded response from a student, a request to speak to a human, detecting that the "reason for absence" needs escalation (e.g., mentions of a safety issue). My recommendation there isn't "use a bigger model for every turn" but "route": run the fast/cheap model by default, and have deterministic logic (keyword/intent triggers) escalate specific turns to a stronger model or to a human-handoff flow. This is standard practice in the platforms reviewed above (Vapi's server-side function calling, Bland's Pathways) and keeps both cost and latency low on the 95% of turns that don't need it.

### **Cascaded vs. speech-to-speech — resolve this explicitly, don't default to whichever sounds more "cutting edge"**

This is the architecture decision I think the brief under-weights. As of mid-2026:

* **Speech-to-speech models** (OpenAI Realtime `gpt-realtime`, Google Gemini Live) process audio-in/audio-out in a single model pass, cutting the STT→LLM→TTS latency chain. TTFA in independent testing ranges \~0.78s (xAI) to \~2.98s (Gemini 3.1 Flash Live), with OpenAI's `gpt-realtime-1.5` around 0.82s (Source: softcery.com Artificial Analysis-sourced benchmark, April 2026\) — **notably, this is not obviously faster than a well-tuned cascaded pipeline** (§3 above put tuned cascaded at 600–900ms).  
* **Cascaded pipelines** give you a text artifact at every stage — critical for exactly what your brief asks for: transcripts, structured summaries, audit logs, tool-calling for CSV-field extraction. Independent analysis is blunt about this trade-off: *"for agents that need 5+ tools with strict schema enforcement (booking, payments, healthcare intake, structured form filling), cascaded is the safer 2026 default"* (Source: futureagi.com, 2026\) — **your absent-student use case is structured-form-filling.** Cascaded also remains the enterprise/compliance default because every stage is independently observable, loggable, and redactable (Source: deepgram.com, reactify-solutions.com, 2026).  
* Speech-to-speech also currently has materially weaker language coverage — this matters directly for your Telugu roadmap, since neither OpenAI Realtime nor Gemini Live has anything close to Sarvam's Telugu depth.

**Recommendation:** cascaded architecture (STT → LLM with tool-calling → TTS), not speech-to-speech, for this entire project. This isn't a "settle for less exciting tech" call — it's the architecture every credible 2026 source converges on for exactly your requirements (structured extraction, auditability, non-English languages).

---

## **8\. Cost — worked estimates, and why "cheaper than a human" isn't automatic in India**

### **Per-minute component cost (my synthesis of the sourced ranges above, self-built cascaded stack, English)**

| Component | Range (₹/min) |
| ----- | ----- |
| Telephony (Plivo/Exotel local outbound) | ₹0.60–1.00 |
| STT (Deepgram/AssemblyAI) | ₹0.50–1.00 |
| LLM (Groq-hosted small/fast model) | ₹0.20–1.00 |
| TTS (Cartesia) | ₹1.00–2.00 |
| **Total (English, self-built)** | **\~₹3–5/min** |

For Telugu, swap in Sarvam pricing (STT ₹1.5/min flat; TTS \~₹30 per 10k characters, which works out to roughly ₹2–3/min at typical conversational pace): expect **\~₹4.50–7.50/min all-in** for Telugu, before infra/hosting overhead.

For context, if you instead *bought* a fully managed Indian voice-AI vendor (Gnani, Skit, Yellow.ai, etc.) rather than building, expect **₹4.50–9/min plus a platform fee of ₹1–6 lakh/month** at meaningful scale (Source: caller.digital, 2026\) — that's the "buy" price, and it's the reason a build-your-own approach is worth the engineering investment for a project where voice quality is the whole point and long-term unit economics matter (e.g., if you later commercialize this for other colleges).

### **Monthly cost at scale (assuming \~3 min average call, English, self-built stack, \~₹4/min all-in including infra amortization)**

| Volume | Minutes/month | Approx. monthly cost |
| ----- | ----- | ----- |
| 100 calls | \~300 | ₹1,200–1,500 |
| 1,000 calls | \~3,000 | ₹12,000–15,000 |
| 10,000 calls | \~30,000 | ₹1.2–1.5 lakh |
| 100,000 calls | \~300,000 | ₹10–13 lakh (volume discounts typically kick in, bringing effective rate toward ₹3.5–4/min) |

These are component costs only — add DLT registration (\~₹5,900 one-time \+ template fees), number rental (\~₹250–1,000/month per number), hosting/infra for your orchestration layer, storage for recordings/transcripts (marginal), and engineering time.

### **The human-calling comparison, done honestly for India**

US-context comparisons (the kind that show up in most vendor blogs) compare AI at $0.05–0.25/min to a US call-center agent at $35–50k/year — a comparison that doesn't transfer to India. A campus/admin telecaller in India typically costs **₹15,000–25,000/month fully loaded**, and can plausibly handle 80–150 calls/day depending on call complexity — at \~2,500–3,500 calls/month and \~3 min average, that's roughly **₹2–3.5/min**, which is *at or below* the low end of your self-built AI cost, and meaningfully below a bought managed platform.

**My take:** don't pitch this project on "AI is cheaper per minute than a human" in the Indian context — for your absent-student use case specifically, the real value is (a) every student gets called on the same day rather than admin staff working through a list over days, (b) structured, consistent data capture (reason, expected return date) instead of handwritten notes, (c) zero marginal cost to scale to every section/hostel simultaneously, and (d) it runs outside office hours. That's a genuinely strong pitch — it's just a different pitch than "cost savings."

---

## **9\. Scalability**

| Concurrency | What breaks first |
| ----- | ----- |
| 1 call | Nothing — this is where you validate conversation quality |
| 10 concurrent | Still trivial on any provider; useful for load-testing turn-detection tuning under real network jitter |
| 100 concurrent | Telephony provider's **channel/CPS (calls-per-second) limits** become the first bottleneck — Plivo's AI-agent tier, for example, is quoted at 50 concurrent calls / 3 CPS on its documented plan (Source: Plivo pricing page, 2026); you'll need to confirm and likely negotiate higher limits, or shard across multiple provider accounts/numbers |
| 1,000 concurrent | This is enterprise-scale telephony provisioning — direct carrier SIP trunking (the "20 lakh+ minutes/month" tier some sources describe going direct to Airtel/Jio) rather than a standard CPaaS plan (Source: caller.digital, 2026); at this point your LLM/STT/TTS provider rate limits and your own orchestration layer's horizontal scaling (stateless WebSocket workers behind a load balancer, session state in Redis/Postgres, a queue-throttled outbound dialer respecting CPS limits) become the binding constraints, not any single component |

**My take on architecture for this:** use a framework that already solves the concurrency/session-management problem rather than building it — LiveKit Agents and Pipecat both handle per-call session isolation, horizontal worker scaling, and WebRTC/SIP media at scale as first-class concerns (Source: multiple framework comparisons, 2026). Building your own WebSocket-per-call orchestrator from scratch is exactly the kind of "not your differentiator" engineering effort I'd avoid — your differentiator is conversation quality and domain flexibility, not real-time media infrastructure.

For a *campaign* use case specifically (call all absent students today), you also need a **rate-limited outbound dialer** — a queue that respects your telephony provider's CPS limit and retries on no-answer/busy according to a policy you define, independent of your real-time voice engine's own concurrency.

---

## **10\. Indian telecom/legal — this needs actual legal review, not just engineering**

I want to be direct about the limits of what I can tell you here: **this section should not be treated as legal advice, and several points below are genuinely unresolved gray areas that need a lawyer, not a search engine.**

**What's clear from current sources:**

* **DLT registration is mandatory** for any commercial/business outbound calling in India — register as a Principal Entity, register your number series and call templates, before making any calls (Source: TRAI TCCCPR framework, multiple 2026 compliance guides).  
* **TRAI classifies AI-generated voices under existing robocall/TCPA-equivalent rules** — meaning your AI calling platform is legally treated the same as any automated dialing system, not as a novel unregulated category (Source: qcall.ai, 2026).  
* **Following the 2026 IT Rules amendment, AI voice agents must self-identify as automated at the start of the call** and must not impersonate a specific real individual (Source: autointerviewai.com, 2026).  
* **DPDP Act 2023 \+ DPDP Rules 2025** (notified Nov 13, 2025\) govern what you can do with the *data* generated by the call — the recording, transcript, and any extracted fields are all "personal data." You need purpose-specific, informed consent (not just a TRAI dial-permission), a defined retention period, and — notably — **data localization**: Indian personal data should be processed/stored within India, and if you route audio through an international LLM/STT/TTS provider, you need to understand where that data actually flows (Source: caller.digital, gistly.ai, 2026). This is directly relevant to your provider choice — Sarvam explicitly markets India-only data processing/storage as a compliance feature; verify the equivalent for whichever English-stack providers you pick.  
* **Indian law is generally one-party consent for recording** (if your institution is a participant in the call, you can record it) — but DPDP's *processing* consent requirement is separate and additional to this (Source: frejun.com, caller.digital, 2026).

**The genuine gray area for your specific use case:** TRAI's number-series framework is built around **promotional (140-series)** vs **transactional/service (1600-series, BFSI-oriented)** calls. A college calling an already-enrolled student's registered number to ask about an absence is neither classic marketing nor a BFSI transaction — it's institutional/administrative outreach to an existing relationship. None of the sources I found address this category directly. **Recommendation: get this specific classification confirmed with your DLT-registration provider or telecom counsel before your first real campaign** — misclassifying it risks calls being silently dropped (wrong series) or, worse, a DND/consent complaint if students haven't been asked to opt in to this kind of automated call. A pragmatic mitigation: collect explicit consent for "the college may call you or your guardian using an automated system regarding attendance" at admission/enrollment time, which sidesteps most of the ambiguity.

* **Recording retention**: sector guides cite RBI-style retention windows (6 months–3 years) for regulated (BFSI) sectors; there's no equivalent published standard for education specifically — set a defined, disclosed retention policy rather than keeping everything indefinitely, both for DPDP compliance and to bound your own storage costs.

---

## **11\. English → Telugu: what actually changes**

This is the section where I'd tell you most directly: **treat Phase 2 as a second STT/TTS integration project, not a configuration change.**

What changes:

1. **STT and TTS providers swap entirely.** Deepgram/AssemblyAI (STT) and Cartesia/ElevenLabs (TTS) — your likely English-phase choices — do not have credible production Telugu. **Sarvam AI (Saaras v3 for STT, Bulbul V3 for TTS)** is the standout India-specific option, explicitly built and benchmarked on Telugu, with sub-250ms/sub-150ms latency claims, native Telugu-English code-switching ("Tenglish"), and correct handling of Indian names/numbers (Source: sarvam.ai product pages, 2026 — these are provider claims; validate WER/latency against your own call audio before committing, exactly as the STT benchmarking sources above caution generally).  
2. **Code-switching is not an edge case in Telugu, it's the norm.** Real conversational Telugu (as shown in Sarvam's own example transcripts) constantly mixes in English words mid-sentence ("naa account balance check cheyali"). An STT/TTS stack that treats this as noise will fail constantly; Sarvam's models are explicitly trained for this.  
3. **The LLM layer can likely stay similar** (most frontier and mid-tier LLMs handle Telugu text reasonably for understanding intent, even if you wouldn't trust them for Telugu *voice*) — but you should validate that your chosen model doesn't silently default to Hindi or standard-register Telugu when the input transcript contains colloquial or regional phrasing.  
4. **Turn-detection tuning likely needs to be redone**, not reused — Telugu sentence rhythm, pause patterns, and prosody differ from English, and the semantic/prosody turn-detection models discussed in §4 are typically trained/tuned on specific language data.  
5. **Regional variation and dialect**: sourced comparisons note real accuracy variance by region even within a single Indian language (e.g., one WER benchmark noted "Delhi Hindi" claims collapsing on "Lucknow Awadhi-influenced Hindi" in practice — Source: caller.digital, 2026). The equivalent risk exists for Telugu across Telangana/Andhra/coastal-vs-Rayalaseema variation. **Don't accept a vendor's aggregate Telugu WER claim — test against audio from your actual target population** (your parents' boutique customer base or students' likely demographic, depending on which project this is for).

**Biggest current ecosystem gap:** there is no evidence of a mature, production-proven **speech-to-speech** option for Telugu (the OpenAI Realtime / Gemini Live category) — reinforcing the cascaded-architecture recommendation in §7, since it's the only path with credible Telugu coverage at all.

---

## **12\. Competitive landscape**

Two genuinely different categories are relevant to you, and I'd resist conflating them:

**Global/English-first voice-agent platforms** (Retell AI, Vapi, Bland AI, plus the open-source LiveKit Agents/Pipecat): differentiate mainly on latency consistency, developer control, and pricing transparency — not on anything India- or Telugu-specific. Independent 2026 head-to-head testing found Retell fastest/most consistent (\~600–620ms median, \~$0.07/min), Vapi most flexible (component-level control, BYOK, effective cost $0.12–0.33/min once the full stack is added), Bland strongest for high-volume deterministic outbound flows (\~700–900ms, bundled pricing) (Source: techsy.io independent build-on-all-three test, 2026). None of these have meaningful Telugu.

**India-specific voice AI vendors** (Gnani.ai, Skit.ai, Yellow.ai, Bolna, Sarvam, Caller Digital, Squadstack): this is the more relevant comparison set for your roadmap.

* **Gnani.ai** is the largest India-headquartered player by scale (30M+ daily conversations, 40+ languages/dialects including deep Telugu coverage, 14M hours of Indian telephony training data, government IndiaAI Mission selection) — but it's enterprise-only with custom pricing, not a self-serve API you'd build a prototype on (Source: caller.digital, gnani.ai, 2026).  
* **Skit.ai** — outbound-native, strong in collections/insurance, "Hyper-Real" prosody claims (provider claim).  
* **Bolna** — the most directly relevant to your build-it-yourself plan: an open-source agent framework that **ships Sarvam \+ Twilio-India as defaults**, i.e., someone has already assembled roughly the stack this report recommends. Worth evaluating as a starting point rather than building your orchestration layer fully from scratch (Source: thinnest.ai, bolna.ai, 2026).  
* **Sarvam AI** — not a full voice-agent platform, but the STT/TTS layer underlying several of the above; you can use it directly.

**My take on what actually differentiates the strongest systems** (synthesizing across all the sourced comparisons rather than any single vendor's marketing): it is *not* raw model quality — WER and TTS MOS scores have converged across top providers. The differentiators that show up consistently across independent 2026 testing are: (1) turn-detection tuning specific to the target language/population, (2) pricing transparency vs. hidden per-component markups, and (3) for the India-specific vendors, actual dialect/regional coverage validated on real audio rather than a single benchmark language variant. Marketing claims about "hyper-real" or "indistinguishable from human" should be discounted heavily — none of the independent, third-party benchmarks I found support a categorical "indistinguishable" claim for any vendor.

---

## **13\. Critical risks — direct challenges to the project**

* **Robotic voice / high latency**: the median achievable latency in 2026 (600–900ms, per §3) is still roughly 3–4x slower than human-to-human turn-taking (\~200ms). No amount of vendor selection closes this gap entirely — manage expectations that "as close to human as technically possible" still has a perceptible, if small, robotic edge in 2026\. This isn't a solvable-with-more-budget problem; it's close to the current technical frontier.  
* **Poor turn detection / false interruptions**: this is the failure mode most likely to make the *English* version feel bad even with a good voice — and it needs real-call tuning, not just picking a good-sounding vendor.  
* **Telugu quality risk is the single biggest project risk in your roadmap**, not a secondary concern — you have exactly one credible specialist vendor (Sarvam) for the full stack; if its Telugu performance on your actual population doesn't hold up, there is no obvious second choice at comparable maturity today.  
* **Hallucination / incorrect information extraction**: for the absent-student use case, an LLM inferring a plausible-but-wrong "reason for absence" or "expected return date" is a real risk with real consequences (a college acting on fabricated data). Mitigate with strict tool-calling/function-schema enforcement (part of why cascaded \> speech-to-speech here), and a "low confidence → flag for human review" path rather than trusting every extraction.  
* **Telecom/regulatory risk**: silently dropped calls due to DLT misclassification, or a DPDP complaint from a student/parent about an unconsented automated call, are both plausible operational failure modes, not hypothetical ones — build the consent-capture step into your admin/enrollment flow now, not as an afterthought before "moving to production" (your prototype-phase "no auth needed" plan is fine for internal testing, but the *consent and DLT compliance* pieces are not something you can defer the same way — they gate whether calls connect at all).  
* **Concurrency/provider lock-in**: standard CPaaS concurrency tiers (tens of concurrent calls) will not support a "call every absent student across a large college simultaneously" campaign without either a higher-tier plan or a properly throttled dialer — plan the campaign dialer's pacing explicitly rather than assuming the telephony provider absorbs bursts for free.  
* **Cost risk at scale**: the ₹4-9/min range for a bought platform, or ₹3-7/min for a well-built one, is a real ongoing cost once you're calling thousands of students per campaign across multiple colleges — model this against your actual expected campaign frequency before assuming "AI is basically free at scale."

---

## **14\. Recommended technology strategy**

*(Recommendations, explicitly — not facts. Multiple viable alternatives are noted for each.)*

1. **Telephony**: Start on **Plivo** (cheapest, LiveKit/Pipecat-native, fast DID provisioning). Move to **Exotel** if you want DLT/compliance handled for you at a modest premium, or once call volume justifies enterprise support. Avoid Twilio for India-domestic calling.  
2. **Indian number approach**: DLT-registered virtual number via the chosen CPaaS provider — not SIM/eSIM. Start DLT Principal Entity registration in parallel with prototyping, since it's the longest lead-time item.  
3. **STT**: Deepgram (Flux, for built-in turn detection) or AssemblyAI for English. **Sarvam Saaras v3** for Telugu — no credible alternative at comparable maturity.  
4. **TTS**: **Cartesia Sonic** for English (latency-critical). **Sarvam Bulbul V3** for Telugu.  
5. **LLM strategy**: cascaded (not speech-to-speech) architecture throughout, for tool-calling reliability and Telugu support. Default to a fast/cheap model (Groq-hosted Llama 3.3-class, or GPT-4o-mini-class) for standard turns; add deterministic escalation logic (not a bigger model on every turn) for ambiguous/sensitive responses.  
6. **Real-time communication architecture**: build on **LiveKit Agents** or **Pipecat** rather than a from-scratch WebSocket orchestrator — both solve session isolation, concurrency scaling, and telephony integration as first-class problems, and both plug directly into Plivo/Exotel and every STT/TTS/LLM provider above. Consider evaluating **Bolna** directly as a starting scaffold, since it's already assembled close to this exact stack for the Indian market.  
7. **Backend architecture**: FastAPI (or equivalent) admin/API layer \+ your chosen agent framework for the real-time voice layer; a queue-based outbound campaign dialer that respects provider CPS limits; async workers for post-call processing (summary generation, structured field extraction, export).  
8. **Database**: Postgres for structured data (contacts, campaigns, calls, extracted fields, status) — this is a relational, reporting-heavy workload, not a vector/document-store problem at this stage. Object storage (S3-compatible, India-region for data-localization) for recordings.  
9. **Deployment**: containerized, deployed in an India-region cloud (Mumbai) for DPDP data-localization alignment. Managed LiveKit Cloud or Pipecat Cloud is a reasonable Phase-1 choice to avoid owning real-time media infra before you've validated conversation quality; revisit self-hosting purely as a cost optimization once volume justifies it.  
10. **Development roadmap**:  
    * **Phase 0 (now)**: single-number English prototype, no auth, cascaded pipeline (Plivo/Exotel \+ Deepgram \+ fast LLM \+ Cartesia) on LiveKit Agents or Pipecat, validated against real (not scripted) test calls for turn-detection quality.  
    * **Phase 1**: DLT registration \+ consent-capture flow \+ admin CSV upload/campaign/export UI; move from single-call testing to a rate-limited campaign dialer; nail down the absence-call domain logic (question flow, structured extraction schema, escalation rules).  
    * **Phase 2**: Telugu — swap STT/TTS to Sarvam, re-tune turn detection on real Telugu call audio, validate on your actual target population's dialect before declaring it production-ready.  
    * **Phase 3**: Tanglish code-switching, then generalize the domain layer (question flows, extraction schemas) so new use-cases beyond "absent students" are configuration, not new code.  
    * **Phase 4+**: additional Indian languages, scale-out concurrency, and only then revisit authentication/production hardening.

---

## **Sources**

This report draws on \~25 web searches across current (2026) provider documentation, independent benchmarking sites, and industry comparison articles, conducted August 2026\. Key sources cited inline include: Exotel, Plivo, and Twilio pricing/documentation pages; caller.digital, frejun.com, and awaaz.ai telephony comparison guides; TRAI-compliance guides (frejun.com, autointerviewai.com, ondial.ai, expressivr.com); DPDP Act guides (recordinglaw.com, caller.digital, gistly.ai); voice-platform comparisons (techsy.io, retellai.com, bland.ai, tested.media, alphacorp.ai); framework comparisons (thinnest.ai, forasoft.com, evalgent.com, techsy.io); STT/TTS benchmarks (assemblyai.com, futureagi.com, coval.ai, deepgram.com, gladia.io, codesota.com, burki.dev); Sarvam AI product pages; Groq/inference benchmarks (baytechconsulting.com, neuraplus-ai.github.io, apiscout.dev); cascaded-vs-speech-to-speech analysis (futureagi.com, deepgram.com, inworld.ai, reactify-solutions.com, softcery.com); cost models (inworld.ai, retellai.com, bitbytes.io, ravan.ai, caller.digital, famulor.io, klariqo.com); and Indian voice-AI competitor pages (gnani.ai, lumay.ai, vyora.ai, carmaone.ai).

**Given how fast this market is moving (several sources note major model/pricing changes within the last 1–2 months), re-verify pricing and latency figures directly against provider pages before committing to a contract — treat everything above as a well-sourced starting map, not a final quote.**

# Final approch

### 1\. The Final Technology Stack (The "Winning" Combination)

This stack is optimized for ultra-low latency (\<800ms), Indian telecom compliance, and natural turn-taking.

| Component | The Best Choice | Why it won (and what to avoid) |
| ----- | ----- | ----- |
| Telephony (India) | Exotel (Primary) or Plivo (Backup) | Avoid Twilio. Twilio is too expensive for domestic India, lacks local DLT hand-holding, and routes via international servers adding latency. Exotel/Plivo offer native Indian DIDs, WebSocket audio streaming, and DLT compliance dashboards. |
| Orchestration Framework | Pipecat (by Daily.co) | Avoid Vapi/Retell for the core engine. While Vapi/Retell are great for quick MVPs, they abstract away the audio buffer control. To achieve your goal of "human-like barge-in and turn-taking," you need Pipecat's granular, code-level control over the audio pipeline. |
| STT (English) | Deepgram (Nova-3 / Flux) | Unmatched speed (\<150ms latency). Specifically trained on telephony (8kHz) audio and handles Indian English accents far better than OpenAI Whisper. |
| STT (Telugu/Phase 2\) | Sarvam AI (Saaras) | Global models fail at "Tanglish" (Telugu-English code-switching). Sarvam is built specifically for Indic languages and mixed-script telephony audio. |
| TTS (English) | Cartesia (Sonic) or ElevenLabs (Turbo v2.5) | Cartesia wins on pure speed (\~40ms Time-To-First-Audio). ElevenLabs wins on emotional naturalness. Use Cartesia if latency is your \#1 priority; ElevenLabs if voice acting is. |
| TTS (Telugu/Phase 2\) | Sarvam AI (Bulbul V3) | ElevenLabs mispronounces Telugu names and places. Sarvam provides native prosody and handles regional dialects. |
| LLM (Brain) | Groq (Hosting Llama 3.1 8B/70B) | Avoid GPT-4o / o1 for every turn. They are too slow and expensive. Groq provides near-instant inference (crucial for voice). Use a fast model for 95% of the chat. |
| Backend API | Python (FastAPI) | Best ecosystem for AI, Pipecat integration, and asynchronous WebSocket handling. |
| State & Memory | Redis | Mandatory. You must store ephemeral call state, audio buffers, and barge-in flags in Redis for sub-millisecond access during the call. |
| Database | PostgreSQL | For persistent relational data: Campaigns, Student Lists, Call Logs, and Structured JSON Extractions. |
| Hosting / Cloud | AWS Mumbai (ap-south-1) | Non-negotiable. Hosting in the US/EU will add 200ms+ of network latency, ruining the "human" feel. Your servers must be in Mumbai. |

---

### 2\. The Core Architecture (How to achieve "Human" Quality)

To avoid the "User speaks  
→  
→ AI waits  
→  
→ AI thinks  
→  
→ AI speaks" robotic loop, you must implement a Continuous Full-Duplex Streaming Pipeline.

#### A. The "Secret Sauce": Semantic Endpointing & Barge-In

Do not rely on simple "silence timeouts" (e.g., waiting 800ms of silence to know the user is done). Humans say "um", pause to think, and take breaths.

1. Acoustic VAD (Silero): Runs locally on the audio stream to detect *any* human noise instantly.  
2. Semantic Endpointing: Send partial STT transcripts to a lightweight LLM classifier that asks: *"Is this a complete thought, or is the user just pausing?"*  
3. The Barge-In Event Bus: If the user speaks while the AI is talking, Pipecat must instantly send a clear\_buffer signal to the Telephony provider, flush the unplayed TTS audio, cancel the current LLM generation, and listen to the user.

#### B. Deterministic Logic vs. AI Logic

* AI (LLM) handles: Intent recognition, natural language generation, handling objections, and conversational empathy.  
* Code (Python/Pydantic) handles: Call state machine (Dialing  
* →  
* → Ringing  
* →  
* → Answered), Date/Time parsing, Student ID validation, and CSV export formatting. *Never let the LLM format your final database entries; it will hallucinate.*

---

### 3\. Indian Telecom & Compliance Strategy (The Make-or-Break Factor)

If you ignore this, TRAI (Telecom Regulatory Authority of India) and telecom operators will block your numbers within 48 hours.

1. SIM Cards / GSM Gateways: Absolutely forbidden. Using SIM farms for bulk automated calling is illegal telecom fraud in India. You must use enterprise Cloud Telephony (Exotel/Plivo).  
2. DLT Registration: You must register your business (or the College) as a "Principal Entity" on the telecom DLT portals.  
3. Number Series (Crucial):  
   * 140 Series: For Promotional/Marketing (Blocked on DND numbers). Do not use this.  
   * 160 Series / Standard DIDs: For Transactional/Service calls. Since a college calling its own students about attendance is a "Service/Transactional" call, you qualify for this. It bypasses DND restrictions *if* you have implicit consent.  
4. AI Disclosure: TRAI's 2025/2026 frameworks mandate that AI callers must not deceive. Your opening script must include: *"Hello, this is an automated AI assistant calling on behalf of \[College Name\]..."*  
5. Calling Hours: Strictly between 9:00 AM and 9:00 PM IST.  
6. Recording Consent: The AI must state, *"This call is being recorded for administrative purposes,"* within the first 10 seconds.

---

### 4\. The English

### →

### → Telugu Transition (Phase 2\)

The research universally agrees on one thing: An English pipeline will fail in Telugu.  
When you move to Phase 2, you do not rebuild the app; you only swap the "Speech Providers" via a Language Profile configuration.

* The Code-Switching Problem: Students will say, *"Nenu bus miss ayyindi, so late ga vasthanu."* Deepgram will turn this into gibberish.  
* The Swap:  
  * STT: Switch from Deepgram to Sarvam AI (specifically configured for Tanglish/code-mixing).  
  * TTS: Switch from Cartesia/ElevenLabs to Sarvam Bulbul V3.  
  * VAD Tuning: Telugu speakers have different cadences and elongate vowels at the end of sentences. You will need to increase your VAD silence threshold from 300ms (English) to \~500ms (Telugu) so the AI doesn't interrupt them mid-sentence.  
  * Entity Extraction: Force the LLM to output structured data (Dates, Reasons) in English/ASCII via JSON tool-calling, even if the conversation is in Telugu. This prevents database corruption.

---

### 5\. Your Step-by-Step Execution Roadmap

Do not build the web dashboard first. Build the voice loop first.

* Phase 1: The Telecom Proof (Days 1-5)  
  * Register an Exotel/Plivo account. Complete KYC using the College's entity documents.  
  * Provision a 160-series or Transactional DID.  
  * Write a basic Python script to initiate an outbound call and stream the raw 8kHz PCM audio to a local WebSocket.  
* Phase 2: The "Hello World" Voice Loop (Days 6-15)  
  * Implement Pipecat. Connect Exotel WebSockets  
  * →  
  * → Silero VAD  
  * →  
  * → Deepgram STT  
  * →  
  * → Groq (Llama 3\)  
  * →  
  * → Cartesia TTS  
  * →  
  * → back to Exotel.  
  * *Goal:* Have a 60-second conversation with the AI with zero robotic delays. Tune the barge-in logic until it feels natural.  
* Phase 3: The Business Logic (Days 16-25)  
  * Implement Pydantic schemas for the "Student Absence" workflow.  
  * Add Tool Calling: The LLM extracts {"reason": "fever", "return\_date": "2026-08-16"} and your Python backend validates the date and saves it to PostgreSQL.  
* Phase 4: The Campaign Engine & Dashboard (Days 26-40)  
  * Build the FastAPI backend to ingest CSVs.  
  * Use Redis Queues (Celery/BullMQ) to manage concurrent call limits (start with 10 concurrent, scale to 100+).  
  * Build the Next.js/React frontend for the Administrator to upload lists and download the final Excel report.  
* Phase 5: Telugu Pilot (Month 3\)  
  * Swap STT/TTS providers to Sarvam AI.  
  * Build a test dataset of 500 Tanglish audio clips to benchmark your new pipeline before deploying to students.

### Summary of the Strategy

You are not building a "Vapi clone." You are building an India-first, compliance-heavy, ultra-low-latency voice runtime using Exotel \+ Pipecat \+ Groq \+ Deepgram. This specific combination gives you the developer control needed to make the AI feel human, while respecting the strict realities of the Indian telecommunications grid.

# Tab 10

Twilo   
Livekti  
Agora  
Pipecat  
Bolna  
TEN framework  

---

# 5. Market & Vendor Research - India

> Consolidated from source file: AI_Voice_Calling_Agent_India_Research.md

# AI Voice Calling Agent — Independent Technical & Commercial Research (India, Aug 2026)

**How to read this:** Given the size of this brief, I'm not tagging every sentence. Instead: figures with a `(Source: ..., 2026)` note are things I found in current, dated sources — treat vendor blog numbers as *provider claims* unless I say "independent benchmark." Anything under a **"My take"** or **"Recommendation"** heading is my own inference/judgment, not a cited fact. I've flagged the places where I think your brief is making an assumption worth challenging.

---

## 0. TL;DR — the four places I'd push back on the brief

1. **Don't evaluate SIM/eSIM at all.** It's not a real option for this use case — no programmability, no legal outbound-calling compliance path, no concurrency, no audio streaming. The real decision is *which cloud telephony/CPaaS provider*, not telephony architecture type.
2. **"Best latency" and "best voice quality" are not settled by picking one vendor.** The entire market has converged on a *cascaded* pipeline (STT → LLM → TTS) as the production default, specifically *because* your core requirement — structured data extraction ("why were you absent," "when will you return") — needs reliable tool-calling and auditable text at every stage. Speech-to-speech models (OpenAI Realtime, Gemini Live) are lower-latency in theory but worse at exactly the thing your admin-use-case needs most. This is the single biggest architectural decision in your brief, and I'd resolve it in the opposite direction of where "most natural conversation" intuition points.
3. **Telugu is not a "harder version of English" — it's a different vendor stack.** None of the providers that are strong in English (Deepgram, Cartesia, ElevenLabs, AssemblyAI) have credible production Telugu. The market has a genuine India-first specialist (Sarvam AI) that is *purpose-built* for this, including Telugu-English code-switching. Plan for a stack swap, not a stack extension, in Phase 2.
4. **Cost math: "AI is cheaper than a human caller" is not obviously true in India at your scale.** In the US, human agents cost $35–50k/year, making AI's ~$0.05–0.25/min trivially cheaper. In India, a telecaller costs roughly ₹15,000–25,000/month and handles ~2,500–3,500 calls/month at ~3 min average — that's roughly ₹2–3.5/min *fully loaded*, which is in the same range as, or cheaper than, a well-run AI stack at low volume once you include Indian STT/TTS/LLM/telephony costs. AI's actual advantage for your use case is concurrency, 24/7 availability, consistency of data capture, and not needing to staff a calling team every semester — not raw per-minute cost. Sell it internally on that basis, not on "cheaper than a human."

---

## 1. Telephony: the real decision is which CPaaS provider, not what "kind" of number

### Why SIM/eSIM is off the table
A physical/eSIM-based approach (a phone connected to a modem/GSM gateway) has no API-level call control, no reliable concurrency beyond the number of physical SIMs you buy, no programmatic WebSocket/RTP audio access for STT/TTS integration, and critically, **no path to DLT compliance** — Indian carriers treat bulk automated calling from a personal-SIM-style number as spam and will silently block or throttle it (Source: multiple TRAI-compliance guides, 2026). This isn't a trade-off to weigh against cloud telephony; it simply doesn't do the job.

### The real shortlist for India

| Provider | India fit | Outbound rate (typical) | Number rental | Streaming for voice AI | DLT handling | Notes |
|---|---|---|---|---|---|---|
| **Exotel** | India/APAC-native, UL-VNO licensed telecom operator | ~₹0.80–1.00/min (Source: Exotel migration guide, 2026) | Varies by plan | AgentStream — bidirectional WebSocket, 16-bit 8kHz PCM, <20–50ms media latency (provider claim) | Strongest — handles DLT/DND as part of the platform (Source: caller.digital, 2026) | Best "compliance handled for you" option; ~10–25% pricier than Plivo per-minute (Source: caller.digital, 2026) |
| **Plivo** | Global CPaaS with strong India presence | Local outbound ~₹0.60/min (Source: awaaz.ai, 2026) | ~₹250/month (Source: awaaz.ai, 2026) | Native SIP trunking + audio streaming; explicitly integrates with LiveKit and Pipecat (Source: Plivo pricing page, 2026) | Competent, self-managed DLT registration | Best "developer-first, cheapest to prototype on" option; 24–48hr Indian DID provisioning (Source: caller.digital, 2026) |
| **Ozonetel** | India CCaaS + telephony | Unlimited-minute agent pricing on some plans (unusual model) | — | Yes | Strong | Leans more contact-center-suite than raw API; good if you eventually want agent-desktop/CCaaS features |
| **Knowlarity (Vonage)** | India-native | — | — | Yes | Strong | Similar profile to Exotel |
| **Twilio** | Global, weakest India economics | ~₹1.20–1.50/min outbound, ~₹0.50–0.80 inbound (Source: Exotel migration guide citing Twilio's own India pricing, 2026) | — | Best-in-class docs, `<Stream>` verb, ConversationRelay | DLT is **self-managed with no platform tooling** (Source: frejun.com, 2026) | 50–100% more expensive than India-native providers for India-domestic calls; best documentation ecosystem but that's not worth the premium here |
| **Bolna (open-source India-focused agent framework)** | India-specific, ships **Sarvam + Twilio-India defaults out of the box** (Source: thinnest.ai framework comparison, 2026) | Depends on underlying telephony chosen | — | Built for exactly this stack | Handled at the framework level | Worth evaluating directly — it's the framework in this landscape closest to "built for an India + regional-language voice agent," see §12 |

**Reality check on the pricing figures above:** these numbers come from vendor blogs and comparison sites, not directly from a live quote. Treat them as *directionally correct, not contractual* — get an itemized INR quote from 2–3 providers before committing, since several sources explicitly warn that "quote only in USD" or vague per-minute figures are a red flag at contract stage (Source: frejun.com voice-api-india guide, 2026).

### KYC / DLT / regulatory requirements (this is not optional paperwork — see §10 for the full legal picture)
- Register as a **Principal Entity** on TRAI's DLT platform (PAN, GST, CIN, Aadhaar biometric auth required); one-time fee ~₹5,900 on the first TSP platform (Source: frejun.com TRAI guide, 2026).
- Choose the correct number series: **140-series** for promotional/marketing calls, **1600-series** (was 160) for BFSI/transactional service calls (Source: multiple TRAI-compliance guides, 2026). **Neither cleanly fits an educational-institution "why were you absent" call** — this is a genuine gray area (see §10). Get this classified correctly before your first campaign; carriers silently drop non-compliant calls rather than erroring (Source: autointerviewai.com, 2026).
- Registration typically takes 5–10 business days when documentation is correct, longer if resubmission is needed (Source: multiple sources, 2026).

### Recommendation
Prototype on **Plivo** (cheapest, cleanest API, works directly with LiveKit/Pipecat, fast DID provisioning) or **Exotel** if you'd rather have DLT/compliance handled for you at a ~15–25% cost premium. Do **not** start with Twilio for India-domestic calling — its India economics are worse on every axis and its DLT tooling is weaker, and its main advantage (documentation quality) matters less once you're using LiveKit/Pipecat docs instead of Twilio's. Register DLT in parallel with prototyping — it's the long pole, and calls will silently fail without it once you leave a sandbox/test-number phase.

---

## 2. Real-time voice architecture: the components, ranked by effect on perceived quality

A production voice agent is a pipeline, not a model:

**Telephony (PSTN/SIP) → Audio streaming (WebSocket/RTP) → VAD → STT (streaming) → Turn/endpoint detection → LLM (streaming, with tool calling) → TTS (streaming) → Audio playback**, wrapped in session/state management that tracks conversation history, call status, and structured data extraction per call.

Ranked by how much each one actually affects whether a caller thinks they're talking to a human (my inference, based on the aggregate of what the sourced benchmarks measure and emphasize):

1. **Turn detection / endpointing** — this is the component every serious 2026 source calls "the least understood and most important" (Source: autointerviewai.com, 2026). Get this wrong and nothing else matters: the agent either talks over people or leaves robotic dead air.
2. **TTS time-to-first-audio** — the single largest controllable contributor to perceived responsiveness (Source: codesota.com, burki.dev, 2026).
3. **STT streaming latency + accuracy on telephone-quality (8kHz, noisy) audio** — most STT benchmarks are run on clean audio; production phone audio is materially harder (Source: sarvam.ai, gladia.io, 2026).
4. **LLM time-to-first-token**, less so total generation time, since responses stream.
5. **Barge-in / interruption handling** — technically straightforward (stop TTS playback, flush buffer) but the *policy* around it (is this a real interruption or a backchannel "mhm"?) is where quality is actually won or lost.

**My take:** most teams over-invest in "which LLM" and under-invest in turn detection and TTS latency tuning. For your project, I'd budget engineering time in the opposite proportion to where the brief's question list implies effort — turn-taking tuning and TTS provider selection will move the needle on "feels human" far more than LLM choice will.

---

## 3. Latency: the pipeline and realistic targets

**Human conversational turn-taking gap averages ~200ms** (Source: reactify-solutions.com citing production 2026 figures). No cascaded system fully matches this yet, but the target for "doesn't feel robotic" is generally cited as **under ~800ms** end-of-caller-speech to start-of-agent-speech, with a hard ceiling around 900ms–1.2s before callers perceive it as "the AI is thinking" (Source: retellai.com, autointerviewai.com, 2026).

Realistic 2026 component budget for a well-tuned cascaded pipeline (my synthesis of the sourced benchmarks in §5–§7, not a single vendor's number):

| Stage | Typical range (2026, tuned) |
|---|---|
| VAD / end-of-turn detection | ~200–300ms (Silero VAD baseline; semantic/prosody turn detectors add ~20ms but cut false-cutoffs) (Source: reactify-solutions.com, livekit docs, 2026) |
| STT first-partial / streaming | 100–300ms (Deepgram Nova-3/Flux, AssemblyAI Universal-Streaming) (Source: assemblyai.com, futureagi.com, 2026) |
| LLM time-to-first-token | 200–300ms on a fast small model via Groq; 300–600ms+ on a standard hosted frontier model (Source: neuraplus-ai, reactify-solutions.com, 2026) |
| TTS time-to-first-audio | 40–90ms (Cartesia Sonic) to 75–300ms (ElevenLabs, depending on model tier) (Source: multiple TTS comparisons, 2026) |
| Network/orchestration overhead | 50–200ms depending on region pinning (Source: reactify-solutions.com, 2026) |
| **Realistic end-to-end (tuned, cascaded)** | **~600–900ms median**, matching what Retell/Vapi/LiveKit teams report in independent 2026 tests (Source: techsy.io head-to-head test, tested.media, 2026) |

**My take:** don't chase sub-500ms as a Phase-1 target — even the best-funded commercial platforms (Retell, Vapi) sit at 500–900ms median in independent testing, with P95 regularly exceeding 1.5s under load (Source: techsy.io, 2026). A more useful Phase-1 goal is "consistent 700–900ms with no P95 tail above ~1.5s," because *consistency* matters more to perceived quality than best-case latency (Source: retellai.com, 2026).

---

## 4. Interruption & turn-taking

The 2026 production pattern has three layers, and this is worth building deliberately rather than treating as a VAD afterthought:

1. **VAD (Voice Activity Detection)** — continuous per-frame confidence that incoming audio contains a voice. Silero VAD is the open-source default used across LiveKit, Pipecat, and most managed platforms.
2. **Endpointing** — deciding *when* the user's turn has actually ended. Pure silence-threshold endpointing (typically 700–1000ms of silence) is the baseline but can't distinguish a genuine pause from someone still thinking mid-sentence (Source: autointerviewai.com, 2026).
3. **Semantic/prosody turn detection** — the 2026 upgrade path: models that read pitch drop, rising intonation, and semantic completeness of the partial transcript to distinguish "done talking" from "thinking pause" from "backchannel" (uh-huh/mhm). LiveKit's Turn Detector v1 reports a **9.9% false-cutoff rate at a 300ms latency budget** in their own testing (Source: livekit/autointerviewai.com, 2026) — an independently-reproducible number worth validating on your own audio before trusting it wholesale. Deepgram's **Flux** model folds end-of-turn detection directly into the STT model, claiming under 300ms median with no external VAD needed (Source: coval.ai, 2026 — vendor claim).

For interruption handling specifically: when the caller speaks while the agent is talking, the system needs to distinguish a genuine interruption ("actually, wait—") from background noise or a backchannel, then immediately stop TTS playback and discard unplayed audio if it's genuine. This is largely a solved engineering pattern in LiveKit Agents and Pipecat (both ship "adaptive interruption handling" and "false interruption" guards out of the box per their docs) — I would not try to build this from scratch.

**My take:** For your college-absence use case specifically, students will frequently pause mid-explanation ("I was... um... I had a family thing"). A silence-only endpointer will cut them off. Budget explicit tuning time for endpointing thresholds against real Indian-English and Telugu speech patterns — this is exactly the kind of thing that reads fine in a demo and breaks on real calls.

---

## 5. Voice quality (TTS) — don't assume open-source is cheaper or better

| Provider | Time-to-first-audio | Strength | Weakness | Telugu? |
|---|---|---|---|---|
| **Cartesia Sonic** | ~40–90ms (Source: multiple 2026 comparisons) | Latency leader; State Space Model architecture, not transformer-based | Voice character/emotional range slightly behind ElevenLabs; latency *spread* is wider than ElevenLabs (Source: forasoft.com, 2026) | No |
| **ElevenLabs (Flash v2.5 / Turbo)** | ~75–300ms depending on model tier | Best voice realism/emotional expressiveness, cloning, broadest language count (32+) | Slower than Cartesia on the fast path; the highest-quality models (Multilingual v2) are 500–800ms — too slow for real-time turns | Limited — general multilingual, not Telugu-specialist |
| **Deepgram Aura-2** | ~90ms tuned | Bundled into Deepgram's Voice Agent API (single WebSocket for STT+LLM+TTS) | Newer, less proven on voice character | No |
| **Sarvam Bulbul V3** | Sub-250ms first-byte via WebSocket (provider claim, sarvam.ai 2026) | **Purpose-built for Telugu and 10 other Indian languages** — vowel harmony, Tenglish code-switching, Indian name/number pronunciation, top-ranked in a Josh Talks blind study of 20k+ votes (provider-cited study) | Not competitive for pure-English use vs. Cartesia/ElevenLabs | **Yes — this is the answer to your Telugu TTS question** |

**My take on "open-source vs. paid":** the brief specifically asks not to assume open-source is automatically cheaper/better, and the evidence supports that skepticism — self-hosted open-weight TTS (e.g., Kokoro) is genuinely cheaper at very high volume but requires you to own GPU infrastructure, and for a project whose *entire differentiator is voice quality*, that's the wrong place to cut corners in Phase 1. Rent a top-tier API until conversation quality is proven, then reconsider self-hosting purely as a cost optimization once volume justifies it.

**Recommendation:** Cartesia Sonic for English (latency-critical outbound calls, where every hundred milliseconds compounds into "feels robotic"). Sarvam Bulbul V3 for Telugu — there isn't a credible alternative with comparable Telugu-specific tuning (code-switching, prosody, name pronunciation) among the global providers.

---

## 6. Speech recognition (STT) — telephone audio is the hard case, and vendor benchmarks mostly don't test it

Independent 2026 benchmarking (Hamming.ai, 4M+ production calls) found **AssemblyAI's Universal-3 Pro Streaming faster *and* more accurate than Deepgram Nova-3** on real production call audio — 307ms P50 latency / 8.14% WER vs. Deepgram's 516ms / 9.87% (Source: assemblyai.com citing Hamming.ai, 2026 — note this is AssemblyAI's own blog citing a third-party benchmark, so treat the framing with mild skepticism even though the underlying benchmark is independent). Deepgram's counter is **Flux**, a model purpose-built for voice agents that folds end-of-turn detection into the STT step itself and posts the lowest end-of-speech latency as of mid-2026 (Source: coval.ai, futureagi.com, 2026).

Word error rate has genuinely plateaued among the top players on *clean* audio — Deepgram Nova-3, AssemblyAI Universal-3 Pro, OpenAI gpt-4o-transcribe, ElevenLabs Scribe v2, and Microsoft's MAI-Transcribe-1 all sit within 1–2 percentage points of each other on standard benchmarks (Source: coval.ai, 2026). **The real competitive surface has moved to streaming latency, end-of-turn detection, and multilingual/code-switching depth** — which is exactly where the India/Telugu question becomes decisive.

For Telugu (and Indian accents generally), **Sarvam's Saaras v3** is the standout: trained on 1M+ hours of real Indian audio specifically (not adapted from an English-first model), explicitly built for 8kHz noisy telephony audio rather than clean studio recordings, with native code-mixing/diarization support and <150ms time-to-first-token (provider claim, sarvam.ai 2026). **Gnani.ai** is the enterprise alternative — 14M+ hours of Indian telephony training data, #1 on 8 of 9 Indian languages on the "Kathbath Noisy" benchmark (provider claim), but it's an enterprise-only, custom-pricing platform rather than a self-serve API, which matters for a bootstrapped project.

**Recommendation:** Deepgram (Flux, for the built-in turn detection) or AssemblyAI for English. Sarvam Saaras v3 for Telugu — same reasoning as TTS above.

---

## 7. LLM strategy — this is where I'd most directly challenge the brief's framing

### Does this need a large reasoning model? Mostly no.
The actual reasoning load per turn in your use case (understand "I was absent because my grandmother was in the hospital," extract a reason, decide the next question, detect when the conversation is complete) is not a hard reasoning problem — it's closer to structured intent classification + slot-filling with natural-language wrapping. This is squarely in "small/fast model" territory, not "frontier reasoning model" territory.

**Groq's LPU-hosted open models** deliver genuinely large latency wins here: Llama 3.3 70B running at ~276+ tokens/sec on Groq vs. ~40–80 tokens/sec for GPT-4o on OpenAI's standard API (Source: apiscout.dev, 2026), and independent testing puts full voice-pipeline latency (STT + LLM + TTS) at ~330ms using Groq vs. ~880ms using an H100-hosted equivalent (Source: neuraplus-ai.github.io, 2026 — this is a third-party benchmark site, treat the exact numbers as illustrative rather than guaranteed on your traffic). Cost follows the same pattern: Groq's Llama 3.1 8B is $0.05/million input tokens; GPT-4o-mini is $0.15/$0.60 per million input/output (Source: baytechconsulting.com, aipricing.guru, 2026).

**Where you *do* want more model capability:** edge cases — an ambiguous or emotionally loaded response from a student, a request to speak to a human, detecting that the "reason for absence" needs escalation (e.g., mentions of a safety issue). My recommendation there isn't "use a bigger model for every turn" but "route": run the fast/cheap model by default, and have deterministic logic (keyword/intent triggers) escalate specific turns to a stronger model or to a human-handoff flow. This is standard practice in the platforms reviewed above (Vapi's server-side function calling, Bland's Pathways) and keeps both cost and latency low on the 95% of turns that don't need it.

### Cascaded vs. speech-to-speech — resolve this explicitly, don't default to whichever sounds more "cutting edge"
This is the architecture decision I think the brief under-weights. As of mid-2026:

- **Speech-to-speech models** (OpenAI Realtime `gpt-realtime`, Google Gemini Live) process audio-in/audio-out in a single model pass, cutting the STT→LLM→TTS latency chain. TTFA in independent testing ranges ~0.78s (xAI) to ~2.98s (Gemini 3.1 Flash Live), with OpenAI's `gpt-realtime-1.5` around 0.82s (Source: softcery.com Artificial Analysis-sourced benchmark, April 2026) — **notably, this is not obviously faster than a well-tuned cascaded pipeline** (§3 above put tuned cascaded at 600–900ms).
- **Cascaded pipelines** give you a text artifact at every stage — critical for exactly what your brief asks for: transcripts, structured summaries, audit logs, tool-calling for CSV-field extraction. Independent analysis is blunt about this trade-off: *"for agents that need 5+ tools with strict schema enforcement (booking, payments, healthcare intake, structured form filling), cascaded is the safer 2026 default"* (Source: futureagi.com, 2026) — **your absent-student use case is structured-form-filling.** Cascaded also remains the enterprise/compliance default because every stage is independently observable, loggable, and redactable (Source: deepgram.com, reactify-solutions.com, 2026).
- Speech-to-speech also currently has materially weaker language coverage — this matters directly for your Telugu roadmap, since neither OpenAI Realtime nor Gemini Live has anything close to Sarvam's Telugu depth.

**Recommendation:** cascaded architecture (STT → LLM with tool-calling → TTS), not speech-to-speech, for this entire project. This isn't a "settle for less exciting tech" call — it's the architecture every credible 2026 source converges on for exactly your requirements (structured extraction, auditability, non-English languages).

---

## 8. Cost — worked estimates, and why "cheaper than a human" isn't automatic in India

### Per-minute component cost (my synthesis of the sourced ranges above, self-built cascaded stack, English)

| Component | Range (₹/min) |
|---|---|
| Telephony (Plivo/Exotel local outbound) | ₹0.60–1.00 |
| STT (Deepgram/AssemblyAI) | ₹0.50–1.00 |
| LLM (Groq-hosted small/fast model) | ₹0.20–1.00 |
| TTS (Cartesia) | ₹1.00–2.00 |
| **Total (English, self-built)** | **~₹3–5/min** |

For Telugu, swap in Sarvam pricing (STT ₹1.5/min flat; TTS ~₹30 per 10k characters, which works out to roughly ₹2–3/min at typical conversational pace): expect **~₹4.50–7.50/min all-in** for Telugu, before infra/hosting overhead.

For context, if you instead *bought* a fully managed Indian voice-AI vendor (Gnani, Skit, Yellow.ai, etc.) rather than building, expect **₹4.50–9/min plus a platform fee of ₹1–6 lakh/month** at meaningful scale (Source: caller.digital, 2026) — that's the "buy" price, and it's the reason a build-your-own approach is worth the engineering investment for a project where voice quality is the whole point and long-term unit economics matter (e.g., if you later commercialize this for other colleges).

### Monthly cost at scale (assuming ~3 min average call, English, self-built stack, ~₹4/min all-in including infra amortization)

| Volume | Minutes/month | Approx. monthly cost |
|---|---|---|
| 100 calls | ~300 | ₹1,200–1,500 |
| 1,000 calls | ~3,000 | ₹12,000–15,000 |
| 10,000 calls | ~30,000 | ₹1.2–1.5 lakh |
| 100,000 calls | ~300,000 | ₹10–13 lakh (volume discounts typically kick in, bringing effective rate toward ₹3.5–4/min) |

These are component costs only — add DLT registration (~₹5,900 one-time + template fees), number rental (~₹250–1,000/month per number), hosting/infra for your orchestration layer, storage for recordings/transcripts (marginal), and engineering time.

### The human-calling comparison, done honestly for India
US-context comparisons (the kind that show up in most vendor blogs) compare AI at $0.05–0.25/min to a US call-center agent at $35–50k/year — a comparison that doesn't transfer to India. A campus/admin telecaller in India typically costs **₹15,000–25,000/month fully loaded**, and can plausibly handle 80–150 calls/day depending on call complexity — at ~2,500–3,500 calls/month and ~3 min average, that's roughly **₹2–3.5/min**, which is *at or below* the low end of your self-built AI cost, and meaningfully below a bought managed platform. 

**My take:** don't pitch this project on "AI is cheaper per minute than a human" in the Indian context — for your absent-student use case specifically, the real value is (a) every student gets called on the same day rather than admin staff working through a list over days, (b) structured, consistent data capture (reason, expected return date) instead of handwritten notes, (c) zero marginal cost to scale to every section/hostel simultaneously, and (d) it runs outside office hours. That's a genuinely strong pitch — it's just a different pitch than "cost savings."

---

## 9. Scalability

| Concurrency | What breaks first |
|---|---|
| 1 call | Nothing — this is where you validate conversation quality |
| 10 concurrent | Still trivial on any provider; useful for load-testing turn-detection tuning under real network jitter |
| 100 concurrent | Telephony provider's **channel/CPS (calls-per-second) limits** become the first bottleneck — Plivo's AI-agent tier, for example, is quoted at 50 concurrent calls / 3 CPS on its documented plan (Source: Plivo pricing page, 2026); you'll need to confirm and likely negotiate higher limits, or shard across multiple provider accounts/numbers |
| 1,000 concurrent | This is enterprise-scale telephony provisioning — direct carrier SIP trunking (the "20 lakh+ minutes/month" tier some sources describe going direct to Airtel/Jio) rather than a standard CPaaS plan (Source: caller.digital, 2026); at this point your LLM/STT/TTS provider rate limits and your own orchestration layer's horizontal scaling (stateless WebSocket workers behind a load balancer, session state in Redis/Postgres, a queue-throttled outbound dialer respecting CPS limits) become the binding constraints, not any single component |

**My take on architecture for this:** use a framework that already solves the concurrency/session-management problem rather than building it — LiveKit Agents and Pipecat both handle per-call session isolation, horizontal worker scaling, and WebRTC/SIP media at scale as first-class concerns (Source: multiple framework comparisons, 2026). Building your own WebSocket-per-call orchestrator from scratch is exactly the kind of "not your differentiator" engineering effort I'd avoid — your differentiator is conversation quality and domain flexibility, not real-time media infrastructure.

For a *campaign* use case specifically (call all absent students today), you also need a **rate-limited outbound dialer** — a queue that respects your telephony provider's CPS limit and retries on no-answer/busy according to a policy you define, independent of your real-time voice engine's own concurrency.

---

## 10. Indian telecom/legal — this needs actual legal review, not just engineering

I want to be direct about the limits of what I can tell you here: **this section should not be treated as legal advice, and several points below are genuinely unresolved gray areas that need a lawyer, not a search engine.**

**What's clear from current sources:**
- **DLT registration is mandatory** for any commercial/business outbound calling in India — register as a Principal Entity, register your number series and call templates, before making any calls (Source: TRAI TCCCPR framework, multiple 2026 compliance guides).
- **TRAI classifies AI-generated voices under existing robocall/TCPA-equivalent rules** — meaning your AI calling platform is legally treated the same as any automated dialing system, not as a novel unregulated category (Source: qcall.ai, 2026).
- **Following the 2026 IT Rules amendment, AI voice agents must self-identify as automated at the start of the call** and must not impersonate a specific real individual (Source: autointerviewai.com, 2026).
- **DPDP Act 2023 + DPDP Rules 2025** (notified Nov 13, 2025) govern what you can do with the *data* generated by the call — the recording, transcript, and any extracted fields are all "personal data." You need purpose-specific, informed consent (not just a TRAI dial-permission), a defined retention period, and — notably — **data localization**: Indian personal data should be processed/stored within India, and if you route audio through an international LLM/STT/TTS provider, you need to understand where that data actually flows (Source: caller.digital, gistly.ai, 2026). This is directly relevant to your provider choice — Sarvam explicitly markets India-only data processing/storage as a compliance feature; verify the equivalent for whichever English-stack providers you pick.
- **Indian law is generally one-party consent for recording** (if your institution is a participant in the call, you can record it) — but DPDP's *processing* consent requirement is separate and additional to this (Source: frejun.com, caller.digital, 2026).

**The genuine gray area for your specific use case:** TRAI's number-series framework is built around **promotional (140-series)** vs **transactional/service (1600-series, BFSI-oriented)** calls. A college calling an already-enrolled student's registered number to ask about an absence is neither classic marketing nor a BFSI transaction — it's institutional/administrative outreach to an existing relationship. None of the sources I found address this category directly. **Recommendation: get this specific classification confirmed with your DLT-registration provider or telecom counsel before your first real campaign** — misclassifying it risks calls being silently dropped (wrong series) or, worse, a DND/consent complaint if students haven't been asked to opt in to this kind of automated call. A pragmatic mitigation: collect explicit consent for "the college may call you or your guardian using an automated system regarding attendance" at admission/enrollment time, which sidesteps most of the ambiguity.

- **Recording retention**: sector guides cite RBI-style retention windows (6 months–3 years) for regulated (BFSI) sectors; there's no equivalent published standard for education specifically — set a defined, disclosed retention policy rather than keeping everything indefinitely, both for DPDP compliance and to bound your own storage costs.

---

## 11. English → Telugu: what actually changes

This is the section where I'd tell you most directly: **treat Phase 2 as a second STT/TTS integration project, not a configuration change.**

What changes:
1. **STT and TTS providers swap entirely.** Deepgram/AssemblyAI (STT) and Cartesia/ElevenLabs (TTS) — your likely English-phase choices — do not have credible production Telugu. **Sarvam AI (Saaras v3 for STT, Bulbul V3 for TTS)** is the standout India-specific option, explicitly built and benchmarked on Telugu, with sub-250ms/sub-150ms latency claims, native Telugu-English code-switching ("Tenglish"), and correct handling of Indian names/numbers (Source: sarvam.ai product pages, 2026 — these are provider claims; validate WER/latency against your own call audio before committing, exactly as the STT benchmarking sources above caution generally).
2. **Code-switching is not an edge case in Telugu, it's the norm.** Real conversational Telugu (as shown in Sarvam's own example transcripts) constantly mixes in English words mid-sentence ("naa account balance check cheyali"). An STT/TTS stack that treats this as noise will fail constantly; Sarvam's models are explicitly trained for this.
3. **The LLM layer can likely stay similar** (most frontier and mid-tier LLMs handle Telugu text reasonably for understanding intent, even if you wouldn't trust them for Telugu *voice*) — but you should validate that your chosen model doesn't silently default to Hindi or standard-register Telugu when the input transcript contains colloquial or regional phrasing.
4. **Turn-detection tuning likely needs to be redone**, not reused — Telugu sentence rhythm, pause patterns, and prosody differ from English, and the semantic/prosody turn-detection models discussed in §4 are typically trained/tuned on specific language data.
5. **Regional variation and dialect**: sourced comparisons note real accuracy variance by region even within a single Indian language (e.g., one WER benchmark noted "Delhi Hindi" claims collapsing on "Lucknow Awadhi-influenced Hindi" in practice — Source: caller.digital, 2026). The equivalent risk exists for Telugu across Telangana/Andhra/coastal-vs-Rayalaseema variation. **Don't accept a vendor's aggregate Telugu WER claim — test against audio from your actual target population** (your parents' boutique customer base or students' likely demographic, depending on which project this is for).

**Biggest current ecosystem gap:** there is no evidence of a mature, production-proven **speech-to-speech** option for Telugu (the OpenAI Realtime / Gemini Live category) — reinforcing the cascaded-architecture recommendation in §7, since it's the only path with credible Telugu coverage at all.

---

## 12. Competitive landscape

Two genuinely different categories are relevant to you, and I'd resist conflating them:

**Global/English-first voice-agent platforms** (Retell AI, Vapi, Bland AI, plus the open-source LiveKit Agents/Pipecat): differentiate mainly on latency consistency, developer control, and pricing transparency — not on anything India- or Telugu-specific. Independent 2026 head-to-head testing found Retell fastest/most consistent (~600–620ms median, ~$0.07/min), Vapi most flexible (component-level control, BYOK, effective cost $0.12–0.33/min once the full stack is added), Bland strongest for high-volume deterministic outbound flows (~700–900ms, bundled pricing) (Source: techsy.io independent build-on-all-three test, 2026). None of these have meaningful Telugu.

**India-specific voice AI vendors** (Gnani.ai, Skit.ai, Yellow.ai, Bolna, Sarvam, Caller Digital, Squadstack): this is the more relevant comparison set for your roadmap.
- **Gnani.ai** is the largest India-headquartered player by scale (30M+ daily conversations, 40+ languages/dialects including deep Telugu coverage, 14M hours of Indian telephony training data, government IndiaAI Mission selection) — but it's enterprise-only with custom pricing, not a self-serve API you'd build a prototype on (Source: caller.digital, gnani.ai, 2026).
- **Skit.ai** — outbound-native, strong in collections/insurance, "Hyper-Real" prosody claims (provider claim).
- **Bolna** — the most directly relevant to your build-it-yourself plan: an open-source agent framework that **ships Sarvam + Twilio-India as defaults**, i.e., someone has already assembled roughly the stack this report recommends. Worth evaluating as a starting point rather than building your orchestration layer fully from scratch (Source: thinnest.ai, bolna.ai, 2026).
- **Sarvam AI** — not a full voice-agent platform, but the STT/TTS layer underlying several of the above; you can use it directly.

**My take on what actually differentiates the strongest systems** (synthesizing across all the sourced comparisons rather than any single vendor's marketing): it is *not* raw model quality — WER and TTS MOS scores have converged across top providers. The differentiators that show up consistently across independent 2026 testing are: (1) turn-detection tuning specific to the target language/population, (2) pricing transparency vs. hidden per-component markups, and (3) for the India-specific vendors, actual dialect/regional coverage validated on real audio rather than a single benchmark language variant. Marketing claims about "hyper-real" or "indistinguishable from human" should be discounted heavily — none of the independent, third-party benchmarks I found support a categorical "indistinguishable" claim for any vendor.

---

## 13. Critical risks — direct challenges to the project

- **Robotic voice / high latency**: the median achievable latency in 2026 (600–900ms, per §3) is still roughly 3–4x slower than human-to-human turn-taking (~200ms). No amount of vendor selection closes this gap entirely — manage expectations that "as close to human as technically possible" still has a perceptible, if small, robotic edge in 2026. This isn't a solvable-with-more-budget problem; it's close to the current technical frontier.
- **Poor turn detection / false interruptions**: this is the failure mode most likely to make the *English* version feel bad even with a good voice — and it needs real-call tuning, not just picking a good-sounding vendor.
- **Telugu quality risk is the single biggest project risk in your roadmap**, not a secondary concern — you have exactly one credible specialist vendor (Sarvam) for the full stack; if its Telugu performance on your actual population doesn't hold up, there is no obvious second choice at comparable maturity today.
- **Hallucination / incorrect information extraction**: for the absent-student use case, an LLM inferring a plausible-but-wrong "reason for absence" or "expected return date" is a real risk with real consequences (a college acting on fabricated data). Mitigate with strict tool-calling/function-schema enforcement (part of why cascaded > speech-to-speech here), and a "low confidence → flag for human review" path rather than trusting every extraction.
- **Telecom/regulatory risk**: silently dropped calls due to DLT misclassification, or a DPDP complaint from a student/parent about an unconsented automated call, are both plausible operational failure modes, not hypothetical ones — build the consent-capture step into your admin/enrollment flow now, not as an afterthought before "moving to production" (your prototype-phase "no auth needed" plan is fine for internal testing, but the *consent and DLT compliance* pieces are not something you can defer the same way — they gate whether calls connect at all).
- **Concurrency/provider lock-in**: standard CPaaS concurrency tiers (tens of concurrent calls) will not support a "call every absent student across a large college simultaneously" campaign without either a higher-tier plan or a properly throttled dialer — plan the campaign dialer's pacing explicitly rather than assuming the telephony provider absorbs bursts for free.
- **Cost risk at scale**: the ₹4-9/min range for a bought platform, or ₹3-7/min for a well-built one, is a real ongoing cost once you're calling thousands of students per campaign across multiple colleges — model this against your actual expected campaign frequency before assuming "AI is basically free at scale."

---

## 14. Recommended technology strategy

*(Recommendations, explicitly — not facts. Multiple viable alternatives are noted for each.)*

1. **Telephony**: Start on **Plivo** (cheapest, LiveKit/Pipecat-native, fast DID provisioning). Move to **Exotel** if you want DLT/compliance handled for you at a modest premium, or once call volume justifies enterprise support. Avoid Twilio for India-domestic calling.
2. **Indian number approach**: DLT-registered virtual number via the chosen CPaaS provider — not SIM/eSIM. Start DLT Principal Entity registration in parallel with prototyping, since it's the longest lead-time item.
3. **STT**: Deepgram (Flux, for built-in turn detection) or AssemblyAI for English. **Sarvam Saaras v3** for Telugu — no credible alternative at comparable maturity.
4. **TTS**: **Cartesia Sonic** for English (latency-critical). **Sarvam Bulbul V3** for Telugu.
5. **LLM strategy**: cascaded (not speech-to-speech) architecture throughout, for tool-calling reliability and Telugu support. Default to a fast/cheap model (Groq-hosted Llama 3.3-class, or GPT-4o-mini-class) for standard turns; add deterministic escalation logic (not a bigger model on every turn) for ambiguous/sensitive responses.
6. **Real-time communication architecture**: build on **LiveKit Agents** or **Pipecat** rather than a from-scratch WebSocket orchestrator — both solve session isolation, concurrency scaling, and telephony integration as first-class problems, and both plug directly into Plivo/Exotel and every STT/TTS/LLM provider above. Consider evaluating **Bolna** directly as a starting scaffold, since it's already assembled close to this exact stack for the Indian market.
7. **Backend architecture**: FastAPI (or equivalent) admin/API layer + your chosen agent framework for the real-time voice layer; a queue-based outbound campaign dialer that respects provider CPS limits; async workers for post-call processing (summary generation, structured field extraction, export).
8. **Database**: Postgres for structured data (contacts, campaigns, calls, extracted fields, status) — this is a relational, reporting-heavy workload, not a vector/document-store problem at this stage. Object storage (S3-compatible, India-region for data-localization) for recordings.
9. **Deployment**: containerized, deployed in an India-region cloud (Mumbai) for DPDP data-localization alignment. Managed LiveKit Cloud or Pipecat Cloud is a reasonable Phase-1 choice to avoid owning real-time media infra before you've validated conversation quality; revisit self-hosting purely as a cost optimization once volume justifies it.
10. **Development roadmap**:
    - **Phase 0 (now)**: single-number English prototype, no auth, cascaded pipeline (Plivo/Exotel + Deepgram + fast LLM + Cartesia) on LiveKit Agents or Pipecat, validated against real (not scripted) test calls for turn-detection quality.
    - **Phase 1**: DLT registration + consent-capture flow + admin CSV upload/campaign/export UI; move from single-call testing to a rate-limited campaign dialer; nail down the absence-call domain logic (question flow, structured extraction schema, escalation rules).
    - **Phase 2**: Telugu — swap STT/TTS to Sarvam, re-tune turn detection on real Telugu call audio, validate on your actual target population's dialect before declaring it production-ready.
    - **Phase 3**: Tanglish code-switching, then generalize the domain layer (question flows, extraction schemas) so new use-cases beyond "absent students" are configuration, not new code.
    - **Phase 4+**: additional Indian languages, scale-out concurrency, and only then revisit authentication/production hardening.

---

## Sources
This report draws on ~25 web searches across current (2026) provider documentation, independent benchmarking sites, and industry comparison articles, conducted August 2026. Key sources cited inline include: Exotel, Plivo, and Twilio pricing/documentation pages; caller.digital, frejun.com, and awaaz.ai telephony comparison guides; TRAI-compliance guides (frejun.com, autointerviewai.com, ondial.ai, expressivr.com); DPDP Act guides (recordinglaw.com, caller.digital, gistly.ai); voice-platform comparisons (techsy.io, retellai.com, bland.ai, tested.media, alphacorp.ai); framework comparisons (thinnest.ai, forasoft.com, evalgent.com, techsy.io); STT/TTS benchmarks (assemblyai.com, futureagi.com, coval.ai, deepgram.com, gladia.io, codesota.com, burki.dev); Sarvam AI product pages; Groq/inference benchmarks (baytechconsulting.com, neuraplus-ai.github.io, apiscout.dev); cascaded-vs-speech-to-speech analysis (futureagi.com, deepgram.com, inworld.ai, reactify-solutions.com, softcery.com); cost models (inworld.ai, retellai.com, bitbytes.io, ravan.ai, caller.digital, famulor.io, klariqo.com); and Indian voice-AI competitor pages (gnani.ai, lumay.ai, vyora.ai, carmaone.ai).

**Given how fast this market is moving (several sources note major model/pricing changes within the last 1–2 months), re-verify pricing and latency figures directly against provider pages before committing to a contract — treat everything above as a well-sourced starting map, not a final quote.**

---

# 6. EchoSarathi Final Architecture (CONFIDENTIAL)

> Consolidated from source file: docs/plans/echosarathi-final-architecture.md

# VocalIQ / EchoSarathi — Final Multilingual Voice-Agent Architecture

**CONFIDENTIAL — internal only.** §5 (closed-source stack + negotiated economics) is the actual moat and should never leave the team. §6 (open-source/BYOK edition) is the only part safe to make public.

**Date:** August 26, 2026
**Synthesized from:** `multilingual.md` (multilingual-researcher agent, Phase-2 report) and `telephony-alternatives.md` (telephony cost-optimization report), both dated Aug 26 2026. No new vendor claims are introduced here — this document combines, re-does the arithmetic across, and makes product decisions on top of those two reports. Where something is unresolved in the source material, it's carried forward as unresolved, not quietly settled.

---

## 1. Executive Summary

**Two-tier product strategy:**

| | Open-source / BYOK edition | Closed-source managed edition |
|---|---|---|
| Who runs the infra | Customer, on their own vendor accounts | You, on negotiated enterprise rates |
| Who pays STT/LLM/TTS/telephony vendors | Customer, directly | You (COGS target: **₹2–2.5/min**) |
| What you sell | The orchestration framework + domain-config tooling (subscription/license) | The full managed call, billed ~₹3–5/min per your existing pricing |
| What's public | Agent pipeline scaffolding, domain-config schema, provider-abstraction interface | Nothing — this is §5 |
| What's confidential | — | Negotiated rates, tuned guardrail thresholds, escalation logic, domain-configs, compliance playbook |

This isn't just a licensing gimmick — it's the reason the confidentiality requirement makes structural sense. The BYOK edition's value is the *engineering* (a working, tested, config-driven pipeline). The managed edition's value is the *economics and tuning* (which vendors, at what negotiated rate, with what thresholds) — and economics/tuning are exactly what's cheap for a competitor to copy if they can see it, and expensive for them to rediscover if they can't.

**Is ₹2–2.5/min achievable?** Yes, at *negotiated* rates — but not with margin to spare at *sticker* rates. Your own multilingual report's sensitivity analysis puts the stack at ≈₹1.1–2.0/min expected, ≈₹1.9–3.4/min worst-case-sticker. Full combined math with the (cheaper than assumed) telephony numbers from your telephony report is in §5.4 — short version: **on target at negotiated rates, over target if you pay every vendor's list price.** Treat ₹2.5/min as something you negotiate your way under, not something that falls out automatically.

**Languages:** Telugu, Hindi, English fluency + mid-call code-switching is achievable with the stack your own research already points to (Sarvam Saaras v3 STT + Sarvam-M/30B LLM + Bulbul v3 TTS) — but "the agent switches its own spoken language when the caller switches" is **application logic you still have to build**, not a feature any single vendor ships. Detail in §3.4 — this is the one place in your ask that's a real engineering task, not a vendor-selection task.

**Telephony:** literal zero-telephony-vendor isn't legally possible. What's actually rare and enterprise-grade is self-hosting the SIP/media bridge (`livekit/sip`) instead of renting a CPaaS's proprietary streaming layer — that's the "nobody else is doing this" version of your ask. Parallel calling is solved with a primary+overflow hybrid, not a single alternative provider. Detail in §4.

---

## 2. Language & Voice Architecture

### 2.1 Speech-to-Text

| Model | Telugu accuracy | Code-switching | Streaming | 8kHz telephony fit | Cost |
|---|---|---|---|---|---|
| **Sarvam Saaras v3** ✅ recommended | ~19.3% avg WER, code-mixed <12% [VENDOR] | **Native** — dedicated `codemix` output mode | <150ms first-token | Purpose-built for 8kHz telephony | ₹0.50/min (verify — pricing page shows ₹30/hr, marketing shows ₹1.5/min; **unresolved discrepancy, resolve before contract**) |
| Deepgram Nova-3 `te` (incumbent, A/B) | No public Telugu WER yet | Multilingual code-switch endpoint | <300ms | Telephony-grade heritage | ≈₹0.44/min |
| AI4Bharat IndicWhisper/Conformer (open) | 28.8% avg Telugu (worse) | Weak | No native streaming | Explicitly "future work" per AI4Bharat themselves | Free weights, GPU-hour only |

**Decision:** Saaras v3 primary, Nova-3 `te` as A/B (already wired). Open-weight options are not production-ready for telephony-domain Telugu today — don't let the open-source narrative pull you toward them prematurely; this is a case where the closed API genuinely earns its ₹0.50/min.

### 2.2 LLM

| Model | Telugu/Tenglish evidence | Notes |
|---|---|---|
| **Sarvam-M / Sarvam-30B (non-think)** ✅ recommended | Only model with published conversational Telugu/Tenglish evidence (Indic Vibe Check 8.12/9 vs Llama-4-Scout 7.58) [VENDOR — Sarvam's own eval, favorable-but-interested] | General reasoning is mediocre (#121/137 independent rank) — irrelevant for constrained call flows, would matter if you ever need open-ended reasoning |
| Groq GPT-OSS-120B (escalation tier) | No Telugu-specific benchmarks — evidence gap | Rule-based escalation for hard turns only; forced migration anyway since Llama-3.3-70B was deprecated Aug 16, 2026 |

**Unresolved and load-bearing:** Sarvam-M's function-calling/field-extraction accuracy has **no independent benchmark** — your own report flags this as the one claim to verify in your qa-eval harness before committing. Token cost either way is a rounding error (<₹0.05–0.30/min) — this is a quality decision, not a price one.

### 2.3 TTS + Voice Cloning

| Engine | Telugu naturalness | Cloning | Cost |
|---|---|---|---|
| **Sarvam Bulbul v3** ✅ recommended | Won a 20k+ vote blind study; docs admit per-language variance (rare vendor honesty, worth trusting) | Consent-based enterprise cloning only — **no self-serve cloning exists yet** | ₹1.05–1.80/min (v3) or ₹0.53–0.90/min if v2 pricing negotiated — **dominant cost line, negotiate here first** |
| Cartesia Sonic (latency fallback) | No independent Telugu MOS | Self-serve instant cloning | ~₹1.8–3.0/min |
| F5-TTS / XTTS-v2 (open) | N/A | Zero-shot | ❌ **Legally barred for commercial use, and neither speaks Telugu** — do not consider these regardless of cost |

**The honest gap:** there is no commercial-safe open-source Telugu voice cloner today. This is the single biggest strategic gap in the whole stack per your own research — don't plan around one appearing on your timeline.

### 2.4 Mid-Call Code-Switching — the part you have to build

This is the one place where "pick a vendor" doesn't finish the job. Saaras v3's `codemix` mode gives you an accurate transcript when a caller mixes Telugu and English in one utterance — but *deciding which language the agent should speak back in, turn by turn,* is orchestration logic on top of that, not a toggle any vendor exposes. The design:

1. **Per-turn language signal**: Saaras's codemix transcript already tags mixed spans; use the dominant language of the caller's last turn (not the whole call) as the switch trigger — a caller who drops into English for one sentence and back to Telugu shouldn't flip the agent's voice for the rest of the call.
2. **Response-language selection**: prompt Sarvam-M with the detected turn language and instruct it to respond in kind — it's trained on code-mixed and romanized forms, so this is within its documented capability, not a stretch.
3. **Voice routing**: maintain a **per-language voice mapping** in the agent/domain-config (your own research's UX section already recommends exactly this pattern for the admin dashboard) so the TTS call picks the right Bulbul voice for the response language automatically — never hardcode a voice ID.
4. **Fallback discipline**: keep the translation-in-the-middle cascade (STT→IndicTrans2→English LLM→IndicTrans2→TTS) *only* as an emergency path for a pure-Telugu turn if Sarvam-M fumbles — never the standing path. Your own latency budget math shows it barely fits even without code-switching overhead; treating it as primary would blow the ≤900ms turn target you're already thin on.

Net effect: code-switching is buildable on the stack you already have, on a 1–2 week timeline of orchestration work — not a new vendor search.

---

## 3. Telephony Architecture — Enterprise-Grade, Parallel-Capable

### 3.1 Correcting "no telephone clouds" — the physical constraint

Every legal call to an Indian mobile pays PSTN termination to a licensed access provider. No software choice removes that — your own telephony report is explicit that ₹0 telephony is impossible, and that the only sub-₹0.10/min offers on the market are illegal SIM-box/grey routes (documented arrests through 2026, carriers are mandated to actively hunt this traffic, first violation bars *all* your telecom resources for 15 days). This isn't a compliance nicety to route around — it's a hard floor.

**What's actually achievable, and what's genuinely rare:** most vendors in this space (and most competitors) run their agent pipeline through a CPaaS's proprietary media-streaming bridge (Twilio Media Streams, or equivalent), paying a per-stream surcharge on top of the per-minute rate. Self-hosting the bridge — `livekit/sip`, which matches your already-locked LiveKit decision — removes that middle layer entirely. The callee joins your LiveKit room directly; there's no separate streaming fee, fewer network hops, and you own the entire pipeline from carrier trunk to agent. **That's the enterprise-grade, not-personal-tier version of your ask** — a self-hosted, production SIP bridge is a fundamentally different posture than a personal Twilio account, even while the underlying carrier connection (Plivo, then eventually direct carrier SIP) is unavoidably still "a telephony vendor" in the strict sense.

### 3.2 Recommended path

| Stage | What | Concurrency ceiling | When |
|---|---|---|---|
| **Now** | `livekit/sip` self-hosted bridge → Plivo domestic trunk (₹0.38/min, streaming free) | 50 concurrent (PAYG cap) | Immediately — config-level trunk swap, no agent code changes |
| **Overflow / parallel burst** | Second provider (Exotel) behind the same provider-abstraction interface, absorbing calls once Plivo's ceiling is hit | Sales-defined, effectively higher | As soon as campaign concurrency approaches ~40-50 |
| **At scale (>100k calls/mo or >300k min/mo sustained)** | Direct carrier SIP (Jio/Tata/Airtel) fronted by Kamailio (signaling) + rtpengine (media, kernel-mode RTP forwarding) | **10,000+ concurrent per instance** — tier-1 carrier-grade | Trigger-based, not calendar-based |

This is the hybrid you described: the primary path (Plivo via self-hosted LiveKit SIP) carries baseline traffic; a second path absorbs parallel overflow; and the carrier-grade path (Path C) is the ceiling-breaker once volume justifies the operational overhead. None of this is "pick one alternative" — it's a provider-abstraction layer with a defined escalation order, which is also what makes a single vendor outage non-fatal to a campaign.

**Reality check on jumping straight to Path C:** your own cost model shows direct carrier SIP is *more* expensive than Plivo below ~100k–200k calls/month — channel rental minimums dominate at low volume. If current call volume is closer to college-pilot scale (thousands/month), starting there would work against your own cost-cutting goal, not for it. The self-hosted bridge (Path A) is what gets you the "enterprise, own-the-stack" posture *today* without paying the carrier-SIP premium before you've earned it.

### 3.3 Concurrency math at representative volumes (from your own report)

| Volume | Avg concurrent (3-min avg call) | Fits on |
|---|---|---|
| 10k calls/mo | ~3 concurrent | Trivially inside Plivo's 50-cap |
| 100k calls/mo | ~28 average, peak 45–60 | **Right at Plivo's ceiling** — this is where overflow provider #2 or Path C becomes necessary, not optional |

---

## 4. Combined Unit Economics (Closed-Source Managed Tier)

Recomputing your multilingual report's stack total with the more precise telephony figures from your telephony report (₹0.38/min Plivo PAYG rather than the ₹0.80 placeholder used in the multilingual doc's own table):

| Component | Choice | ₹/min | Confidence |
|---|---|---|---|
| Telephony | Plivo (self-hosted LiveKit bridge) | 0.38 | [INDEP, vendor pricing page] |
| STT | Saaras v3 | 0.50 | [VENDOR — pricing page vs marketing discrepancy unresolved] |
| LLM | Sarvam-M/30B + Groq escalation | 0.05–0.30 | Token cost, low risk |
| TTS | Bulbul v3 (v2 pricing if negotiated: 0.53–0.90) | 0.55–1.80 | Dominant cost line |
| Cloning | Sarvam enterprise (bundled) | ~0–0.30 | Enterprise-deal dependent |
| Orchestration | LiveKit Agents (self-hosted) | ~0 | Infra cost only |
| **Total** | | **≈1.48–3.28/min sticker → ≈0.98–1.88/min at negotiated TTS + expected LLM usage** | |

**Against your ₹2–2.5/min target:** comfortably inside it at negotiated rates; the sticker-price ceiling (~3.28) would miss it. **TTS is the lever** — it's the single largest and most negotiable line item. Priority order for protecting margin: (1) negotiate Bulbul v2 pricing, (2) tune domain-configs toward shorter agent phrasing to cut TTS chars/min, (3) revisit self-hosting Indic Parler-TTS only past >1M chars/month, where the amortized math starts to work (₹0.05–0.25/min self-hosted vs ₹0.55+ API).

**Margin against your stated ₹3–5/min customer price:** even at sticker-price worst case (₹3.28), you're inside a ₹3–5/min sell price, though thin at the ₹3 end. At negotiated rates you're looking at 40–65% gross margin on the managed tier — healthy, and worth protecting by locking TTS pricing before scaling volume.

---

## 5. Open-Source / BYOK Edition — What's Actually Public

To keep the confidentiality boundary real rather than nominal:

**Safe to open-source:**
- The provider-abstraction interface itself (the pattern, not your specific negotiated endpoints)
- Domain-config *schema* (the shape of a call flow), not your populated domain-configs (e.g., the absent-student flow's actual prompts/logic)
- The LiveKit SIP bridge integration pattern
- Generic guardrail *scaffolding* (the check types), not your tuned thresholds

**Never in the open edition:**
- Negotiated rate cards with any vendor
- Populated domain-configs for real customer flows
- Tuned guardrail floors/thresholds (these took real iteration to get right and are directly reusable by anyone who sees them)
- Compliance playbook specifics (DLT template wording, consent scripts)
- Any qa-eval harness results that reveal which vendor combination actually performs best in production

The BYOK customer gets a working, honest framework and pays retail vendor prices for the privilege of running it themselves — which is a legitimate product on its own, and structurally can't undercut your managed tier's margin since they're paying full freight to the vendors you've negotiated volume discounts with.

---

## 6. Open Risks — Carried Forward, Not Resolved Here

These are unresolved in your source research and should block signing anything, not just architecture planning:

1. **Sarvam STT pricing discrepancy** (₹30/hr vs ₹1.5/min marketing) — get this in writing before contracting.
2. **Sarvam-M function-calling/extraction accuracy** — no independent benchmark exists; run your domain-config harness against it before committing the LLM tier.
3. **Bulbul v3 Telugu MOS on your actual scripts** — blind-test candidate voices with real users; Sarvam's own docs admit per-language variance.
4. **No commercial-safe open Telugu voice cloner exists** — don't plan a self-host cloning fallback around one appearing.
5. **Concurrency ceiling proximity** — 100k calls/month sits right at Plivo's 50-concurrent cap; load-test at 1.5× planned peak CPS before a campaign, not during one.

---

## 7. Immediate Next Actions

1. Get Sarvam's STT pricing discrepancy resolved in writing — it's a 3x swing (₹0.50 vs ₹1.5/min) that changes the whole economics table.
2. Stand up the qa-eval harness for Sarvam-M function-calling before any commitment — this is the one unverified claim the whole LLM tier depends on.
3. Deploy `livekit/sip` against Plivo now (Phase 0/1 from your telephony report) — this is the fastest concrete step toward the "own the bridge" architecture and doesn't wait on any of the above.
4. Design the per-language voice-mapping schema in the domain-config format now, even before code-switching logic is built — it's needed either way and unblocks the TTS voice-gallery UX work in parallel.
5. Negotiate Bulbul v2 pricing before scaling call volume — this is your single biggest lever on hitting ₹2–2.5/min with margin to spare.

---

# 7. Research: Multilingual Telugu Stack

> Consolidated from source file: docs/research/multilingual.md

# Phase-2 Multilingual Research: Fluent Telugu, Tenglish Code-Switching & Natural Cloned Voices

*Generated: 2026-08-26 · Author: multilingual-researcher agent · Status: DECISION DOCUMENT (planning artifact only — per project guardrails, no Telugu implementation work starts until Phase-2 kickoff)*
*Method: live web research across ~20 queries (vendor docs, independent benchmarks, pricing trackers, GitHub, arXiv). Sources dated inline. Confidence labels:*
- **[VENDOR]** = vendor-published claim, unaudited
- **[INDEP]** = independent/third-party measurement or benchmark
- **[EST]** = our arithmetic from stated assumptions — verify before contracting

---

## 0. TL;DR Decision Table

| Component | Recommendation | ₹/connect-min [EST] | Why |
|---|---|---|---|
| STT | **Sarvam Saaras v3 streaming** (A/B vs incumbent Deepgram Nova-3 `te`, which added Telugu May 2026) | ₹0.50 API (self-host path ₹0.10–0.25 later) | Only streaming ASR with published IndicVoices/code-mix numbers + 8 kHz telephony focus |
| LLM | **Sarvam-M / Sarvam-30B (non-think)** primary, rule-based escalation to Groq GPT-OSS-120B | ₹0.05–0.30 | Best public Telugu/Tenglish evidence (Indic Vibe Check 8.12/9 [VENDOR]); token cost negligible either way |
| TTS | **Sarvam Bulbul v3 catalog voices** at launch; enterprise consent-cloning for custom voices | ₹0.5–2.4 (dominant cost) | Top Indic naturalness (blind-study claim), sub-250 ms TTFB, native 8 kHz output |
| Cloning | **Phase 2a: Sarvam consent-based enterprise cloning. Phase 2b (scale): self-host commercial-safe stack — but no proven open Telugu cloner exists today (gap, see §3.4)** | ₹0 (enterprise deal) / ₹0.1–0.3 amortized | F5-TTS & XTTS-v2 are license-barred for commercial use AND lack Telugu |
| **ALL-IN** | | **≈ ₹1.1–2.0/min** | Comfortably under ₹3.5 competitor line with ~₹0.8 telephony (§5) |

---

## 1. STT — Telugu + Code-Switched Speech on Real 8 kHz Phone Audio

### 1.1 Comparison

| Model | Telugu WER (best available) | Code-switching | Streaming / latency | 8 kHz telephony fit | Price | License / hosting |
|---|---|---|---|---|---|---|
| **Sarvam Saaras v3** (Feb 2026) | ~19.3% avg IndicVoices 10-lang; code-mixed <12%, Hindi <8%, Indic-English <6% [VENDOR, third-party roundup concurs] | Native (trained-in; dedicated `codemix` output mode) | Yes — WebSocket, <150 ms first-token "Fast" mode [VENDOR] | Explicitly positioned for 8 kHz telephony; LiveKit/Pipecat integrations exist | **₹30/hr = ₹0.50/min** official API pricing page ⚠️ marketing pages show ₹1.5/min — reconcile before contract | Closed API, India-hosted, DPDP/SOC2 claims |
| **Deepgram Nova-3** (incumbent vendor) | Telugu (`te`) GA; accuracy improvements announced May 2026; no public Telugu WER [VENDOR] | Multilingual code-switching endpoint + keyterm prompting [VENDOR] | Yes, <300 ms claim [VENDOR]; Flux adds turn detection (English/multi — **no Telugu**) | Telephony-grade heritage | ~$0.0043–0.0074/min ≈ ₹0.37–0.65/min [INDEP tracker] | Closed API; US-hosted by default (data-residency question — see compliance-agent) |
| **AI4Bharat IndicWhisper** (fine-tuned Whisper, MIT) | **28.8% avg Telugu** across Vistaar benchmarks (Kathbath 25.0, KB-hard 27.8, FLEURS 25.4, IndicTTS 33.8, MUCS 32.1) [INDEP, AI4Bharat paper] | Weak — trained on monolingual Indic corpora | No native streaming (Whisper seq2seq, chunked hacks only) | Poor — AI4Bharat itself lists "handle 8 kHz telephony data" as *future work* | Free weights; GPU-hour only | MIT, self-host, weights on HF/E2E object store |
| **AI4Bharat IndicConformer 600M** (multi) + mono Telugu large | Vaani Hindi 13.2%; no published Telugu headline in card; Vistaar-family lineage suggests mid-20s% [INDEP partial] | Monolingual-leaning; multi model covers 22 langs but not mixed-utterance optimized | RNNT decoder is streaming-*capable* but not packaged as a low-latency server | Same caveat as above | Free weights; ~600M params runs many streams/GPU | MIT, NeMo ecosystem |
| **Whisper-large-v3 (+ fine-tunes)** | Zero-shot Indic far behind Indic-tuned models [INDEP roundups]; community Hindi LoRA cut FLEURS 35.6→22.3% — directionally instructive, no equivalent public Telugu fine-tune found | Poor zero-shot; synthetic-data CS fine-tuning is research-grade | No native streaming | Poor (studio-domain training) | Free weights | Apache/MIT ecosystem; turbo variant fastest |
| **Gnani Prisma v2.5** | "<4% WER Indian English", "#1 on Kathbath-Noisy 8 kHz in 8/9 languages", 96% code-switch accuracy — **all [VENDOR]**, methodology unpublished | Native, BFSI-domain vocabulary (PAN/UPI/EMI…) | Yes, sub-200 ms [VENDOR] | Purpose-built on 14M hrs telephonic audio [VENDOR] | ~₹27/hr via API reseller [INDEP tracker]; direct = enterprise quote | Closed; on-prem option |

### 1.2 Economics: API vs self-host [EST]

Self-host math form requested: **₹/hr ÷ concurrent streams**. Reference GPU rates (E2E Networks, INR, 2026): L4 ₹49/hr · A100-80GB ₹189/hr (spot ₹66) · H100 ₹362/hr (spot ₹70–180). IndiaAI-subsidised compute ~₹67–92/GPU-hr if approved.

| Scenario | Math | ₹/min |
|---|---|---|
| Saaras v3 API | ₹30/hr ÷ 60 | **0.50** |
| Deepgram Nova-3 API | $0.005 ± /min × ₹87/$ | **0.44** |
| faster-whisper-lg-v3 / Conformer on L4, 12 concurrent streams (optimistic) | ₹49 ÷ 60 ÷ 12 | 0.07 |
| Same, 5 concurrent (conservative, streaming chunks) | ₹49 ÷ 60 ÷ 5 | 0.16 |
| On A100-80GB spot, 25 streams | ₹66 ÷ 60 ÷ 25 | 0.04 |
| Add ops overhead ×2 (monitoring, failover, idle GPU in bursty campaign traffic) | — | **0.10–0.35 realistic** |

Break-even vs Saaras API ≈ 1.6 continuously-active streams (raw GPU), realistically ~6–10 average with utilization waste. Worth it only at steady campaign volume (>~50k min/month) — and **accuracy risk remains**: open models are demonstrably weaker on noisy/telephony audio, which is exactly our domain.

> **RECOMMENDATION (STT): Ship Phase-2 on Sarvam Saaras v3 streaming (₹0.50/min), keeping Deepgram Nova-3 `te` as the cheap-to-integrate A/B arm since it's already wired into `/voice-agent`; revisit self-hosting (Conformer-RNNT on spot A100) only after qa-eval proves ≥25k min/month sustained and open models close the 8 kHz noise gap.**

---

## 2. LLM — Native Spoken Telugu + Tenglish, Tool-Calling, Rock-Bottom Tokens

### 2.1 Evidence table

| Model | Telugu / Tenglish evidence | Tool-calling | Latency profile | Price (in/out per 1M tok) |
|---|---|---|---|---|
| **Sarvam-M → Sarvam 30B/105B family** (24B Mistral-Small-derived → newer MoE) | **Best available**: Indic Vibe Check **8.12/9 avg across 11 langs** vs Llama-4-Scout 7.58 & Llama-3.3-70B 6.93; MMLU-IN 0.79; romanized-Telugu-class GSM8K +86% vs base; Telugu = 8% of SFT mix; trained on formal + code-mixed + romanized forms [VENDOR — Sarvam's own evals; treat as favorable-but-interested]. Independent Artificial Analysis ranks its *general* intelligence low (#121/137) → fine for constrained call flows, not open-ended reasoning | Documented think/non-think modes; **function-calling must be verified in our harness — no independent benchmark row** [GAP] | India-hosted; ~100 tok/s (high-concurrency config) to ~300 tok/s (low-concurrency) [VENDOR] | Sarvam 105B: **₹29.28 / ₹73.20** official page; Sarvam-M ≈ ₹35/₹35 via resellers |
| **Groq-hosted open models** (current stack's host) | No Telugu-specific public benchmarks for any of them — **evidence gap**. General multilingual signals only | Yes (OpenAI-compatible tools) | TTFT ~0.2–0.7 s measured [INDEP, Artificial Analysis] | GPT-OSS-120B **$0.15/$0.60**; GPT-OSS-20B $0.075/$0.30; Qwen3-32B $0.29/$0.59; Gemma-2-9B $0.20/$0.20 (⚠️ Llama-3.3-70B & 3.1-8B **deprecated Aug 16 2026** — migration forced anyway) |
| **DeepSeek-V3/R1** | Strong MMMLU/multilingual aggregates but training is English+Chinese-dominant [INDEP tech report]; no Telugu conversational evidence found | Yes | Cheap but heavier TTFT; R1 thinking incompatible with voice budgets | $0.27/$1.10 (V3) [INDEP tracker] |
| **Gemma 2/3 27B** | Gemma 3: 140+ languages in pretraining [VENDOR]; won multilingual category vs Qwen-3.5-27B 83.1% vs 71.4% in one third-party suite [INDEP, single source] | Yes | Good on vLLM/Groq | $0.10/$0.20 Deepinfra (cheapest capable tier) [INDEP]; Sarvam also hosts a Gemma-4-class model at ₹36.60/₹91.50 |
| **Qwen 2.5 / 3** | CJK-optimized multilingual; strong general benchmarks [INDEP]; Telugu anecdotal only | Yes | Excellent on Groq LPU | See Groq rows above |
| **Llama-3.x** | Weakest Indic showing among candidates (Indic Vibe Check 6.93 for 70B [VENDOR]) | Yes | — | Deprecation pressure on Groq |

**Honest read:** there is **no rigorous, independent, spoken-register Telugu benchmark** for any global-open model. The only Telugu-relevant head-to-head that exists is Sarvam's own Indic Vibe Check — favorable to Sarvam, unsurprisingly. Everything else is proxy evidence (multilingual aggregates ≠ conversational Tenglish fluency).

### 2.2 Translation-in-the-middle: measure, don't guess

Option: STT (Telugu) → IndicTrans2 → English LLM → IndicTrans2 → Telugu TTS.

- IndicTrans2-distilled (~250M) via CTranslate2-int8: ~**40 ms/clause** on GPU per one open pipeline build; full ASR+NMT+TTS pipeline demonstrated "<300 ms" target [INDEP, single hobby-grade repo — weak evidence]
- AI4Bharat's hosted demo translates a sentence in 2–3 s; naive HF inference took 17 s in a user report [INDEP issue tracker] — i.e., **latency is entirely an engineering variable**, 100 ms possible, seconds likely if done casually
- Structural costs regardless of speed: **error propagation** through two NMT hops, nuance loss on pivot, and doubled failure surface — flagged by AI4Bharat themselves as reasons they built direct M2M models

**Verdict vs our ≤900 ms median turn target:** a tight clause-level pivot adds ~100–300 ms on top of an already-tight cascade (Saaras 150 ms + LLM 250–500 ms + Bulbul 250 ms ⇒ ~650–900 ms). Translation-in-the-middle **does not fit inside the budget with headroom** and degrades extraction reliability (FR-12 escalation logic depends on trustworthy transcripts). It is acceptable **only** as an emergency fallback for pure-Telugu turns if the primary LLM fumbles — never as the standing path.

> **RECOMMENDATION (LLM): Primary = Sarvam-M/Sarvam-30B in non-think mode, prompt-locked to our domain-config flow with tool schemas; validate function-calling + extraction accuracy in the qa-eval harness BEFORE commitment (the one unverified load-bearing claim). Escalation tier = Groq GPT-OSS-120B for hard turns (rule-based escalation per locked architecture — note Groq's Aug-2026 model deprecations force a Phase-1 migration anyway). Skip translation-in-the-middle; keep distilled IndicTrans2 warm only as fallback. Token cost is a rounding error (<₹0.05–0.30/min) — decide on quality, not price.**

---

## 3. TTS — Most-Human Telugu + Voice Cloning

### 3.1 Comparison

| Engine | Telugu naturalness | TTFB / streaming | Cloning | Price → ₹/agent-min [EST] | License / risk |
|---|---|---|---|---|---|
| **Sarvam Bulbul v3** (Feb 2026) | 11 langs incl Telugu; 30–35 persona voices; **won Josh Talks blind study (20k+ votes)** [VENDOR]; docs candidly admit per-language voice-quality variance | **<250 ms** WebSocket [VENDOR]; 8 kHz mulaw supported (native telephony) | **Consent-based enterprise cloning** — blog demos Telugu generation from reference clip; ⚠️ **no self-serve cloning product as of Aug 2026** (two sources concur) | Official ₹30/10k chars (beta); v2 legacy ₹15/10k. Agent speaks ~350–600 Telugu-script chars/connect-min ⇒ **₹1.05–1.80/min** (v3) or **₹0.53–0.90** (v2) [EST] | Closed API, India-resident, SOC2/DPDP claims |
| **Cartesia Sonic** (incumbent vendor) | Dedicated Telugu page; "native prosody" [VENDOR]; no independent Telugu MOS found | **<90 ms** claim [VENDOR] — best-in-class | Instant cloning self-serve | ~$0.065/1k chars [INDEP tracker] ⇒ ~₹5/1k ⇒ **₹1.8–3.0/min** [EST] | Closed, US-hosted |
| **ElevenLabs (Multilingual v2/v3)** | 70+ langs claimed; Telugu present in v3-era coverage [VENDOR]; quality on Dravidian langs consistently rated below Hindi in community tests [INDEP anecdotes] | ~500 ms; Flash cheaper/faster [INDEP] | IVC (1-min sample) + PVC (30-min, 95% likeness, identity verification) | Business-tier self-publishes "**as low as $0.05/min**"; retail effective $0.18–0.30/1k chars [INDEP] ⇒ **₹4–6/min** realistic | Closed, expensive, strongest cloning-consent tooling |
| **Gnani Timbre v2.5** (beta) | MOS 4.23 claim, <250 ms p95 [VENDOR]; cloning for 12 Indian languages announced [INDEP press] | Beta | Yes (announced) | Unpublished (enterprise) | Closed; early-stage risk |
| **AI4Bharat Indic-TTS** (FastPitch+HiFi-GAN, ICASSP'23) | Solid intelligibility, dated prosody; Telugu included in 13-lang release [INDEP] | Non-streaming batch design | None | Free weights; GPU-only ⇒ **₹0.05–0.15/min** amortized [EST] | Open (Bhashini); verify fork license |
| **AI4Bharat Indic Parler-TTS Mini** | 21 langs incl Telugu; speaker-similarity ~88–89 (Telugu row) on their evals [VENDOR/INDEP]; description-controlled style | Chunk-streamable, slower than Bulbul-class | **No true cloning** (description-driven voice creation) | Apache-2.0 family [INDEP registry] | Best open *catalog* option; needs own serving layer |
| **F5-TTS** | Top-tier English/Chinese prosody; **no Telugu** [INDEP] | ~2.8 s to first audio (non-causal design) [INDEP] | Zero-shot, excellent (EN/ZH) | Free weights | ❌ **CC-BY-NC-4.0 — non-commercial. Cannot ship.** |
| **XTTS-v2 (Coqui)** | 17 langs, **no Telugu**; MOS ~4.0 [INDEP] | ~3.5 s TTFA | Zero-shot, mature ecosystem | Free weights | ❌ **CPML non-commercial; company defunct — no one to license from.** |
| **Chatterbox / Fish Speech / Kokoro** | Commercial-safe licenses (MIT/Apache) [INDEP]; Chatterbox reportedly beats ElevenLabs in ~65% blind tests [VENDOR-of-claim, single source]; **Telugu support: none documented** [GAP] | Varies; Kokoro fast but no cloning | Chatterbox/Fish yes (EN-centric) | Free weights | ✅ licenses, ❌ Telugu |

### 3.2 The cloning reality check (read this twice)

The two most famous open-source cloners — **F5-TTS (CC-BY-NC) and XTTS-v2 (CPML) — are both legally barred from commercial products AND neither speaks Telugu.** The commercial-safe open cloners (Chatterbox, Fish Speech, OpenVoice-v2) have **no documented Telugu capability** as of this research date. Practitioner guidance converges on the same conclusion: stay on managed APIs below ~10M chars/year; self-host only permissive models at scale [INDEP, Forasoft 2026 guide + Spheron deployment guide].

Self-host TTS economics when it eventually makes sense [EST]: XTTS-class throughput ~600 chars/sec/GPU [INDEP, Spheron benchmark] ⇒ one L4 (₹49/hr) could theoretically carry dozens of streams; realistic streaming Parler/Bulbud-class serving ⇒ **₹0.05–0.25/min** amortized. The savings vs Bulbul API are real but second-order until volume is large — and they buy you *worse* Telugu naturalness today.

### 3.3 Latency budget check

Cascade sum (median): Saaras fast-mode first-token <150 ms [VENDOR] + LLM TTFT 250–500 ms [INDEP] + Bulbul first-byte <250 ms [VENDOR] ≈ **650–900 ms + network** — inside our ≤900 ms target, with zero slack. Cartesia's <90 ms TTFB is the escape hatch if we blow the budget, at ~2× TTS cost and offshore hosting.

> **RECOMMENDATION (TTS): Launch on Bulbul v3 catalog voices (per-language recommended-speaker mapping from Sarvam's own docs) with Bulbul v2 pricing negotiated if volume justifies; contract Sarvam's consent-based enterprise cloning as the custom-voice path (it is the only demonstrated Telugu-capable cloner reachable today). Keep Cartesia Sonic wired as latency/quality fallback behind our existing provider-abstraction. Do NOT burn sprints on open-source Telugu TTS in Phase 2 — revisit Indic Parler-TTS self-hosting at >1M chars/month.**

---

## 4. Voice-Selection UX — What Platforms Do, What We Copy

Precedent observed (Aug 2026):

| Platform | Pattern |
|---|---|
| **Vapi** | `assistant.voice = {provider, voiceId}` per assistant; pluggable providers (ElevenLabs, Smallest-Lightning built-in…); **voice-fallback chain** config; providers expose "pick a voice **or clone your own from a few seconds of audio**" inside assistant settings |
| **Retell AI** | Per-agent voice picker over categorized voice library; multilingual voices tagged per language; agent-level config object |
| **ElevenLabs** | Searchable Voice Library (use-case tags, instant previews); two cloning tiers — Instant (1-min sample, seconds) vs Professional (30-min+, 4–6 h train, **identity verification + consent capture** before activation) |
| **Smallest AI (via Vapi)** | 217-voice catalog, ~100 ms streaming, clone-from-seconds flow embedded in partner dashboards |
| **Sarvam** | Publishes **per-language recommended voices** (docs admit quality varies by language) — rare honesty worth copying outright |

**Copy-list for our admin dashboard (frontend-agent + conversation-ai-agent handoff):**
1. `voice_id` lives on the **agent config / domain-config**, never hardcoded (consistent with PRD §4.3 config-over-code rule)
2. Curated **Telugu-first voice gallery** with per-language recommended mapping + inline `<audio>` preview before commit
3. Clone flow = upload ≥30 s clean sample → recorded verbal-consent statement + checkbox (DPDP; compliance-agent owns wording) → async clone job → **QC preview gate** → activate per agent
4. Voice **fallback chain** (primary → secondary provider) so a TTS outage never dead-airs a call
5. Never surface raw provider IDs/slugs to customers; friendly names + samples only

---

## 5. Final Recommended Phase-2 Stack

Assumptions: $1 ≈ ₹87 [EST]; connect-minute = billed phone minute; agent speaks ~45% of airtime (~350–600 Telugu-script chars); LLM ≈ 2.5–4k tokens/connect-min combined.

| # | Component | Choice | ₹/connect-min | Quality verdict | Risk |
|---|---|---|---|---|---|
| 1 | Telephony | Plivo (locked) | ~0.80 | Proven | Low (existing) |
| 2 | STT | **Saaras v3 streaming** (A/B: Deepgram Nova-3 `te`) | **0.50** (DG ≈ 0.44) | Best public Indic/code-mix numbers; 8 kHz-focused | Sarvam pricing-page inconsistency (₹30/hr vs ₹1.5/min marketing) — resolve pre-contract; single-vendor concentration |
| 3 | LLM | **Sarvam-M/30B non-think** + Groq GPT-OSS-120B escalation | **0.05–0.30** | Only model with published Tenglish/Telugu conversational evidence; general reasoning mediocre but sufficient for config-driven flows | **Function-calling unverified independently** — hard-gate on qa-eval results |
| 4 | TTS | **Bulbul v3 catalog** (negotiate v2 pricing) | **0.55–1.80** | Best Indic naturalness claim + blind-study win; 8 kHz native | No self-serve cloning; per-language voice variance is real |
| 5 | Cloning | **Sarvam consent-based enterprise cloning**; Phase-2b option: self-host permissive stack when (a) volume >1M chars/mo AND (b) a Telugu-capable commercial-safe cloner ships | ~0 (bundled) | Only demonstrated Telugu cloner | Enterprise-deal dependency; open-source Telugu cloning **does not exist yet** — biggest strategic gap on this page |
| 6 | Orchestration | LiveKit Agents (locked) — swap STT/TTS providers via existing abstraction | — | — | Low |
| **Σ** | | | **≈ 1.90–3.40 sticker → 1.1–2.0 expected** | | **vs ₹3.5/min competitor + ₹0.8 telephony: PASS with 35–65% headroom** |

**Sensitivity:** worst case (all stickers, max chars, v3 pricing) ≈ ₹3.40 — still under the line but thin; mitigations in order: negotiate v2-rate TTS (−₹0.5–0.9), shift default voices to shorter phrasings in domain-config, move TTS in-house at scale (−₹1+).

**Compliance notes carried forward:** consent capture precedes any cloning (DPDP); recording-retention and disclosure scripts unchanged from Phase-1 compliance-agent work; Sarvam's India-residency claim supports localization posture, Deepgram's does not — factor into the STT A/B weighting.

---

## 6. Sources (accessed 2026-08-26)

1. Sarvam — Saaras v3 launch blog (2026-02-10), STT product page (upd. 2026-05-06), official API pricing page, Bulbul docs & product pages, Bulbul v3 blog (2026-02-05) — sarvam.ai / docs.sarvam.ai
2. Third-party STT roundup: Saaras v3 vs Whisper vs Google Chirp (anuragwagh.com, 2026-07-23) — independent IndicVoices/Odia numbers
3. AI4Bharat — Vistaar paper + repo (arXiv 2305.15386, INTERSPEECH 2023), IndicConformer HF card (upd. 2026-03-02), Indic-TTS repo (ICASSP 2023), Indic Parler-TTS HF card, AI4Bharat ASR roadmap page ("8 kHz telephony" as future work)
4. Gnani.ai — Prisma v2.5 / Timbre v2.5 product & FAQ pages, homepage claims; CallMissed model listings (Gnani ₹27/hr, Saaras ₹30/hr, Sarvam-M ₹35/M) [reseller pass-through]
5. Deepgram — Nova-3 APAC expansion (2026-05-14), Telugu product page, Models & Languages docs
6. Sarvam-M/Sarvam-30B — CallMissed model dossier (training-mix & Indic Vibe Check figures), Artificial Analysis Sarvam-M pages (intelligence rank, deprecation notice)
7. Groq — CloudZero pricing table (2026-05-04), MarkAICode Groq benchmark/deprecation report (2026-07-12), Tickerr/aipricing.guru tables (Aug 2026)
8. llm-stats.com DeepSeek-V3 vs Gemma-3-27B (pricing/benchmarks); Data-Dynamics OSS LLM comparison (2026-04-16)
9. IndicTrans2 — AI4Bharat blog (M2M/distilled latency), GitHub issue #31 (hosted-demo vs local latency)
10. Spheron — self-host voice-cloning guide (XTTS-2/F5/OpenVoice, GPU economics, 2026-05-31); India GPU-cloud pricing survey (ecorpit.com, 2026); E2E Networks GPU pricing pages; Spheron India-provider guide (2026-05-23)
11. Forasoft voice-cloning build-vs-license guide (2026-08-02) — license traps, MOS landscape; Codesota OSS TTS registry (2026-03-28); gigagpu TTS rankings (2026-04)
12. InVideo Bulbul v3 explainer (2026-08-07) — pricing, no-self-serve-cloning confirmation; Economic Times Bulbul v3 launch (2026-02)
13. Cartesia — Telugu TTS page, all-languages page; PkgPulse TTS API comparison (2026-03-09)
14. ElevenLabs — pricing page (Business "$0.05/min" line), aiofm cloning guide (2026-05-05)
15. Vapi docs (voice pipeline, voice-fallback-plan), Smallest×Vapi integration page, Retell docs/homepage
16. sunlo-core repo — IndicTrans2-CT2 ~40 ms/clause pipeline datapoint (single-source, hobby grade)

## 7. Known gaps / follow-ups for qa-eval-agent

1. **No independent Telugu WER on real 8 kHz recordings exists for Saaras v3 vs Nova-3-te vs Prisma v2.5** — build a 60-min annotated test set (mixed Telugu/Tenglish, mobile+landline) and score all three; this single experiment decides STT.
2. **Sarvam-M function-calling + field-extraction accuracy unmeasured** — run the domain-config harness (absent-student flow translated) before signing anything.
3. **Bulbul v3 Telugu MOS on OUR scripts** — blind-test 5 candidate voices with college-office staff; Sarvam's own docs warn voices vary by language.
4. **Confirm Sarvam STT list price** (₹30/hr vs ₹1.5/min discrepancy) and enterprise cloning terms/pricing in writing.

> **RESOLVED ADDENDUM (2026-08-26):** Saaras v3 STT pricing confirmed **₹30/hour = ₹0.50/min**
> (docs.sarvam.ai/api-pricing — operative sheet; billed per second, rounded up). The
> "₹1.5/min" marketing figure is stale — disregard. Also: **Sarvam-M deprecated Jul 2026**
> → LLM tier = Sarvam-105B/30B chat API (₹2.5–4 per 1M input tokens, ~₹0.05–0.15/min
> effective), matching cost-cutter-overhaul Phase C. Bulbul v3 remains flagged
> beta-pricing = negotiation leverage. Sources: sarvam.ai/api-pricing,
> docs.sarvam.ai/api/getting-started/pricing, speech.dev/models/sarvam-saaras-v3
> (verified 2026-05-23).

---

# 8. Research: Telephony Alternatives

> Consolidated from source file: docs/research/telephony-alternatives.md

# Telephony Alternatives: Cutting VocalIQ's Biggest Cost Line — Legally

**Date:** 26 Aug 2026 · **Purpose:** options doc for slashing per-minute telephony spend on outbound AI voice calls terminating in India. All prices ex-GST unless noted; INR unless marked `$`. Every claim is cited inline with a source date. List prices are negotiation anchors, not quotes — re-verify before any contract.

---

## 0. TL;DR

| Question | Answer |
|---|---|
| Where does the money go today? | On Twilio we pay roughly **₹1.55–1.60/effective minute**: voice ~₹0.65–1.50/min + Media Streams $0.0044/min ≈ ₹0.37/min + recording/AMD extras. |
| Biggest single legal saving | **Move India legs to Plivo-class domestic routing: ₹0.38/min, audio streaming free → ~75% cut** (plivo.com/voice/pricing/in, retrieved Aug 2026). At 100k calls/mo ≈ **₹3.5 lakh/month avoided**. |
| Endgame rate | Direct carrier SIP (Jio/Tata/Airtel) lands at **~₹0.30–0.45/min all-in**, but only pays off around **20 lakh+ minutes/month** (caller.digital, 23 Jun 2026). |
| Cheapest legal ₹/min | **≈ ₹0.30–0.38/min telephony-only at scale. ₹0 is impossible** — PSTN termination is always billed by licensed access providers; DLT/KYC/DID carry non-zero floors (§6). |
| Legal landmine | Grey routes / SIM banks / eSIM banks are **criminal risk** (arrests Jan 2026; DoT shut 44 illegal exchanges Apr 2026), and the Feb 2025 TCCCPR amendment lets carriers bar our *entire legal* SIP trunk for 15 days on a first UCC violation (§2). |

---

## 1. The landscape: ways to buy Indian telephony minutes

### 1.1 Comparison table

Outbound calls to Indian mobiles assumed (our dominant cost); ~3 min avg/call.

| Dimension | **Global CPaaS (Twilio)** | **India CPaaS (Plivo)** | **India CPaaS (Exotel)** | **India CCaaS (Ozonetel / Knowlarity–Gupshup)** | **Direct carrier SIP (Airtel/Jio/Tata)** | **Self-hosted PBX + carrier SIP** |
|---|---|---|---|---|---|---|
| Outbound rate, India mobile | ~₹0.65 landline, **~₹1.20–1.50 mobile** (edesy.in, Jan 2026; frejun.com Voice API guide, May 2026) | **₹0.38/min** out & in (plivo.com/voice/pricing/in, retrieved Aug 2026) | Credit-based (~₹1/credit), est. **₹0.50–1.50/min**, opaque (prospeo.io 2026; edesy.in May 2026) | Knowlarity prepaid **₹0.40–0.60/min** after bundled mins (knowlarity.com/pricing/voice, Aug 2026); Ozonetel KooKoo **₹0.70/min + ₹500/mo** rental (prospeo.io 2026) | Benchmarks: **₹0.30–0.50 PSTN, ₹0.40–0.70 mobile termination**; high-volume direct-SIP contracts **₹0.60–1.20/min** (frejun.com Jul 2026 citing TRAI; caller.digital 23 Jun 2026) | Same as carrier SIP **+ your infra** — software layer free; aggregator margin removed |
| Platform/add-on fees | **Media Streams +$0.0044/min**, recording +$0.0025/min, AMD $0.0075/call (quiq.com Twilio breakdown, 2 Aug 2026) | Audio streaming & recording **free/included** (plivo.com/pricing, retrieved Aug 2026) | Bundled credits; dialer/SMS metered separately (cloudtalk.io, 2 Jul 2026) | Plan bundles; toll-free inbound ₹1.05/min extra | Channel rental + DID only | DevOps time; infra ₹10–50k/mo at scale |
| DID rental | ~$2.00/mo ≈ ₹200 (twilio.com voice pricing IN, May 2026) | **₹200/mo** (plivo.com) | Bundled/via sales | ₹250–1,500/mo typical (caller.digital, 10 Jul 2026) | ₹250–1,500/mo per DID | As carrier SIP |
| Setup effort | Hours, self-serve | **Days**: business KYC mandatory; DIDs 24–48 h (support.plivo.com Nov 2024; caller.digital Jun 2026) | Days–weeks; UL-VNO licensee, DLT hand-holding (frejun.com May 2026) | Weeks, sales-led; implementation often ₹25k–₹5L (prospeo.io 2026) | **Weeks–months**: enterprise KYC, link commissioning, static-IP/SBC work | Weeks–months on top of carrier SIP; "you become your own CPaaS" (caller.digital, Jun 2026) |
| Concurrency ceiling | 1 CPS free → up to 30 CPS provisioned; elastic concurrency (quiq.com Aug 2026) | PAYG hard-capped **2 RPS / 50 concurrent**; Enterprise from **$1,000/mo** (plivo.com/pricing; costbench.com 20 Jul 2026) | Sales-defined; thousands possible on contract | Prepaid channels 10–40; bespoke above | Jio: **10–5,000 channels/link**, pay for active channels (jio.com/business SIP Trunk, retrieved Aug 2026); TTBS **20–1,500 simultaneous** (tatatelebusiness.com); Airtel 30/number standard, more by quote | Hardware-bound: FreeSWITCH "thousands/node" (hirevoipdeveloper.com 7 Jul 2026); Asterisk tested **4,542 concurrent on 48 cores** (vitalpbx.com Oct 2023); rtpengine kernel module **10k+/instance** (17 Jul 2026) |
| Compliance burden (DLT/TRAI) | Self-managed; thinnest India tooling (frejun.com May 2026) | Native DLT workflow; enforces **KYC + India media anchoring** (support.plivo.com Nov 2024) | Strongest built-in DLT header/template/consent flows (frejun.com May 2026) | Mature posture; slower product velocity post-Gupshup acquisition (caller.digital Jun 2026) | Carrier runs scrubbing; you still register as PE/TM yourself | You own all of it: scrubbing, chain binding, traceability logs |
| KYC | Account + India docs for IN numbers | Business KYC before renting IN numbers (support.plivo.com Nov 2024) | Full business KYC | Full KYC + physical verification under 2025 rules | Heaviest: company docs, signatory verification; physical verification/biometrics now mandated (sigmachambers.in TCCCPR analysis 2025) | As whichever carrier you ride |
| Failure modes | Price shock at scale; **Media Streams has no India region** (US1 default, IE1/AU1 optional) → cross-border media hop = latency + DPDP optics (twilio.com/docs, 19 Aug 2026); vendor outage | Silent concurrency cliff at 50 calls; media-anchoring hangups if a leg leaves India ("Violates Media Anchoring", docs.plivo.com) | Credit exhaustion halts all calls instantly; opaque rates | Call-drop complaints at scale (61 G2 mentions, prospeo.io 2026); slow AI-media-streaming API evolution (caller.digital Jun 2026) | You own failover — one carrier outage = full stop until second trunk; long procurement; channel minimums waste money at low volume | Every CPaaS feature becomes your bug: retries, AMD, DTMF, status webhooks, NAT/SBC hardening, toll fraud |

### 1.2 Analysis at our volumes

**1k–10k calls/month (3k–30k min): managed CPaaS wins outright.** Carrier SIP economics invert at low volume: channel rentals (~₹350–700/channel/mo market norm, callin.io Mar 2025) plus minimums exceed what these minutes should ever cost. Plivo's flat ₹0.38/min with zero platform fee is the floor. Exotel/Knowlarity beat Plivo only if we need their DLT hand-holding or CCaaS features — we don't; LiveKit Agents *is* our contact center.

**100k calls/month (300k min): aggregator margin starts to hurt.** Aggregators charge ₹0.80–1.80/min retail on outbound mobile vs ₹0.60–1.20 on direct SIP contracts; enterprises cut direct deals around **20 lakh+ min/month** (caller.digital, 23 Jun 2026). Our crossover sits between ~100k–200k calls/mo — not before. Plivo's PAYG concurrency cap also bites near this tier (§4 math).

**Concurrency reality check (Erlang, not marketing):**
- 10k calls/mo ≈ 333 calls/day inside a ~6-hour calling window ≈ 56/hr ≈ **~3 concurrent** average. Trivial everywhere.
- 100k calls/mo ≈ 556/hr ≈ 9 CPS avg ≈ **~28 concurrent** (3-min holding time), peak ~45–60. Exactly where Plivo PAYG (50) and Knowlarity prepaid (10–40 ch) hit ceilings — and where a 60-channel carrier trunk becomes rational.

**Why not Twilio at any volume:** 2–3× India-rooted pricing, thinnest India compliance tooling, no India region for Media Streams (cross-border audio hop contradicts our localization stance), and per-feature surcharges stack invisibly (quiq.com, 2 Aug 2026). It survives only as a multi-country escape hatch — not our Phase-1 market.

---

## 2. The eSIM / SIM-bank grey-route question — documented so we never touch it

Grey routing = terminating calls through consumer SIMs held in SIM boxes/banks (or scaled consumer eSIM profiles) instead of licensed interconnect, dodging termination fees. Offers appear at ₹0.05–0.10/min. Verdict: **criminal, unreliable, banned for this project.**

**Illegal, with active enforcement:**
- Delhi Police IFSO busted an interstate SIM-box racket, seizing **thousands of illegally obtained SIMs** (ETTelecom/ANI, 10 Jan 2026); AP CID + DoT arrested **14 members** of an international SIM-box network, ~₹20 crore fraud (Communication Today, 27 Dec 2025); Chennai police seized **14 high-capacity Quectel SIM boxes** (Sep 2025, undercoverist.org); DoT dismantled **44 illegal telecom centres** nationwide per MHA's report to the Supreme Court (the420.in, 29 Apr 2026).
- Bulk SIM acquisition breaches DoT KYC/subscriber norms; **~4 million SIMs blacklisted via AI detection** (the420.in, 6 Aug 2025).
- **TCCCPR Second Amendment Regulations (12 Feb 2025)** obliges every access provider to deploy methods detecting "SIM Farm/SIM box type usage" and AI/ML-based proactive UCC monitoring, plus evidence-gathering honeypots (≥10 per service area) (trai.gov.in regulation PDF, Feb 2025). Carriers are mandated to hunt exactly this traffic.

**Unreliable even before getting caught:** carrier anti-spam firewalls **silently drop** grey/unregistered traffic — dead-ring calls, collapsing answer rates mid-campaign, unstable CLI, zero SLA recourse (grey routes ≈23% of A2P traffic and the top blocked-delivery source; voxsolutions.co CFO guide, 17 Jun 2026).

**Project policy:** grey routes are prohibited in code, vendors, and vendor conversations. Legal substitutes: DLT registration + designated-series numbers; volume negotiation (§4); shorter conversations via domain-config tuning.

**Compliance floors on the LEGAL path (Feb 2025 amendment; sigmachambers.in 2025):**
- Commercial calls may not originate on ordinary 10-digit numbers. Designated series: **140** promotional, **160 transactional/service — 160-series is not DND-scrubbed**, fitting our absent-student notification use case.
- Robocall/auto-dialer use must be **pre-declared** to the originating access provider.
- Penalties: **first UCC violation → ALL telecom resources (SIP trunks AND SIMs) barred 15 days; second → disconnection across all access providers** (Regulation 25 as amended, trai.gov.in, 12 Feb 2025). One sloppy campaign freezes our whole dialer for half a month — compliance is a cost line.
- Watch-item: *IndiaMART v. TRAI* (Delhi HC, listed Mar 2026; barandbench.com 9 Mar 2026) challenges complaint-driven barring for B2B callers; plan as if the rule stands.

---

## 3. Open-source stacks that pair with carrier SIP (replacing the Twilio Media Streams bridge)

Today: a CPaaS places the call and **Media Streams** pushes 8 kHz mulaw audio over WebSocket to our bridge, which relays to Deepgram → LLM → Cartesia. Three open-source paths replicate this on infrastructure we control:

### Path A — LiveKit SIP server (recommended; matches our locked LiveKit decision)

The open-source **`livekit/sip`** service is a SIP↔WebRTC bridge: define an outbound trunk pointing at any standard SIP provider (`<trunk-id>.zt.plivo.com`, `sip.telnyx.com`, …) plus inbound trunks + dispatch rules (docs.livekit.io/telephony outbound-trunk & sip-trunk-setup guides, rendered Aug 2026; github.com/livekit/sip). Self-hosted LiveKit carries "full support" for SIP/telephony — SIP runs as a separate service next to our existing LiveKit server (docs.livekit.io/intro/cloud comparison, 8 Aug 2026). Plivo publishes a first-party LiveKit guide and states its trunks "speak standard SIP… whether you self-host LiveKit or run it on LiveKit Cloud," with India media anchoring satisfied by running LiveKit in the India region (plivo.com/livekit, retrieved Aug 2026).

- **What replaces Media Streams:** nothing — the callee joins the LiveKit room as a participant; agents subscribe directly. The WebSocket relay layer disappears (fewer hops, lower latency, no per-stream fee).
- **What breaks / must be rebuilt:** call-status events → LiveKit webhooks; answering-machine detection → native AMD in LiveKit Agents (docs.livekit.io/telephony/features/answering-machine-detection, Jun 2026); DTMF → handled by livekit/sip (RFC2833/INFO); retry/redial logic stays in our backend dialer worker untouched.
- **What it saves:** the entire media-streaming surcharge category ($0.0044/min on Twilio; free on Plivo and free-once-self-hosted), plus CPaaS call-control margin when later paired with a raw carrier trunk.
- **Effort:** days–weeks: static egress IP or IP-ACL trunk auth, TLS/SRTP, one new service in docker-compose.

### Path B — FreeSWITCH + mod_audio_fork / mod_audio_stream

FreeSWITCH attaches a channel media bug and streams **bidirectional L16 PCM over WebSocket** (`uuid_audio_fork <uuid> start <wss-url> mono 16k`), accepting returned audio plus JSON control messages for barge-in/interruption (github.com/mdslaney/drachtio-freeswitch-modules README; callsphere.ai production walkthrough, 7 Apr 2026). That source calls it "structurally identical to the Twilio Media Streams bridge… but on infrastructure you control" — our FastAPI WSS bridge survives nearly intact; only framing changes (PCM vs base64 mulaw).

- **What breaks:** TwiML call control, mark/clear buffer semantics, Twilio-side AMD/recording — rebuilt as ESL logic or dropped. Tuned FreeSWITCH sustains "thousands" of concurrent calls/node (hirevoipdeveloper.com scaling guide, 7 Jul 2026).
- **Pick over A only if** we need deep dialplan control (predictive pacing, per-leg recording) livekit/sip doesn't expose.

### Path C — Kamailio + rtpengine (carrier-grade core for direct SIP)

Kamailio = signaling proxy; rtpengine = media proxy whose kernel module forwards RTP in-kernel — **10,000+ concurrent calls per instance** at modest CPU (hirevoipdeveloper.com rtpengine explainer, 17 Jul 2026); this pair is what tier-1 carriers run. Topology: carrier trunk → Kamailio (auth, topology hiding, fraud filtering) → rtpengine (RTP anchored in Mumbai) → agent stack via A/B behind it.

- **Use when:** direct carrier SIP at ~1M+ min/mo, multi-carrier failover, SBC duties. Overkill below that.
- **Gotchas:** rtpengine ng-control protocol on a private VLAN; strict-source learning on; `max-sessions` sized by load tests, not spec sheets (same source). Home-grown SBC scripts are easy to get wrong (irontec/itsbc README).

### What open source actually saves

**Platform fees, not physics** — the carrier still bills per-minute termination regardless of who bridges audio. Versus Twilio we delete: voice-rate premium (~₹0.8–1.1/min), Media Streams $0.0044/min, recording $0.0025/min, AMD $0.0075/call (quiq.com, 2 Aug 2026). Versus Plivo we delete only future Enterprise-tier/concurrency premiums. Hence the staged plan: **Path A on Plivo now; Paths A/C on carrier SIP when volume justifies** — not a big-bang PBX build.

Asterisk footnote: viable (4,542 concurrent tested on 48 cores, vitalpbx.com Oct 2023; community benchmarks ≈50 calls/core without transcoding, ~20 with), but weakest fit: its strengths are desk-phone PBX features we don't need; G.729 transcoding is CPU-hungry and licensed ($8/channel, asterisk.org, Jan 2025). Carriers give us G.711 end-to-end, so this rarely matters.

---

## 4. True cost model — 1k / 10k / 100k calls per month

**Assumptions:** 3.0 min avg connected call; we pay connected minutes only; FX ≈ ₹87/USD (Aug 2026); GST +18% excluded; DLT telemarketer/entity registration **₹5,900 one-time** (₹5,000+GST at Airtel/Jio/Vi DLT portals; BSNL ₹3,330; headers/templates ~free; 3–7 working days — smsgatewayhub.com & 2factor.in DLT guides, 2025–26).

Monthly telephony-only cost (platform fee + per-minute + DID/channel rentals):

| Option (rate basis) | 1k calls (3k min) | 10k calls (30k min) | 100k calls (300k min) |
|---|---|---|---|
| **Twilio** (₹1.20/min avg mobile + Media Streams ₹0.37/min + ₹200 DID) | **~₹4,900** | **~₹47,000** | **~₹471,000** |
| **Plivo PAYG** (₹0.38/min + ₹200 DID) | **~₹1,340** ✅ best | **~₹11,600** ✅ best | ~₹114,200* ⚠️ 50-concurrent cap borderline → Enterprise +$1,000/mo ⇒ ~₹201,000 |
| **Exotel** (est. ₹0.60–1.00/min blended + bundle) | ~₹2,600–3,800 | ~₹19,000–31,000 | ~₹185,000–305,000 (negotiable) |
| **Knowlarity prepaid** (Advance ₹16,800/yr ⇒ ₹1,400/mo incl 1,200 min, then ₹0.60/min, 10 ch) | ~₹2,600 | ~₹18,700 | Premium Plus (₹60k/yr, 40 ch, 10k free min, ₹0.40/min): ~₹126,000 |
| **Ozonetel KooKoo** (₹500 rental + ₹0.70/min out, +₹0.50/min port on entry plan) | ~₹3,200 | ~₹21,700 | ~₹210,700+ before sales discounts |
| **Carrier SIP direct** (₹0.35/min usage + channels @ ~₹400/ch/mo + ₹500 DID; install amortized) | ~₹5,300 ❌ minimums dominate | ~₹14,500 | ~₹130,500 (60 ch) → **~₹115,000** negotiated at scale ✅ best-at-scale |
| **Self-hosted (A/B/C) + carrier SIP** | carrier row + ₹8–15k infra (overkill) | carrier row + ₹10–20k infra | carrier row + ₹15–40k infra (media nodes + Kamailio/rtpengine) — buys independence, not cheaper minutes |
| **One-time, any legal path** | DLT **₹5,900** + KYC + (carrier-only) SIP install ₹5k–15k | — | — |

\* Peak Erlang at 100k calls/mo (~45–60 concurrent) straddles Plivo's PAYG cap; crossing it flips economics toward Enterprise tier or carrier SIP.

**Read-outs**
1. Per-connected-call cost drops **~₹4.90 → ~₹1.15** by moving Twilio→Plivo — a ~76% cut via a config-level trunk swap, zero agent-code change ("a configuration change, not a rewrite," plivo.com/livekit, Aug 2026).
2. Carrier-SIP crossover vs best CPaaS sits between ~100k–200k calls/mo (~300k–600k min), consistent with caller.digital's "direct SIP at 20 lakh+ minutes" guidance (23 Jun 2026). Below crossover, channel minimums lose money.
3. Fixed-cost gravity: at 1k calls/mo rentals are >50% of bill — boring pay-as-you-go wins. At 100k, per-minute dominates — every paisa is negotiable.
4. Telephony ≠ total cost: India full-stack AI voice sells at ₹6–12/min (bolti.co.in, 26 Jun 2026); at Plivo rates telephony is ~25–35% of unit economics. Keep logging STT/LLM/TTS vs telephony cost splits per call (CLAUDE.md convention) so the next optimisation targets the right line.

---

## 5. Migration sketch: off Twilio, onto the locked Plivo-first path

CLAUDE.md already locks "Plivo first (Exotel fallback), not Twilio." This executes that; the cascaded LiveKit architecture is untouched.

**Phase 0 — Compliance & accounts (week 1, all parallel).**
File DLT entity/telemarketer registration on a Jio/Airtel portal (₹5,900, 3–7 working days); register header + consent/content templates for the absent-student flow. Open Plivo account + business KYC (mandatory before IN numbers — support.plivo.com, Nov 2024). Buy 1–2 **160-series** service numbers; pre-declare auto-dialer use to the access provider (§2).
*Risks:* template rejections burn days — submit day one; KYC back-and-forth — keep incorporation/GST/signatory docs ready.

**Phase 1 — Parallel-run voice path (weeks 2–4).**
Deploy `livekit/sip`; create outbound trunk to Plivo (`<trunk-id>.zt.plivo.com`) and inbound trunk + dispatch rule (docs.livekit.io/telephony, Aug 2026). Pin LiveKit + Plivo media to India region for anchoring. Keep Twilio trunks configured as instant fallback. Test: answer rate, ASR accuracy on telephony audio, barge-in latency, AMD hit rate, DTMF, call-status webhooks.
*Exit criterion:* 2 weeks of parallel traffic with ≥ parity on connect rate + extraction accuracy.

**Phase 2 — Dialer cutover (month 2).**
Point the campaign worker at Plivo-originated calls; Twilio stays warm (disabled by default). Add Exotel as second provider behind a provider-abstraction interface (already our stated fallback) so no single vendor can halt campaigns. Verify in-India media anchoring on every call leg (hangup-cause monitoring for "Violates Media Anchoring").

**Phase 3 — Scale renegotiation (month 3+, trigger: >300k min/mo sustained or concurrency cap hits).**
Either Plivo Enterprise tier (custom concurrency, volume rates from $1k/mo commitment — plivo.com/pricing) **or** begin direct Jio/Tata SIP evaluation with Path C (Kamailio+rtpengine) fronting it. Keep CPaaS as failover trunk permanently.

**What stays throughout:** domain-config runtime (`/domain-configs`), agent pipeline (Deepgram/Groq/Cartesia), FastAPI backend, React frontend, consent/retention jobs. Only the telephony edge changes — which is exactly why the swap is cheap.

**Top migration risks:** DLT delay (mitigate: Phase 0 starts immediately); number porting lead times if we port the prototype number (ports take 2–4 weeks at some vendors vs 24–48 h for new DIDs — caller.digital, Jun 2026; prefer new 160-series numbers); anchoring misconfig silently failing calls (monitor hangup causes); concurrency cap surprises during a campaign burst (load-test at 1.5× planned CPS).

---

## 6. Honest bottom line

**Cheapest legal achievable telephony-only ₹/min:**
- **Now → 100k calls/mo: ~₹0.38/min** (Plivo domestic, streaming free) ≈ **₹1.15/call** at 3 min.
- **At scale (~20 lakh+ min/mo): ~₹0.30–0.45/min all-in** via negotiated carrier SIP (usage + channel rentals + DID blended), per TRAI-anchored market benchmarks (frejun.com Jul 2026; caller.digital Jun 2026). Self-hosting the bridge layer removes platform fees but cannot go below carrier termination — physics of the PSTN.

**Where ₹0 is impossible — explicitly:**
1. **PSTN termination is metered by licensed access providers.** Any legal call to an Indian mobile pays carriage; no software choice changes that. Only app-to-app WebRTC (both parties in our app) approaches ₹0 — useless for calling absent students' phones.
2. **Regulatory floor:** DLT registration ₹5,900 + KYC effort; designated-series number rentals; consent-management and traceability engineering mandated by TCCCPR (Feb 2025).
3. **Reliability floor:** SLA'd failover (second provider/trunk) costs money precisely because single-route grey-style "free" capacity gets silently blocked (§2).

**The one-sentence strategy:** cut ~75% today by replacing Twilio's India legs + Media Streams with Plivo + self-hosted LiveKit SIP (₹5,900 DLT once), stay pay-as-you-go until ~100k calls/mo, then trade aggregator margin for direct carrier SIP — and never, under any circumstances, let a ₹0.05/min SIM-bank offer through the door.

---

## Sources (accessed Aug 2026)

- Plivo India voice/SIP pricing ₹0.38/min, ₹200 DID, streaming included — plivo.com/voice/pricing/in & /sip-trunking/pricing/in
- Plivo PAYG caps (2 RPS / 50 concurrent), Enterprise $1k/mo — plivo.com/pricing; costbench.com (20 Jul 2026)
- Plivo India KYC + media anchoring rules — support.plivo.com "Domestic Calling in India" (18 Nov 2024)
- Twilio India outbound ₹0.65–1.50/min; DID $2/mo — twilio.com/voice/pricing/in (18 May 2026); edesy.in guides (Jan/May 2026); frejun.com Voice API guide (27 May 2026)
- Twilio surcharges (Media Streams $0.0044/min etc.), CPS limits, Media Streams regions — quiq.com Twilio pricing breakdown (2 Aug 2026); twilio.com/docs/voice/media-streams/websocket-messages (19 Aug 2026)
- Exotel credit model & plans — cloudtalk.io Exotel guide (2 Jul 2026); prospeo.io (2026)
- Knowlarity prepaid plans ₹16,800–60,000/yr, ₹0.20–0.30/30 s — knowlarity.com/pricing/voice (22 Aug 2026); Gupshup acquisition — gupshup.ai press releases (2022/2025)
- Ozonetel CloudAgent $25–55/agent/mo; KooKoo ₹500/mo + ₹0.70/min — prospeo.io Ozonetel/KooKoo analyses (2026); cloudtalk.io (28 Apr 2026)
- Carrier SIP benchmarks ₹0.30–0.70/min; channel rentals ₹350–700/mo; direct-SIP threshold 20 lakh+ min/mo — frejun.com SIP trunk guide (10 Jul 2026); caller.digital telephony-partner comparison (23 Jun 2026) & voice-AI cost breakdown (10 Jul 2026); callin.io (11 Mar 2025)
- Jio SIP Trunk 10–5,000 channels, unlimited-domestic rental plans, 140xx trunks — jio.com/business/services/voice-and-collaboration/sip-trunk (retrieved Aug 2026); indicative entry tariffs — call-soft.com (2026)
- Airtel SIP trunk 30 simultaneous/number — airtel.in/b2b/sip-trunk; TTBS 20–1,500 channels — tatatelebusiness.com; Smartflo ₹950–1,250/license/mo, OBD ₹0.48–0.60/min effective — tatatelebusiness.com/features/smartflo; infinian.net (19 Feb 2026)
- TCCCPR Second Amendment Regulations (12 Feb 2025): SIM-farm detection mandate, honeypots, 140/160 series, 10-digit ban, 15-day barring/disconnection penalties — trai.gov.in Regulation_12022025 PDF; sigmachambers.in analysis (2025); barandbench.com *IndiaMART v. TRAI* (9 Mar 2026); PIB releases (Mar–Jun 2025)
- DLT registration ₹5,900 (BSNL ₹3,330), process/timelines — smsgatewayhub.com/dlt-registration; 2factor.in (2025); digintra.com (2026)
- SIM-box enforcement: ETTelecom/ANI (10 Jan 2026); Communication Today/AP CID (27 Dec 2025); the420.in DoT-44-exchange report to SC (29 Apr 2026) & 4M-SIM blacklist (6 Aug 2025); undercoverist.org Chennai seizures (6 Oct 2025)
- Grey-route economics — voxsolutions.co CFO guide (17 Jun 2026); Subex bypass-fraud analysis (5 Jun 2026)
- LiveKit open-source SIP server, self-hosted support, trunk config, native AMD — github.com/livekit/sip; docs.livekit.io/telephony/* (rendered Jun–Aug 2026); docs.livekit.io/intro/cloud (8 Aug 2026); plivo.com/livekit integration (retrieved Aug 2026)
- FreeSWITCH mod_audio_fork bidirectional WebSocket PCM bridge — drachtio-freeswitch-modules README (github); callsphere.ai walkthrough (7 Apr 2026); arkade-ai/mod_audio_stream (2025–26)
- Capacity: FreeSWITCH thousands/node (hirevoipdeveloper.com, 7 Jul 2026); rtpengine kernel module 10k+ concurrent (17 Jul 2026); Asterisk 4,542 concurrent/48 cores (vitalpbx.com, 7 Oct 2023); Asterisk community benchmarks & G.729 license (asterisk.org, 18 Jan 2025)



---

# 9. Cost-Cutter Overhaul Approach

> Consolidated from source file: docs/plans/cost-cutter-overhaul-approach.md

# Cost-Cutter Overhaul — Implementation Approach

**Author:** senior-ai-engineer · **Date:** 2026-08-26 · **Status:** APPROVED direction, ready for orchestration dispatch
**Mandate:** beat the ₹3.5/min multilingual competitor using open-source-first components — multilingual (English + Telugu + Tenglish) calls at ≤₹2/min all-in on Plivo India legs, same product surface.
**Inputs grounded:** `docs/research/telephony-alternatives.md`, `docs/research/multilingual.md`, actual code (`backend/app/services/{telephony,twilio_bridge,g711}.py`, `backend/app/routers/{twilio,test_call}.py`, `backend/app/services/{dialer,calls_service}.py`, `backend/app/main.py`, `backend/app/config.py`, `voice-agent/app/{pipeline,config}.py`, `frontend/src/components/VoiceSettingsForm.jsx`, `.env.example`) + live vendor-doc verification (Plivo `<Stream>`, Sarvam chat-completions) performed 2026-08-26.

---

## 0. Research-vs-code conflicts found while reading — read these first

1. **Sarvam-M is DEPRECATED (multilingual.md §2 recommendation is stale).** Official docs fetched today state: *"Sarvam-M (24B) has been deprecated and is no longer available through the Chat Completions API. Please migrate to Sarvam-30B or Sarvam-105B"* (docs.sarvam.ai Chat Completions Overview, accessed 2026-08-26). This plan targets **`sarvam-105b`** (non-think mode) everywhere multilingual.md says "Sarvam-M".
2. **The two research docs disagree on Plivo cost.** multilingual.md §5 assumes telephony ≈ ₹0.80/min; telephony-alternatives.md lands **₹0.38/min all-in** (plivo.com/voice/pricing/in, Aug 2026, streaming + recording included). This plan uses **₹0.38**; multilingual.md's Σ rows are therefore conservative by ~₹0.42/min.
3. **`voice_settings.stt_language` and `speaking_rate` are dead config today.** The frontend saves them (`frontend/src/components/VoiceSettingsForm.jsx:87` shape `{tts_voice_id, speaking_rate, stt_language, llm_model}`), `/internal/agent-config` returns them (`backend/app/routers/internal.py:114`), but `pipeline._voice_overrides()` (`voice-agent/app/pipeline.py:114-123`) reads only `llm_model` and `tts_voice_id`, and Deepgram language is hardcoded `"en"` (`pipeline.py:144`). Phase B makes these live.
4. **`main.py::_should_run_dialer()` hardcodes the Twilio credential gate** (`backend/app/main.py:34-40`). If we only provisioned Plivo credentials, the dialer silently wouldn't start. Must be made provider-aware in Phase A.
5. **Plivo `<Stream>` bidirectional support: VERIFIED.** Official docs confirm two-way audio for voice-AI: `<Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">wss://…</Stream>`; outbound audio via `{"event":"playAudio","media":{"contentType":"audio/x-l16|x-mulaw","sampleRate":8000,"payload":"<base64>"}}`; barge-in flush via `clearAudio` control event; Plivo retries a dropped WS twice before disconnecting (plivo.com/docs/voice/xml/audio-streaming; plivo.com/docs/voice-agents/audio-streaming/xml/stream, upd. 2026-07-17; old-support.plivo.com Audio Stream FAQ). Constraints: with `bidirectional=true`, `audioTrack` cannot be `outbound`/`both` (caller-audio only); **default contentType is `audio/x-l16;rate=8000` PCM, NOT mulaw** — we set mulaw explicitly so `g711.py` is reused unchanged; **`extraHeaders` allows only `[A-Za-z0-9]` (max 512 B)** — underscore illegal, so `call_id` rides the answer_url query string instead (we generate the answer XML per call, same pattern as `_voice_webhook()` today).
6. **Protocol deltas vs Twilio Media Streams** (drives Phase A parser work): no `"connected"` greeting frame (first frame is `start`); metadata lives at `start.callId` / `start.streamId` (not `streamSid`/customParameters); outbound event is `playAudio` (not `media`); signature header is `X-Plivo-Signature-V3` (not `X-Twilio-Signature`). Structurally still "base64 8 kHz mulaw over WSS with start/media/stop events" — our bridge pumps survive almost intact.
7. **`docs/research/cost-engineering.md` does not exist** despite being referenced by my operating rules — the ₹/min ledger below follows the conventions of the two research docs that do exist (ex-GST, FX ₹87/$, connected-minute billing). Creating that ledger file should be a follow-up for devops/backend.
8. **Scope guardrail:** CLAUDE.md says "don't start Telugu/Sarvam work — that's Phase 2." This approved mandate *is* the Phase-2 kickoff; Phases B/C remain execution-gated behind Phase D acceptance numbers regardless.
9. **Path choice note:** telephony-alternatives.md recommends self-hosted `livekit/sip` (Path A). The mandate directs the Plivo XML `<Stream>` bridge instead — the correct near-term call: it reuses our existing Media-Streams-style bridge (~days, not weeks), keeps every rupee of the ₹0 streaming fee (free on Plivo either way), and leaves `livekit/sip` as the >50-concurrent scale option. Revisit only when PAYG concurrency caps bind (§Risk R7).

---

## 1. Target end-state

VocalIQ places outbound calls on Plivo Indian 160-series legs (₹0.38/min, streaming/recording/AMD included, media anchored in India) through a provider-neutral `TelephonyClient` seam selected by `TELEPHONY_PROVIDER`, with Twilio kept warm as an instant-revert fallback; the cascaded LiveKit pipeline resolves its STT/LLM/TTS per immutable AgentVersion from `voice_settings` — Deepgram/Groq/Cartesia remain the platform defaults for English agents, while Telugu/Tenglish agents select Sarvam Saaras-v3 STT + `sarvam-105b` (non-think) + Bulbul-v3 TTS, all reachable behind the same `ProviderBundle` construction and instrumented turn telemetry; qa-eval owns numeric promotion gates (WER, ≥85 % extraction accuracy, ≤900 ms median e2e) so any component flips to default only on evidence and reverts by env flip or a new AgentVersion row — landing multilingual calls at **≈ ₹1.5–2.1/min all-in** (sticker ceiling ≈ ₹3.0, held under ₹2.0 by TTS char discipline + rate negotiation), versus ≈ ₹3.8–5.4 today.

---

## 2. Phased plan (each phase independently deployable AND revertible)

### Phase A — Telephony provider abstraction: `PlivoClient` + Plivo media bridge

**Goal:** dialer/test-call place calls through Plivo; Plivo legs stream into the same `phone-*` LiveKit rooms the voice-agent already serves. Deployable alone; revert = `TELEPHONY_PROVIDER=twilio` + restart (both webhook surfaces stay mounted permanently).

**New modules**

```python
# backend/app/services/plivo_client.py  (mirrors TwilioClient style: lazy import,
# settings injected, logger.info on placement)
class PlivoClient:
    """Production telephony client using the Plivo REST API."""
    def __init__(self, settings: Settings) -> None: ...
    def _answer_webhook(self, call_id: int) -> str:
        # f"{settings.public_base_url.rstrip('/')}/plivo/voice?call_id={call_id}"
        ...
    def place_call(self, to: str, call_id: int) -> str:
        # lazy `from plivo import RestClient`
        # client.calls.create(
        #     src=settings.plivo_phone_number, dst=to,
        #     answer_url=self._answer_webhook(call_id), answer_method="POST",
        #     hangup_url=f"{base}/plivo/status", hangup_method="POST",
        #     machine_detection="true",                      # AMD included on Plivo
        #     record="record-from-answer-dual",              # ⚠ confirm exact kwarg +
        #     recording_callback_url=...,                    #   callback name vs plivo-python at impl
        # )
        # returns CallUUID (str) — stored in Call.provider_call_id like CallSid
        ...

# backend/app/services/plivo_bridge.py  (pure logic + XML builders, unit-testable
# like twilio_bridge.py; reuses MediaEvent dataclass)
PHONE_STREAM_CONTENT_TYPE = "audio/x-mulaw;rate=8000"

def build_answer_xml(ws_base_url: str, call_id: int) -> str:
    # <Response><Stream bidirectional="true" keepCallAlive="true"
    #   contentType="audio/x-mulaw;rate=8000"
    #   statusCallbackUrl="{base}/plivo/stream-status">{ws_base_url}/plivo/media</Stream></Response>
    # call_id reaches the handler via the answer_url QUERY PARAM (extraHeaders
    # charset forbids underscores), not via XML attributes.
def parse_plivo_event(raw: Any) -> "MediaEvent":
    # start: ev.event="start", ev.stream_sid=start.streamId, ev.call_sid=start.callId
    # media: ev.media_payload = media.payload (base64 mulaw — contentType pinned above)
    # stop/dtmf passthrough; NO "connected" frame exists (unlike Twilio)
def build_play_audio(stream_id: str, ulaw_b64: str) -> str:
    # {"event":"playAudio","streamId":sid,"media":{"contentType":"audio/x-mulaw",
    #  "sampleRate":8000,"payload":b64}}   ← Plivo's outbound frame
def build_clear_audio(stream_id: str) -> str:
    # {"event":"clearAudio","streamId":sid}  ← barge-in flush (upgrade over Twilio path)
```

**New router** `backend/app/routers/plivo.py` — mirrors `routers/twilio.py` structure exactly:

- `POST /plivo/voice` (`plivo_voice(request, call_id: int, db)`) — `_check_plivo_signature()` (X-Plivo-Signature-V3 via plivo SDK validator, gated on `settings.plivo_validate_signature`), same Call/contact bookkeeping block as `twilio_voice` (`routers/twilio.py:319-346`), then `Response(build_answer_xml(settings.media_ws_base_url, call_id), media_type="application/xml")`.
- `WS /plivo/media` (`plivo_media(websocket)`) — clone of `twilio_media` (`routers/twilio.py:193-316`) with three deltas: (a) handshake expects `start` first (drop the `"connected"` continue at line 231), `ev.call_id` comes from the `call_id` query param on the upgrade request, `ev.call_sid == call.provider_call_id` replaces the CallSid check (line 247); (b) inbound pump feeds `ulaw_to_pcm16(payload)` → same `_make_frame`/`source.capture_frame`; (c) outbound pump sends `build_play_audio(...)` frames and `build_clear_audio(...)` when the room signals agent interruption. Reuses `_make_frame`, `_drain_track`, `_put_sentinel`, queue/backpressure logic verbatim — extract those three into `backend/app/services/media_bridge.py` and have **both** routers import them (twilio.py behavior unchanged; pure move).
- `POST /plivo/status` — hangup callback; `PLIVO_STATUS_MAP` added beside `TWILIO_STATUS_MAP` in `services/calls_service.py` (Plivo mirrors TwiML status enums: queued/ringing/in-progress/completed/busy/no-answer/failed/canceled — confirm exact strings against first sandbox callbacks), then the same `end_call(...)` branch as `twilio_status` (`routers/twilio.py:349-394`).
- `POST /plivo/recording` — persists `RecordingUrl` onto `Call.recording_url`, mirroring `twilio_recording`.
- Mount in `main.py::create_app` next to `fast_app.include_router(twilio.router)` (line 102), still prefix-less.

**Touch-points on existing code**

- `backend/app/config.py` — add: `telephony_provider: str = "twilio"`, `plivo_auth_id/plivo_auth_token/plivo_phone_number: str = ""`, `plivo_validate_signature: bool = False`; extend `provider_presence` with `"plivo"` and `"telephony_provider"`.
- `backend/app/main.py` — rewrite `_build_telephony()` (lines 26-31) as a registry: build `TwilioClient` iff twilio creds, `PlivoClient` iff plivo creds, always keep `FakeTelephonyClient` fallback; `fast_app.state.telephony_registry: dict[str, TelephonyClient]` + `fast_app.state.telephony = registry[settings.telephony_provider]` (back-compat for `test_call._get_telephony`). Rewrite `_should_run_dialer()` (lines 34-40) to `settings.dialer_enabled and bool(registry-with-real-clients)` — fixes conflict #4.
- `backend/app/routers/test_call.py` — add optional `provider: Optional[str] = None` to `TestCallRequest`; `_get_telephony(request, payload.provider)` resolves from the registry (default = `settings.telephony_provider`). **This is the dual-run lever:** A/B arms on live calls without redeploy.
- `.env.example` — add `TELEPHONY_PROVIDER=twilio`, `PLIVO_AUTH_ID=`, `PLIVO_AUTH_TOKEN=`, `PLIVO_PHONE_NUMBER=` (+160-series placeholder), `PLIVO_VALIDATE_SIGNATURE=false`.
- Tests: `backend/tests/test_plivo_client.py` (fake RestClient injection: URL shapes, sid returned, failure → exception like `test_call_flow.py` pattern), `backend/tests/test_plivo_bridge.py` (XML golden test, `parse_plivo_event` happy/junk/start-no-callid, playAudio/clearAudio frame shapes), extend `test_call_flow.py` with provider-override resolution cases.

**Verification gate A:** unit suite green → sandbox call to own allowlisted number via `POST /api/test-call {provider:"plivo"}` → transcript appears in dashboard, `turn_latency` log lines show nonzero e2e_ms, hangup maps to internal status correctly, recording URL persists, `clearAudio` observed on intentional interruption. Exit: 2 weeks dual-run parity (connect rate within ±5 %, ASR accuracy eyeball-parity on telephony audio) before `TELEPHONY_PROVIDER=plivo` becomes default.

---

### Phase B — Sarvam speech providers (STT/TTS) behind `voice_settings`

**Goal:** Telugu/Tenglish agents run Saaras-v3 STT + Bulbul-v3 TTS; Deepgram/Cartesia stay platform defaults until Phase D promotes otherwise. Revert = save a new AgentVersion without the sarvam keys (immutable-version model makes this trivial) or unset `SARVAM_API_KEY` (graceful degradation path already exists: `bundle.problems`).

**New module** `voice-agent/app/providers_sarvam.py` (livekit-plugins pattern: subclasses of `stt_module.STT` / `tts_module.TTS`, constructed with keys, degrade-by-absence handled in `build_providers`):

```python
class SarvamSTT(stt_module.STT):
    """Saaras v3 streaming ASR over Sarvam's WebSocket API (8 kHz telephony focus)."""
    def __init__(self, *, api_key: str, model: str = "saaras:v3",
                 language: str = "te-IN", codemix: bool = True,
                 sample_rate: int = 16000) -> None: ...
    # implements stream(): emit stt_module.SpeechEvent(interim/final transcripts)

class SarvamTTS(tts_module.TTS):
    """Bulbul v3 streaming synthesis; native 8 kHz mulaw output for telephony rooms."""
    def __init__(self, *, api_key: str, model: str = "bulbul:v3",
                 voice: str, sample_rate: int = 8000) -> None: ...
    # implements synthesize()/stream() yielding rtc.AudioFrame at 8 kHz
```

If a maintained `livekit-plugins-sarvam` package exists at implementation time (research notes "LiveKit/Pipecat integrations exist"), vendor-thin-wrap it instead of hand-writing the WS layer — decide at Task 1, interface above is fixed either way.

**Touch-points on existing code**

- `voice-agent/app/pipeline.py` — replace `_voice_overrides()` tuple with a frozen dataclass and consume it in `build_providers()` (signature unchanged):

```python
@dataclass(frozen=True)
class VoiceOverrides:
    llm_provider: str = ""      # ""|"groq"|"sarvam"
    llm_model: str = ""
    stt_provider: str = ""      # ""|"deepgram"|"sarvam"
    stt_language: str = ""      # "en"|"en-IN"|"te-IN"|...
    tts_provider: str = ""      # ""|"cartesia"|"sarvam"
    tts_voice_id: str = ""

def _voice_overrides(voice_settings: Optional[Mapping[str, Any]]) -> VoiceOverrides: ...

def build_providers(settings: Settings,
                    voice_settings: Optional[Mapping[str, Any]] = None) -> ProviderBundle:
    # STT branch: sarvam if overrides.stt_provider=="sarvam" AND settings.sarvam_api_key
    #             else deepgram.STT(model="nova-3",
    #                 language=overrides.stt_language or "en",   # ← un-hardcodes line 144
    #                 endpointing_ms=200, ...)
    # TTS branch: sarvam if overrides.tts_provider=="sarvam" AND key
    #             else cartesia.TTS(api_key=..., voice=overrides.tts_voice_id or default)
    # missing-key degradation appends to bundle.problems exactly as today
```

  `run_session` (line 642 `config.get("voice_settings")`) needs zero changes.
- `voice-agent/app/config.py` — add `sarvam_api_key: Optional[str]` + `_get("SARVAM_API_KEY")`; extend `provider_problems()` messaging.
- `backend/app/config.py` — add `sarvam_api_key: str = ""` (presence-only, mirrors deepgram/cartesia block, lines 78-84) + `provider_presence["sarvam"]`.
- `backend/app/domain_config_schema.py:118` — `voice_settings` is already free-form `Dict[str, Any]`: **no migration**; optionally whitelist the six keys above to catch typos in AgentBuilder.
- `frontend/src/components/VoiceSettingsForm.jsx` — extend `LANGUAGES` with `te`/`te-IN`; add provider radio pairs (STT: Deepgram/Saaras · TTS: Cartesia/Bulbul) shown when `SARVAM_API_KEY` presence flag is served; add a Bulbul preset section to `VOICE_PRESETS` populated from Sarvam's per-language recommended-speaker mapping (their own docs admit per-language variance — copy their mapping outright per multilingual.md §4). Persist through the existing `{...v.voice_settings}` merge (`AgentBuilderPage.jsx:89`).
- `.env.example` — `SARVAM_API_KEY=`, `SARVAM_STT_MODEL=saaras:v3`, `SARVAM_TTS_MODEL=bulbul:v3`.
- Tests: offline-only (livekit-agents import guard respected — pure logic in `providers_sarvam.py` kept thin): override-parsing tests for `VoiceOverrides` in `voice-agent/tests/` mirroring existing prompting/extraction test layout; contract test asserting `/internal/agent-config` roundtrips the six keys (`backend/tests/_qa_contract.py` pattern).

**Verification gate B:** sandbox Telugu test call end-to-end on a `phone-*` room; `TurnTelemetry` shows `transcription_delay_ms` + `tts_first_audio_ms` populated for the Sarvam path; Telugu script renders in transcript rows and browser captions (`_publish_caption` already UTF-8-safe); barge-in works (Silero VAD is language-agnostic). Exit: hand the arm to Phase D.

---

### Phase C — LLM routing: `sarvam-105b` (non-think) + Groq escalation

**Goal:** per-agent `voice_settings.llm_provider="sarvam"` routes through Sarvam's OpenAI-compatible chat completions; Groq remains default and escalation tier. Revert = AgentVersion re-save or unset provider key. Cost-neutral vs Groq (₹0.05–0.30/min either way) — this phase is quality-driven (Indic Vibe Check 8.12/9), decided by Phase D numbers.

**Endpoint facts (verified today, docs.sarvam.ai):** OpenAI-compatible request/response; **tool calling documented** (`tools`/`tool_choice`, `finish_reason:"tool_calls"`, max 128 tools) — closes part of multilingual.md GAP #2, though LiveKit-framework validation remains the hard gate; auth accepts `Authorization: Bearer <key>` in addition to `api-subscription-key` (so `livekit.plugins.openai.LLM` works unmodified); `stream_options`/`max_completion_tokens`/`service_tier` are auto-stripped server-side (LiveKit may send them — tolerated); **setting `reasoning_effort` to ANY value enables think mode** → we simply never send it (non-think default), mirroring the existing Qwen `reasoning_effort:"none"` concern at `pipeline.py:166-169`.

**Touch-points**

- `voice-agent/app/pipeline.py::build_providers` — insert before the Groq branch:

```python
if overrides.llm_provider == "sarvam" and settings.sarvam_api_key:
    bundle.llm = openai.LLM(
        model=overrides.llm_model or settings.sarvam_model,   # "sarvam-105b"
        api_key=settings.sarvam_api_key,
        base_url=settings.sarvam_llm_base_url,                # "https://api.sarvam.ai/v1"
        # NOTE: no reasoning_effort kwarg — any value enables think mode (latency)
    )
elif settings.groq_api_key:  # existing Groq branch untouched (escalation/default)
    ...
```

  Exact version-segment caveat: reference pages show both `/v1`-style and `POST …/v2/chat/completions` paths — pin `SARVAM_LLM_BASE_URL` via env and confirm with one curl during implementation; if `/v2` is authoritative, `base_url="https://api.sarvam.ai/v2"` is the only change.
- `voice-agent/app/config.py` — add `sarvam_model: str = "sarvam-105b"`, `sarvam_llm_base_url: str = "https://api.sarvam.ai/v1"`.
- `frontend/src/components/VoiceSettingsForm.jsx` — extend `LLM_MODEL_CHOICES`: `{value:"sarvam-105b", label:"Sarvam 105B — best Telugu/Tenglish"}`; label the pair `(llm_provider,llm_model)` in the saved object (empty provider = legacy model-string behavior preserved for existing versions).
- Rule-based escalation wiring (locked architecture): hard-turn triggers in `escalation_rules` already flow through prompts; the escalation *tier* stays Groq GPT-OSS-120B — implemented as prompt/session guidance, not a second LLM connection (unchanged from today; revisit only if qa-eval shows Sarvam failing specific turns that Groq passes).
- `.env.example` — `SARVAM_MODEL=sarvam-105b`, `SARVAM_LLM_BASE_URL=https://api.sarvam.ai/v1`.
- Tests: provider-selection unit tests (sarvam branch chosen iff provider+key; falls back to Groq with a `problems` entry otherwise).

**Verification gate C:** synthetic tool-loop test — AgentSession with `record_extracted_field`/`end_call` tools driven against Sarvam in a scripted conversation; assert tool_calls fire with parseable `function.arguments` JSON (docs warn arguments are a JSON *string*). Only then live-call gate via Phase D.

---

### Phase D — qa-eval acceptance harness (gates every default-flip)

**Goal:** no provider swap becomes default without numbers. Nothing here ships to prod paths; it's the referee.

**New tree** `qa-eval/` (repo root, sibling of `backend/`):

```
qa-eval/
  datasets/
    telugu_8khz_gold.jsonl     # 60-min annotated set: mixed Telugu/Tenglish,
                               # mobile+landline captures (multilingual.md §7 gap #1)
    absent_student_flow.json   # Telugu translation of the domain-config question flow
  harness.py                   # offline leg: replay dataset audio -> candidate STT;
                               # score WER (jiwer) + extraction accuracy vs gold fields
  live_suite.py               # live leg: N calls via POST /api/test-call per arm
                               # (allowlisted numbers only), pull turns/latency/
                               # extracted_fields from existing APIs, emit report.json
  report.py                    # renders the gate table; exit code 1 on any gate fail
  gates.yaml                   # the numeric contract below, versioned
```

**Gate contract (`gates.yaml`, initial values)**

| Gate | Threshold | Source |
|---|---|---|
| STT WER (Telugu, 8 kHz gold set) | Sarvam ≤ 25 % absolute AND ≤ Deepgram-`te` + 0 pts relative | decides STT swap |
| Extraction accuracy | ≥ 85 % required-field accuracy per arm (FR-12; no fabricated values — low-confidence flags counted as failures only if unfilled) | PRD constraint |
| Median e2e latency | ≤ 900 ms (`e2e_ms` from existing `TurnTelemetry` posts) | locked NFR-1 |
| p95 e2e latency | ≤ 1500 ms | headroom guard |
| Connect rate (live leg) | within ±5 pts of incumbent arm | Phase A parity carry-over |
| TTS naturalness | blind MOS ≥ 4.0 on OUR scripts, 5 voices × college-office staff | multilingual.md §7 gap #3 |
| Tool-call reliability | ≥ 95 % of turns requiring `record_extracted_field` produce a well-formed call | Phase C hard gate |

**Promotion rule:** an arm (e.g., `plivo+saaras+sarvam-105b+bulbul`) becomes platform default only after (1) two consecutive passing weekly runs, (2) owner sign-off on the report. Default-flips are env/version operations (`TELEPHONY_PROVIDER`, new AgentVersion rows), so rollback is always one flip away.

**Touch-points:** consumes only existing surfaces (`/api/test-call` with `provider` override from Phase A, `/internal/*`, transcript/latency tables). One backend addition allowed: expose extracted-fields-per-call via the existing calls API if not already exported (check `routers/export.py` first — likely reusable as-is).

---

## 3. Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **Plivo stream quirks**: no `connected` frame breaks naive handshake; default codec is L16 not mulaw; `extraHeaders` charset excludes `_`; WS retried only twice then disconnects; bidirectional forbids `audioTrack=outbound/both` | High → Low | Handshake written against Plivo grammar (Phase A); `contentType` pinned to mulaw; call_id via query param; `keepCallAlive=true` keeps call alive across reconnect attempts; integration test replays recorded Plivo frame sequences |
| R2 | **Sarvam latency at 8 kHz**: cascade budget 650–900 ms has zero slack vs ≤900 ms target; Saaras "Fast mode" <150 ms is a [VENDOR] claim | High | Per-turn `e2e_ms` telemetry already exists — alarm on p95 breach; Cartesia (<90 ms TTFB) stays wired as per-agent TTS escape hatch; `endpointing_ms`/VAD knobs already tuned; if budget blows, keep Sarvam STT + Cartesia TTS hybrid (still beats competitor on Indic accuracy) |
| R3 | **Tenglish extraction accuracy**: code-mixed utterances may yield wrong/garbled structured fields | High | FR-12 enforced in tools (`LOW_CONFIDENCE_THRESHOLD`, `MAX_ASKS_PER_FIELD`, never guess); `heuristic_extract` (`pipeline.py:301`) needs Telugu-script review in Phase D; gate: 85 % extraction floor blocks promotion |
| R4 | **DPDP data residency**: Deepgram/Cartesia US-hosted today; Twilio Media Streams hops US1 (no India region). Sarvam is India-hosted — swap *improves* posture; but recordings still land wherever Plivo stores them | Medium | Plivo India media anchoring (KYC + INR account mandatory before IN numbers); verify Plivo recording storage region at account setup; retention job (`RECORDING_RETENTION_DAYS`) unchanged; compliance-agent sign-off before campaign-scale Plivo cutover (DLT registration ₹5,900, 160-series numbers, auto-dialer pre-declaration — telephony-alternatives.md §5 Phase 0 starts day one, in parallel) |
| R5 | **Sarvam single-vendor concentration + pricing-page inconsistency** (₹30/hr vs ₹1.5/min marketing) | Medium | Get written list pricing pre-contract (multilingual.md gap #4); Deepgram/Cartesia remain one env flip away; negotiate Bulbul v2 rates as condition of volume |
| R6 | **Groq model churn** (Llama deprecations Aug 2026 forced migration anyway) — escalation tier drift | Low | Escalation model pinned via `GROQ_MODEL` env; quarterly model audit folded into qa-eval cadence |
| R7 | **Plivo PAYG concurrency cliff** (2 RPS / 50 concurrent; Enterprise $1k/mo) during campaign bursts | Medium | Load-test at 1.5× planned CPS before any campaign cutover; monitor concurrent-leg metric; trigger documented: sustained >300k min/mo or cap hits → renegotiate Enterprise or start carrier-SIP eval (telephony-alternatives.md Phase 3) |
| R8 | **Compliance barring risk**: one UCC violation bars ALL telecom resources 15 days (Feb 2025 TCCCPR amendment) | High | 160-series transactional numbers (not DND-scrubbed, fits absent-student notification), disclosure script first in every prompt (already rendered first — `render_system_prompt`), calling-hours enforcement unchanged, consent_enforcement stays on |

---

## 4. Verification gates (consolidated, incl. live-call acceptance)

Per-phase gates are stated inline above. **Live-call acceptance criteria (any phase claiming success on real calls):**

1. Calls placed only to `TEST_PHONE_NUMBERS` allowlist while `CONSENT_ENFORCEMENT=true` (guardrail honored; DLT/KYC sign-off required before widening).
2. Full loop observable: `phone-{call_id}` room joined by bridge, agent speaks within 2.5 s of pickup, transcript rows + captions render, `turn_latency` JSON lines posted per exchange with all four timing columns non-null.
3. End-state correctness: hangup maps to the right internal status via the provider status map; `end_call` posts completion; extracted fields visible; recording persisted; retry/backoff bookkeeping fires on no-answer.
4. Interruption: caller talks over agent → VAD triggers, agent stops, playback buffer cleared (`clearAudio` on Plivo), agent resumes coherently.
5. Degradation path: kill a provider key mid-suite → session degrades with apology + `post_complete(status="error")` rather than dead air (`_degrade` path exercised).
6. Numbers, not vibes: Phase D report attached to every default-flip decision.

---

## 5. ₹/min before → after (ex-GST, FX ₹87/$, connected-minute basis, 3-min avg call)

| Phase | Telephony | STT | LLM | TTS | **All-in ₹/min** |
|---|---|---|---|---|---|
| **Baseline (today)** Twilio + Deepgram-en + Groq + Cartesia | 1.55–1.60 (voice 1.20–1.50 + Media Streams 0.37 + recording/AMD extras) | 0.37–0.65 | 0.02–0.30 | 1.8–3.0 | **≈ 3.8–5.5** |
| **After Phase A** Plivo legs (streaming/recording/AMD included) | **0.38** | unchanged | unchanged | unchanged | **≈ 2.6–4.1** |
| **After Phase B** Telugu arm: Saaras v3 in, Bulbul v3 in | 0.38 | 0.50 | unchanged | 0.55–1.80 | **≈ 1.5–3.0** |
| **After Phase C** `sarvam-105b` in | 0.38 | 0.50 | 0.05–0.30 | 0.55–1.80 | **≈ 1.5–3.0** (cost-neutral; quality-driven) |
| **Cumulative expected** (mid TTS chars + v2-rate negotiation −0.5–0.9) | 0.38 | 0.50 | ~0.15 | ~0.55–1.10 | **≈ ₹1.5–2.1 ✅ ≤ ₹2.0 target** |

Notes: English agents can stay on Deepgram-en (₹0.44) + Cartesia where they're already cheapest — per-language routing means the ₹2 figure binds on the *Telugu* arm. Sticker-worst-case (max chars, v3 TTS rates, no negotiation) is ≈ ₹3.0, still under the ₹3.5 competitor line; the three ordered mitigations (v2-rate TTS deal, shorter domain-config phrasings, self-host TTS at >1M chars/mo) hold the ₹2 line. One-time: DLT ₹5,900 + Plivo KYC effort. At ~100k calls/mo, Phase A alone avoids ≈ ₹3.5 lakh/month (telephony-alternatives.md §0).

---

## 6. Dispatch order & ownership

1. **Phase A** → `telephony-agent` (+`backend-agent` for registry/config edits), compliance-agent starts DLT/KYC track in parallel (day one).
2. **Phase B** → `voice-pipeline-agent` (+`frontend-agent` for VoiceSettingsForm), gated on Phase A sandbox green (need Plivo legs to test telephony-grade audio).
3. **Phase C** → `conversation-ai-agent` (small diff; can overlap Phase B tail once `sarvam_api_key` lands).
4. **Phase D** → `qa-eval-agent`, dataset collection starts immediately (it's calendar-bound, not code-bound); all promotions route through it.

Each phase ends with its verification gate as the merge criterion; every default-flip afterward is a one-line env change or one immutable AgentVersion save.

---

# 11. User Guide (Beginner Path)

> Consolidated from source file: docs/USER_GUIDE.md

# User Guide — AI Voice Calling Agent

A beginner-friendly guide to the platform. No technical background needed —
every screen is explained in plain English, and every step below is something
you can do from your browser.

---

## 1. What is this product?

This platform lets you build an **AI voice agent** — a computer voice that can
phone people (or talk in your browser), hold a natural conversation in
English, ask a set of questions you define, and write down the answers in an
organised table.

**Typical use:** a college wants to call students who missed classes. Instead
of staff dialling dozens of numbers, you upload the list, and the AI calls each
student, politely asks what happened, records their reason, and gives you a
neat spreadsheet at the end. The same recipe works for surveys, appointment
reminders, lead qualification — it's all configuration, not new software.

Everything runs on Indian infrastructure and respects Indian rules: calls only
go out between **9 AM and 9 PM IST**, and consent is tracked for every contact.

---

## 2. The Golden Path (start to finish)

Follow these steps in order. Each one builds on the previous.

### Step 0 — Open the app and sign up

1. Start the local stack (one command):
   ```
   powershell -ExecutionPolicy Bypass -File scripts\dev-local.ps1
   ```
2. Open **http://localhost:3000** in Chrome or Edge.
3. Click **Sign up** and fill in three fields:
   * **Organisation name** — your company/college name; everything you create
     belongs to this organisation and is invisible to other organisations.
   * **Email** + **Password** — this becomes the owner login.

   > Demo shortcut: log in with `demo@example.com` / `demo1234` to explore a
   > pre-seeded account.

### Step 1 — Dashboard tour

After logging in you land on the **Dashboard**. In plain English:

* A row of **feature cards** acts as a map of the product: Agents, Playground,
  Campaigns, Calls, Dev Tools.
* Status tiles show whether the voice services behind the scenes are healthy
  (LiveKit, speech-to-text, text-to-speech, the LLM brain).
* If anything is red here, jump to [Troubleshooting](#4-troubleshooting) —
  the rest of the path won't work until providers are green.

### Step 2 — Create an agent ("train your caller")

An **agent** is your phone-caller persona. Click **Agents → New Agent** and
walk through six short steps:

| # | Step | What it means (one sentence) |
|---|------|------------------------------|
| 1 | **Basics** | Name your agent and describe in one line what it's for. |
| 2 | **Company Context** | Paste background facts the agent should know (e.g. "We are ABC College calling about attendance"). |
| 3 | **Question Flow** | Write the ordered questions the agent asks, with follow-ups allowed. |
| 4 | **Extraction Schema** | Define the answer fields to capture per call (e.g. `reason`, `will_return_date`) so results land in tidy columns. |
| 5 | **Voice Settings** | Choose how the agent sounds and speaks (voice style and pace). |
| 6 | **Review & Save Version** | Check everything, then click save — this freezes a numbered version. |

> **Versions matter:** a saved version never changes, even if you edit the
> agent later. Campaigns pin a version, so a running campaign always behaves
> exactly as tested.

### Step 3 — Test-drive it in the Playground (no phones involved)

The **Playground** is a browser-to-browser call with your agent — free,
instant, and nothing is dialed anywhere.

1. Open your agent's page and click **Test in Playground**.
2. Your browser asks for **microphone permission — click Allow**. Without it
   the agent cannot hear you (see troubleshooting).
3. Talk naturally: introduce yourself, let the agent ask its questions, answer
   out loud. You'll see live captions as you speak, then:
   * the full **transcript** of the conversation,
   * the **extracted fields** it filled from your schema,
   * **latency** figures showing how fast the agent reacts.

If the conversation feels wrong, edit the agent, save a **new version**, and
test again. Only move on when the playground conversation feels right.

### Step 4 — Create a campaign

A **campaign** = one contact list + one pinned agent version + one launch.

1. Go to **Campaigns → + New Campaign**, give it a name, pick your agent
   (its current version), click **Create campaign**.
2. On the campaign page, open the **Contacts** tab and upload a CSV or XLSX:
   * The system **auto-detects columns** — it looks for a phone column and a
     name column automatically and shows its guess; adjust if needed.
   * There's a review step: fix or drop rows marked invalid before anything
     is called.
3. Contacts arrive in *pending review* status. Rows without recorded consent
   stay parked there even after launch — that's the compliance gate working
   as designed.

### Step 5 — Launch (and why it may say no)

Click **Launch campaign**. Two built-in guardrails decide whether calls start:

* **Calling window:** outbound calls only run between **9 AM and 9 PM IST**.
  Outside that window the Launch button explains itself instead of failing
  mysteriously — come back during the window.
* **Telephony:** real outbound dialing needs a telephony provider connected.
  **Right now that isn't switched on yet, so campaigns cannot place real
  calls** — launching will be blocked until the provider is enabled and the
  compliance checklist is complete. This is temporary and deliberate; the UI
  will tell you plainly once it changes.

While a campaign runs, the **Dashboard tab** shows live counters (calling /
completed / failed / no-answer) and recent calls.

### Step 6 — Review results and export

When calls finish:

* Open any call from the campaign dashboard to read the full **transcript**
  and the **extracted field values** captured from the person.
* Use the **Export → CSV / XLSX** buttons on the campaign page to download
  everything as a spreadsheet.

---

## 3. Daily cheat-sheet

| I want to… | Do this |
|---|---|
| Start everything locally | `powershell -ExecutionPolicy Bypass -File scripts\dev-local.ps1` |
| Try the AI without calling anyone | Agents → your agent → Test in Playground |
| Change what the agent says | Edit agent → save → a new version number appears |
| See who was called and what they said | Campaign → Dashboard tab → click a call |
| Get results into Excel | Campaign page → Export → XLSX |

---

## 4. Troubleshooting

| Symptom | Likely cause & fix |
|---|---|
| Browser never asks for mic, or agent says "I can't hear you" | Microphone permission denied earlier. Click the lock/tune icon in the address bar → allow microphone → reload the Playground page. Also check no other app has exclusive use of the mic. |
| "Port already in use" / a service won't start | Something else owns :8000 (backend), :7880 (LiveKit) or :3000 (frontend). Close the old process or reboot; `scripts\dev-local.ps1` deliberately skips ports that are already listening, so a stale half-dead service must be killed by hand. |
| Dashboard shows a provider toggle as **false** (or Playground fails to start) | One API key is missing/wrong in the root `.env`. Which key: the toggle name maps to it — e.g. `deepgram` false → `DEEPGRAM_API_KEY`, `cartesia` false → `CARTESIA_API_KEY`, `groq`/`llm` false → `GROQ_API_KEY`. Fix the value, restart the backend + worker. |
| Agent joins the Playground but stays silent / session times out | The worker isn't registered with LiveKit. Open `worker_out.log` in the repo root — if it shows connection errors or nothing new, restart the stack with `scripts\dev-local.ps1`. |
| Launch says "outside calling hours" | It's before 9 AM or after 9 PM IST. That's a rule, not a bug — try again inside the window. |
| Launch says contacts missing | Upload the contact list on the campaign's Contacts tab first; rows marked invalid don't count. |
| Login loops back to the sign-in page | The backend isn't reachable. Check http://127.0.0.1:8000/api/health responds; if not, restart via the launcher script and check `logs\backend_err.log`. |

---

## 5. What's next / coming soon

* **Real outbound calls** — once the telephony provider is enabled and the
  India compliance gate (DLT registration + consent flow) clears, the Launch
  button starts actual dialing to your approved test list first.
* **More languages** — Telugu and other Indic-language support is planned as
  the next phase; today the agents speak English only.
* Richer analytics, retry policies for unanswered calls, and team member roles
  beyond owner/admin are also on the roadmap.

*Found a gap in this guide? Tell the team — this file lives at
`docs/USER_GUIDE.md`.*

## Real phone test call (Twilio beta)

Prereqs in `.env`: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER,
destination mobile verified in the Twilio console (trial rule), plus a public tunnel:

    cloudflared tunnel --url http://localhost:8000

Put the printed https URL into `.env` as PUBLIC_BASE_URL=... , restart backend
(`docker compose -f infra/docker-compose.yml up -d backend --force-recreate`),
open UI -> Test Call -> enter your verified number -> Start. Answer the phone;
the Twilio trial preamble plays first, then the agent disclosure. Hang up from
either side; view transcript + export XLSX from Call Detail.

---

# 10. Build History - Specs & Plans Index

| Artifact | Outcome |
|---|---|
| spec: enterprise-platform (2026-08-23) | Shipped - auth/tenancy, agents+versions, playground, campaigns |
| plan: enterprise-platform (2026-08-23) | Executed via SDD, merged to master |
| spec: phase1-finish (2026-08-25) | Shipped - cost dashboard, landing motion |
| plan: phase1-finish (2026-08-25) | Executed, final review PASS after keyframe fix |
| spec: twilio-phone-bridge (2026-08-25) | Shipped - media gateway, phone-* rooms, test-call dispatch |
| plan: twilio-phone-bridge (2026-08-25) | 6 tasks TDD, final review fixes accepted, 100 tests |

---

# 12. Run Book - Commands

```
docker compose -f infra/docker-compose.yml up -d --build   # full stack
# app :3000 - API :8000/docs - LiveKit :7880 - login demo@example.com/demo1234
backend\.venv\Scripts\python.exe -m pytest -q               # backend tests (from backend/)
voice-agent\.venv\Scripts\python.exe scripts\e2e_caller.py --wav caller.wav --wav2 caller2.wav --hold 60
python scripts/seed_demo.py                                # demo tenant (clean beta)
python scripts/seed_demo.py --purge-sample-data            # wipe demo campaigns/calls
tools\cloudflared\cloudflared.exe tunnel --url http://localhost:8000 --protocol http2
```

