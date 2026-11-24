# CLAUDE.md — AI Voice Calling Agent

## What this project is
A real-time AI voice calling platform for India. The first proven use case is the college absent-student follow-up, but the platform stays **domain-independent** — new call use-cases are config files under `domain-configs/`, not new code. Consolidated spec, research and build history: `docs/PROJECT_MASTER.md` (the old standalone `PRD.md` and research doc were folded into it).

## Current phase
**Phase 1 — working product, not a scaffold.** Multi-tenant auth, real outbound calls via Vobiz, browser playground, campaigns, billing and observability are shipped. Telugu/Tenglish via Sarvam is in the build (originally a Phase-2 item — see `docs/PROJECT_MASTER.md` for the recorded scope change). Remaining gates: DLT registration for campaign dialing, carrier call-length limit, durable backend writes, and module splits. Do not build ahead of a documented milestone without asking.

## Locked technical decisions — do not change without discussing first
- Voice architecture: **cascaded** (STT → LLM tool-calling → TTS). Never build a speech-to-speech (OpenAI Realtime / Gemini Live) path — it was deliberately rejected, see `docs/PROJECT_MASTER.md` §1/§3.
- Real-time voice orchestration: **LiveKit Agents** (Python). Don't hand-roll WebSocket/session management.
- Telephony: **Vobiz** (India CPaaS). Twilio adapter stays dormant. Plivo/Exotel were the original prototype choice and are **superseded** — recorded in `docs/PROJECT_MASTER.md`.
- STT: **Deepgram Nova-3** (English) with **Sarvam Saaras** for Indic/code-mixed calls. TTS: **Cartesia** (English) with **Sarvam Bulbul** for Indic. LLM: fast/cheap by default (Groq Qwen 3.8-27B with fallbacks), rule-based escalation for hard turns — not a large model on every turn.
- Backend: **FastAPI** + **PostgreSQL**. Session/queue state lives in Postgres — the original **Redis** decision is superseded.
- Frontend: **React** (Vite).
- All of the above are India-region hosted for data-localization reasons.

## Repo layout (target — scaffold this if it doesn't exist yet)
```
/backend          FastAPI app: campaign/contact/call APIs, dialer worker, DB models
/voice-agent       LiveKit Agents service: STT/LLM/TTS pipeline, turn detection, domain-config runtime
/frontend          React admin dashboard
/domain-configs    Versioned JSON/YAML call-flow configs (see PRD.md §4.3) — "absent-student.json" is the first one
/infra             docker-compose, deployment configs
.env.example       every required API key/secret, no real values committed
```

## Subagents available in this project
Delegate to these instead of doing cross-cutting work in the main session. Each owns one layer and should not edit files outside its lane without saying so explicitly.

| Agent | Owns | Invoke when the task is about... |
|---|---|---|
| `telephony-agent` | Vobiz/Twilio integration, call placement, webhooks, DID/number config | placing calls, call status webhooks, provider SDK issues |
| `voice-pipeline-agent` | LiveKit Agents service, STT/TTS wiring, VAD/turn-detection tuning, barge-in, latency instrumentation | anything inside `/voice-agent`, "the agent talked over the caller," latency tuning |
| `conversation-ai-agent` | LLM prompts, tool-calling schemas, domain-config format and runtime, escalation logic | conversation flow, extraction accuracy, `/domain-configs`, prompt changes |
| `backend-agent` | FastAPI app, Postgres schema/migrations, campaign dialer/queue, export | anything inside `/backend`, DB schema changes, CSV/XLSX import-export |
| `frontend-agent` | React admin dashboard | anything inside `/frontend`, UI/UX for upload/review/campaign/dashboard/export |
| `compliance-agent` | DLT/DPDP requirements, consent flow, disclosure script, retention/deletion jobs | anything touching consent, recording retention, calling-hours enforcement, regulatory questions |
| `qa-eval-agent` | Test-call harness, latency/accuracy measurement, regression tests, load testing | "test this," "measure latency," "did extraction accuracy regress" |
| `devops-agent` | docker-compose, CI/CD, secrets, India-region deployment, monitoring | deployment, environment setup, infra changes |

Claude decides which subagent to use based on the task and each agent's `description` frontmatter — you don't have to name them explicitly, but you can ("use the voice-pipeline-agent to...") when you want to be sure.

## Conventions
- Python: FastAPI + Pydantic models for `/backend`; LiveKit Agents' standard project layout for `/voice-agent`. Type hints required.
- Never hardcode API keys — everything through `.env`, and `.env.example` must be kept in sync whenever a new credential is introduced.
- Every call domain (question flow + extraction schema) is a config file under `/domain-configs`, never a code branch in `/voice-agent` or `/backend`.
- Log per-call latency (STT/LLM/TTS timing) and cost from day one — don't bolt this on later.

## Guardrails
- Do not place real outbound **campaign** calls outside an approved, consented list until `compliance-agent` confirms DLT registration and consent flow are live (`docs/PROJECT_MASTER.md` §8/M3). Test against your own number or an authorised test number by default.
- Test calls are capped to `TEST_PHONE_NUMBERS` plus consenting roster contacts by default. `ALLOW_ANY_OUTBOUND_NUMBER=true` is an explicit, demo-only opt-in — never a shipped default — and dial only numbers you are authorised to call.
- Never fabricate a structured-field value when the LLM extraction is low-confidence — escalate/flag per FR-12, don't guess.
- Auth/multi-tenancy and Telugu/Tenglish are already in the build; treat them as existing surface, not new scope. Don't expand them without an explicit ask.
- Never add a speech-to-speech path (OpenAI Realtime / Gemini Live) — the cascaded pipeline was a deliberate choice.

## Commands
- Backend tests: `cd backend; .venv\Scripts\python.exe -m pytest -q` (409 tests)
- Voice-agent tests: `cd voice-agent; .venv\Scripts\python.exe -m pytest tests -q` (230 tests)
- Frontend build/dev: `cd frontend; npm run build` / `npm run dev`
- Full local stack: `powershell -File scripts\dev-up.ps1` then `scripts\seed.ps1` → <http://localhost:3000>
- Single live call: `powershell -File scripts\test_call.ps1 -To +91... -Hold 45`
- Demo runbook and pitch notes: `docs/DEMO_READINESS.md`, `docs/PITCH_CHEAT_SHEET.md`
