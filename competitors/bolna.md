# Bolna — competitor profile

Researched 2026-10-28 from bolna.ai pricing and product pages. USD at ~₹88.

**One-liner:** AI voice agents for Indian businesses, sold per minute.
**Type:** AI-native voice agent platform, India-first.
**Threat level:** **High — our closest direct rival.** Same country, same
per-minute model, same vernacular promise, published pricing we can compare to.

---

## 1. What they sell

Hosted voice agents that run over telephony. The customer describes an agent,
picks voice/STT/LLM, uploads a contact list, and Bolna dials. Models are bundled
into the per-minute rate; BYOK is available if the customer wants to plug in
their own provider keys. Their own headline is **"Only pay for what you use."**

They claim **1,000+ companies** and **10+ Indic languages including Telugu** —
the exact language pair we run.

## 2. Feature set

| Area | What they ship |
|---|---|
| Agent building | **Agent Studio** — prompt, voice, model, tools, test in-browser |
| Telephony | Outbound campaigns, inbound agents, Indian numbers |
| Languages | 10+ Indian languages + English, code-mixing |
| Voices | Catalogue of TTS voices, cloning on higher tiers |
| Models | Bundled defaults or BYOK (OpenAI/Anthropic/etc.) |
| Campaigns | Contact upload, scheduling, retries, concurrency control |
| Concurrency | Up to **25 simultaneous calls** on published tiers |
| Integrations | Webhooks, API, CRM connectors |
| Observability | Call logs, transcripts, recordings |
| Billing | Prepaid USD credits, **30-second billing pulses** |

## 3. User flow (as a new customer sees it)

1. Sign up on the site, no sales call. **$5 free credits** land automatically.
2. Create an agent → pick language, voice, write system prompt, attach tools.
3. Test in the browser (or on a Twilio/Vobiz-style number).
4. Buy credits — packages from **$10 up to $5,000**.
5. Upload a CSV, set a schedule, launch the campaign.
6. Read transcripts and outcomes; export if needed.

The flow is self-serve and fast, which is the bar we have to meet.

## 4. Pricing

| Item | Published | ≈ ₹/min |
|---|---|---|
| Standard PAYG | **$0.06/min** | **5.52** |
| Volume tier (high spend) | down to **$0.0451/min** | 3.97 |
| Pilot — $500 pack | 12,000 min (~$0.042/min) | ~3.70 |
| Pilot — $300 pack | 6,500 min (~$0.046/min) | ~4.05 |
| Free trial | $5 credits | ~90 min |
| BYOK | model cost removed, platform + telephony fee still applies | — |

Notes that matter commercially:
- Billed in **USD on a card**, prepaid credits. No INR invoice, no GST, no PO.
- **30-second pulses** — a 20-second answered call bills a full 30 seconds.
- Telephony and platform fee are **added on top** of the published model rate.
- Max **25 concurrent** calls.

## 5. The words they use

Headline/hooks: *"Only pay for what you use"*, *"AI voice agents for your
business"*, *"Agent Studio"*, *"Go live in minutes"*.

Keyword vocabulary on the site: voice AI agents, outbound calling, inbound
calling, Indic languages, vernacular, code-mixing, bring your own key, credits,
concurrency, campaigns, call analytics, webhooks, latency.

Tone: developer-friendly, price-forward, "build and ship" energy. Almost no
vertical language — they sell a **capability**, not a job to be done.

## 6. Where they are stronger

- **Published, comparable price** — buyers can budget without a sales call.
- **Self-serve onboarding with free credits** — friction is near zero.
- **Agent Studio** is a more complete prompt→voice→test loop than our builder.
- **25 concurrent** is above our Growth cap of 5 (though above our Scale cap of
  15 as well — see gap 2).
- **BYOK** appeals to technical buyers who already have Groq/OpenAI contracts.
- **Language breadth** — they advertise 10+ Indic languages; we do Telugu and
  English well rather than claiming many.

## 7. Gaps we attack

1. **₹5.52 vs our ₹3.00.** Same job, 46% cheaper, GST included, billed in INR.
2. **They sell a builder, we sell a finished campaign.** A college principal
   still has to write the prompt, design the extraction, and read transcripts.
   We ship the roster import, the parent-verification script and the report.
3. **USD credits are a procurement dead end.** Indian institutions need a GST
   invoice and often a PO. We do both.
4. **30-second pulses.** Our per-second metering is cheaper on short calls —
   which is exactly the shape of an attendance call.
5. **No structured outcome.** They return a transcript; we return columns
   (reason absent, parent informed, callback time) plus a PDF for the principal.
6. **Concurrency is a number, not a control.** We show live in-flight calls
   against the plan cap in the dashboard.
7. **No tenant voice identity per campus.** Our per-tenant agent name, voice and
   greeting is the branding hook (`project-tenant-branding`).

## 8. Demo moves / how we win side-by-side

- Run the **same 20-contact list** on both, quote the invoice in rupees, show the
  cost difference for a 60-second call and a 25-second call.
- Show **the report** next to **the transcript**. Let the buyer try to build the
  report from Bolna's export in under five minutes.
- Ask for a **PO and a GST invoice** — the sales cycle stops there for them.
- Show the **concurrency gauge** while the campaign runs.
- Do not compete on language count or studio polish. Compete on the finished
  job and the invoice.
