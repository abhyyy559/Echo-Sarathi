# AI Voice Calling Agent - Local Setup & Runbook

Real-time AI voice calling platform for India. **This phase: browser playground
only** - build an agent in the UI and talk to it through your microphone.
No telephony calls are placed anywhere in this stack (see the warning below).

---

## 1. Architecture at a glance

```
                 +----------------------+
   your browser  |  React admin UI      |        http://localhost:3000
  (mic + audio)  |  (nginx :3000)       |
                 +----------+-----------+
                            | REST/JSON (JWT)
                            v
                 +----------------------+        http://localhost:8000
                 |  FastAPI backend     |        /docs = Swagger UI
                 |  (:8000)             |
                 +----+------------+----+
                      |            |
          +-----------+--+      +--+-----------+
          | PostgreSQL   |      | Redis        |
          | :5432        |      | :6379        |
          +--------------+      +--------------+

                 +----------------------+        ws://localhost:7880
   browser mic   |  LiveKit server      |   (signaling; RTC on :7881 tcp/udp)
  <============> |  (self-hosted dev)   |
                 +----------+-----------+
                            | room jobs ("playground-*")
                            v
                 +----------------------+
                 |  voice-agent worker  |   cascaded pipeline per turn:
                 |  (LiveKit Agents)    |   Deepgram STT -> Groq/OpenAI LLM
                 +----+-----+-----+-----+   -> Cartesia TTS
                      |     |     |
                      v     |     v
                 Deepgram   |   Cartesia
                 (cloud)    |   (cloud)
                            v
                        Groq / OpenAI (cloud)

   worker -> backend internal API (X-Internal-Token): fetches the agent
   config, posts transcript turns / extracted fields / call completion.
```

Everything runs as containers from `infra/docker-compose.yml`. The only cloud
dependencies are the STT/TTS/LLM provider APIs (your API keys).

## 2. Prerequisites

| Tool | Required? | Notes |
|---|---|---|
| Docker Desktop | **Yes** | Linux containers mode. Give it ~4 GB RAM if asked. |
| Git | Yes | clone/track the repo |
| Node.js 20 | Optional | only for host-side frontend dev (`npm run dev`); the stack builds the frontend inside Docker |
| Python 3.12+ | Optional | only for host-side backend dev; the backend runs in a container |

## 3. Quickstart (three scripts)

From the repo root in PowerShell:

```powershell
# 1. Start everything (builds images, waits for backend health).
powershell -ExecutionPolicy Bypass -File scripts\dev-up.ps1

# 2. Seed the demo tenant (org + user + demo agent v1 + draft campaign).
powershell -ExecutionPolicy Bypass -File scripts\seed.ps1

# 3. When done for the day (data volumes are kept):
powershell -ExecutionPolicy Bypass -File scripts\dev-down.ps1
```

First-run notes:

- `dev-up.ps1` creates `.env` from `.env.example` if missing and warns loudly
  to fill in provider keys (section 5). It does not block you otherwise.
- `seed.ps1` is idempotent - rerun it safely any time.
- Log in at **http://localhost:3000** with `demo@example.com` / `demo1234`.

## 4. Manual path (no scripts)

```powershell
# From the repo root:
copy .env.example .env        # then edit .env (next section)

# Build & start the whole stack:
docker compose -f infra\docker-compose.yml --env-file .env up --build -d

# Watch logs:
docker compose -f infra\docker-compose.yml --env-file .env logs -f backend

# Apply DB migrations manually (usually unnecessary: seed_demo.py applies them
# automatically when the schema is missing):
docker compose exec backend alembic upgrade head

# Seed the demo tenant:
docker compose exec backend python scripts/seed_demo.py

# Tear down (keep data):       docker compose -f infra\docker-compose.yml down
# Tear down AND wipe volumes:  docker compose -f infra\docker-compose.yml down -v
```

## 5. `.env` checklist

Copy `.env.example` -> `.env`, then sort keys into these buckets.

### REQUIRED for web playground testing (fill with real keys)

| Key | Get it from | Why |
|---|---|---|
| `DEEPGRAM_API_KEY` | console.deepgram.com | speech-to-text (the agent must hear you) |
| `CARTESIA_API_KEY` | cartesia.ai | text-to-speech (the agent must speak) |
| `GROQ_API_KEY` *or* `OPENAI_API_KEY` | console.groq.com / platform.openai.com | the LLM brain (Groq preferred for latency/cost) |

Without these the stack still boots and `/api/health` stays green, but
playground sessions degrade gracefully (clear logs, polite early wrap-up)
instead of crashing.

### AUTO-HANDLED by docker-compose (safe dev defaults; no editing needed locally)

| Key | Default used by compose | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@db:5432/voice_agent` | wired to the `db` service |
| `REDIS_URL` | `redis://redis:6379/0` | wired to the `redis` service |
| `JWT_SECRET` | `change_me_dev` | obvious dev placeholder; set a real value before any real deployment |
| `INTERNAL_API_TOKEN` | `change_me_internal` | shared secret backend <-> voice worker; keep both sides equal |
| `LIVEKIT_URL` | `ws://localhost:7880` | browser-facing URL baked into playground tokens |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | `devkey` / `secret_for_local_dev_only` | must match across backend / voice-agent / livekit services (compose keeps them in sync) |

### DORMANT this phase (leave placeholders - nothing reads them meaningfully yet)

| Key | Status |
|---|---|
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER` | Twilio adapter implemented but dormant; **trial minutes are intentionally preserved** |
| `EXOTEL_SID` / `EXOTEL_TOKEN` / `EXOTEL_NUMBER` | India production fallback, later phase |
| `TEST_PHONE_NUMBER`, `DLT_*`, calling-hours/limits tuning | compliance work lands before any real dialing |

> **Single-agent state (post-cleanup):** only `domain-configs/presets/absent-student-followup.json` ships (Agents page lists the one seeded agent). Verify with `(Get-ChildItem domain-configs/presets/*.json).Count` → `1` and `python scripts/validate_presets.py` → PASS. Presets (`GET /api/agents/presets`) need a bearer token; `/api/domain-configs` list is public. Orphan rows from deleted configs are removed manually (no auto-delete in sync): `DELETE FROM domain_configs WHERE name IN ('hospital-appointment','schema');` then reseed + restart the stack.
>
> ```powershell
> # PowerShell-safe auth-aware smoke (no curl, no &&):
> $Body = @{ email = 'demo@example.com'; password = 'demo1234' } | ConvertTo-Json
> $T = (Invoke-RestMethod http://localhost:8000/api/auth/login -Method Post -Body $Body -ContentType 'application/json').token
> $H = @{ Authorization = ('Bearer ' + $T) }
> Invoke-RestMethod http://localhost:8000/api/domain-configs -Headers $H
> (Invoke-RestMethod http://localhost:8000/api/agents/presets -Headers $H).preset_id  # -> absent-student-followup only
> ```

## 6. Web testing walkthrough (mic playground, zero telephony)

1. **Start + seed**: run `scripts\dev-up.ps1`, then `scripts\seed.ps1`.
2. **Log in** at http://localhost:3000 with `demo@example.com` / `demo1234`.
3. **Open Agents** and pick the seeded agent "Absent Student Follow-up"
   (or build your own with the wizard: Basics -> Context -> Questions ->
   Extraction schema -> Voice -> Review & Save version).
4. **Save the agent as version 1** if you edited it - versions are immutable;
   saving always creates a new numbered version.
5. **Open Playground** for that agent version. The browser asks for
   microphone permission - click Allow (see troubleshooting if blocked).
6. Press connect. The browser joins a `playground-*` LiveKit room; the
   voice-agent worker accepts the job, loads your agent version config from
   the backend, speaks the disclosure script, then works through the question
   flow. Talk naturally - barge-in is supported.
7. **End the session** (or just disconnect). The worker posts transcript
   turns, extracted fields, and latency metrics to the backend.
8. **Read the post-call panel**: transcript turns, extracted fields table,
   and per-turn latency bars (`stt_final_ms` / `llm_first_token_ms` /
   `tts_first_audio_ms` / `e2e_ms`; targets: median <= 900 ms, P95 <= 1.5 s).
9. Cross-check health any time at http://localhost:8000/api/health
   (all provider booleans green except `twilio`, which is expected false).

> **+============================================================+**
> **|  WARNING: NO TELEPHONY THIS PHASE.                         |**
> **|                                                            |**
> **|  Nothing in this stack places outbound phone calls. The    |**
> **|  Twilio adapter exists in code but is dormant; Twilio      |**
> **|  trial minutes are intentionally preserved for later       |**
> **|  milestones. Do not "helpfully" wire dialing back in -     |**
> **|  telephony unblocks only after DLT registration and the    |**
> **|  consent flow are live (PRD.md section 8, milestone M3).   |**
> **+============================================================+**

## 7. How to add a second use case (zero code changes)

Every call domain is data, not code:

1. Log in -> Agents -> create a new agent (e.g. "Fee Reminder").
2. Walk the builder wizard: system prompt, company context, question flow,
   extraction schema, voice settings -> save as version 1.
3. Test it immediately in the Playground.
4. Attach it to a campaign when you are ready to (later) dial.

The voice-agent worker and backend never learn about new use cases - they
fetch whichever agent version the room/campaign pins at runtime.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `docker: command not found` / daemon errors | Start Docker Desktop first; wait until its whale icon settles, then rerun `dev-up.ps1`. |
| Port already allocated (3000/8000/7880/5432/6379) | Another process owns the port. Stop it, or change the host-side mapping in `infra/docker-compose.yml` (left side of each `ports:` entry). If you move :8000 or :7880 you must also update `VITE_API_URL` (frontend build arg) and `LIVEKIT_URL` accordingly. |
| Microphone permission denied in browser | Browser settings -> site permissions -> allow microphone for `localhost:3000`, then reconnect. Chrome/Edge also need the page served over http://localhost (fine) or https. Close other apps holding the mic. |
| Playground says connected but no audio / room join fails | Usually a LiveKit key mismatch: `LIVEKIT_API_SECRET` must be identical for the `backend`, `voice-agent`, and `livekit` services (compose enforces this via one variable - do not override only one). Check `docker compose logs livekit` and `logs voice-agent`. Also confirm nothing else is bound to :7880/:7881. |
| Agent joins but stays silent / can't hear me | Missing provider keys. Run `curl http://localhost:8000/api/health` (or open it) - `deepgram`/`cartesia`/`groq`(or `openai`) must be `true`. Fill keys in `.env`, then `docker compose up -d --force-recreate voice-agent backend`. |
| Tables missing / migration errors | Apply migrations inside the container: `docker compose exec backend alembic upgrade head`. The seed script normally does this automatically on an empty database. |
| Backend unhealthy after `up` | `docker compose -f infra\docker-compose.yml --env-file .env logs backend` - most common cause is a stale `.env` overriding compose defaults. |
| Want a completely fresh start | `powershell -ExecutionPolicy Bypass -File scripts\dev-down.ps1 -Clean` (deletes all local data volumes), then `dev-up.ps1` + `seed.ps1` again. |

## 9. Pointers

- Full product spec: `PRD.md`; vendor research: `AI_Voice_Calling_Agent_India_Research.md`.
- Voice-runtime details, smoke tests, and the latency glossary: `voice-agent/README.md`.
- Domain configs (source of truth for seeded agents): `domain-configs/`.
- Compose stack: `infra/docker-compose.yml`. DevOps scripts: `scripts/`.

Remember: this phase is English-only, playground-only, telephony-dormant.
Telugu (Sarvam) and real dialing are later phases by design.

