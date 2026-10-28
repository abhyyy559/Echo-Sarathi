# Competitor landscape — AI voice calling in India

Researched 2026-10-28. Prices are as published on each vendor's site or a
reputable review site; anything quote-only is marked **not public**.

Our reference point: **₹3.00/min all-in** at a blended cost of **₹2.30/min**
(`docs/BUSINESS_MODEL.md`), plans Starter ₹2,990 / Growth ₹8,700 / Scale
₹28,000, concurrency 2 / 5 / 15.

---

## 1. Who actually competes with us

There are two different markets that both look like "competitors":

| Group | Examples | What they sell | Why they matter to us |
|---|---|---|---|
| **Legacy Indian CPaaS** | Exotel, Ozonetel, Knowlarity, Acefone | Telephony + IVR + contact centre, AI bolted on | They own the enterprise budget and the phone numbers |
| **AI-native voice platforms** | Bolna, Vapi, Retell, Bland, ElevenLabs | Agent runtime + model orchestration, you bring the use case | They set the per-minute price anchor |

Nobody in either group sells **the job a college actually needs done**:
import the roster, call every parent, verify who is speaking, extract the
reason, escalate the unanswered ones, and hand back a report. That is our wedge.

## 2. Price per minute (the headline)

| Vendor | Published rate | ≈ ₹/min | Included | Notes |
|---|---|---:|---|---|
| **Us** | ₹3.00 | **3.00** | STT + LLM + TTS + telephony + platform | 18% GST included |
| Bolna | $0.06 | 5.52 | bundled models, telephony + fee added | volume tiers to ~₹4.15; Pilot ~₹4 |
| Vapi | $0.05 | 4.40 | platform only | STT/LLM/TTS/telephony billed at cost |
| Retell | $0.07–0.31 | 6.16–27.3 | range depends on components | 20 concurrent on PAYG |
| Bland | $0.12–0.14 | 10.6–12.3 | LLM + STT + TTS | "no token charges" |
| Acefone (AI estimates) | — | 0.80–3.00 | varies | their own blog's India range |
| Knowlarity | 70p / 30 s | 1.40 | **telephony only** | AI/IVR is separate |
| Exotel / Ozonetel | **not public** | — | quote only | enterprise sales-led |

USD converted at ~₹88. The important line: the only Indian AI-native vendor with
public pricing sells at **₹5.52**, and the cheapest global platform fee alone is
**₹4.40 before a single model token**. ₹3.00 all-in is a real, defensible
undercut — roughly **46% below Bolna**.

## 3. Where the whole market is weak

These are the gaps we build into, in order of how much they matter:

1. **Price opacity.** Exotel, Ozonetel and Acefone publish no AI per-minute
   price. A college principal cannot find out what a campaign costs without a
   sales call. We publish ₹3/min and show the wallet balance live.
2. **No vertical workflow.** Every competitor ships an *agent builder* and
   leaves the campaign design to the customer. Nobody ships "attendance calling
   for a college" with roster import, parent verification and a per-student
   outcome report.
3. **Compliance is the customer's problem.** DLT registration, consent capture,
   calling hours and opt-out are add-ons or documentation. We enforce them in
   the product and refuse to dial outside them.
4. **Seat-based pricing.** Acefone charges per user ($19.99–29.99) and bundles
   minutes to seats. A 2-person college office pays for seats it never uses.
   We charge for minutes, not people.
5. **Credits in USD.** Bolna, Vapi, Retell and Bland bill in dollars on a card.
   An Indian institution wants an INR invoice with GST and a PO. We do that.
6. **Structured extraction is missing.** Competitors give transcripts and
   sentiment. A college needs "reason absent = fever, parent informed = yes,
   call back after 6pm" as columns in a spreadsheet.
7. **Vernacular quality without a voice identity.** Bolna advertises 10+ Indian
   languages. Almost nobody lets a tenant keep its own agent name, voice and
   greeting per campus. We do (see `project-tenant-branding`).
8. **Concurrency is invisible.** Plans quote numbers, the product never shows
   how many lines are busy. Our dashboard shows live in-flight calls against the
   plan cap.

## 4. Where they are stronger (be honest)

- **Enterprise trust:** Exotel and Ozonetel have 2,000+ deployments, SOC-style
  security pages, and 25B+ interactions/year credibility. We have neither yet.
- **Inbound contact centre:** queues, agent desktop, supervisor barge-in, WFM,
  CRM connectors. We only do outbound campaigns and a test surface.
- **Global telephony:** local numbers in dozens of countries. We are India-only
  via Vobiz.
- **Studio UX:** Bolna's Agent Studio and Vapi's dashboard are more mature than
  our builder. Ours is functional, not polished.
- **Support depth:** 24×7 and dedicated account managers at enterprise tiers.

## 5. Our positioning, in one line

> **The attendance-and-outreach agent for Indian institutions: ₹3 a minute,
> all-in, with the roster in and the report out — not another agent builder.**

Three proof points to lead with: **₹3/min** (vs ₹5.52), **launch in minutes**
(vs a sales call), **structured report** (vs a transcript).

## 6. Pricing ladder to defend the wedge

| Move | Why |
|---|---|
| Keep ₹3.00 list, ₹2.90/₹2.80 at volume | Undercuts Bolna by ~46% while holding ~23% gross margin |
| Free 10 trial minutes, no card | Competitors give $5 credits that expire in USD |
| INR invoices + GST, PO accepted | Removes the #1 blocker for institutions |
| Charge per minute, never per seat | Direct contrast to Acefone |
| Do **not** go below ₹2.30 cost to win a logo | A ₹1.99 plan loses money on every call |

If we need a sharper number for education pilots, give **free minutes**, not a
lower rate. The cost floor is ₹2.30; the TTS line (₹1.05) is the only lever big
enough to move it, and that is a provider negotiation, not a pricing decision.

## 7. What to build next, ranked by gap value

1. **Vertical campaign templates** (college attendance, fee reminder, admission
   follow-up) with pre-written prompts and extraction schemas.
2. **Outcome report export** — one row per student, columns from extraction, PDF
   for the principal.
3. **Live campaign console** — in-flight calls, concurrency vs plan, per-call
   outcome as it lands.
4. **Public pricing page parity** — every number a salesperson would quote is on
   the site (we already do this; keep it).
5. **Inbound** — same agent answers callbacks. This is the biggest functional
   gap to Exotel/Ozonetel and the natural next vertical feature.

## 8. Files

| File | Vendor | Type |
|---|---|---|
| [exotel.md](exotel.md) | Exotel | Enterprise CPaaS + AI agents |
| [ozonetel.md](ozonetel.md) | Ozonetel | Enterprise cloud contact centre |
| [knowlarity.md](knowlarity.md) | Knowlarity | CPaaS (Gupshup) |
| [acefone.md](acefone.md) | Acefone | SMB cloud telephony + AI |
| [bolna.md](bolna.md) | Bolna | AI-native, Indian languages — **closest rival** |
| [vapi.md](vapi.md) | Vapi | Global developer platform |
| [retell.md](retell.md) | Retell AI | Global pay-as-you-go |
| [bland.md](bland.md) | Bland AI | Global self-serve |
| [elevenlabs-agents.md](elevenlabs-agents.md) | ElevenLabs | Voice-first agent platform |

Watchlist (not profiled yet): Sarv, Fibr.ai, CallHippo, MyOperator, TeleCMI,
PolyAI, Parloa.

## Sources

- Exotel pricing hub and AI voice agent product page (visited 2026-10-28)
- Bolna pricing page (visited 2026-10-28)
- Vapi, Retell, Bland, ElevenLabs pricing pages (fetched 2026-10-28)
- Knowlarity pricing page (search extract), Acefone pricing via Capterra
- Ozonetel: no public pricing; quote-only
