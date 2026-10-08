# EchoSarathi Architecture + Operating Guidelines

Strict rules for anything that touches the call path. Violate these only with owner approval.

## 1. System map (one call, end to end)

```
PSTN phone --(Vobiz/Twilio/Plivo)--> provider media WS --> backend bridge
  --> LiveKit room (phone-<call_id>) --> voice-agent worker:
     Deepgram STT --turn--> Groq LLM (+tools) --reply--> Cartesia TTS
  --> audio back the same way. Transcript + latency + costs -> backend DB.
Browser playground skips PSTN: mic -> same LiveKit room -> same worker.
```

## 2. Component contracts (strict)

- **Telephony (`backend/app/services/telephony.py`)**: `place_call(to, call_id)` only. Provider choice via `TELEPHONY_PROVIDER` ("" | twilio | plivo | vobiz); empty = auto (Plivo > Twilio). No credentials = `FakeTelephonyClient`, dialer must never dial without them (`_provider_configured`).
- **Bridges (`twilio_bridge`, `plivo_bridge`, `vobiz_bridge` + routers)**: mu-law 8kHz both directions, always. WS handshake ≤10s or close 4400. Unknown events are skipped, never crash. Call matching: our `?call_id=` first, provider id second.
- **Call rows**: a media leg ending IS the call ending — finalize to a terminal status on close. Never leave `in_progress`/`ringing` rows (they vanish from reports). Test-call campaigns MUST carry `org_id` (org-scoped reads hide NULL-org rows entirely).
- **Voice pipeline (`voice-agent/app`)**: cascaded STT -> LLM tools -> TTS only — no speech-to-speech path, ever. Missing keys degrade with clear logs, never raise. `max_completion_tokens=300` on Groq (on_demand 1000 OTPM tier 429s anything larger and wedges the call).
- **Prompt (`prompting.py`)**: disclosure first verbatim; verify-then-continue (never end after identity check); end only when REQUIRED goals are covered or caller ends; never fabricate field values (ask again, flag at `end_call`).
- **Frontend**: no `type="submit"` without a `<form>`; no `.map` on possibly-missing API arrays; mock demo tokens must never trigger login redirects; captions honor worker `final` flags (interim updates in place).
- **Secrets**: `.env` is gitignored and never committed; `.env.example` stays in sync; no key VALUES in logs, health, or docs (presence booleans only).
- **Health (`GET /api/health`, no auth)**: db, redis, provider presence, egress TCP reachability, LiveKit WS. Presence without reachability is a lie — probe both.

## 3. Environment / network laws learned the hard way

- Docker `localhost` inside a container is the container, not the host. Browser-facing URLs use host ports; container-to-container uses compose service DNS (`backend:8000`, `livekit:7880`).
- Never redeclare `env_file` values with `${VAR:-default}` in compose `environment:` — a run without `--env-file` silently substitutes placeholders and desyncs secrets (caused the LiveKit 401 outage).
- Docker Desktop's embedded DNS flakes per-container: internal names resolve while external ones fail. Symptom = `ClientConnectorDNSError`/`NameResolutionError` with valid keys. Fix = force-recreate that container, then re-probe.
- Cloudflare quick tunnels die with the process/host reboot — always re-check the tunnel URL before a phone demo (Vobiz validates `answer_url`).

## 4. Compliance (India, non-negotiable)

- Real PSTN traffic only to `TEST_PHONE_NUMBERS` until DLT registration exists; test contacts get `consent_source=test_allowlist`.
- Calling hours 09:00–21:00 Asia/Kolkata; 90-day recording retention; every call discloses AI + recording in the opening line.
- Production India numbers need KYC; promotional vs transactional routes differ — never improvise this.

## 5. Cost / latency budgets (Phase 1)

- Per-minute target < ₹3.5 all-in (telephony ~1.00 + STT ~0.35 + LLM ~0.30 + TTS ~0.50 + infra ~0.20). Log per-call tokens/audio so campaigns stay queryable.
- Turn latency targets: median ≤900ms end-to-end, p95 ≤1500ms. Default LLM is Llama 3.1 8B Instant (TTFT ~80ms); reasoning models (Qwen-27B, GPT-OSS) are banned from the hot path — they deliberate instead of answering. Per-agent `llm_model` override exists for harder agents (Llama 4 Scout next step up, never 70B+ on voice). If slow: suspect model first, then TTS, then network — measure per-turn breakdowns, never guess.
- Fallbacks are same-tier, different-provider — never change model intelligence mid-call (a personality shift is worse than a graceful failure). Apologize + `end_call` beats a mid-call brain transplant.

## 6. Phase-2 reservations (designed, not built)

- **Voicemail detection**: detect IVR/beep, hang up or leave one concise message — never converse with a recording (burns credits).
- **Outcome classification**: every call ends `goal_achieved | not_interested | callback_requested | voicemail | no_answer | failed` — feeds campaign success rate, not just transcripts.
- **Warm transfer**: `transfer_call(call_id, to)` sibling to `place_call` (SIP REFER / provider transfer API). Interface first, implementation later.
- **Contact card required**: Test Call UI blocks placing without name + purpose + goal. The agent is never launched blind (generic greetings are a process bug).
- **PII**: extracted PII masked in logs; encrypt at rest before hospital/finance use cases.
- **Concurrency**: queue + worker pool + CPS caps for parallel calling; backend must multiplex simultaneous media websockets (Vobiz supports it).
- **A/B hooks**: immutable agent versions pinned per campaign already give this — keep it that way, never mutate a live version.
