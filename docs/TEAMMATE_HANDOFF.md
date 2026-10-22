# EchoSarathi - Teammate Handoff for the Faculty Demo

> Verified against the code in this repository on 2026-10-22. The commands
> and endpoint names below match the code, not the older draft handoff. This
> is a code-level verification; place one browser call and one phone call
> before relying on it live.

---

## 0. Pick the demo path first

There are two supported paths. The browser path is the safest fallback if the
phone path has trouble.

| Path | What it uses | Needs a tunnel? | Needs Vobiz? |
|:---|:---|:---|:---|
| **Browser playground** | Frontend + LiveKit + voice worker | No | No |
| **Real phone call** | Browser/API -> backend -> Vobiz -> LiveKit | Yes, for Vobiz webhooks | Yes |

Do a browser call first. If it works, do the phone call. If the phone path
fails during the demo, switch to the browser playground instead of debugging
Vobiz in front of faculty.

> Note: `README.md` and the header of `infra/docker-compose.yml` still carry an
> older "no telephony this phase" comment. That comment is stale for this
> demo: the Vobiz REST/XML test-call path is implemented, and the current
> `.env` sets `TELEPHONY_PROVIDER=vobiz`. Use the Test Call page or
> `scripts/test_call.ps1`; do not let the old comment talk you out of the
> phone path.

---

## 1. What to share

Share privately (password manager or encrypted archive), never in a group chat.

### Files/folders

| Item | Why |
|:---|:---|
| `.env` (repo root) | All provider keys, Vobiz credentials, LiveKit config, model config |
| `infra/docker-compose.yml` | Full stack topology |
| `backend/` | FastAPI API, migrations, seed script |
| `voice-agent/` | LiveKit worker and voice pipeline |
| `frontend/` | The admin UI and Test Call page |
| `domain-configs/` | Call-flow JSON used by the agent and seed script |
| `scripts/` | `dev-up.ps1`, `seed.ps1`, `test_call.ps1` |
| `.env.example` | Reference for every variable |

`backend/.env` exists, but it is **not authoritative**. The backend loads
`backend/.env` first and the repo-root `.env` last, so the root file wins on
overlapping names. Do not copy the root `.env` into `backend/.env`; that just
duplicates secrets and creates drift. For the compose path, the root `.env` is
the one you need; leave `backend/.env` alone (or delete it in your copy if it
confuses you).

### Required credentials in the root `.env`

```dotenv
# LiveKit (pick ONE mode)
# Local compose mode:
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_URL_INTERNAL=ws://livekit:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret_for_local_dev_only

# LiveKit Cloud mode (instead of local):
# LIVEKIT_URL=wss://your-project.livekit.cloud
# LIVEKIT_URL_INTERNAL=wss://your-project.livekit.cloud
# LIVEKIT_API_KEY=...
# LIVEKIT_API_SECRET=...

# LLM chain (5 Groq keys -> GPT-OSS-120B -> Sarvam overflow)
GROQ_API_KEY=gsk_...,gsk_...,gsk_...
GROQ_MODEL=qwen/qwen3.8-27b
GROQ_SECONDARY_MODEL=openai/gpt-oss-120b

# Voice
STT_PROVIDER=sarvam
TTS_PROVIDER=sarvam
SARVAM_TTS_API=...
SARVAM_TTS_MODEL=bulbul:v3
SARVAM_TTS_SPEAKER=priya
SARVAM_TTS_LANG=en-IN
SARVAM_TTS_SAMPLE_RATE=8000

# Optional fallbacks
DEEPGRAM_API_KEY=...
CARTESIA_API_KEY=...

# Vobiz outbound calls (REST + XML stream, NOT a SIP trunk)
TELEPHONY_PROVIDER=vobiz
VOBIZ_AUTH_ID=...
VOBIZ_AUTH_TOKEN=...
VOBIZ_PHONE_NUMBER=+91XXXXXXXXXX   # your Vobiz caller ID / DID

# Backend + worker shared secrets
JWT_SECRET=...
INTERNAL_API_TOKEN=...
```

There is **no `VOBIZ_SIP_DOMAIN`, `VOBIZ_USERNAME`, or `VOBIZ_PASSWORD`** in
this codebase. Do not use `lk sip outbound create`; that is a LiveKit SIP
workflow, not the Vobiz REST/XML bridge this repo implements.

### Secrets: who needs what

- If the teammate runs the **full stack** (recommended), they need the full
  `.env`, including `JWT_SECRET` and `INTERNAL_API_TOKEN`.
- If they run **only the voice worker** against your existing backend, they
  need `LIVEKIT_*`, the provider keys, `BACKEND_INTERNAL_URL`, and
  `INTERNAL_API_TOKEN` (the worker authenticates to the backend). They do not
  need `JWT_SECRET` unless they also use the frontend/login.
- Rotate keys after the demo if access was temporary.

---

## 2. Prerequisites

- Docker Desktop installed and running.
- Python is **not required** for the compose path; the images include it.
  If running the worker outside Docker, use Python 3.11+.
- For the phone path: an ngrok or cloudflared account, a phone that can
  receive calls, and Vobiz credit.
- The destination phone number must be in `TEST_PHONE_NUMBERS` **or** be a
  consenting contact in the user's org. `CONSENT_ENFORCEMENT` defaults to
  `true`, so an arbitrary number will be rejected with HTTP 422.

---

## 3. Start the stack (both paths)

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev-up.ps1
```

That runs the equivalent of:

```powershell
docker compose -f infra\docker-compose.yml --env-file .env up --build -d
```

Do **not** run `docker compose up` from the repo root without `-f
infra\docker-compose.yml`; there is no root-level compose file.

Compose starts all of these:

- `db` (Postgres)
- `redis`
- `backend` (`:8000`)
- `livekit` (`:7880`, local mode)
- `voice-agent` (the worker)
- `frontend` (`:3000`)

### Seed the demo tenant

```powershell
powershell -ExecutionPolicy Bypass -File scripts\seed.ps1
```

This creates/updates the demo org, the absent-student agent, and the demo
login:

```text
http://localhost:3000
demo@example.com / demo1234
```

### Verify

```powershell
curl http://localhost:8000/api/health
docker compose -f infra\docker-compose.yml --env-file .env ps
```

`voice-agent` has no healthcheck, so it will show `running` rather than
`healthy`. That is expected.

### Important: do not start a second worker

The `voice-agent` service is already in compose. Starting `python agent.py dev`
in another terminal creates a second worker. That can cause jobs to be handled
by the wrong process and makes the demo flaky.

If you specifically want the worker in a terminal:

1. Stop the compose worker:
   ```powershell
   docker compose -f infra\docker-compose.yml --env-file .env stop voice-agent
   ```
2. Set the host-side LiveKit URL for the local process:
   ```powershell
   $env:LIVEKIT_URL_INTERNAL = "ws://localhost:7880"
   $env:BACKEND_INTERNAL_URL = "http://localhost:8000"
   ```
   The root `.env` sets `LIVEKIT_URL_INTERNAL=ws://livekit:7880`, which is
   only resolvable inside the compose network.
3. Run:
   ```powershell
   cd voice-agent
   python agent.py dev
   ```

For the demo, prefer the compose worker and keep its logs visible:

```powershell
docker compose -f infra\docker-compose.yml --env-file .env logs -f voice-agent
```

---

## 4. Browser demo (no Vobiz, no tunnel)

1. Start the stack and seed (section 3).
2. Open `http://localhost:3000`.
3. Log in with `demo@example.com / demo1234`.
4. Go to **Playground**, pick the demo agent version, and start a session.
5. Allow microphone access and talk.

This exercises the same voice worker, Sarvam STT/TTS, Qwen LLM, turn
detection, and tool filler as the phone path, without Vobiz.

---

## 5. Phone demo

> **Compliance gate:** per `docs/AGENTS.md`, do not place real outbound calls
> to third parties. For this demo, dial only your own phone or a number in
> `TEST_PHONE_NUMBERS` / a consenting roster contact. If DLT registration and
> the consent flow have not been signed off, use the browser playground
> instead. This is a demo guardrail, not a suggestion.

### 5.1 Expose the backend

Vobiz needs a public HTTPS URL for the answer webhook and the media WebSocket.

```powershell
ngrok http 8000
```

Copy the `https://...ngrok-free.app` URL. Then edit the root `.env`:

```dotenv
PUBLIC_BASE_URL=https://YOUR-TUNNEL.ngrok-free.app
PUBLIC_WS_BASE_URL=wss://YOUR-TUNNEL.ngrok-free.app
```

**Do not reuse the tunnel URL currently in the shared `.env`.** It points at
the owner's old Cloudflare tunnel and will be dead for the teammate. Replace
both lines. If you leave `PUBLIC_WS_BASE_URL` blank, the backend derives
`wss://` from `PUBLIC_BASE_URL`, but the shipped `.env` has an explicit stale
value, so set both to avoid surprises.

Recreate the backend so it picks up the new environment:

```powershell
docker compose -f infra\docker-compose.yml --env-file .env up -d --force-recreate backend
```

Cloudflared also works for the backend webhook/WebSocket. Do not put the
LiveKit server behind a tunnel for this path; the phone audio is bridged by the
backend and LiveKit is server-side.

### 5.2 Add the destination number

Add the phone you will call to `TEST_PHONE_NUMBERS` (comma-separated):

```dotenv
TEST_PHONE_NUMBERS=+9193XXXXXXXX,+9180XXXXXXXX
```

Alternatively, use a contact that already has `consent=true` in the demo org.
If you see HTTP 422 saying the number is not in `TEST_PHONE_NUMBERS`, this is
the cause. Do not disable consent enforcement for the demo.

### 5.3 Vobiz settings

The backend places outbound calls through the Vobiz REST API and passes the
answer URL per call:

```text
https://YOUR-TUNNEL.ngrok-free.app/vobiz/answer?call_id=<call row id>
```

For the test-call path you do **not** need to configure a Vobiz XML
application answer URL manually. The per-call `answer_url` in the Call-create
request is what Vobiz uses.

Do **not** point a Vobiz console application at `/vobiz/answer` without a
`call_id`; that route requires the query parameter and will return HTTP 422.
The outbound test-call request supplies it automatically. If your Vobiz
account forces an application-level answer URL and ignores the per-call one,
the outbound test-call path will not work; check the backend logs for the
`answer_url` it sent and fix the Vobiz account setting. Do not hand-enter a
bare `/vobiz/answer` URL.

### 5.4 Place the call

**Easiest:** open `http://localhost:3000/test-call`, pick the agent/version,
fill in the contact card, and press **Place test call**.

**One-command script:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test_call.ps1 -To +91XXXXXXXXXX -Hold 60
```

The script logs in as the demo user, calls `POST /api/test-call`, and polls the
call status. If you omit `-To`, it uses the first number in
`TEST_PHONE_NUMBERS`. It does **not** pass a contact card, so the greeting uses
the generic test-call contact name. Use the UI when you want the agent to greet
a named parent/student.

There is **no `make_call.py`** in this repo. Use the UI or the script above.

The API payload is:

```json
{
  "to": "+91XXXXXXXXXX",
  "agent_version_id": 1,
  "contact": {
    "name": "Ram",
    "student_name": "Abhi",
    "parent_name": "Ram",
    "class_section": "10-B",
    "absent_date": "2026-10-22"
  }
}
```

Replace `agent_version_id` with the ID shown in the UI; it is not always `1`.
The field is `contact`, not `contact_card`. `POST /api/calls` does not exist;
the endpoint is `POST /api/test-call` and it requires an `Authorization: Bearer
<token>` header.

---

## 6. Demo checklist

| Check | Pass criteria | Where to look |
|:---|:---|:---|
| **Opening** | One greeting, one institution, one identity question; no second greeting or repeated disclosure | `voice-agent/app/prompting.py::build_opening_line()` |
| **First response** | Turn decision is capped at 2.5 s; first audio typically 2.5-3 s | `max_delay=2.5` in `voice-agent/app/pipeline.py` |
| **Tool turn** | Short spoken filler before silence | `ToolTurnFiller` in `voice-agent/app/pipeline.py`; `tests/test_tool_filler.py` |
| **No dead air** | No unexplained gap >3 s | `EOU |`, `STT |`, `LLM |`, `TTS |` log lines |
| **AI disclosure** | First utterance identifies the AI and the recording | `mandatory_disclosure` + prompt rule |
| **Qwen first** | First LLM call is Qwen | `LLM | ttft=... model=groq/qwen/qwen3.8-27b` |
| **Telugu** | Telugu agent uses `te-IN` and 8 kHz | `SARVAM_TTS_LANG=te-IN`, `SARVAM_TTS_SAMPLE_RATE=8000` |
| **Call duration** | Target ~60 s; the prompt has a call budget, but this is not a hard code gate | Call detail page |

The absent-student opening is roughly **35 words**: the mandatory disclosure
alone is about 19 words, plus the first identity question. Do not apply a
literal 30-word gate to this config; the important part is that it is one
greeting, one institution, one question, with no repetition.

The greeting is **not pre-rendered**. It is deterministic text streamed
through TTS, which avoids an LLM round-trip and avoids the old
"Hello... Hello..." monologue. `session.say()` starts the TTS stream directly.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|:---|:---|:---|
| Call rings, no greeting | `PUBLIC_BASE_URL`/`PUBLIC_WS_BASE_URL` stale or tunnel down | Replace both with the current tunnel; recreate backend; check `docker compose ... logs backend` for `vobiz_answer` |
| Greeting, then silence | Turn detection/endpointing stall | Check `EOU |` logs; confirm `max_delay=2.5`; check worker logs |
| Garbled phone audio | Wrong TTS sample rate | Keep `SARVAM_TTS_SAMPLE_RATE=8000` for phone; the Vobiz bridge converts 8 kHz PCM to mu-law |
| "Model not found" | Wrong/decommissioned Groq model | Keep `GROQ_MODEL=qwen/qwen3.8-27b`; do not use `llama-3.1-8b-instant` |
| Call drops immediately | Vobiz credit exhausted or call-create rejected | Check Vobiz balance; inspect backend logs for the Vobiz 4xx body |
| HTTP 422 "not in TEST_PHONE_NUMBERS" | Consent enforcement | Add the number to `TEST_PHONE_NUMBERS` (plural) or use a consenting contact; the singular `TEST_PHONE_NUMBER` is not read |
| Backend uses the "wrong" model | Root `.env` wins over `backend/.env` | Edit the root `.env`; do not maintain a second model config |
| Worker cannot reach LiveKit | Local worker is using `ws://livekit:7880` | Use the compose worker, or set `LIVEKIT_URL_INTERNAL=ws://localhost:7880` and stop the compose worker |
| Two agents answer / jobs are flaky | Compose worker plus a second local worker | Stop one; use only the compose worker for the demo |
| `docker compose` says no config file | Wrong path | Use `-f infra\docker-compose.yml` or `scripts\dev-up.ps1` |

Useful log command:

```powershell
docker compose -f infra\docker-compose.yml --env-file .env logs -f voice-agent backend
```

Look for:

```text
Turn detection: ...
Noise cancellation: ...
EOU | end_of_utterance_delay=...
STT | ...
LLM | ttft=... model=groq/qwen/qwen3.8-27b
TTS | ttfb=...
```

---

## 8. Security notes

- Send `.env` through a password manager or encrypted archive, never plain
  email/WhatsApp.
- The root `.env` contains `JWT_SECRET`, `INTERNAL_API_TOKEN`, Vobiz
  credentials, and all provider keys. Rotate anything the teammate no longer
  needs after the demo.
- `.env` is gitignored. Do not commit it.
- The tunnel URL is public. The `/vobiz/answer` webhook is provider-facing; the
  media WebSocket uses a per-call bridge token. For extra protection set
  `VOBIZ_WEBHOOK_SECRET` and configure Vobiz to send the matching
  `X-Vobiz-Signature` header if your account supports it.
- Replace the tunnel URL in the shared `.env`; do not reuse the owner's old
  Cloudflare tunnel.

---

## 9. One-paragraph summary to send

> Run `scripts\dev-up.ps1` to start the full stack (it uses
> `infra\docker-compose.yml`), then `scripts\seed.ps1` and log in at
> `http://localhost:3000` with `demo@example.com / demo1234`. For a browser
> demo, use Playground. For a phone demo, run `ngrok http 8000`, put the
> `https://` URL in both `PUBLIC_BASE_URL` and `PUBLIC_WS_BASE_URL` in the root
> `.env`, add your phone to `TEST_PHONE_NUMBERS`, recreate the backend, and use
> the Test Call page or `scripts\test_call.ps1 -To +91...`. Vobiz is configured
> with `VOBIZ_AUTH_ID`/`VOBIZ_AUTH_TOKEN`/`VOBIZ_PHONE_NUMBER`; there is no SIP
> trunk or `make_call.py`. The worker is already part of compose-do not start a
> second one. Check `docker compose ... logs -f voice-agent` for
> `EOU |`, `STT |`, `LLM |`, and `TTS |` lines if anything is slow.
