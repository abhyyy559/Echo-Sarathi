# Echo Sarathi — SaaS Business Model (v1)

Status: **decided 2026-10-28**. This document is the source of truth for plans,
pricing, entitlements and billing behaviour. Code constants live in
`backend/app/services/plans.py`; change both together.

## 1. What we sell

Echo Sarathi is a multi-tenant AI voice-calling platform. A customer creates an
agent (prompt + question flow + extraction schema), imports contacts, launches a
campaign, and gets transcripts, structured outcomes and call analytics.

The product is **domain-independent**. The first proven use case is college
absentee follow-up; vertical presets make coaching centres, clinics, real-estate
teams and collections teams a configuration change, not new code.

**One-line positioning:** *Outbound calling that sounds human, reports like a
CRM, and bills by the connected minute — built for Indian phone networks.*

## 2. Who buys

Two motions, one product:

| Motion | Buyer | How they buy | What they need |
|---|---|---|---|
| Self-serve | SMB, coaching centre, clinic, small sales team | Card/UPI on the pricing page, starts in minutes | Instant signup, clear per-minute price, wallet top-ups, GST invoice |
| Sales-led | College/university, hospital group, enterprise | Demo → pilot → annual contract/PO | GST invoice, security/DPDP answers, onboarding help, SLA, custom limits |

The **institution motion is the wedge** because the absentee use case is already
proven and the buyer values outcome reporting. Self-serve keeps CAC low and
feeds the sales pipeline.

## 3. Revenue model — hybrid

1. **Monthly plan** with included connected minutes and higher limits.
2. **Prepaid wallet** for overage and for customers who do not want a plan.
3. **Enterprise contract** (annual, invoiced, custom limits).

Included minutes are consumed first. Once exhausted, calls debit the wallet at
the plan's overage rate. A plan with an empty wallet stops dialing when both the
included minutes and the wallet are exhausted. Top-up credits never expire;
unused included minutes do not roll over.

### Plans (v1)

| Plan | Price / month | Included min | Overage / min | Users | Agents | Concurrent calls | Retention | Support |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Free | ₹0 | 0 (10 trial min once) | ₹3.00 | 1 | 3 | 2 | 30 days | Community |
| Starter | ₹2,990 | 1,000 | ₹3.00 | 3 | 3 | 2 | 90 days | Email |
| Growth | ₹8,700 | 3,000 | ₹2.90 | 10 | 10 | 5 | 180 days | Priority email |
| Scale | ₹28,000 | 10,000 | ₹2.80 | 30 | 30 | 15 | 365 days | Priority + onboarding |
| Enterprise | Custom (from ₹75,000) | 30,000+ | Contract | Custom | Custom | Custom | Custom | SLA + DPO support |

All displayed prices are **inclusive of 18% GST**. Extra minutes are sold as
one-time top-up packs: 60 min ₹180, 300 min ₹870, 1,000 min ₹2,800. Packs credit
wallet value at the ₹3.00 list rate, so every pack delivers at least its
advertised minutes at the plan's overage rate.

### Unit economics

Our blended cost is **₹2.30 per connected minute**:

| Component | ₹ / min |
|---|---:|
| Vobiz telephony | 0.45 |
| Sarvam STT | 0.50 |
| Sarvam TTS | 1.05 |
| Groq LLM | 0.12 |
| LiveKit/Render/Neon platform | 0.18 |

Gross margin at full included usage:

| Plan | Revenue | Cost | Margin | Margin / min |
|---|---:|---:|---:|---:|
| Starter | ₹2,990 | ₹2,300 | ₹690 (23%) | ₹0.69 |
| Growth | ₹8,700 | ₹6,900 | ₹1,800 (21%) | ₹0.60 |
| Scale | ₹28,000 | ₹23,000 | ₹5,000 (18%) | ₹0.50 |

Guardrails:

- Never price a connected minute below **₹2.80** without a negotiated volume
  commitment or a cheaper TTS mix.
- Unanswered, busy and failed legs are free to the customer and near-zero cost
  to us (telephony only).
- Playground/browser sessions are free; they must never consume plan minutes.
- The dialer refuses to start a leg with less than ~12 seconds of payable
  capacity, so a zero-balance call cannot burn carrier money.

## 4. Trial and conversion

- 10 free minutes on signup, no card. Enough for a real pilot, not a demo.
- Free plan limits keep trial orgs small: 1 user, 3 agents, 2 concurrent calls.
- Conversion prompts: low-balance banner, included-minutes meter, plan-expiry
  reminders at 7 and 1 day, one-click renewal, upgrade when a limit is hit.
- Activation event: first **connected phone call** (not signup). Track it.

## 5. Billing mechanics

- Metering is per connected second, rounded up to the whole second.
- Included minutes are counted from answered phone calls in the plan period.
- Overage is debited from the wallet; the ledger is append-only and idempotent
  per call.
- Every successful payment produces a **GST invoice** with a sequential number,
  taxable value and 18% GST breakdown. Prices are GST-inclusive.
- Invoice and receipt emails go to the org billing email (fallback: owner).
- **Renewal in v1 is manual**: the customer buys the next plan period; we send
  reminders. Auto-renew via Razorpay mandates/UPI Autopay is the next milestone,
  not part of this release.
- Cancellation stops renewal at period end; unused included minutes are not
  refunded.
- Wallet credits are refundable within 7 days of purchase, unused, minus
  gateway fees; plan fees are non-refundable after activation. GST credit note
  issued for refunds.

## 6. Entitlements enforced in product

- Users per org (seat cap on invite acceptance).
- Agents per org (cap on agent creation).
- Concurrent phone calls per org (dialer cap; global cap still applies).
- Phone-number/DID limits are listed in plans but provisioning is still
  operator-managed in v1.
- Data retention is recorded per plan; the retention job remains global until
  per-org retention is implemented.

When a limit is hit the API returns **402 Payment Required** with a message
that names the limit and the next plan. The UI links to Billing.

## 7. Go-to-market

### Self-serve funnel
Landing page → pricing → signup (10 free minutes) → create agent from a preset
→ playground test → test call → campaign → plan/top-up.

### Institution funnel
Demo call → pilot proposal (Starter or 500-minute pilot) → security/DPDP
questionnaire → annual Growth/Scale contract with PO and GST invoice → onboarding
checklist → quarterly outcome review.

### 90-day targets (directional)

| Metric | Target |
|---|---|
| Signup → first connected call | ≥ 40% |
| Trial → paid (self-serve) | ≥ 12% |
| Design partners converted | 3 institutions |
| Paid orgs | 10 |
| Gross margin | ≥ 20% |
| Logo churn (monthly) | < 5% |

Track: MRR, plan mix, expansion (top-ups), minutes per org, revenue per minute,
invoice DSO, activation, churn, support load.

## 8. Compliance and legal checklist (India)

Required before charging the first external customer:

- [ ] Terms of Service, Privacy Policy, Refund & Cancellation Policy, DPA.
- [ ] DPDP Act 2023: notice + consent for called parties, purpose limitation,
      retention schedule, deletion on request, breach notification, grievance
      officer, sub-processor list.
- [ ] TRAI/UCC: consent basis per contact, calling hours 9am–9pm, DND handling,
      AI disclosure at the start of every call, recording consent where recorded.
- [ ] DLT registration only if we send SMS; voice-only campaigns still need an
      authorised telemarketer/enterprise registration with the carrier.
- [ ] GST registration, SAC code confirmed with a CA, sequential invoices,
      credit notes for refunds.
- [ ] Razorpay KYC completed; webhook secret configured; no card data stored.
- [ ] Data localisation: API/database in India (Mumbai/Singapore region review).
- [ ] Fair-use policy: no spam, no regulated advice, no impersonation, opt-out
      honoured immediately.

## 9. Non-goals for v1

- Auto-recurring mandates (UPI Autopay/card mandate) — manual renewal only.
- Proration on mid-cycle upgrades — a new plan starts a new period.
- Multi-currency and international GST/VAT.
- Reseller/partner billing and revenue share.
- Per-org data-retention automation (limits are advertised, job is global).
