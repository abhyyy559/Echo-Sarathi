# Production deployment — 100% free tier

Everything below fits inside free plans. No credit card is required for any of
the four services, and nothing scales to a paid plan on its own.

```
Browser / faculty
   |
   |  https://<vercel-app>
   v
Vercel  ── direct fetch (VITE_API_URL) ──►  Render free web service
(Vite SPA)                                  echosarathi-api (FastAPI)
        └── /api/* proxy fallback ─────────►      |
                                                  ├── Neon free Postgres
                                                  └── webhooks from Vobiz
LiveKit Cloud  ◄── browser playground
      ▲
      └── echosarathi-voice (LiveKit Cloud agent, scales to zero)
```

| Piece | Provider | Free plan reality |
|---|---|---|
| Frontend | Vercel Hobby | Unlimited deploys, 100 GB bandwidth |
| Backend API | Render **free** web service | 512 MB RAM, sleeps after 15 min idle, ~1 min cold start, 750 instance-hours/month per workspace |
| Database | Neon **free** Postgres | 0.5 GB, branches, no 30-day expiry (Render's free Postgres *is* deleted after 30 days — that is why it is not used) |
| Redis | not used | `REDIS_URL` stays empty; `/api/health` reports `redis: null` |
| Voice worker | LiveKit Cloud **Build** | 1 agent deployment, monthly agent-minute allowance, scales to zero, 10–20 s cold start |

There is no free background worker on Render, and a 750-hour workspace budget
cannot host an always-on one anyway, so the always-on voice worker lives on
LiveKit Cloud (which is where the media already is).

---

## 1. One-time accounts (10 minutes)

| Account | What to create | Where |
|---|---|---|
| Render | Account + GitHub connected | <https://dashboard.render.com> |
| Neon | A project in the region closest to Render (Singapore) | <https://console.neon.tech> |
| LiveKit Cloud | A project (region **ap-south / Mumbai**) | <https://cloud.livekit.io> |
| Vercel | Already done — the project exists | <https://vercel.com> |

**Connect GitHub to Render once.** Open
<https://dashboard.render.com/select-repo?type=web>, authorize the GitHub app,
and make sure `abhyyy559/Echo-Sarathi` is visible. Skip this and the API cannot
create the service (there is no way to grant repo access through the API).

---

## 2. Fill `.deploy.env`

`.deploy.env` is gitignored. Copy the template if it does not exist:

```powershell
Copy-Item .deploy.env.example .deploy.env
```

Then fill these six values. `JWT_SECRET`, `INTERNAL_API_TOKEN`,
`DEMO_EMAIL`, and `DEMO_PASSWORD` are already generated — do not reuse them
anywhere else.

| Key | Where to get it |
|---|---|
| `RENDER_API_KEY` | Render → **Account Settings → API Keys → Create API Key** (`rnd_...`) |
| `DATABASE_URL` | Neon → your project → **Connect** → copy the **pooled** string (`-pooler` host, ends with `?sslmode=require`). Paste it verbatim: `deploy-render.ps1` rewrites the scheme to `postgresql+psycopg2://`, because psycopg (v3) prepares statements server-side and Neon's PgBouncer pooler rejects that. |
| `LIVEKIT_URL` | LiveKit Cloud → project → **Settings → Keys** → the `wss://<project>.livekit.cloud` URL |
| `LIVEKIT_API_KEY` | same page |
| `LIVEKIT_API_SECRET` | same page (the secret, **not** a participant JWT) |
| `VERCEL_TOKEN` | <https://vercel.com/account/tokens> → Create, scope to the team |

Optional: `RENDER_OWNER_ID` (workspace id — the script looks it up),
`APP_ORIGIN` (auto-detected from the Vercel project domains),
`LIVEKIT_REGION` (default `ap-south`), `RENDER_REGION` (default `singapore`).

Provider keys (Deepgram, Cartesia, Sarvam, Groq, Vobiz, `TEST_PHONE_NUMBERS`)
are **not** duplicated here: the scripts read them from the repo-root `.env`
and push them to both Render and LiveKit. Nothing is ever printed.

---

## 3. Deploy

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy\deploy-all.ps1
```

Five steps, all idempotent — re-run after changing anything:

1. **Resolve the Vercel origin** from the project domains (`APP_ORIGIN`).
2. **Render**: find or create `echosarathi-api` (free, Singapore, Python
   3.12) with the full environment baked into the create call, then wait for
   the deploy to go `live`.
3. **Vercel**: set `VITE_API_URL` (direct cross-origin calls), refresh the
   `/api/*` proxy fallback in `frontend/vercel.json`, link the existing
   project, and run `vercel deploy --prod`.
4. **LiveKit Cloud**: write `voice-agent/livekit.toml` if missing (first
   `agent create`, then `agent deploy`), push secrets, deploy the worker.
5. **Verify**: run the smoke suite and fail loudly.

Useful flags / single steps:

```powershell
# skip the pieces you are not changing
powershell -File scripts\deploy\deploy-all.ps1 -SkipLiveKit
powershell -File scripts\deploy\deploy-all.ps1 -SkipVercel

# individual phases
powershell -File scripts\deploy\deploy-render.ps1   -AppOrigin https://your-app.vercel.app
powershell -File scripts\deploy\deploy-vercel.ps1   -RenderServiceUrl https://echosarathi-api.onrender.com
powershell -File scripts\deploy\deploy-livekit.ps1
powershell -File scripts\deploy\deploy-vercel.ps1 -OriginOnly   # just resolve the origin
powershell -File scripts\deploy\deploy-livekit.ps1 -StatusOnly
```

### Why the migrations run in the start command

Render's `preDeployCommand` is a paid-plan feature. On the free plan the start
command is therefore:

```
cd backend && alembic upgrade head && python scripts/seed_demo.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Both steps are idempotent, so every cold start is safe. `seed_demo.py` reads
`DEMO_EMAIL`/`DEMO_PASSWORD` from the environment and never prints the password.

### Why the frontend calls Render directly

Vercel's rewrite proxy will cut a request off long before a sleeping Render
instance finishes booting. With `VITE_API_URL` set, the browser talks to Render
directly, so the first request after a sleep is slow instead of broken. The
`/api/*` rewrite stays in `vercel.json` as a same-origin fallback for anything
that ignores the baked-in URL.

---

## 4. Vobiz wiring

The backend derives its public base URL from Render's own `RENDER_EXTERNAL_URL`,
so nothing has to be pasted back in after the first deploy. Per call it sends:

```
https://echosarathi-api.onrender.com/vobiz/answer?call_id=<internal-call-id>
wss://echosarathi-api.onrender.com/vobiz/media?call_id=<id>&bridge_token=...
```

Do **not** configure a bare `/vobiz/answer` in the Vobiz dashboard: `call_id`
is generated per call. Keep the Vobiz application assigned to
`VOBIZ_PHONE_NUMBER`. `VOBIZ_WEBHOOK_SECRET` stays empty unless Vobiz is
configured to send the same `X-Vobiz-Signature` header.

The media bridge itself is authenticated with `INTERNAL_API_TOKEN` (sent by the
worker, verified by the backend), so a stranger cannot join a call's audio.

---

## 5. Smoke checks

`deploy-all.ps1` ends by running these; run them again any time with:

```powershell
powershell -File scripts\deploy\verify-production.ps1
```

What it asserts:

- `GET /` on Render returns 200 (the instance is awake)
- `/api/health` reports `db: true`, all three provider keys present, a
  non-empty LLM fallback chain
- demo login returns a token, and `/api/agents` shows the seeded agent
- CORS preflight from the Vercel origin is allowed
- the Vercel page serves the SPA shell, and `/api/health` through the proxy
  also answers
- LiveKit agent status (warning only — a cold agent is not an error)

Manual spot check:

```powershell
Invoke-RestMethod https://echosarathi-api.onrender.com/api/health | ConvertTo-Json -Depth 4
```

---

## 6. Faculty demo flow — all from the UI

1. Wake the API first: `powershell -File scripts\deploy\wake.ps1`
2. Open the Vercel URL (`APP_ORIGIN` in `.deploy.env`) and sign in with
   `DEMO_EMAIL` / `DEMO_PASSWORD` from `.deploy.env`.
3. **Agents** → the seeded **Absent Student Follow-up** agent.
4. **Playground** → connect the mic. First connection may take 10–20 s while
   the LiveKit agent cold-starts; it proves the voice pipeline for free.
5. **Test Call** → enter your own number (or leave it blank to use the first
   `TEST_PHONE_NUMBERS` entry) and place the call.
6. **Call History** → open the call for transcript, extracted fields, latency.
7. **Campaigns** → import a consenting CSV and launch; the dialer enforces
   9 AM–9 PM IST.

No Python, no scripts, no terminal during the demo.

---

## 7. Operating inside the free tier

| Symptom | Reality | What to do |
|---|---|---|
| First request after 15 min is slow | Free instance slept | `scripts\deploy\wake.ps1` before the demo |
| Around a demo you want it warm | 750 h/month is shared | Enable `.github/workflows/keep-warm.yml` (`KEEP_WARM=true`, `API_URL` repo variable) — then turn it **off**, it burns nearly the whole monthly budget |
| Voice agent answers after ~15 s | Build plan scales to zero | Connect the playground once before the demo |
| Build fails on Render | 512 MB limit | Check the deploy logs; `pip install` is the heaviest step |
| Postgres grows | Neon free 0.5 GB | Recording retention is 90 days; purge with `python scripts/seed_demo.py --purge-sample-data` |

Free-tier gotchas that were deliberately designed around:

- **Render free Postgres is deleted after 30 days** → Neon instead.
- **Render free services have no `preDeployCommand`** → migrations in the start command.
- **Render has no free background worker** → voice worker on LiveKit Cloud.
- **LiveKit Cloud injects `LIVEKIT_URL` / `LIVEKIT_API_KEY` /
  `LIVEKIT_API_SECRET`** into the agent at runtime. They must **not** be in the
  agent's secrets file, or the deployment is rejected.
- **LiveKit builds need** a glibc base image, a non-root user, a fixed
  `CMD ["python","agent.py","start"]`, a 1 GB build context, and finish within
  10 minutes.

---

## 8. Security posture of this deployment

- `ALLOW_PUBLIC_REGISTRATION=false` — only the seeded owner can sign in.
- `CORS_ORIGINS` is exactly the Vercel origin; no `*`.
- `JWT_SECRET` and `INTERNAL_API_TOKEN` are freshly generated (96 hex chars)
  and exist only in `.deploy.env` and the providers' encrypted env stores.
- The demo password is generated, 17 characters, and no longer `demo1234`.
- `CONSENT_ENFORCEMENT=true` and `TEST_PHONE_NUMBERS` limits outbound calls to
  numbers you own.
- `/api/health` exposes only booleans, model names, and TCP reachability —
  never key values.
- `.deploy.env` is gitignored; `.deploy.env.example` is the tracked template.
- `frontend/vercel.json`, `render.yaml`, and the scripts contain no secrets.

Rotate after the demo: Groq, Sarvam, Deepgram, Cartesia, Vobiz, LiveKit keys,
the Render API key, the Vercel token, and `DEMO_PASSWORD`. Rotating
`JWT_SECRET`/`INTERNAL_API_TOKEN` invalidates every session and bridge token —
update `.deploy.env`, then re-run `deploy-all.ps1`.

---

## 9. Teardown

```powershell
# 1. stop the voice worker (LiveKit CLI, installed at .tools\lk\lk.exe)
.\.tools\lk\lk.exe agent delete --url $env:LIVEKIT_URL --api-key $env:LIVEKIT_API_KEY --api-secret $env:LIVEKIT_API_SECRET --yes
# 2. suspend/delete the Render service in the dashboard
# 3. delete the Neon project
# 4. delete the Vercel project if it is no longer needed
```

Deleting the Render service does not delete Neon or LiveKit — they are separate
accounts on purpose.

---

## 10. Troubleshooting

| Symptom | First check |
|---|---|
| `Render refused to create the service` | GitHub is not connected to Render — do step 1 |
| `Missing required values in .deploy.env` | A blank line above; the script names the keys |
| Render deploy ends `build_failed` | Build logs; usually a missing system package or the 512 MB limit |
| Deploy `live` but health shows `db: false` | `DATABASE_URL` must be the Neon connection string with `sslmode=require`; check the Render logs for a psycopg/PgBouncer error |
| Login fails with the password from `.deploy.env` | The tenant was seeded on a previous run with a different password; see below |
| Vercel page loads, every API call fails | Service asleep → `wake.ps1`; confirm `VITE_API_URL` in Vercel → Settings → Environment Variables |
| `vercel link` creates a new project | The project name changed; run `deploy-vercel.ps1` (it links by name from the API) |
| Playground connects but the agent is silent | Provider keys missing on the **worker**, not just the backend — re-run `deploy-livekit.ps1` |
| Call rings then silence | Vobiz media WS URL, `INTERNAL_API_TOKEN` matching on both sides |
| Test call returns 422 | The number is not in `TEST_PHONE_NUMBERS` |

### Reset the demo password

The seed is idempotent: if the demo user already exists it is left alone, so a
changed `DEMO_PASSWORD` does not take effect by itself. Rotate it from the
Render shell (dashboard → your service → **Shell**):

```powershell
cd backend && python scripts/seed_demo.py --reset-password
```

It reads `DEMO_EMAIL`/`DEMO_PASSWORD` from the service environment, so update
`.deploy.env`, re-push the variable (`deploy-render.ps1`), then run the command.

---

## Appendix — the old Blueprint path

`render.yaml` is kept as a manual alternative: Render Dashboard → **New** →
**Blueprint** → pick the repo → it creates only the backend (Neon, LiveKit, and
Vercel are still manual). Use **either** the Blueprint **or**
`deploy-render.ps1`, not both, or you end up with two services and two
monthly-hour bills against the same 750-hour allowance.
