# Retell AI — competitor profile

Researched 2026-10-28 from retellai.com pricing. USD at ~₹88.

**One-liner:** "True pay as you go" voice agents.
**Type:** Global AI-native voice agent platform.
**Threat level:** **Medium-low in India.** Strong product, but the published rate
is 2–9× ours and the sale is in dollars.

---

## 1. What they sell

Hosted conversational voice agents over telephony. You define an agent (prompt,
voice, model, tools), attach a number, and run inbound or outbound calls. Retell
emphasises low latency, natural turn-taking, and a clean developer API with a
usable dashboard — closer to "Vapi with a nicer default" than a campaign product.

## 2. Feature set

| Area | What they ship |
|---|---|
| Agents | Prompt, voice, language, tools, post-call analysis |
| Telephony | Numbers in multiple countries, inbound + outbound |
| Realtime | Interruption handling, backchannels, low-latency loop |
| Analysis | **Post-call data extraction** into structured fields |
| Tooling | Function calls, webhooks, transfers, knowledge base |
| Campaigns | Batch/outbound calling with concurrency control |
| Observability | Transcripts, recordings, latency and cost per call |
| Pricing model | Component-based, fully usage-metered |

Notably, Retell does advertise **post-call extraction** — the closest any global
platform gets to the structured report we sell. They still leave the schema,
the roster and the escalation workflow to the customer.

## 3. User flow

1. Sign up → dashboard.
2. Create agent → pick voice/model, write prompt, set post-call analysis fields.
3. Test in browser.
4. Buy a number and point it at the agent.
5. Import a list and run a batch campaign, setting concurrency.
6. Read transcripts and extracted fields per call.

## 4. Pricing

| Item | Published | ≈ ₹/min |
|---|---|---|
| Usage range | **$0.07 – $0.31 / min** | **6.16 – 27.3** |
| Low end | base agent + standard components | 6.16 |
| High end | premium voice / telephony / add-ons | 27.3 |
| Concurrency (PAYG) | **20 simultaneous calls** | — |
| Billing | prepaid USD, card only | — |

The range is wide because Retell prices **components**: model, transcriber,
voice and telephony each contribute. That is honest, and it is also the
problem — the buyer cannot know the per-minute number until they have chosen
every component. At the *low* end it is still **more than double ₹3.00**.

## 5. The words they use

Headlines: *"True pay as you go"*, *"conversational voice AI"*, *"human-like
voice agents"*, latency, interruption handling, post-call analysis.

Keyword vocabulary: agents, telephony, numbers, batch calls, concurrency,
transcripts, extraction, webhooks, transfers, knowledge base, LLM, TTS, STT,
pay-as-you-go.

Tone: honest infrastructure pricing, developer-plus-ops audience. Global by
default; nothing India-specific (no DLT, no GST, no Indic language story).

## 6. Where they are stronger

- **Product maturity** in realtime turn-taking — interruptions and backchannels
  are a first-class feature.
- **Post-call structured extraction** already exists (we still have to make ours
  the reason to switch).
- **Global numbers** and multi-country telephony.
- **20 concurrent** on PAYG, more than our Growth plan.
- **Cost transparency per component** — a genuinely good engineering story.

## 7. Gaps we attack

1. **Price.** ₹6.16 at the *floor*; typical configured rates are far higher.
   ₹3.00 all-in is a different category.
2. **Extraction without a workflow.** They extract fields; they do not import a
   roster, verify the parent, decide who to retry, or produce a per-student
   report a principal can sign.
3. **India compliance and billing are absent** — USD card, no GST, no DLT help,
   no calling-hours policy.
4. **Component pricing is a budgeting trap** for a non-technical buyer.
5. **No vertical templates** for Indian institutions.
6. **Concurrency is a setting**, not a live gauge tied to a plan.

## 8. Demo moves / how we win side-by-side

- Compare **all-in** numbers, not component rates. Pick one realistic
  configuration (Indian number, Indic voice, fast LLM) and price it on both.
- Show the **report**, and explicitly acknowledge they can extract fields — then
  show that our report also carries retries, escalation and a PDF for the
  principal.
- Show **INR + GST invoice** and a PO path.
- Do not argue realtime polish; if the buyer is a developer, they may legitimately
  prefer Retell. Sell the institution, not the engineer.
