# CLAUDE.md — AI Voice Calling Agent

## What this project is
A real-time AI voice calling platform for India. Phase 1 = English only, one use case proven end-to-end ("college calls absent students"), but the platform must stay **domain-independent** — new call use-cases are a config file, not new code. Full spec: `PRD.md`. Full vendor/market research behind these decisions: `AI_Voice_Calling_Agent_India_Research.md`.

## Current phase
**Phase 0 — scaffold and single-call proof of concept.** No auth yet. No Telugu yet. No production hardening yet. Do not build ahead of the current milestone in `PRD.md` §10 unless asked.

## Locked technical decisions — do not change without discussing first
- Voice architecture: **cascaded** (STT → LLM tool-calling → TTS). Never build a speech-to-speech (OpenAI Realtime / Gemini Live) path — it was deliberately rejected, see `PRD.md` §3.
- Real-time voice orchestration: **LiveKit Agents** (Python). Don't hand-roll WebSocket/session management.
- Telephony: **Vobiz** (India CPaaS). Twilio adapter stays dormant.
- STT: **Deepgram**. TTS: **Cartesia**. LLM: a fast/cheap model by default (Groq-hosted or GPT-4o-mini class), with rule-based escalation for hard turns — not a large model on every turn.
- Backend: **FastAPI** + **PostgreSQL**.
- Frontend: **React**.
- All of the above are India-region hosted (Mumbai) for data-localization reasons.

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
- Do not place real outbound calls to real phone numbers outside an explicitly-approved test list until `compliance-agent` confirms DLT registration and consent flow are live (PRD.md §8/M3). Test against your own number or a sandbox/test number by default.
- Never fabricate a structured-field value when the LLM extraction is low-confidence — escalate/flag per FR-12, don't guess.
- Don't add authentication/authorization work unless explicitly asked — it's an intentional non-goal until Phase 1 hardening.
- Don't start Telugu/Sarvam work — that's Phase 2, a separate PRD.

## Commands (fill in once the scaffold exists)
- Backend tests: `[to be added]`
- Voice-agent local run: `[to be added]`
- Frontend dev server: `[to be added]`
- Lint/format: `[to be added]`
