# Voice-AI competitor research — corrected evidence base

Reviewed 2026-10-28 for Echo Sarathi's proposed SaaS frontend launch. This revision supersedes the earlier comparison: several conclusions and price comparisons in that version were unsupported.

## Executive conclusion

**Outpero and Bolna are direct India-first rivals.** Vapi, Retell, Bland and ElevenAgents set the product/enterprise benchmark. Exotel, Ozonetel, Knowlarity and Acefone compete through telephony/contact-centre distribution.

Do not position Echo Sarathi as the only product with campaigns, structured outcomes, templates, INR credits, tenant identity or compliance controls. Competitors already advertise many of these. The defensible opportunity is a simpler, reliable, demonstrably useful call-to-report workflow for Indian teams, with education as an initial proof case rather than a restriction on the business.

## Research scope and confidence

The main agent attempted all ten websites using Browser Use. Seven vendors' public pages were readable. Ozonetel and Knowlarity timed out; Acefone returned a Cloudflare block. Outpero's public documentation and app sign-in page were also inspected.

The browser connector could read rendered text/DOM but had no attached viewport. Screenshot and pointer actions failed with `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`; selecting the page to bring it forward did not repair that. No authenticated dashboard, signup, payment, microphone, live call, or audio quality test was performed. No access controls were bypassed.

- **Observed:** public text, links, form structure and limited asset/font signals.
- **Advertised:** features, scale, security, latency, testimonials and pricing the vendor publishes; not independent performance proof.
- **Unknown:** gated workflow quality, actual contracts, tax eligibility, rounding not disclosed, backend stack, legal compliance and real reliability.
- **Hypothesis:** a proposed advantage to test, not a proven competitor omission.

Public-site experience below means information architecture and content clarity. Visual quality, responsiveness, accessibility behavior and audio quality remain unverified. Source URLs and limitations are recorded in each profile.

## Profiles and coverage

| Vendor | Tier and reason | Inspected material | Profile |
|---|---|---|---|
| Outpero | Direct: India, credits, multi-industry calling | Home, pricing, campaigns, docs, app login | [Outpero](outpero/README.md) |
| Bolna | Direct: Indic languages, self-serve and enterprise | Home and pricing | [Bolna](bolna/README.md) |
| Vapi | Adjacent/aspirational: developer platform and operability | Home and pricing calculator content | [Vapi](vapi/README.md) |
| Retell | Adjacent/aspirational: no-code contact-centre workflow | Home, product sections, public pricing FAQ | [Retell](retell/README.md) |
| Bland | Aspirational: regulated operations and managed stack | Home and pricing | [Bland](bland/README.md) |
| ElevenAgents | Aspirational: voice/omnichannel platform | Home, agents, agents-specific pricing | [ElevenAgents](elevenlabs-agents/README.md) |
| Exotel | Adjacent: enterprise CX and telephony distribution | Home and pricing hub | [Exotel](exotel/README.md) |
| Ozonetel | Adjacent, provisionally: contact-centre buyer | Browser timed out; indexed vendor excerpts only | [Ozonetel](ozonetel/README.md) |
| Acefone | Adjacent, provisionally: telephony and AI product | Browser blocked; indexed AI-product excerpt only | [Acefone](acefone/README.md) |
| Knowlarity | Adjacent, provisionally: telephony buyer | Browser timed out; indexed home/voice-price excerpts | [Knowlarity](knowlarity/README.md) |

These tiers describe offer and market overlap, not independently established company size. There is insufficient evidence to rank product quality numerically. No claim to cover every competitor in the market.

## Pricing: compare like with like

| Vendor | Public price evidence | Important exclusions or scope |
|---|---|---|
| Echo Sarathi | Code/docs: ₹3/min list/overage; paid plans have allowances | GST-inclusive; actual cost, billing duration and deployed capacity need validation |
| Outpero | Standard ₹5, premium ₹6.80, negotiated from ₹3.50/min | GST extra; number ₹649/month including one channel; each extra channel ₹649/month |
| Bolna | $0.06/min, vendor displays ₹5.52; fixed-volume tiers lower | Bundled models only; telephony/platform fee extra; Pilot has distinct rates and 30-second pulses |
| Vapi | $0.05/min hosting | Model/transport usage extra; optional success packages; Core $29/mo, Pro $999/mo minimum |
| Retell | Homepage FAQ: $0.07–$0.31/min configured | Component-dependent; get an India-specific configured quote |
| Bland | Start $0.14/min; Build $0.12/min plus $299/month | LLM/STT/TTS included; pricing FAQ says carrier separately; transfer charges can apply |
| ElevenAgents | Free 15 min; paid tiers; PAYG/additional $0.08/min shown | LLM and carrier extra; taxes excluded; distinguish first-month promotions from regular prices |
| Exotel | No numeric AI-minute quote in inspected hub | Sales quote/product tab detail not exercised |
| Ozonetel/Acefone/Knowlarity | Current comparable AI-minute price unverified | Site failure is not proof that prices are unpublished |

No blanket USD-to-INR conversion is used. Bolna's own ₹5.52 display uses a different implied exchange rate from the old report's ₹88/USD assumption: $0.06 × ₹88 is ₹5.28, not ₹5.52. Currency, GST, carrier, rental, pulse, included usage, support and concurrency must be normalized before a savings claim.

### Our economics: correction before pricing decisions

Current business-model estimates say ₹2.30 cost per connected minute and prices include 18% GST. If ₹2.30 is the comparable net cost:

- ₹3 / 1.18 = ₹2.5424 net revenue.
- Contribution ≈ ₹0.2424/min, or 9.5% of net revenue, **before payment fees, support and other overhead**.
- Cash price needed just to cover ₹2.30 net cost plus 18% GST ≈ ₹2.714/min, before those other expenses.
- Free minutes have a real cost; they are not a costless substitute for discounts.

The earlier 23% margin and ₹2.30 retail floor were misleading. Actual provider invoices, input-tax credits, duration measurement, plan utilization and fixed overhead must be established. No price changes are authorized by this research.

## Corrections to the old report

1. Outpero, Retell and others explicitly market campaigns and captured fields. “Everyone only returns transcripts” is false.
2. Outpero's pricing is already INR credit-based; it also has education pages, branded employees and scheduling/consent claims.
3. Bolna's 25 concurrency and 30-second pulses are explicitly attached to the Pilot plan, not its entire platform.
4. Vapi Core currently lists 10 concurrent calls; 4 belongs to usage-only. Bland Build's $299 monthly fee was omitted.
5. ElevenAgents has a dedicated pricing page. TTS-only pricing does not represent agent pricing; paid seats are not required at every tier.
6. Exotel offers a public “Try For Free” entry in addition to sales demos. Do not claim every visitor must take a sales call.
7. Missing evidence is not proof that a vendor lacks GST invoices, purchase orders, exports, branding, Indian languages, or compliance controls.
8. Our CSV/XLSX exports exist; an institutional PDF report and a live capacity gauge must not be described as shipped without verifying them.
9. Our catalogue concurrency limits are not evidence of delivered production capacity. Deployment files cap campaign concurrency at one per organization.
10. Calling-hours and consent checks are not DLT/DPDP certification, and the deployment file specifies Singapore rather than India-only hosting.

## Gap-to-delivery map

| Opportunity | Competitor evidence | Our current evidence | Frontend launch response | Validation |
|---|---|---|---|---|
| Outcome-first explanation | Outpero shows conversation → fields → action | Agents, campaigns, call details and CSV/XLSX exist | Show a clearly labelled illustrative workflow, then link to real product screens | Every CTA reaches a working route; examples never imply live customer data |
| Fast, comprehensible setup | Outpero job description; Bolna templates; Retell visual studio | Six-step builder and agent workspace exist | Improve hierarchy, terminology, progress and field errors without changing payloads | Create/edit payload regression checks in fixtures |
| Trustworthy pricing | Outpero exposes channels/rental/GST; Vapi component calculator | Wallet, plans and invoice code exist; commercial readiness uncertain | Separate plan allowance, overage, wallet, GST and supported capacity; qualify uncertain claims | Compare UI against backend responses and operational sign-off |
| Understand failures | Outpero explains retries/carrier refusal; Retell QA/monitoring | Campaign status/error data and call details exist | Clear blocked/empty/error/low-credit states using actual response data | Offline/401/402/422/empty/loading examples render correctly |
| Reviewable outcomes | Retell CRM outcomes; ElevenAgents analytics | Confidence and source-turn data on call detail | Prioritize structured fields, review flags and transcript evidence | Do not invent missing values or omit uncertainty |
| Complete buyer journey | Outpero app/docs/legal; major vendors trust resources | No dedicated legal routes; marketing/signup claims conflict with defaults | Honest CTA, consistent public navigation, user-approved legal content | No dead links; no unavailable public-signup promise |
| Mobile/keyboard polish | Not visually tested across competitors | Code review found focus/sign-out/motion issues | Accessible navigation, forms, tables, themes and reduced motion | Actual browser/keyboard screenshots and regression matrix |

These improvements address our observed weaknesses. Claims that they outperform competitors require later, authorized head-to-head testing.

## Deferred capability work: not part of a reskin

Inbound callbacks, WhatsApp/CRM/calendar integrations, self-serve number provisioning, increased concurrency, automatic prompt generation, changes to billing duration, and telephony/call-flow changes require separate backend scope and approval. Do not place decorative controls for these in the shipped UI or describe them as implemented.

## Recommended positioning and page strategy

**Draft:** “Business calls. Clear outcomes.” Explain configurable agents, campaigns and reviewable results for Indian teams; use a proven education scenario as one example, not the only supported business.

Use deliberate typography, generous but functional spacing, clear tables and a restrained accent. Lead with product evidence and clear actions, not simulated latency dashboards, invented customer logos or decorative 3D. Keep both themes and make any motion optional. The [launch redesign plan](../docs/SAAS_LAUNCH_REDESIGN_PLAN.md) defines page ownership, safety boundaries and acceptance gates.

## Next research required

A functional browser viewport and authorized vendor test accounts are needed for full onboarding, dashboards, import edge cases, voice listening, mobile, accessibility and latency/quality comparisons. No absence claim should be inferred from those untested areas.

Each profile contains direct source links. A later reviewer should re-open pricing before a sales proposal; promotional and commercial terms change.
