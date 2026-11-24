# Demo readiness — live voice call (pitch, 25 Nov 2026)

Prepared 24 Nov 2026 from the current `master` (`fa207d0`). Goal: show the **interface**, then a
**real single outbound call** to the number supplied on the day, then the **Call Detail** view.
No campaign launch needed — use the Playground's **Phone** test mode (the old `/test-call` route
redirects there).

## Go / no-go checklist

Run this first. Every item was checked on 24 Nov 2026 unless marked otherwise.

| # | Check | Command / where | State |
|---|---|---|---|
| 1 | Backend suite green | `cd backend; .\.venv\Scripts\python.exe -m pytest -q` | ✅ 409 passed |
| 2 | Worker suite green | `cd voice-agent; .\.venv\Scripts\python.exe -m pytest tests -q` | ✅ 230 passed |
| 3 | Frontend builds | `cd frontend; npm run build` | ✅ built (chunk-size warnings only) |
| 4 | Provider keys present | `.env`: Deepgram, Cartesia, Groq, LiveKit URL/keys, INTERNAL_API_TOKEN, Vobiz auth | ✅ present (never print values) |
| 5 | Semantic turn detection | `voice-agent\.venv\Scripts\python.exe -c "from app.pipeline import _turn_detection; d=_turn_detection(); print(d if isinstance(d,str) else type(d).__name__)"` | ✅ `SmartTurnDetector` (installed locally 24 Nov; Docker image prewarms weights) |
| 6 | Dial gate | `.env` → `ALLOW_ANY_OUTBOUND_NUMBER=true` **or** demo number in `TEST_PHONE_NUMBERS` | ✅ true locally — demo-only, revert after |
| 7 | Webhook URL reachable | `PUBLIC_BASE_URL` (Cloudflare quick tunnel) must be live — Vobiz validates `answer_url` at call-create | ⚠️ re-check on the day; tunnels die on reboot |
| 8 | Calling hours | 09:00–21:00 IST unless an operator approved an extension | ⚠️ confirm the slot |
| 9 | Call length | Vobiz cut the 22 Oct campaign legs at exactly **60s** (account/trunk cap) | ⚠️ keep the demo call under ~50s |
| 10 | Credits | Billing must allow a dial (`billing.can_dial`) — check Overview → plan/wallet | ⚠️ confirm |
| 11 | LiveKit server | Docker Desktop started and the full stack is up; worker registered with LiveKit | ✅ up now (24 Nov) |

### Verified live on 24 Nov 2026 (not just tests)

- `scripts\dev-up.ps1` → all five containers healthy; `scripts\seed.ps1` → demo tenant + 4 agents
  (Anu, Bunty, Priya, Sahithi). Frontend `http://localhost:3000` returned **200**; API login with
  `demo@example.com / demo1234` succeeded; `/api/agents` returned 4 agents.
- `GET /api/health` is fully green: `db=true`, all providers present, egress reachable,
  **`livekit_ws=true`**, LLM chain starts with `qwen/qwen3.8-27b`.
- Fixed a real local blocker found during this check: `.env` had
  `LIVEKIT_URL_INTERNAL=ws://localhost:7880`, which inside the backend container points at itself
  (health showed `livekit_ws=false`, and the Vobiz bridge would have failed to join the room). It is
  now `ws://livekit:7880`. Do not change it back for the compose stack; browser tokens still use
  the separate `LIVEKIT_URL=ws://localhost:7880`.
- Deployed fallback: web `https://echosarathi-web-loki.onrender.com` returned **200 in 0.6 s**;
  API health returned **200 only after ~51 s** (Render free-tier cold start) — warm it before the
  pitch. Deployed login is **not** `demo1234` (401); use `DEMO_PASSWORD` from `.deploy.env`. The
  local stack uses `demo1234`.
- **Real pipeline smoke test passed**: `scripts\deploy\e2e_worker_check.py` against the local API
  (`API_BASE=http://localhost:8000`, `DEMO_EMAIL`/`DEMO_PASSWORD` set) created a playground room,
  the participant joined, `agent-AJ_...` connected and published `roomio_audio`, and the worker
  logged `TTS | ttfb=213ms` plus a `turn_latency` event — the STT→LLM→TTS path is live, not just
  unit-tested. The demo agent (Anu, v1) used the **Sarvam-first** stack
  (Saaras STT / 105B LLM / Bulbul TTS); an English agent uses Deepgram/Groq/Cartesia.

## Path A — local Docker stack (more controllable, shows the whole system)

```powershell
# 1. Start Docker Desktop, wait for the whale icon to settle.
# 2. From repo root:
powershell -ExecutionPolicy Bypass -File scripts\dev-up.ps1
# 3. Only on a fresh DB:
powershell -ExecutionPolicy Bypass -File scripts\seed.ps1
```

- App: <http://localhost:3000> · API: <http://localhost:8000> · LiveKit: `ws://localhost:7880`
- Login: `demo@example.com` / `demo1234`
- Health: `GET http://localhost:8000/api/health` (db, provider presence **and** reachability, egress, LiveKit WS)
- Logs: `docker compose -f infra\docker-compose.yml logs -f backend voice-agent`

If `dev-up.ps1` fails on ports, the left-hand ports in `infra/docker-compose.yml` are editable
(3000 / 8000 / 7880 / 7881 / 5432); update `VITE_API_URL` and `LIVEKIT_URL` with them.

## Path B — deployed web app (fewer moving parts, watch cold starts)

- Web: <https://echosarathi-web-loki.onrender.com> · API:
  <https://echosarathi-api.onrender.com>
- Health probe first: `Invoke-RestMethod https://echosarathi-api.onrender.com/api/health | ConvertTo-Json -Depth 4`
- If a build is needed: `scripts\deploy\deploy-render.ps1` then `scripts\deploy\verify-production.ps1`.
- Free-tier instances sleep. Give the first page load and the first dial **30–60 s**; the dialer
  keepalive ping exists so a running campaign survives a closed tab, but a cold worker still needs
  to connect.
- The deployed image installs Smart Turn v3 and prewarms its ONNX weights at build time, so
  turn detection there is stronger than an unpatched local venv (checklist item 5 fixes that).

## The 90-second demo — exact clicks

1. **Login**, land on Overview. Say the one-liner: *"Outbound calling that sounds human, reports
   like a CRM, and bills by the connected minute — built for Indian phone networks."*
2. **Agents** → pick **Absent Student Follow-up** (or Bunty/Anu persona). Point at the vertical
   preset: the call flow and extraction schema are a JSON file under `domain-configs/`, not code.
3. **Playground** → switch to **Phone** mode (`/playground?mode=phone`). Fill the contact card
   (student name / parent name) — the greeting uses those tokens, so the caller is addressed by
   name.
4. **Call** with the number given on the day. Put the phone on speaker. Say *"Yes, I'm here"*,
   then give a reason and a return day. Keep it short — 60 s carrier cap.
5. **Calls → Call Detail** for that call: show transcript, per-turn `EOU / STT / LLM / TTS`
   latency, extracted fields, AI-disclosure line. This is the observability differentiator.
6. Close with: *"New use case = new config file; same pipeline, same dashboard."*

**Backup path if the UI misbehaves:** place the same call via the CLI helper, then show the UI:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test_call.ps1 -To +91XXXXXXXXXX -Hold 45
# uses local API at http://localhost:8000; add -BaseUrl https://echosarathi-api.onrender.com for deployed
```

It logs in, POSTs `/api/test-call`, and polls call status. Ctrl+C only stops polling, not the call.

## Known constraints (say these before they become surprises)

| Constraint | Why | What to do |
|---|---|---|
| ~60 s leg cap seen on 22 Oct | Vobiz account/trunk limit, not our code — `place_call()` sends only from/to/answer_url/hangup_url | Demo conversation short; if a longer run is needed, ask Vobiz to raise it or pass an explicit duration parameter |
| `ALLOW_ANY_OUTBOUND_NUMBER=true` | Lets the Test Call screen dial the number you supply; gate is off for the demo | Dial only the authorised number. After the demo set it `false` in `.env` (or remove the number from `TEST_PHONE_NUMBERS`) |
| Cloudflare tunnel dies with the host/process | Vobiz validates `answer_url` when the call is created | Re-check `PUBLIC_BASE_URL` with a browser/curl on the day; restart the tunnel if stale |
| False barge-in | VAD can trip on echo/background noise | Smart Turn v3 + **0.5 s** / 1-word gate + `resume_false_interruption`; STT endpointing is 500 ms and the VAD threshold 0.55 (both raised 24 Nov for phone audio). If a caller still gets cut off, raise `VOICE_MIN_ENDPOINTING_DELAY` to 0.5 in `.env` and restart the worker |
| Silence after pickup | Cold STT/TTS/filler path | Confirm worker log shows `Turn detection: SmartTurnDetector` (English) or `Turn detection: stt` (Sarvam), plus a `TTS | ttfb=...` line under ~300 ms |
| Carrier refusals | Real +91 numbers can return busy/no-answer | Have a second authorised number ready; a refusal closes the call as `busy` and frees the slot immediately |

## Campaign pipeline stress test (24 Nov 2026)

Dialer was tested offline with a stub telephony client over an in-memory DB
(`backend/tests/test_dialer_resilience.py` pins the three bugs below as
regressions). Measured behaviour:

| Scenario (200 contacts) | Dialer result |
|---|---|
| Concurrency 10, CPS 100 | exactly 10 legs placed |
| Concurrency 10, CPS 5 | exactly 5 legs placed |
| Concurrency 50, CPS 50 | exactly 50 legs placed |
| Provider adds 200 ms per leg, cap 10 | 10 legs in ~2 s (dialer places serially on one thread) |
| Provider returns 5xx, cap 10 | **0 reported dials**, 3 probe calls, all contacts still queued |

So the answer to "how many calls are going on concurrently": exactly
`min(plan.max_concurrent_calls, DEFAULT_CONCURRENCY_LIMIT)` per org — the demo
tenant is on the Free plan, so **2 concurrent calls** (Starter/Growth = 2/5,
Scale = 15). CPS default is 1.0/s. Provider latency, not the plan, sets how
fast a burst ramps.

Bugs found and fixed:

1. **A provider outage burned contact attempts.** A 5xx was charged as a
   "no answer": with cap 10 the first 3-second outage marked 3 contacts
   failed permanently. Placement failures are now parked 60 s
   (`DIAL_FAILURE_BACKOFF_SECONDS`) without touching `attempt_count`, and a
   run of consecutive placement failures stops the tick.
2. **Ghost slots froze campaigns.** `_place` commits the call row as
   `queued` before the provider call; a process death in between left that
   row as an in-flight count forever. `_sweep_stale_queued` reclaims any
   queued leg without a provider id after `STALE_QUEUED_SECONDS` (120 s).
3. **No claim-before-dial.** The contact status flips to `calling` only
   after the provider accepts, so two workers could dial the same contact.
   It is now flipped in the same commit that creates the call.
4. **One long tick could swallow a whole 0-consent roster** (2000 contacts
   polled once). Consents now retire at a per-tick budget of 100
   (`DIALER_MAX_SKIPS_PER_TICK`).

Key rotation: `DEEPGRAM_API_KEYS` / `CARTESIA_API_KEYS` (comma-separated)
rotate per session; `GROQ_API_KEYS` rotates per LLM request (existing).
See `.env.example` lines 49-62.

## Troubleshooting, fast

| Symptom | Check | Fix |
|---|---|---|
| Login fails | seed present? | run `scripts\seed.ps1` (demo creds above) |
| `422 not in TEST_PHONE_NUMBERS` | gate off and number unknown | set `ALLOW_ANY_OUTBOUND_NUMBER=true` for the demo, or add the number to `TEST_PHONE_NUMBERS` |
| Call fails at placement | tunnel / Vobiz credentials | `PUBLIC_BASE_URL` reachable; Vobiz auth in `.env`; check `vobiz call-create failed` in backend log |
| Phone rings, no voice | LiveKit worker not connected | worker log shows room join; `LIVEKIT_API_SECRET` identical in backend, worker and livekit service |
| Agent talks over caller / long pauses | wrong turn detector | worker log must say `Turn detection: SmartTurnDetector` for Deepgram/English agents, or `Turn detection: stt` for Sarvam agents (both valid). If English shows `vad`, install `smart-turn-livekit[resample]==0.4.0` in the worker env |
| Transcript truncated | call cut at 60 s | keep demo under 50 s; check Call Detail events for `vobiz_answer_terminal` |
| Deployed site slow / 502 | Render cold start | wait 30–60 s and retry; health endpoint must return provider reachability, not just presence |

## After the demo

1. Set `ALLOW_ANY_OUTBOUND_NUMBER=false` in `.env` (local and any deployed service) — the
   repository's shipped default is `false` as of this fix; the `true` value was demo-only.
2. Remove any demo number from `TEST_PHONE_NUMBERS` if it is not a permanently authorised test
   number.
3. Note the call ID in your talk-track so you can cite the transcript/latency screenshot later.
