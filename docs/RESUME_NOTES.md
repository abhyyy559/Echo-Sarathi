# Echo Sarathi — SaaS Launch Redesign — Resume Notes

> Documentation Lead notes. Every claim below is drawn from the repository's own
> `README.md`, `docs/PROJECT_MASTER.md`, `docs/ARCHITECTURE.md`,
> `docs/SAAS_LAUNCH_REDESIGN_PLAN.md`, `backend/requirements.txt`,
> `voice-agent/requirements.txt`, `frontend/package.json` and source files. No
> metric or capability has been invented or independently re-measured here; where
> figures come from the repo's own docs, they are labelled as such. This branch is
> a frontend-only redesign (`redesign/saas-launch`, HEAD `deb869b`).

## One-sentence description

Echo Sarathi is a domain-independent, multi-tenant AI voice-calling SaaS — an
React/Vite admin workspace and public site over a FastAPI backend and a LiveKit
voice worker that conducts calls, extracts structured fields and exports campaign
results — and this branch delivers a presentation-only SaaS redesign that
restyles every public and authenticated surface without changing calling behavior.

## Tech stack (verified from manifests and source)

- **Frontend:** React 18.3.1, Vite 5.4.8, react-router-dom 6.26.2, livekit-client
  2.22.0, xlsx 0.18.5, Three.js 0.160.0 (legacy landing path); Node utility tests
  via `node --test`.
- **Backend:** FastAPI ≥0.110, SQLAlchemy 2.0 + Alembic, Pydantic 2, PostgreSQL
  drivers (`psycopg2-binary`, `psycopg[binary]`) with local SQLite
  (`backend/voice_agent.db`); PyJWT + bcrypt + google-auth auth; Twilio/Vobiz
  telephony clients; livekit-api; openpyxl; numpy; pytest + httpx tests.
- **Voice worker:** Python LiveKit Agents 1.8.3 with Deepgram STT (nova-3) and
  Cartesia TTS (Sarvam Saaras/Bulbul plugins also present); Groq LLM with OpenAI
  fallback; Smart Turn v3 semantic turn detection, Hush noise suppression, Silero
  VAD; cascaded STT → LLM tool-calling → TTS only.
- **Infrastructure/deploy:** Docker Compose (`infra/docker-compose.yml`),
  vendored LiveKit server binary, Vercel (frontend), Render (`render.yaml`,
  backend), Cloudflare quick tunnel for telephony webhooks.
- **Redesign artifacts (this branch):** new scoped style layers `launch.css`,
  `public-site.css`, `workspace-pages.css`, `account-pages.css` and a shared
  `PublicLayout`; existing global stylesheets untouched.

## LinkedIn-ready bullets (problem → built → constraint)

1. A working voice-calling product had inconsistent marketing and console UI, a
   landing page with scripted "live call" and hardcoded latency/confidence claims,
   and an undefined `STONE` reference in a WebGL path that threw on init.
   **Built** a frontend-only SaaS redesign on an isolated branch: one shared public
   header/footer, a truthful labelled transcript-to-fields example, honest
   pricing/roadmap separation, consistent light/dark tokens and scoped styles
   (`es-public-*`, page-local classes) across all 20 page components; removed the
   misleading scripted-demo claims; preserved every route, API payload and session
   handler. **Real constraint:** this is presentation only — the plan records an
   empty `git diff f7eefc1 -- backend voice-agent domain-configs render.yaml`, so
   no calling, telephony or billing behavior changed and the documented launch
   gates (signup, payments, DLT/KYC) remain open.

2. A natural-sounding call agent needs low perceived latency and reliable,
   auditable field extraction without inventing answers. **Built** a cascaded
   LiveKit Agents pipeline with semantic turn detection (Smart Turn v3 with a
   2.5 s wall-clock ceiling), same-tier cross-provider fallbacks, short spoken
   fillers for silent tool calls, per-stage `EOU/STT/LLM/TTS` latency logging and
   confidence-based escalation that never fabricates a value; new use cases are
   added as JSON domain configs with zero pipeline code changes. **Real
   constraint:** median ≤900 ms / p95 ≤1.5 s are design targets, not measured
   results here — the repo's own status doc records an older end-to-end average
   of ~2739 ms, and no fresh measurement was run for these notes.

3. A multi-tenant SaaS needs auth, org isolation, campaigns and billing without
   destabilizing live calls. **Built** a FastAPI app with JWT/password/Google
   auth, per-org isolation, immutable agent versions, CSV/XLSX campaign import
   with 9 AM–9 PM IST guardrails, transcript/extracted-field export and a
   cost-dashboard endpoint; the repo reports 83 backend tests green and 43
   frontend utility tests passing at this HEAD. **Real constraint:** the local
   stack runs SQLite with Redis absent (dialer queue features degraded), a code
   audit flags billing duration/coverage issues, and those test counts were read
   from repo documentation rather than re-executed here.

## Known limits (stated honestly)

- **Frontend-only scope:** no backend, voice-worker, domain-config, deployment or
  environment file was edited on this branch; the redesign does not fix any
  product defect it surfaces.
- **Verification gap:** the in-app browser MCP was unusable (viewport 0 × 0), so
  visual QA used a local headless-Edge CDP harness with the seeded demo account;
  25 screenshots covered public/authenticated pages at 390/1440 px in both themes,
  but 768/1280 widths, 200% zoom, reduced motion, keyboard-only traversal,
  simulated 401/402/empty/large-value states, Playground lifecycle and measured
  LCP/CLS remain unverified. No real mutation, dial or payment was performed.
- **Plan may be stale:** `docs/SAAS_LAUNCH_REDESIGN_PLAN.md` still lists some Task C
  (operations pages) and Task D (account/billing/Playground) verification items
  as unchecked even though the branch commit reports "across public and app
  surfaces"; treat that file as design intent, not final QA evidence.
- **Registration/payments gated:** public signup defaults to false in
  `render.yaml`; Razorpay code exists but operational/webhook readiness was not
  validated, and billing duration/coverage has a documented code-audit flag.
- **Compliance unresolved:** no DLT registration; real PSTN traffic is restricted
  to a `TEST_PHONE_NUMBERS` allowlist and `FakeTelephonyClient` prevents dialing
  without credentials; India-only/certification/retention claims need validation
  (documented render region is Singapore). Not legal clearance.
- **Local-runtime limits:** SQLite (not Postgres) locally, Redis absent so dialer
  queue/rate-limiting features are degraded; Groq free-tier TPM 429 spikes noted
  in the status docs.
- **Root README is worker-specific** (LiveKit voice runtime); the product-level
  narrative lives in `docs/PROJECT_MASTER.md` and `docs/ARCHITECTURE.md`.
- **Existing screenshots are not redesign proof:** `docs/review-2-assets/*.png`
  belong to an earlier review deck, not this branch's visual QA.

## Placeholders to fill before publishing

- **Repository URL:** `https://github.com/abhyyy559/Echo-Sarathi.git` (verified
  via `git remote -v`); replace with a public portfolio URL if desired.
- **Live demo URL:** `<ADD_DEMO_URL_OR_NONE>` — no public preview was authorized
  for this branch.
- **Screenshot / GIF:** `<ADD_CURRENT_REDESIGN_SCREENSHOT_PATH_OR_URL>` — do not
  reuse `docs/review-2-assets/*.png` as evidence of the redesign.
