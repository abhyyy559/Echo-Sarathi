# Vapi — competitor profile

Researched 2026-10-28 from vapi.ai pricing and product pages. USD at ~₹88.

**One-liner:** "Voice AI agents for developers."
**Type:** Global AI-native voice agent platform (BYO models and telephony).
**Threat level:** **Medium.** The price anchor for developers worldwide, but
India-hosted, GST-invoiced, roster-driven work is not their motion.

---

## 1. What they sell

An API-first platform for building voice agents: you define an assistant
(prompt, model, voice, tools), attach a phone number from a provider, and Vapi
orchestrates the realtime loop. Models, STT, TTS and telephony are **passed
through at cost** on top of a platform fee. Aimed at engineering teams building
voice into their own product.

## 2. Feature set

| Area | What they ship |
|---|---|
| Assistants | Prompt, first message, model, voice, tools, structured outputs |
| Model choice | Large catalogue of LLM/STT/TTS providers, bring your own keys |
| Telephony | Numbers via partner providers, inbound + outbound |
| Tooling | Function calls, webhooks, server-side tools, transfers |
| Multi-agent | Composable flows across assistants/squads |
| Observability | Call logs, transcripts, latency and cost breakdowns |
| API/SDK | Full REST + SDK surface; almost everything configurable in code |
| Dashboard | Test calls and logs in-browser |

## 3. User flow

1. Sign up free (no card) → dashboard.
2. Create an assistant → choose model, voice, transcriber, write prompt.
3. Attach tools/webhooks; test in browser or over a number.
4. Buy a number (provider passthrough) and point it at the assistant.
5. Build campaigns **in your own backend** via the API — Vapi does not ship a
   roster-driven campaign product.
6. Watch logs and cost breakdowns per call.

The buyer is a developer who wants the runtime, not a finished campaign.

## 4. Pricing

| Plan | Price | Included |
|---|---|---|
| Free / build | **$0** | platform access, usage at cost |
| Core | **$29 / month** | **4 concurrency**, usage at cost |
| Pro / scale | **$999+ / month** | **30 concurrency**, usage at cost |
| Platform fee | **$0.05 / min** | on top of provider usage |
| Models + telephony | passed through at cost | Groq/OpenAI/Deepgram/ElevenLabs etc. |

₹ terms: the **$0.05 platform fee alone is ₹4.40/min** before a single token of
LLM, second of STT or second of telephony. A realistic all-in stack on Vapi lands
well above that. **Our ₹3.00 includes every line.**

## 5. The words they use

Headlines: *"Voice AI agents for developers"*, *"build voice agents"*,
platform fee, usage-based, bring your own provider, latency, concurrency,
assistants, squads.

Tone: developer infrastructure. Docs-forward, API-first, "you build the product."
No vertical language, no Indian compliance story, no INR invoicing.

## 6. Where they are stronger

- **Provider breadth** — any model, voice or transcriber, swapped per assistant.
- **Developer ergonomics** — API and SDK surface is the product.
- **Cost transparency at the component level** — per-call breakdown of LLM,
  STT, TTS and telephony spend.
- **Global telephony** and a mature testing dashboard.
- **Ecosystem** — examples, community, third-party integrations.

## 7. Gaps we attack

1. **They sell a runtime; we sell the campaign.** No roster import, no parent
   verification, no escalation list, no report. The customer must build all of it
   on the API.
2. **Cost engineering is on the customer.** Passing models through at cost means
   the buyer has to know that Groq's shared 8,000-TPM bucket allows only a few
   turns a minute — a real trap we have already solved and priced around.
3. **USD billing, no GST invoice, no PO.** Institutions cannot buy it easily.
4. **India telephony is DIY** — bring your own number and provider; we handle it.
5. **No compliance posture** for Indian DLT/calling hours/consent built in.
6. **Concurrency is a plan limit**, not a visible gauge tied to a campaign.
7. **Engineering cost.** The cheapest Vapi deployment is one with a developer
   attached; our buyer has a browser and a roster.

## 8. Demo moves / how we win side-by-side

- Do the **all-in math**: $0.05 platform + LLM + STT + TTS + telephony vs ₹3.00
  all-in. Show a 60-second and a 25-second example.
- Ask "who writes the tool-calling code and the extraction schema?" — if the
  answer is "our developer", the campaign ships next quarter.
- Show **sign-up → first call** in one sitting, with no API key.
- Concede provider breadth and API depth; never argue that our runtime is more
  flexible.
- Use Vapi as the **price anchor** in the deck: "even the developer platform's
  fee alone is ₹4.40 before models."
