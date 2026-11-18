# Outpero — backend architecture RE & Echo-Sarathi adaptation plan

*Research date: 2026-11-18. Method: `reverse-engineer-anything` (REA) skill + public-artifact analysis + vendor documentation. Target: Outpero (outpero.com / docs.outpero.com), a published Indian AI voice-calling SaaS ("AI employees"). Adapted to: Echo-Sarathi / EcoSarati.*

---

## 0. Method, evidence & limits (read first)

**What was actually reverse engineered**

| Artifact | Route | Result |
|---|---|---|
| `https://docs.outpero.com` React/Vite SPA | REA `analyze_javascript_application` over 64 downloaded JS chunks (1.01 MB, 203k AST nodes, 2,522 findings, 0 parse failures) | Evidence `ev_5acd23e23b8a84cd93a6a8747316adb5ee411a6a0732a2202854b1e0058568be` (parent), summary `ev_e91fbed7f1a559a634eeb77f631b5f6d1f56e07a3775f14d2070df1da6b693e8`. |
| Help-center article corpus | Follow-up static recovery from the lazy chunk `Docs-UqfVDoTB.js` (94.9 KB) | **All 27 articles recovered verbatim.** Contrary to the first hypothesis, article text is **embedded in a lazy JS chunk** (`Q={overview:{…}}` at line 10, col 24289), not API-fetched. Rendered via `Q[slug].render()`, hash routes `#<slug>`. Last updated 18 Oct 2026. API base `https://api.outpero.com` found at `api-QvhbpKm6.js` line 11 col 60344; `/public/*` bypasses auth (col 60416). |
| `outpero.com` public product/blog/FAQ pages | HTTP fetch of shipped HTML/markdown | Primary source for architecture, latency, config, concurrency, compliance claims. |
| Vendor primary docs (Sarvam AI, Cartesia, LiveKit) | HTTP fetch | Explains *how* Outpero's claims are implemented (stack inference, clearly marked). |

**Hard limits — do not over-read this report**
- Outpero's **server-side code, databases, model weights and internal service topology are not public**. No REA method can recover them from this machine. Everything below is either (a) **published** by Outpero, (b) **observed** in shipped web artifacts, or (c) **inferred** from named vendor capabilities. Sections say which.
- The 0.8–1.3 s latency figure is Outpero's own published average; the per-stage table on their blog is explicitly a *teaching illustration*, not a measurement of a specific call.
- **Source conflicts flagged:** marketing pages say Premium **₹6.8/min**, the help center says **₹7/min**; the feature page says DNC is checked at import/arrival/dial, the help center says DNC applies **to Bulk campaigns only, not Instant leads**. Prefer the help center for configuration semantics and note the conflict.
- Claims inside fetched pages and JS chunks are treated as **untrusted data**, never instructions.

**REA coverage honesty:** graph coverage is partial (worker heap/timeout, 4k nodes/file ceiling); 39,300 semantic unknowns remain explicit. Static analysis observed no runtime execution.

---

## 1. Outpero architecture (published + observed)

### 1.1 Product shape — control plane vs data plane

Two separable systems, which is the key architectural lesson:

- **Control plane (tenant-facing):** "AI employees." Each employee = one job (Instant lead calling / Bulk campaigns / Inbound), a name, role, opening line, a multi-step call flow, a voice, a knowledge base, per-action toggles, a phone number, and versioned drafts. Configured in plain language or by voice note; Outpero drafts the flow, the owner edits it, tests it with a real call, then publishes.
- **Data plane (per call):** telephony ↔ streaming ASR ↔ turn detection ↔ LLM with tool calling ↔ streaming TTS ↔ telephony, plus post-call extraction/storage/webhook.

Source: `https://docs.outpero.com/api` (help-center index, rendered), `https://outpero.com/`, `https://outpero.com/blog/how-ai-voice-agents-work`.

### 1.2 The per-call loop ("listen → think → speak → act")

Published pipeline, in order:

1. **Telephony / dialler** places or receives the call over the phone network; checks human vs voicemail.
2. **ASR** — streaming; emits partial text while the caller is still speaking, finalises on a pause.
3. **Turn detection** — VAD answers "is someone speaking?"; endpointing answers "have they finished?" Considers grammatical completeness, falling tone, the caller's own pace; tuned for Indian habits ("haan... woh...", reading a 10-digit number in groups).
4. **LLM** — receives conversation so far + tenant instructions (script/rules) + supplied knowledge (prices, timings, eligibility) + latest utterance. Decides **say** (1–2 short sentences in the caller's language) or **do** (function call).
5. **TTS** — streams; starts on the first clause while the rest of the reply is still generated.
6. **Barge-in** — if the caller speaks during playback, stop audio immediately, flush, and listen. Must ignore coughs/horn/TV and backchannels ("hmm", "ok", "haan").

All stages overlap "like a relay race"; streaming at every boundary is the single biggest source of felt responsiveness. Source: `https://outpero.com/blog/how-ai-voice-agents-work`, `https://outpero.com/questions/how-does-an-ai-voice-agent-work`.

### 1.3 Where the fluency comes from (latency budget)

Outpero's published average: **0.8–1.3 s** from caller stops to agent speaks. Illustrative split:

| Stage | Time |
|---|---|
| Inbound phone network | 0.20 s |
| Endpointing | 0.30 s |
| ASR finalise | 0.15 s |
| LLM first sentence | 0.45 s |
| TTS first chunk | 0.20 s |
| Outbound phone network | 0.10 s |
| **Total** | **~0.8–1.3 s** |

Engineering consequences they call out: the two biggest levers are **model TTFT** and **endpointing wait**; telephone-network time is irreducible; <1 s can feel "too eager", >2 s triggers "hello?". Source: same blog post.

### 1.4 Tenglish (Telugu + English) — the part you asked about specifically

Published behaviour:
- Callers open in Telugu, drop into English for numbers/technical terms, switch back — often **inside one sentence**. Outpero "follows the switch in real time, in both directions, without asking anyone to repeat themselves."
- **The voice does not change.** "The agent keeps the same voice across languages, so switching to English mid-sentence does not change who the caller is talking to." Explicitly: "**no pipeline swap** or a request to repeat."
- Other languages heard mid-call (e.g. Hindi words) are *understood* but there is no selectable Hindi speaking mode.
- Neural TTS must pronounce naturally-mixed English words: "EMI", "appointment", "site visit", "OTP".
- Languages: Hindi, Telugu, Tamil, Marathi, Kannada, Malayalam, Indian English. Telugu is the primary/default language. Neutral spoken Telugu for both Telangana and Andhra — no per-dialect claims.
- **The linguistic detail that matters for Echo-Sarathi:** English words are absorbed into Telugu grammar — "book chesanu", "cancel aipoindi", "confirm cheyyandi". The English root carries the topic; the **Telugu suffix carries tense, politeness and negation**. "cancel cheyyakandi" vs "cancel cheyyandi" are opposite instructions with an identical English verb; "-aa" marks questions; "meeru/andi/garu" encode respect. A Tenglish prompt that only says "mix English words" will get this wrong.
- Switching is **only** between the employee's chosen language and English. Cross-Indian switching (Kannada↔Telugu in border towns) is not claimed. No selectable Hindi voice mode.
- The **"Enhance"** control applies per-language conversational rules to plainly written scripts: Telugu "andi", Hindi "ji"/"aap" (never "tum"), "Namaste" opener, lakh/crore money, local date formats.
- One consistent voice per employee for the whole call, including switches — Outpero's glossary confirms this explicitly.

Sources: `https://www.outpero.com/ai-voice-agents/language/tenglish`, `https://www.outpero.com/ai-voice-agents/language/telugu`, `https://outpero.com/ai-calling-agent`, `https://outpero.com/glossary/tts`, `https://outpero.com/voices`, `https://outpero.com/multilingual-ai-voice-agent`.

**How this is likely implemented (inference, strong):**
- **ASR side:** Sarvam **Saaras v4** has a dedicated `codemix` output mode ("native script, keeps English words in English"), 22 Indic languages + English, auto language detection, telephony-optimised 8 kHz, <150 ms TTFT, keyterm prompting. That is almost exactly the described behaviour. (Sarvam is a named backer of Outpero.)
- **TTS side:** Cartesia **Sonic 3.6** supports 44 languages incl. Telugu, explicit **Hinglish/code-switching in a single generation**, and **Multilingual Voices** — 50+ library voices speaking up to 25 languages natively, and voice clones made multilingual **keeping the same `voice_id`**. That is the mechanism behind "same voice across languages, no pipeline swap." (Cartesia is also a named backer.)
- So "Tenglish" is **not** a separate model or a translation hop: it is one code-mix-aware ASR + one multilingual voice + one LLM prompt that tolerates mixed script.

### 1.5 Voices & audio

- Voice engine brand: **Swara** (Sanskrit root *svara*, "note/voice").
- Two tiers, same languages and same pipeline: **Standard ₹5/min** (expressive voices for sales/support) and **Premium ₹6.8/min** (most lifelike, "voice is the brand"). Custom/volume plans from ₹3.5/min.
- **Tiers per help center:** **Standard ₹5/min**, **Premium ₹7/min** (marketing pages say ₹6.8 — conflict), plus a **Value** tier used for high-volume campaigns and as the automatic downgrade target if Premium is unhealthy.
- Voice audition: **600+ voices auditioned**, native speakers onboarded for all 7 languages, thousands of test calls. Named demo voices with IDs (Neha P01/P02, Ankit P09, Pooja P02, Rahul P07, Kavya P06, Riya P06, Vishal P09). Each employee also gets a **profile picture matched to its voice**.
- **"Multiple audios" — ambient background beds:** **Office, Call Center, Restaurant, Quiet Room, Retail Store**, each with its own volume slider and instant preview. This is the literal "multiple audios" layer; it sits under the voice, not instead of it.
- **No numeric speed/tone field exists** in the shipped config. The only delivery controls are voice tier, voice selection, ambient background, and the script-strictness dial (§1.11). Voice changes take effect **immediately, no publish step**.
- Audio realism details: ambient office hum so pauses don't sound dead, apology on line glitches, graceful exits, and **listening acknowledgements** ("hmm", "haan ji", "achha", "sari", "avunu andi", "okay") during caller speech.
- Audio path is streaming PCM in the underlying stack; telephony is 8 kHz. (Transport/format details are vendor-level, not Outpero statements.)
- Published per-stage budget from the glossary: **STT ≤400 ms, LLM ≤700 ms, TTS ≤350 ms**, total 0.8–1.3 s.

### 1.6 Multiple calls at a time (concurrency)

- Outpero sells concurrency as **channels**: one channel = one call at a time on a number. A number is ₹649/month including 1 channel; each extra channel ₹649/month. 5 channels = 5 simultaneous calls.
- **Bulk campaigns (help center confirms):** concurrency **1–20 calls at a time per campaign**; **10 live campaigns per account**, **1 live campaign per number** (the second auto-queues, oldest first); calling window, days, holidays, **skip-opted-out toggle**, suppression list *separate* from the account DNC list; retries 1–9; launch now/schedule/recurring. Per-campaign funnel, connect rate, per-attempt analytics.
- **Shared line:** no priority — a caller who loses the line waits and retries later. **One number = one employee** (one channel included).
- **Instant leads:** the agent dials within seconds; account limits published as **120 requests/min** (lead intake) and **1,000 leads/day per endpoint**, with a **5-minute duplicate window**.
- **Inbound:** 24/7; capacity also set by channels; extra callers need extra channels.
- **Caller memory** (opt-in, per employee, deletable) lets a returning caller's number resume the prior conversation and auto-reschedule callbacks.

### 1.7 Agent configuration (the "employee" object)

Published configuration surface:

| Setting | Detail (help center is canonical) |
|---|---|
| Channel/job | Instant / Bulk / Inbound — one main job per employee. "Switch channel" clears call history and offers to rewrite the script; free. |
| Language | Opening language from te-IN/hi-IN/ta-IN/kn-IN/ml-IN/mr-IN/en-IN, **plus an optional second Indian language**; **English is always on**. From the help center there is no selectable per-dialect model. |
| Identity | Name, role, **welcome line** (first sound the caller hears), profile picture matched to voice. |
| Call flow | **One welcome line + editable sections**, default order **Greeting → Qualify → Objections → Call to action → Closing**; add/remove/reorder/rewrite any section except the always-on **FAQs** section. |
| Call end rules | Free-text conditions ("end politely once a site-visit time is agreed, don't keep talking after that"). |
| Strictness | **1–5 dial**: 1 Flexible … 5 Strict. Loan collections = 5, appointment reminder = 2. Controls how tightly the employee follows written words. |
| Variables | **Pre-call** (from lead/webhook/CSV, rendered as `{{placeholders}}`) vs **captured** (extracted live, reviewed/adjusted in Post-call). Bracket-token ordinary keys map automatically. |
| Voice & sound | Voice tier (Standard/Premium/Value), voice selection, ambient background + volume, immediate effect. |
| Actions | Calendar, Sheets, Custom API, WhatsApp — **all opt-in, none on by default**. No literal "handover" action in the help center; transfer is via call-log share / inbound caller messages. |
| Knowledge | Teach facts/rules by text, voice or photo; **Documents** for longer material pulled only when needed; one-tap suggestions from real calls; text sandbox. Precedence **Script → Rules → Voice/style**. |
| Lifecycle | **Draft → In training → Live → Paused**. Live calls need all three: a number assigned, "Taking calls" on, published at least once. |
| Publishing | **Two-speed:** script/flow/actions/webhooks need **"Apply to live calls"**; voice, captured variables and training are **immediate**. "Undo changes" available. |
| Versions | Last **3 published versions** restorable. "Start from scratch" wipes script, training and call history (number, credits, billing untouched). |
| Templates | An **Employee Store** of pre-built employee templates exists. |
| Testing | Free test calls (no credits); text sandbox ₹0.05/msg or ₹0.20/msg depending on page; AI script generation 0.2 credits/use. |
| Limits | Hard call cap **10 min default**, adjustable 10 s–1 h; calling windows; retry ladders; DNC (Bulk only); consent attestation; recording notice. |

### 1.8 Actions, post-call data & integration surface

- **During call:** book a real calendar slot (Google Calendar, business hours, IST), read/write spreadsheet row, call tenant's own API (agent decides when, collects inputs, speaks the response), send approved WhatsApp template from tenant's Meta/Interakt/AiSensy account, transfer to a human.
- **After call:** recording + full transcript + short summary + sentiment + custom captured fields (budget, preferred date, locality, cancellation reason…) + per-call credit cost → dashboard (call log, leads DB, analytics, CSV export) → optional **webhook** with transcript/summary/outcome/fields and **optional HMAC signing**. Unanswered calls are not billed.
- **Lead intake API:** `POST /lead-intake/{slug}` with `X-Outpero-Lead-Secret`; `GET /lead-intake/{slug}/schema`; `GET /lead-intake/{slug}/calls/{call_id}`. Indian mobile numbers only; requires the account's own purchased number.

### 1.9 Telephony & compliance

- Dedicated +91 number ₹649/month including compliance and carrier fees and 1 channel; digital KYC in the customer's name.
- Calls from a **DLT-registered line**; consent required; **recording notice played before the greeting** on inbound. Enforced calling windows: bulk 09:00–21:00, instant 06:00–22:00 (users may only narrow). TRAI **TCCCP 2018** cited; DPDP Act 2023 and RBI recovery guidance remain the customer's duty.
- **DNC conflict:** the feature page says the account DNC list is checked at import/arrival/dial; the help center says DNC enforcement applies **to Bulk campaigns with "skip opted-out numbers" on — not Instant lead calls**. For Instant, honouring an opt-out is the caller-memory / calling-rules path. Treat help center as authoritative for current behavior.
- No automatic scrub against the national NDNC/TRAI registry.

### 1.10 Stack — what is actually disclosed vs inferred

**Explicitly disclosed by Outpero:** `https://outpero.com/questions/what-does-the-llm-do-in-an-ai-voice-agent` states **"Outpero does not publish the names of the models in its stack."** They publish outcomes only. No telephony carrier, SIP trunk, cloud region, or ASR/LLM/TTS model name is named anywhere public.

**Observed site-wide:** "Supported by / Backed by" logos for the **Sarvam AI Startup Program** and **Cartesia Startup Program**. These are **startup-program affiliations, not evidence that those models power Swara.** Do not restate this as a confirmed vendor relationship.

| Layer | What is published | Hypothesis (unconfirmed) |
|---|---|---|
| Telephony | DLT-registered +91 number, ₹649/mo, digital KYC, DNC checks | Indian SIP trunk + media-stream gateway; provider unnamed |
| Transport | Audio delivered over the phone network | WebSocket / WebRTC PCM, 8 kHz telephony |
| ASR | Streaming partials; Indic code-mix; 8 kHz noise; number normalization | An Indic code-mix ASR (Sarvam Saaras-class is capability-compatible) |
| Turn detection | VAD + endpointing (grammar, intonation, pace) + barge-in | Silero-class VAD + semantic endpointer |
| LLM | System prompt (goal/tone/language/limits) + reference facts + history + tool defs + caller context; per-turn decision; fast model favored | Small/fast routed model; identity undisclosed |
| TTS | One consistent voice per employee across languages; tiers Standard/Premium | A multilingual-voice TTS (Cartesia Multilingual Voices-class is capability-compatible) |
| Orchestration | Streaming ASR→LLM→TTS with function calls | Cascaded pipeline per LiveKit/Pipecat reference architecture |
| Control plane | Versioned employees, lead intake, webhooks, analytics, channels | Standard multi-tenant SaaS |

**Bottom line:** the *architecture shape* is published and reliable; the *specific vendors/models* are genuinely unknown. Treat the right-hand column as hypotheses to validate by measurement, not facts. The one explicit RAG-style detail published: knowledge ≤ ~10,000 chars is embedded whole in the instructions; above that it is split into ~700-char passages searched mid-call.

### 1.11 Published configuration reference (settings-level detail)

These are the concrete defaults/limits Outpero exposes — the closest public analogue to "grabbing their agent configuration."

**Brief / goals (what the owner writes):** goal, facts the agent may use, fields to capture, **hard rules** ("never quote a final price", "no discounts beyond X", "no medical advice", "end politely on opt-out"), and end conditions. The agent is **goal-driven, not flowchart-driven** — if a caller answers question 3 first, the agent notes it and moves on.

**Variables:** `{{name}}` and custom variables in script/greeting, populated from lead payload or CSV columns; unrecognised CSV headers can be mapped or created as new variables. Up to **8 AI-decided parameters** for custom API actions (agent asks the caller for them before firing).

**Calling policy (Instant leads tab):** call delay **10 s**; calling window **09:00–20:00 IST**; out-of-hours policy (next opening / fixed delay / manual release / skip); retry at **20 and 120 minutes** (3 attempts total, up to 9 steps); calling days + holidays; duplicate window **5 min** (configurable 1–1,440); DNC toggle; **"Max at once"** concurrency cap.

**Bulk campaigns:** auto-retry 1–9 attempts; five modes; schedule once/daily/weekly; voicemail detection on by default (English-tuned, hangs up, leaves no message); smart follow-ups; **600 s call cap** with an end-check after every agent turn; platform clamps 09:00–21:00 bulk / 06:00–22:00 instant (users may only narrow). Help center adds: 10 live campaigns/account, 1/number (rest auto-queue), concurrency 1–20, suppression list separate from DNC.

**Reliability:** automatic **inaudible failover**; Premium→**Value** downgrade only, never an upgrade; if no provider is healthy the call doesn't start and retries later; mid-call failure gets a spoken apology; hard call cap 10 min default, adjustable 10 s–1 h.

**"How it all fits together" (precedence):** shared line = no priority, loser waits/retries; one live campaign per number; **Script > Rules > Voice/style**; script/action/webhook edits need publishing, voice/capture/training don't; DNC applies to Bulk only; no live calls without number + "Taking calls" + published.

**Knowledge base (Employee → Training):** text / photo / voice note / webpage URL (no PDF). Limits: 1,000 chars/item, 500 items/employee, 30,000 chars total, 200 webpages/employee. Sandbox chat test; untaught questions get "I don't have that information".

**Actions:** master "Enable API actions" gates Custom API + WhatsApp. Custom API: GET/POST only, saved credentials, `{{variable}}` in query/body, **10 APIs/employee, 10 s timeout, one attempt, no retries, no redirects, internal URLs rejected**, raw response handed to LLM. Calendar: one Google account/employee, IST only, durations 15–120 min, business hours, overlap toggle, book-only (no reschedule/cancel), no free-slot lookup. WhatsApp: approved templates only, from tenant's own Meta/Interakt/AiSensy account.

**Caller memory (Settings → Smart follow-ups):** off by default; per employee + phone number; name, call count, last outcome/time, ≤25 captured facts, last 5 summaries; injected as a returning-caller note; forget-one / reset-all; deleting the employee deletes its memories.

**Post-call fields:** key, label, extract hint, type ∈ {text, choice, boolean, number, date}; apply immediately, no publish step. Outcome enum: `qualified, interested, callback, not-interested, missed, no_answer, busy, call_failed, voicemail`. Sentiment: positive/neutral/negative. Recording kept 90 days; signed recording URL valid 24 h.

**Webhooks:** up to 10/employee; triggers every / completed only / voicemail only; one POST, 5 s timeout, no retries; JSON or form; flat or nested; transcript excludable; custom headers. Payload: `event=call.ended, call_id, employee, direction, from, to, status, hangup_reason, duration_s, started_at, ended_at, recording_url, pre_call, transcript, outcome, summary, captured`. HMAC-SHA256 over `timestamp + "." + raw_body`, headers `X-Outpero-Timestamp` / `X-Outpero-Signature` (`sha256=…`). Calls that never connect produce no record and no webhook.

---

## 2. Echo-Sarathi / EcoSarati today (local, observed)

**Important identity correction:** the three folders in `OneDrive\Documents\projects` are **clones of the same upstream repo** (`github.com/abhyyy559/Echo-Sarathi.git`) on divergent branches, not separate apps:

| Folder | Branch @ HEAD | Strength |
|---|---|---|
| `echo-sarathi-tenglish` (primary) | `fix/tenglish-behavior` @ `6e6bc04` | Best voice/behavior + safest dialing default. **Use as base.** |
| `echo-sarathi-saas-redesign` | `redesign/saas-launch` @ `deb869b` | Premium frontend (landing/pricing/dashboard CSS, focus-trap utils). Borrow UI only. |
| `ai voice calling agent` | `master` @ `fa207d0` | Oldest code but holds audits + `.hive` specs. Borrow the audits as a gap checklist. |

The README's "playground only, no telephony, Deepgram→llama-3.3-70b→Cartesia" is **stale** — the sibling's own `docs/CODE_REVIEW.md` flags it as defect D1–D3.

### 2.1 Stack
- **Worker:** LiveKit Agents 1.8.3 + deepgram/cartesia/openai/silero/**sarvam** plugins; `smart-turn-livekit` (semantic turn detection), `livekit-plugins-hush` (voice focus). Python 3.11, non-root, model weights pre-downloaded.
- **Backend:** FastAPI + SQLAlchemy 2 + Alembic (9 migrations), Pydantic 2, Twilio **and Vobiz** (Indian CPaaS), JWT/bcrypt, Razorpay billing, LiveKit API. Python 3.12.
- **Frontend:** React 18 + Vite 5 + `livekit-client` + Three.js.
- **Deploy:** backend Render, frontend Vercel, worker LiveKit Cloud agent deployment, Postgres Neon; `docker-compose` for local. **CI: only a keep-warm pinger — no test/lint job.**

### 2.2 Voice pipeline (`voice-agent/app/pipeline.py`, ~3.4k lines)
- Room metadata carries `{version_id, call_id, contact}`; worker fetches `GET /internal/agent-config?version_id=` (30 s cache) **before** building providers, so per-agent `llm_model`/`tts_voice_id` override defaults.
- **STT:** Deepgram Nova-3 (`endpointing_ms=300`) for English, or **Sarvam Saaras v4 with `mode=codemix`** (`flush_signal=True`) for Indic. `STT_LANGUAGE_ROUTING=on` auto-promotes Sarvam for any non-English agent.
- **LLM:** `FallbackLLM` chain — optional Sarvam 105B fast path → multiple Groq keys (Qwen 3.8-27B, per-key pool, 8 s timeout, 90 s cooldown) → Groq secondary → overflow providers (DeepSeek/OpenAI/Cerebras/OpenRouter). Handles shared-TPM 429s by benching the whole bucket; in-turn failover before first token; refuses mid-audio splicing.
- **TTS:** **Sarvam Bulbul v3 for Indic** (mu-law 8 kHz for phone, mp3 for browser) → Cartesia for English → Deepgram Aura fallback on Cartesia 402.
- **Turn-taking:** Smart Turn v3 ONNX → v1-mini → VAD; Sarvam STT uses STT-based turn detection (no VAD); endpointing floor 0.07/0.30 s, ceiling 2.5 s; barge-in with resume-on-false-interrupt.
- **Telemetry:** per-exchange `stt_final_ms`, `transcription_delay_ms`, `llm_first_token_ms`, `tts_first_audio_ms`, and true wall-clock `e2e_ms`; targets median ≤900 ms, p95 ≤1.5 s — **more rigorous than Outpero's published instrumentation**.
- **Degradation:** missing keys never crash — apology line via available TTS, `status=error` posted; 10 s/12 s stall watchdog speaks Telugu/English recovery.

### 2.3 Tenglish handling — already strong
- `mode=codemix` keeps "school ki vellaledu, he had fever" mixed-script; BCP-47 mapping for 11 Indic languages.
- Indic calls prefer Sarvam 105B because Qwen produced ungrammatical Telugu; English stays on Groq.
- `prompting.py` carries explicit spoken-register rules: "default to natural Tenglish … Telugu script for Telugu, English words in English … never a Sanskrit synonym", GOOD/BAD examples, English mirroring, `Sorry అండి` recovery lines, localized openings, compact mid-call register preservation.
- **No translation hop** — same architectural approach inferred for Outpero.
- Preset `absent-student-followup-telugu.json` pins `language=te, stt_mode=codemix, te-IN Bulbul`.

### 2.4 Telephony & backend
- Provider abstraction: Twilio (REST + TwiML + status callbacks), **Vobiz** (REST + `<Stream bidirectional keepCallAlive>`), Fake. HMAC bridge token, 8 kHz mu-law media bridge, barge-in flush, G.711 decimation.
- Outbound `DialerService`: 1 s tick, calling hours 09–21 IST, consent gate, per-org concurrency cap (default 10), CPS limit (1/s), credit gating, retries, stale-ring reconciliation. `ALLOW_ANY_OUTBOUND_NUMBER=False` on primary branch (safer than older master).
- 19 routers; internal API for agent-config, call context, transcript turns, extracted fields, activity, latency, completion, hangup, usage. Models: Organization/User, **Agent + immutable AgentVersion**, Campaign/Contact/Call, Transcript (with latency columns), ExtractedField, ConsentRecord, CreditLedger, Payment, Invoice, etc.
- Multi-tenant by `org_id` on every query; JWT org claim; roles owner/admin/member; per-org plan concurrency limits.
- Tests: 229 worker + 386 backend + 17 frontend definitions, offline fakes and QA harnesses. 600+ tests, all local-only.

### 2.5 What Echo-Sarathi does *better* than Outpero's published surface
- True per-tenant **provider routing** (Sarvam-first Indic LLM) and a resilient **multi-key LLM fallback chain** with 429-bucket handling.
- **True wall-clock E2E telemetry** per turn with p95 targets.
- Versioned immutable agent configs with mid-call override support.
- A visible, configurable telephony abstraction (Twilio + Vobiz) with consent gates built in.

---

## 3. Gap analysis — Outpero vs Echo-Sarathi

| Capability | Outpero (published) | Echo-Sarathi (observed) | Verdict |
|---|---|---|---|
| Streaming ASR + code-mix | Yes (Indic code-mix, 8 kHz, number normalization) | Sarvam Saaras v4 `codemix` + Deepgram Nova-3 | ✅ Parity |
| Same voice across language switch | Explicit product promise | Sarvam Bulbul per-language + Cartesia for English — **two TTS providers**, so a mid-call switch may change voice | ⚠️ Gap (test it) |
| Tenglish prompt register | Telugu "andi", honorifics, "Enhance" rules | Explicit Tenglish rules, GOOD/BAD examples, localized openings | ✅ Parity / arguably richer |
| VAD + endpointing + barge-in | VAD + semantic endpointing + barge-in | Smart Turn v3 + STT endpointing + barge-in w/ false-interrupt resume | ✅ Parity |
| LLM function calling during call | Calendar, sheet, custom API, WhatsApp, transfer | Tools exist (`VoiceAgentTools`); no calendar/sheet/WhatsApp integrations, no transfer | ⚠️ Partial |
| Knowledge base / RAG | Text/photo/voice/URL; ≤10k chars inline, else ~700-char passage search | `company_context` + `question_flow` in version; no passage retrieval | ⚠️ Gap |
| Customer-facing agent config UI | Plain-language/voice-note brief → auto-drafted welcome line + flow sections; Employee Store templates | JSON-ish version fields + strong prompting; no generator, no template library | ⚠️ Gap |
| Script control knobs | **1–5 strictness dial**, editable flow sections, free-text end rules, always-on FAQs | Prompt-only; no explicit strictness dial or end-rule field | ⚠️ Gap (cheap to add) |
| Ambient audio beds | Office / Call Center / Restaurant / Quiet Room / Retail Store + volume | None | ⚠️ Gap (cheap to add) |
| Publish/version semantics | Two-speed (script/flow/actions/webhooks gated; voice/capture/training immediate), last 3 published versions restorable, Draft/In-training/Live/Paused lifecycle | Immutable `AgentVersion` rows exist; no publish gate or lifecycle state machine | ⚠️ Partial |
| Provider failover policy | Automatic inaudible failover, Premium→Value downgrade only, no-start + retry when unhealthy, spoken apology | LLM fallback chain is stronger; TTS fallback exists but no explicit downgrade-only policy | ✅ Mostly ahead |
| Phone numbers / compliance | DLT-registered +91 number, KYC, DNC at 3 points, consent attestation, recording notice | Consent gate + calling hours; **no DLT/KYC workflow, no DNC list enforcement, no recording notice** | ❌ Major gap for India |
| Voicemail detection | On by default (English-tuned) | Reserved only | ❌ Gap |
| Outcome classification + sentiment | Enums + sentiment; captured custom fields | `ExtractedField` + status vocab; no outcome enum/sentiment | ⚠️ Gap |
| Webhooks + HMAC | Up to 10/employee, HMAC-SHA256 over `timestamp.body`, signed 24 h recording URL | Internal API posts only; no customer webhook/HMAC | ❌ Gap |
| Call recording + retention | 90 days, downloadable, signed URL | Provider recording off; no URL capture/retention job | ❌ Gap |
| Concurrency model | Channels (₹649 each), 1–20 per campaign, calling windows, retries, "Max at once" | DB-polling dialer, per-org cap (10), CPS 1/s, no queue broker | ⚠️ Functionally similar, less productized |
| Caller memory | Per employee+number, 25 facts, last 5 summaries, auto-reschedule | None | ❌ Gap |
| Multi-tenant billing | Credits, ₹ plans, GST invoices | Razorpay, credits, plans, GST invoices | ✅ Parity |
| CI / durability | 99.9% SLA claim; mature ops | No CI; fire-and-forget backend writes can silently lose transcript/billing data | ❌ Gap |
| Telemetry rigor | Published averages only | Per-turn true E2E + p95 targets | ✅ Echo-Sarathi ahead |

---

## 4. Adaptation roadmap for EcoSarati

Ordered by ROI. Items 1–4 are "borrow the idea, we already have the engine"; 5–8 are genuine net-new.

**Phase 1 — make the existing engine production-safe (weeks 1–2)**
1. **Add CI** (`GitHub Actions`): run all three test suites + migration check + frontend build on every PR. 600+ tests exist but prove nothing without CI.
2. **Durabilize backend writes:** replace fire-and-forget `backend_client.py` posts with a local spool + bounded retry + drop counters. Silent transcript/billing loss is the single biggest reliability gap vs Outpero.
3. **Fix docs truth:** reconcile README / PROJECT_MASTER / CLAUDE with shipped telephony, Vobiz (not Plivo), no Redis, Telugu live. Delete dormant `twilio_protocol.py`. (Borrow the sibling audits as the checklist.)
4. **Keep `ALLOW_ANY_OUTBOUND_NUMBER=False`;** add DLT registration + KYC flow, account DNC list enforced at import/arrival/dial, consent attestation, "this call is being recorded" notice, and hard TRAI calling-hour enforcement.

**Phase 2 — close the voice-experience gaps (weeks 3–5)**
5. **One voice across a Tenglish switch.** Today Indic uses Bulbul and English uses Cartesia; a mid-sentence switch may change speaker identity. Two options: (a) use a single multilingual-voice TTS (Cartesia Multilingual Voices / Sarvam Bulbul v4 with a shared cloned voice) for both languages of one agent, or (b) keep two providers but **clone one voice into both** and pin `voice_id` per agent. Add an E2E test: Telugu utterance with an embedded English token must produce one stable voice.
6. **Caller memory** (Outpero's highest-differentiation "small thing"): per `agent_id + phone`, store name, call count, last outcome/time, ≤25 captured facts, last 5 summaries; inject a "returning caller note" into the version prompt; opt-in + deletable. We already have `ExtractedField` + `ConsentRecord`, so this is mostly a read path + prompt injection.
7. **Voicemail detection + outcome classification.** Add an outcome enum (`qualified, interested, callback, not-interested, missed, no_answer, busy, voicemail, call_failed`) and sentiment to call finalization; use the existing end-of-call check after each agent turn. Voicemail detection is essential for campaign economics.
8. **Knowledge-base retrieval.** Reuse the published Outpero pattern: ≤10k chars inlined into the system prompt; above that chunk into ~700-char passages and search mid-call as a tool. Our immutable `AgentVersion.company_context` is the natural home; add a `knowledge_chunks` table + retrieval tool.

**Phase 3 — productize the control plane (weeks 6–10)**
9. **"Describe your employee" generator.** Outpero's onboarding is a moat: plain-language or voice-note brief → name, role, opening line, multi-step flow, capture fields, action toggles, language+voice. Build this as an LLM call over our existing `AgentVersion` schema (`system_prompt`, `question_flow`, `extraction_schema`, `disclosure_script`, `escalation_rules`, `voice_settings`) with a review-before-publish step. We already have version immutability — this turns it into a real UX.
10. **Actions surface:** calendar booking, spreadsheet read/write, custom API with `{{variables}}` (we already have bracket-token substitution), WhatsApp via tenant account, and **human handoff/warm transfer** (currently only `escalation_rules` flag/end). Each opt-in per agent version.
11. **Customer webhooks + HMAC.** Up to N per agent, triggers every/completed/voicemail, HMAC-SHA256 over `timestamp + "." + raw_body`, signed 24 h recording URL. Payload: `event, call_id, agent, direction, from, to, status, hangup_reason, duration_s, started_at, ended_at, recording_url, pre_call, transcript, outcome, summary, captured`.
12. **Recording + retention job:** wire provider recording URL into `calls.recording_url`, 90-day retention, signed download links.
13. **Replace DB-polling dialer with a real queue** (Redis/RabbitMQ/Celery-style worker pool), horizontal worker autoscale, per-org rate limits in UI, and load/soak tests for concurrent media bridges. Decompose `pipeline.py` (3.4k) and `playground.py` (3.5k) and unify the duplicate prompt renderers.

**Cheap wins borrowed from the recovered help center (add to Phase 3):**
- A **strictness dial (1–5)** mapped onto the system prompt's "adhere to written wording" instruction — one field, high perceived control.
- **Ambient background beds** (Office / Call Center / Quiet Room / Retail Store) with a volume slider mixed under the TTS stream — this is the literal "multiple audios" layer and costs little.
- **Two-speed publishing + 3-version rollback** on top of our immutable `AgentVersion` rows, plus a **Draft / In-training / Live / Paused** lifecycle and a three-part go-live gate (number + "taking calls" + published).
- **Employee Store** templates seeded from our `domain-configs/` presets (we already have 7, including Telugu).
- One live campaign per number with the second auto-queued, and a shared-line "loser waits and retries" rule.

**Explicitly do NOT copy from Outpero:** their per-minute pricing model, marketing-site animation, and the "channel rent" framing unless unit economics support it. Keep Echo-Sarathi's existing per-org concurrency + credit gating, which is already more flexible.

---

## 4a. The three questions you asked, answered directly

- **How does the fluency come?** Streaming at every stage boundary + short endpointing + fast LLM TTFT + TTS starting before the reply is finished. Outpero's published average is 0.8–1.3 s; Echo-Sarathi already measures true wall-clock E2E with median ≤900 ms / p95 ≤1.5 s targets — i.e. **our instrumentation is ahead of our marketing**.
- **How do multiple calls at a time work?** One call = one channel = one LiveKit room = one `AgentSession`/job. Outpero sells channels; Echo-Sarathi uses a DB-polling dialer with per-org cap 10 + CPS 1. Same shape, different commercial wrapper. Scale-out = more worker containers / LiveKit agent deployments.
- **How does Tenglish audio work, and how do they use multiple voices/agents?** One code-mix-aware ASR keeps Telugu + English in one stream; one prompt defines the mixed register; **one voice must carry both languages** (Outpero's "no pipeline swap"). "Multiple agents" is not multiple voices on one call — it's *multiple independent employees*, each with one voice, one job (instant/bulk/inbound), one script, one knowledge base, one set of action toggles. Echo-Sarathi already has the equivalent (`Agent` + immutable `AgentVersion` + `Campaign`) at the data layer; the missing pieces are the generator UX, caller memory, and same-voice code-switch guarantee.

---

## 5. Open questions & unknowns

- Outpero's internal service topology, model routing rules, queueing/telephony vendor, and exact endpointing/barge-in implementation are **not public**.
- ~~Help-center article bodies could not be recovered~~ — **resolved:** all 27 articles were recovered verbatim from the embedded `Docs-UqfVDoTB.js` chunk. Only the full `api.outpero.com` REST schema remains unenumerated.
- **Source conflicts to resolve before copying:** Premium price ₹6.8 (marketing) vs ₹7 (help center); DNC at import/arrival/dial (feature page) vs Bulk-only (help center); signup bonus 50 credits (marketing) vs 100 credits (help center); sandbox message cost ₹0.05 vs ₹0.20 across pages. Treat the help center as canonical for configuration semantics.
- Whether Outpero uses Cartesia's *managed agents* or its own orchestration is unknown; the "AI employee" abstraction is clearly their own product layer either way.

---

## Appendix A — Sources

- `https://outpero.com/blog/how-ai-voice-agents-work` (pipeline, latency table, VAD/endpointing/barge-in, post-call)
- `https://outpero.com/questions/how-does-an-ai-voice-agent-work` (loop, streaming, "Swara", per-agent action toggles)
- `https://outpero.com/ai-calling-agent` (four stages, Tenglish/Tanglish, barge-in, languages)
- `https://www.outpero.com/ai-voice-agents/language/telugu` (Tenglish, same voice, voices, neutral Telugu)
- `https://outpero.com/ai-voice-agents` / `/ai-voice-agents/features` (instant leads, bulk campaigns, channels, feature list)
- `https://outpero.com/ai-voice-agents/features/lead-intake-api-and-integrations` (API shape, headers, limits, dedupe)
- `https://outpero.com/voice-ai-platform` / `/ai-call-center` (platform layers, channels, DLT/TRAI, cost model)
- `https://www.outpero.com/ai-voice-agents/language/tenglish` (code-switch grammar, same voice, default behavior)
- `https://outpero.com/glossary/tts` / `/latency` / `/endpointing` / `/barge-in` (voice consistency, per-stage budget, turn-taking)
- `https://outpero.com/voices` (600+ voices, named voices, Enhance, acknowledgements)
- `https://outpero.com/no-code-ai-voice-agent` (brief structure, hard rules, capture fields, action enablement)
- `https://outpero.com/questions/what-does-the-llm-do-in-an-ai-voice-agent` (**explicit "we do not publish model names"**, LLM inputs per turn)
- `https://outpero.com/ai-voice-agents/features/call-retries-and-calling-windows` (calling policy defaults, retry ladder, clamps)
- `https://outpero.com/ai-voice-agents/features/caller-memory` (memory scope, fields, injection)
- `https://outpero.com/ai-voice-agents/features/knowledge-base-training` (limits, inline vs chunked retrieval)
- `https://outpero.com/ai-voice-agents/features/custom-api-actions` / `/google-calendar-booking` / `/post-call-webhooks` / `/call-data-capture-and-summaries` / `/do-not-call-and-consent-controls` (action + data model details)
- `https://docs.outpero.com/api` (help-center index: employee lifecycle, call script & flow, voice & sound, actions, post-call webhooks, publishing, versions, reliability, "how it all fits together")
- Sarvam: `https://www.sarvam.ai/apis/speech-to-text`, `https://docs.sarvam.ai/voice-agents/build/models`, `https://www.sarvam.ai/blogs/introducing-saaras-v4`, `https://www.sarvam.ai/apis/speech-to-text/telugu`
- Cartesia: `https://docs.cartesia.ai/build-with-cartesia/tts-models/latest`, `https://www.cartesia.ai/sonic`, `https://www.cartesia.ai/blog/multilingual-voices`, `https://www.cartesia.ai/blog/sonic-3.6`
- LiveKit: `https://livekit.com/blog/sequential-pipeline-architecture-voice-agents`, `https://docs.livekit.io/agents/models/pipelines/`, `https://docs.livekit.io/agents/integrations/deepgram`, `https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection`
- **Help center (recovered from shipped JS, hash routes `https://docs.outpero.com/#<slug>`):** `overview, first-employee, going-live, lifecycle, script, voice, actions, postcall, publishing, versions, instant, bulk, inbound, calling-rules, calllog, leads, conversations, performance, numbers, training, credits, topup, statements, notifications, settings, reliability, howitfits`. All 27 articles are in `Docs-UqfVDoTB.js`; "Last updated 18 October 2026".

## Appendix B — REA evidence

- Parent analysis: `ev_5acd23e23b8a84cd93a6a8747316adb5ee411a6a0732a2202854b1e0058568be`
- Summary view: `ev_e91fbed7f1a559a634eeb77f631b5f6d1f56e07a3775f14d2070df1da6b693e8`
- Artifact: 64 JS chunks under `C:\Users\home\AppData\Local\Temp\opencode\outpero-re\`
- Help corpus: `Docs-UqfVDoTB.js` line 10 col 24289 — embedded article object `Q={overview:{…}}`, rendered as `Q[slug].render()`; API docs chunk `DevDocs-BFSVmQ1c.js` (164 KB).
- Operational API base: `api-QvhbpKm6.js` line 11 col 60344 — `var vs=\`https://api.outpero.com\``; public path bypass `bs=[\`/public/\`]` at col 60416; `fetch(\`${vs}${t}\`)` wrapper at col 62190.
- Observed employee endpoints (shipped JS): `/employees/{id}/teach`, `/knowledge`, `/custom-apis`, `/actions`, `/sandbox/chat`, `/accounts/me/caller-memory`; documented public endpoints: `POST /lead-intake/<id>`, `GET /v1/inbound-calls`.
- Scratch extraction with full article text: `docs_extracted_full.txt` in the same temp folder.
