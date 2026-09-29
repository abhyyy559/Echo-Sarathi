# AGENTS.md — AI Voice Calling Agent

## Project Overview
Real-time AI voice calling platform for India. Phase 0 = English-only browser playground proof-of-concept. No telephony, no auth, no Telugu. Domain-independent: new call use-cases are config files under `domain-configs/`, not code changes.

**Locked stack (do not change):**
- Voice: cascaded (Deepgram STT → Groq/OpenAI LLM tool-calling → Cartesia TTS) via LiveKit Agents (Python)
- Backend: FastAPI + PostgreSQL + Redis
- Frontend: React + Vite
- Telephony: Plivo first (Exotel fallback) — **dormant this phase**
- All services India-region (Mumbai) for data localization

## Repository Layout
```
/backend          FastAPI app: campaign/contact/call APIs, dialer worker, DB models, Alembic migrations
/voice-agent      LiveKit Agents worker: STT/LLM/TTS pipeline, turn detection, domain-config runtime
/frontend         React admin dashboard (Vite, nginx in Docker)
/domain-configs   Versioned JSON call-flow configs (absent-student.json is first)
/infra            docker-compose.yml, deployment configs
/scripts          dev-up.ps1, seed.ps1, dev-down.ps1 (PowerShell)
.env.example      All required API keys/secrets (never commit real .env)
```

## Key Conventions
- **Python**: FastAPI + Pydantic (backend), LiveKit Agents layout (voice-agent). Type hints required.
- **No hardcoded secrets**: Everything via `.env`; keep `.env.example` in sync.
- **Domain configs only**: Call flows = data files, never code branches.
- **Latency logging**: Per-call STT/LLM/TTS timing + cost from day one.
- **Extraction guardrail**: Confidence < 0.6 or 3 unfilled asks → escalate/flag, never fabricate (FR-12).

## Commands

### Quickstart (PowerShell from repo root)
```powershell
# 1. Start stack (builds images, waits for health)
powershell -ExecutionPolicy Bypass -File scripts\dev-up.ps1

# 2. Seed demo tenant (org, user, agent v1, draft campaign)
powershell -ExecutionPolicy Bypass -File scripts\seed.ps1

# 3. Login at http://localhost:3000 → demo@example.com / demo1234
```

### Manual Docker Compose
```powershell
# From repo root:
copy .env.example .env        # edit .env with real provider keys
docker compose -f infra\docker-compose.yml --env-file .env up --build -d
docker compose exec backend python scripts/seed_demo.py
```

### Testing
```powershell
# Backend tests (pytest)
cd backend
python -m pytest -v

# Voice-agent tests (offline, no network)
cd voice-agent
python -m pytest tests -v

# Frontend dev server (host)
cd frontend
npm run dev
```

### Environment Variables (required for working playground)
| Variable | Source |
|---|---|
| `DEEPGRAM_API_KEY` | console.deepgram.com |
| `CARTESIA_API_KEY` | cartesia.ai |
| `GROQ_API_KEY` or `OPENAI_API_KEY` | console.groq.com / platform.openai.com |

Missing keys = graceful degradation (logs error, speaks apology, posts completion with `status=error`), not crashes.

### LiveKit Dev Server (if not using compose)
```powershell
docker run --rm -p 7880:7880 -p 7881:7881 livekit/livekit-server --dev --bind 0.0.0.0
```

### Voice Worker (standalone, outside compose)
```powershell
cd voice-agent
python agent.py dev        # or: python agent.py start
```

## Common Pitfalls
- **LiveKit key mismatch**: `LIVEKIT_API_SECRET` must be identical for `backend`, `voice-agent`, and `livekit` services. Compose enforces this via single `.env` — do not override only one.
- **Port conflicts**: Default ports 3000 (frontend), 8000 (backend), 7880/7881 (LiveKit), 5432 (Postgres), 6379 (Redis). Change left side of `ports:` in `infra/docker-compose.yml` if needed, then update `VITE_API_URL` and `LIVEKIT_URL` accordingly.
- **Microphone permission**: Browser settings → allow microphone for `localhost:3000`.
- **Stale .env overriding compose defaults**: Run `docker compose logs backend` to diagnose.

## Guardrails
- **No real outbound calls** until compliance-agent confirms DLT registration + consent flow live (PRD §8/M3). Test against your own number or sandbox only.
- **No auth work** unless explicitly asked (Phase 1 hardening).
- **No Telugu/Sarvam** (Phase 2, separate PRD).
- **No speech-to-speech path** (OpenAI Realtime / Gemini Live) — cascaded was deliberate choice (PRD §3).

## Key Files to Reference
- `README_SETUP.md` — full local runbook, troubleshooting table
- `voice-agent/README.md` — worker details, latency glossary, smoke tests
- `CLAUDE.md` — subagent delegation map, locked decisions
- `PRD.md` — full product spec
- `infra/docker-compose.yml` — service definitions, env wiring, healthchecks
- `domain-configs/schema.json` — call-flow config schema