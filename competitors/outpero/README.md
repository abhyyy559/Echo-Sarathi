# Outpero — direct India-first competitor

Public-site review: 2026-10-28. Primary sources listed below. Evidence labels: **Observed** = rendered public content or markup; **Advertised** = vendor claim, not independently tested; **Unknown** = requires account access, a commercial quote, or live validation.

## Scope and limitations

Opened the homepage, pricing, bulk-campaign product page, public documentation, and app sign-in page with Browser Use. Text/DOM reads succeeded. Screenshots and pointer clicks failed because the in-app browser had no attached viewport. No account created, phone number submitted, payment made, microphone activated, or live call placed. This is a public product/content audit, NOT a complete authenticated dashboard or visual/audio experience test.

## Positioning and messaging

- Homepage title: “AI telecalling software. India's most natural-sounding voice agents.”
- Primary concept: an **AI employee**, not a list of speech providers.
- Prompt: “What should your AI telecaller do?”
- Primary CTA: “Build my employee”; secondary entry: “Start free”.
- Campaign headline: “Hand over the list. Get back the interested ones.”
- Pricing headline: “Pay for talk time. Nothing else.”
- Action framing: “India's best voices. Now with hands.”
- Trust framing includes “5,000+ businesses” and startup-programme logos; these are self-reported, not verified customer counts or endorsements.

Keywords: AI telecalling software, AI employees, instant leads, bulk campaigns, inbound, natural-sounding, seven Indian languages, credits, channels, captured fields, caller memory. These are visible copy/SEO themes, not evidence of a particular search ranking.

## Public information architecture

- Product: instant leads, bulk campaigns, inbound, voices, pricing.
- Industries: BFSI, real estate, healthcare, education, automotive, e-commerce, plus an all-industries hub.
- Language-specific pages including Telugu, Tamil, Kannada, Malayalam, Hindi and Marathi.
- Resources: docs, blog, glossary, comparison pages.
- Company/trust: contact, agency services, terms, privacy, refund policy.
- Separate marketing, application and documentation origins.

This breadth makes the offer legible to both a small-business buyer and a technical evaluator. It does not prove every feature works as described.

## Advertised capabilities

| Area | Public evidence | What is not verified |
|---|---|---|
| Agent creation | Describe the job in text or voice; draft name, role, opening and call flow | Draft quality, editing speed, save behavior |
| Languages | Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi, English | Accent quality, switching, noisy calls |
| Modes | Instant new-lead calls, bulk lists, inbound | Operational reliability or real latency |
| Bulk import | CSV/paste, sample CSV, columns mapped to variables, recently-called suppression | Validation edge cases and duplicate handling |
| Scheduling | Calling hours, days, holidays, configured retry intervals, pause/edit/extend | Enforcement and timezone correctness |
| Outcomes | Captured fields, summaries, recordings, CSV export, webhook/CRM updates | Extraction accuracy or export completeness |
| Actions | WhatsApp, Calendar, CRM lookup, custom API, human transfer | Authentication, integration setup and failure recovery |
| Returning callers | Caller memory and incoming callbacks described in docs | Retention controls and cross-call correctness |
| Telephony | Digital KYC and dedicated numbers; channels add parallel calls | Activation time and number availability |
| Safety | DLT-registered numbers, consent checks, DND, spend floor, carrier-refusal pause | Legal compliance or effectiveness; no audit performed |

The homepage's industry audio samples explicitly say both sides are AI. We did not play or benchmark them. Do not mistake a sample for a customer call.

## Acquisition and workflow

### Directly observed

1. Homepage offers job-description input, language selector, voice-description control, and build CTA.
2. Public pages demonstrate a conversation beside structured business fields, then actions and prices.
3. The application opens a sign-in form: Google or email/password; forgot-password and create-account controls; legal links.
4. The create-account click was blocked by the browser viewport limitation. No authenticated onboarding was observed.

### Documented, not exercised

Describe job → review generated employee draft → test on own phone → provision a business number → activate → review recordings/transcripts/summaries and retrain. Docs describe one principal channel per employee, with incoming callbacks configurable separately.

This is more specific than “they sell only a builder”. Bulk campaigns and outcome delivery are central to the public product.

## Pricing observed

| Item | Published amount | Qualifications |
|---|---:|---|
| Standard voice | ₹5/min | GST excluded |
| Premium voice | ₹6.80/min | GST excluded |
| Custom high-volume | As low as ₹3.50/min | Negotiated; not an unconditional retail rate |
| Trial | 50 credits | One credit = ₹1; no card advertised |
| Business number | ₹649/month | One channel; GST excluded; deducted from wallet |
| Extra channel | ₹649/month each | One additional concurrent call; GST excluded |
| Setup/base subscription | No setup/base fee advertised | Number/channel rental still applies |
| Credits | Do not expire, according to pricing page | Contract terms not independently reviewed |

Pricing says **connected minutes**. Rounding/pulse behavior is not established by the inspected text; do not assume whole-minute rounding or per-second billing.

Examples assuming 18% GST and no special tax treatment: standard ₹5.90/min, premium ₹8.024/min, negotiated ₹3.50 becomes ₹4.13/min; one ₹649 number becomes ₹765.82/month. These are calculations, not new vendor quotes.

For 1,000 connected minutes and one number: (₹5,000 + ₹649) × 1.18 = ₹6,665.82, before other unverified charges. Three channels rent for ₹1,947/month before GST; channels change throughput rather than per-minute price. Our comparison must likewise disclose subscription allowance, phone-number arrangements, verified capacity and tax treatment.

Do not describe our ₹3 as “40% cheaper all-in” without normalizing tax, fixed rental, included minutes, rounding and actual service scope. A headline-rate comparison alone is not a total-cost comparison.

## Public frontend signals

Observed `/_next/static` chunks, a Turbopack-named asset and Next image URLs: strong evidence of a Next.js-based public frontend. Observed Geist font and a Vercel Insights script. No canvas element existed in the inspected homepage DOM. This does not establish backend language, database, model routing, hosting region, or the absence of all animation.

Sarvam and Cartesia startup-programme logos do NOT establish which model processes a real call. Internal STT/LLM/TTS infrastructure remains unknown.

## Lessons and defensible opportunities

1. **Match the clarity:** explain the job and demonstrate an outcome before discussing infrastructure.
2. **Match the pricing completeness:** talk-time rate alone is insufficient; explain tax, capacity, rental and wallet usage.
3. **Do not invent missing features:** extraction, retries, education pages, consent, branding and INR billing are not gaps demonstrated here.
4. **Test a narrower hypothesis:** excellent Telugu-English fact-collection, traceable extracted fields, explicit human-review flags and a concise report may win an institutional workflow. Compare on the same authorized evaluation dataset before claiming superiority.
5. **Keep the business general:** education is a demonstrable starting scenario, not the entire Echo Sarathi brand.
6. **Lower procurement friction only when true:** show actual invoice and payment capabilities; neither assume Outpero lacks GST invoices nor promise our PO acceptance without verification.
7. **Improve our launch trust:** honest sample labels, working navigation, accessible forms, clear failure states and real support/legal details are necessary parity, not a unique moat.

## Questions for a later authorized account test

Time from signup to usable draft; test-call safeguards; import errors; edits during active calls; retries/duplicate suppression; cancellation; confidence reporting; credits on failed/short calls; privacy/retention; mobile/keyboard behavior; export fidelity. A dashboard account and functional browser viewport are required. Do not submit a prospect's phone number or start calls merely to complete this review.

## Sources

- https://outpero.com/ — positioning, feature claims, sample disclosures, navigation and frontend signals.
- https://outpero.com/pricing — rates, tax exclusion, rental, channels, calculator and credit terms.
- https://outpero.com/product/campaigns — import, scheduling, retries and result/export illustrations.
- https://docs.outpero.com/#overview — documented onboarding and channel model.
- https://app.outpero.com/ — observed sign-in boundary only.
