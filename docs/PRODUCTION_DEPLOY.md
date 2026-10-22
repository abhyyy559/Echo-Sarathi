# Production deployment — Vercel frontend + Render backend

This is the deployment path for a live faculty demo. The React app stays on
Vercel. The API, the Vobiz media WebSocket, the campaign dialer, and the
LiveKit voice worker run on Render. LiveKit rooms stay on LiveKit Cloud.

```
Browser / faculty
   |
   |  https://<vercel-app>
   v
Vercel  ── /api/* proxy ──►  Render: echosarathi-api (FastAPI + WebSocket)
                                   |            |
                                   |            └── Postgres + Redis
                                   |
Vobiz ── answer/media/status ──────┘
   |
LiveKit Cloud ◄── browser playground + Render voice worker
```

## 1. What must be true before deploying

- A LiveKit Cloud project URL, API key, and **API secret**. The secret is not
  in `.env.example`; copy it from LiveKit Cloud → Settings → Keys. Do not use a
  participant JWT as the API secret.
- A Vobiz auth ID, auth token, and the caller-ID number that is active on the
  Vobiz account.
- Deepgram, Cartesia, Sarvam, and every Groq key you intend to use.
- At least one phone number you are allowed to call. Put it in
  `TEST_PHONE_NUMBERS`; consent enforcement is on by default.

## 2. Deploy the backend stack on Render

1. Open Render Dashboard → **New** → **Blueprint**.
2. Connect `https://github.com/abhyyy559/ai-voice-calling-agent`.
3. Render reads `render.yaml` and creates:
   - `echosarathi-api` — FastAPI, WebSocket media bridge, dialer
   - `echosarathi-voice` — LiveKit Agents worker
   - `echosarathi-db` — Postgres
   - `echosarathi-redis` — Redis-compatible Key Value
4. Fill every value marked `sync: false` in the Render form. At minimum:
   - `CORS_ORIGINS` = the deployed Vercel origin, e.g. `https://your-app.vercel.app`
   - `TEST_PHONE_NUMBERS` = your own phone, comma-separated, e.g. `+9198XXXXXXXX`
   - `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
   - `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `SARVAM_TTS_API`
   - `GROQ_API_KEY`, `GROQ_API_KEYS`
   - `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`, `VOBIZ_PHONE_NUMBER`
   - `LLM_FALLBACK_CHAIN` if you use the Sarvam overflow entry
5. Confirm the backend URL. The Blueprint assumes
   `https://echosarathi-api.onrender.com`. If Render assigns a different URL,
   update `PUBLIC_BASE_URL`, `PUBLIC_WS_BASE_URL`, and the two
   `BACKEND_INTERNAL_URL`/frontend references listed below.
6. Wait for the deploy. The pre-deploy command applies Alembic migrations and
   seeds the demo tenant (`demo@example.com` / `demo1234`) plus the starter
   agent. It never places a call.

### Why the backend is on Render, not Vercel

Vercel Functions can serve WebSockets, but this API also needs a long-lived
dialer task and a Vobiz media bridge that can stay open for the duration of a
call. Render web services keep the process alive, support WebSockets, and can
run the worker as a separate always-on service.

## 3. Point the Vercel frontend at Render

`frontend/vercel.json` proxies `/api/*` to:

```
https://echosarathi-api.onrender.com/api/*
```

If the Render URL is different, change that one `dest` value, commit, and let
Vercel redeploy. The browser then calls the same origin (`/api/...`), so no
backend hostname is baked into the JS bundle and no CORS preflight is needed
for normal UI traffic.

If you prefer a direct cross-origin API call instead of the proxy:

1. Set `VITE_API_URL=https://echosarathi-api.onrender.com` in Vercel →
   Settings → Environment Variables.
2. Add the Vercel origin to `CORS_ORIGINS` on Render.
3. Redeploy the frontend (Vite bakes `VITE_*` values at build time).

## 4. Vobiz setup

The backend sends the answer URL per outbound call. It is built from
`PUBLIC_BASE_URL`:

```
https://echosarathi-api.onrender.com/vobiz/answer?call_id=<internal-call-id>
```

The media stream then connects to:

```
wss://echosarathi-api.onrender.com/vobiz/media?call_id=<id>&bridge_token=...
```

Do **not** configure a bare `/vobiz/answer` in Vobiz: `call_id` is required and
is supplied by the backend for each call. Keep the Vobiz application assigned
to `VOBIZ_PHONE_NUMBER`. `VOBIZ_WEBHOOK_SECRET` is optional; leave it empty
unless you have configured Vobiz to send the same `X-Vobiz-Signature` header.

## 5. Faculty demo flow — all from the UI

1. Open the Vercel URL and sign in with `demo@example.com` / `demo1234`.
2. **Agents** → open the seeded **Absent Student Follow-up** agent.
3. **Playground** → connect the browser mic. This proves the LiveKit room and
   voice pipeline without spending telephony minutes.
4. **Test Call** → the newest saved agent version is selected automatically.
   Enter your own phone (or leave the destination blank to use the first
   `TEST_PHONE_NUMBERS` entry), fill the lead card if you want, and press
   **Place test call**.
5. **Call History** → open the new call to show the live transcript,
   extracted fields, and latency.
6. **Campaigns** → create a campaign, import a CSV of consenting contacts,
   launch it, and show progress. The Render dialer enforces 9 AM–9 PM IST.
7. **Dev** → show service health and provider presence if a key is missing.

There is no script or Python file in this flow.

## 6. Smoke checks

Backend health:

```powershell
Invoke-RestMethod https://echosarathi-api.onrender.com/api/health | ConvertTo-Json
```

Login check:

```powershell
$body = @{ email = 'demo@example.com'; password = 'demo1234' } | ConvertTo-Json
$r = Invoke-RestMethod https://echosarathi-api.onrender.com/api/auth/login -Method Post -Body $body -ContentType 'application/json'
$r.token.Length
```

If health is red, open the Render logs for `echosarathi-api` first. If calls
ring but there is no audio, check `echosarathi-voice` and the LiveKit key pair.

## 7. Security and cleanup

- Never commit `.env`. The repository `.gitignore` already excludes it.
- Rotate Groq, Sarvam, Deepgram, Cartesia, Vobiz, and LiveKit keys after the
  faculty demo.
- Change the demo password or disable the demo account after the demo.
- Keep `CONSENT_ENFORCEMENT=true` and `TEST_PHONE_NUMBERS` limited to numbers
  you own or have explicit consent to call.
- Keep `ALLOW_PUBLIC_REGISTRATION=false` unless you intentionally want anyone
  on the internet to create an organization.
- If you delete the Render stack, delete its Postgres and Redis resources too.

## 8. Common failures

| Symptom | First check |
|---|---|
| Vercel page loads, every API call fails | `frontend/vercel.json` `dest` points at the real Render URL; Render service is awake |
| Login returns “demo account not available” | Render pre-deploy seed failed; inspect `echosarathi-api` deploy logs |
| Test call returns 422 “not in TEST_PHONE_NUMBERS” | Add the number to `TEST_PHONE_NUMBERS` on Render and redeploy |
| Call rings, then silence | Vobiz media WebSocket URL, `PUBLIC_WS_BASE_URL`, and LiveKit key pair |
| Playground connects but agent is silent | Deepgram/Cartesia/Groq/Sarvam keys on the **worker**, not only the backend |
| Vercel 502 on `/api` | Render service is down or still deploying |
| Vobiz call never reaches the API | `PUBLIC_BASE_URL` must be the public Render URL, not localhost or Vercel |
