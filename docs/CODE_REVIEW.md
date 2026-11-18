# Code Review — ai-voice-calling-agent (Wave-1 Audit)

Reviewer: Senior Code Reviewer. Scope: read-only audit of `README.md`, `CONTRIBUTING.md`,
`CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_MASTER.md`, git log/diffs and key
modules (`backend/app/main.py`, `backend/app/services/telephony.py`,
`backend/app/routers/playground.py`, `backend/app/routers/test_call.py`,
`voice-agent/agent.py`, `voice-agent/app/rooms.py`, `voice-agent/app/pipeline.py`).
No application code was changed.

## SCOPE NOTE — read this first

**The declared phase is browser-playground only, with no telephony.** The voice-agent
README states it plainly: "This phase the worker handles **browser playground rooms
only** (`playground-*` prefix). Jobs for any other room prefix are closed gracefully"
and "**No telephony happens here this phase. NO Twilio (or Plivo/Exotel) calls are
placed by this runtime.** The Twilio Media Streams protocol helper
(`app/twilio_protocol.py`) is kept dormant on purpose."

That is the intended contract for this phase, and this review treats it as the spec.
**The code does not honour it.** The backend still mounts live Twilio and Vobiz
webhook routers, builds real provider clients, runs a background dialer, and as of the
latest commit defaults to letting any signed-in user dial any phone number. The worker
itself also accepts `phone-*` rooms, not just `playground-*` rooms. Defects D1–D3 below
are all facets of this single, serious mismatch. Until it is resolved, "no telephony
this phase" is a documentation claim, not a property of the running system.

## Ranked defects (worst first)

### D1 — P0: Outbound dialing guardrail is OFF by default
`backend/app/config.py:140` — `allow_any_outbound_number: bool = True`. Commit `fa207d0`
("let test calls dial any number") flipped this from `false` to `true` in `.env.example`
and `Settings`. With the default, `backend/app/routers/test_call.py:80-92` skips the
consent/allowlist check entirely, so **any authenticated user can place a billable call
to any valid number**. `main.py:195-200` logs a startup warning admitting exactly this:
"any signed-in user can place billable calls to any number."

Why it matters: it directly violates `CLAUDE.md:51` ("Do not place real outbound calls
to real phone numbers outside an explicitly-approved test list until compliance-agent
confirms DLT registration and consent flow are live") and `CONTRIBUTING.md:47-55`.
Shipping a weaker guardrail as the default is the wrong direction for a compliance-
sensitive product. Fix: default back to `false`; opting into unrestricted dialing must be
an explicit, deliberate production override, not the out-of-box value.

### D2 — P0: "No telephony this phase" is contradicted by the whole backend path
`backend/app/main.py:21-26,50-67,203-213` builds `TwilioClient`/`VobizClient` and starts
`DialerService` when credentials exist; `:150-151` mounts `twilio.router` and
`vobiz.router` as unprefixed live webhook endpoints; `backend/app/services/telephony.py`
contains complete `TwilioClient.place_call` and `VobizClient.place_call` implementations.
`backend/app/routers/test_call.py:38` exposes `POST /api/test-call` that actually places
calls. So the runtime does place phone calls — the README's central claim is false at the
system level. Fix: either disable/withhold these routers and the dialer in the playground
build, or rewrite the README so the phase claim matches reality. Do not ship both stories.

### D3 — P1: Worker accepts `phone-*` rooms; README says only `playground-*`
`voice-agent/app/rooms.py:4` — `HANDLED_PREFIXES = ("playground-", "phone-")`.
`voice-agent/agent.py:3` docstring says "Handles playground-* (browser) and phone-*
(Twilio bridge) rooms" and `:57-60` logs "playground + phone rooms".
`voice-agent/app/pipeline.py:3033` branches on `is_phone_room`, and `:2022` has a
phone-room-specific audio path. The README's "Jobs for any other room prefix are closed
gracefully" is true only of prefixes other than these two. Note the one part of the
README that *is* accurate: `app/twilio_protocol.py` has no imports anywhere in `*.py`
source — it really is dormant dead code; keeping a dead module "on purpose" while the
backend actively speaks Twilio is confusing and should be documented or deleted.

### D4 — P1: `test_call.py` docstrings/comments describe behaviour that no longer exists
`backend/app/routers/test_call.py:1-6` says "place an immediate single call to an
allowlisted number"; `:63-68` insists "the request itself is NOT authorization for
arbitrary dialing ... so one authenticated user cannot place billable calls anywhere."
With `D1` shipped, that is no longer true by default. Comments that assert a safety
property the code does not enforce are more dangerous than no comments — reviewers and
future maintainers will trust them. Fix these comments in the same change that revisits
the default.

### D5 — P1: Provider choice is inconsistent across spec and docs
`docs/PROJECT_MASTER.md:57` locks telephony to **Plivo** (fallback Exotel) and explicitly
says "avoid Twilio for India"; `CLAUDE.md:12` locks **Vobiz** ("Twilio adapter stays
dormant"); `docs/ARCHITECTURE.md:18` says auto = Twilio-then-Vobiz. The implementation
has Twilio and Vobiz clients/routers and deleted the Plivo router in `7c6aef2`. Likewise
`PROJECT_MASTER.md:63` locks **Redis** for session/queue state, but `7c6aef2` is titled
"drop Redis and Plivo" and `backend/requirements.txt` lost those deps. Locked decisions
were changed without a recorded re-decision. Fix: record the supersession in
`PROJECT_MASTER.md` and align `CLAUDE.md`/`ARCHITECTURE.md` to one authoritative provider
and state store.

### D6 — P1: Telugu support shipped despite being an explicit Phase-2 non-goal
`docs/PROJECT_MASTER.md:42` lists "Telugu/multilingual support" under Phase-1 non-goals;
`CLAUDE.md:54` says "Don't start Telugu/Sarvam work — that's Phase 2, a separate PRD".
Yet commit `e7e8102` "default Telugu calls to natural Tenglish" and
`domain-configs/presets/absent-student-followup-telugu.json` exist, and
`ARCHITECTURE.md:21` already routes non-English agents to Sarvam. This is scope creep
against a written non-goal. Either revert, or formally promote it into the current phase
with an owner-approved spec update.

### D7 — P2: Stale doc pointers and status claims
`CLAUDE.md:4,7,10,23,51` and `docs/AGENTS.md:103`, `docs/README_SETUP.md:213` still point
to `PRD.md` and `AI_Voice_Calling_Agent_India_Research.md`, which
`docs/PROJECT_MASTER.md:3-5` says were consolidated and removed. `CLAUDE.md:7` still says
"Phase 0 ... No auth yet. No Telugu yet" while auth middleware, tenants and Telugu exist,
and its command section (`:56-60`) still reads "[to be added]" although `CONTRIBUTING.md`
documents working test commands. New contributors will follow dead links.

### D8 — P2: Monolithic playground router (judgement call / Fowler: Divergent Change)
`backend/app/routers/playground.py` is **3,535 lines** in one module: LiveKit token
issuance, DB/call/transcript writes, a direct Groq client with retry/backoff
(`:52-90`), sentence de-duping/capping text cleanup (`:166-245`), and latency metrics.
The file changes for unrelated reasons (billing, prompting, HTTP tuning, telephony
contract). Its own docstring (`:9-11`) admits the system prompt is a "slim server-side
twin of voice-agent/app/prompting.py; the two services are deliberately decoupled" —
two prompt implementations that can drift, putting FR-12 escalation parity at risk.
Split transport/session, persistence, LLM client and reply-post-processing into separate
modules; add a contract test that the two prompt renderers agree on required fields.

### D9 — P3: Tracked binary artifacts and sample call data (repo hygiene)
`git ls-files` shows `tools/cloudflared/cloudflared.exe`,
`tools/livekit/livekit-server.exe` and `testcampaign.csv` committed, plus ~2 MB
`.tmp-worker.log` and several `*.db` files in the working tree (these last are
gitignored, which is correct). `CONTRIBUTING.md:37-38` forbids committing files with a
real phone number or customer record — a committed `testcampaign.csv` should be checked
against that rule. Replace binaries with documented download steps; keep sample contact
data synthetic and clearly labelled.

## Spec-vs-code mismatches (separate from defect severity)

| Spec source | What it asks for | What the code does | Verdict |
|---|---|---|---|
| voice-agent `README.md:7-12` | Playground rooms only; no telephony; Twilio helper dormant | Worker serves `playground-*` **and** `phone-*`; backend mounts Twilio/Vobiz and dials | **Fail** — D2, D3 |
| `PROJECT_MASTER.md:57` PRD locked decision | Telephony = Plivo, avoid Twilio for India | Twilio + Vobiz implemented; Plivo router deleted | **Fail** — D5 |
| `PROJECT_MASTER.md:63` | Redis for session/queue state | Redis dropped in `7c6aef2` | **Fail** — D5 |
| `PROJECT_MASTER.md:42`, `CLAUDE.md:54` | Telugu is a Phase-2 non-goal | Telugu/Tenglish preset and Sarvam routing shipped | **Fail** — D6 |
| `CLAUDE.md:51` guardrail | No real outbound calls outside approved list pre-compliance | `ALLOW_ANY_OUTBOUND_NUMBER=true` by default | **Fail** — D1 |
| `CLAUDE.md:7` | Phase 0, no auth yet | Multi-tenant auth/JWT, orgs, roles implemented | Diverged (spec overtaken) |
| `PROJECT_MASTER.md:88` FR-4.3 acceptance test | New domain use case = config file only, zero code changes | Multiple presets added (prankster, sweet-checkin, clinic, real-estate) without pipeline changes | **Pass** |
| `PROJECT_MASTER.md:111-114` FR-11/FR-12 | Verbatim AI disclosure; never fabricate fields, escalate on low confidence | Disclosure-first prompting and confidence/escalation rules present in prompt and pipeline | Appears implemented |
| `ARCHITECTURE.md:21`, `README.md:94` NFR-1 | Per-turn STT/LLM/TTS latency logging, median ≤900 ms | Structured `turn_latency` events and stage logging present | Appears implemented |
| `CONTRIBUTING.md:37-40` | Never commit `.env`/keys/phone numbers | `.env`, `.deploy.env`, `*.db`, `*.log` correctly gitignored; one tracked CSV needs review | Mostly pass — D9 |

## What is in good shape

- Telephony `mask_phone()` (`:20-29`) hides all but last 4 digits — good PII hygiene.
- Missing-provider credentials produce `FakeTelephonyClient` and the dialer refuses to
  start (`main.py:31-67`); that guardrail is sound, it is only undermined by D1.
- Cascaded STT→LLM→TTS with degradation-on-missing-keys and immutable agent versions are
  implemented as designed.
- Domain configs are files, not code branches — the key FR-4.3 acceptance test holds.

## Recommended next actions

1. Decide the phase truth: if browser-playground-only, disable Twilio/Vobiz routers,
   `/api/test-call` and the dialer in this build and fix the worker prefix list; if not,
   rewrite the README and phase docs. Do this before any further feature work.
2. Restore `ALLOW_ANY_OUTBOUND_NUMBER=false` as the default; make unrestricted dialing an
   explicit production opt-in with an owner sign-off.
3. Fix `test_call.py` comments and reconcile the provider/Redis/Telugu decisions in
   `PROJECT_MASTER.md`, `CLAUDE.md` and `ARCHITECTURE.md`.
4. Then tackle the `playground.py` split and the two prompt implementations drifting apart.

Summary: 2 P0, 4 P1, 2 P2, 1 P3 defects; 6 spec mismatches, 3 apparent passes. Worst issue
overall: the shipped "no telephony" phase claim is false and the outbound-dialing
guardrail is disabled by default.
