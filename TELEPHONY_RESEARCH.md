# Telephony Research — EchoSarathi AI Voice Calling (India)

**Status:** CHOSEN — Twilio trial (no company/tax KYC, fastest config, direct fit for our LiveKit pipeline). Tunnel via vendored `tools/cloudflared` (free, proven on this machine 2026-08-26).
**Usage profile:** website (browser playground) is primary and costs zero telephony; live phone demos are rare. Optimize for easiest configuration + pay-as-you-go.
**Sources:** this repo's own research (`PROJECT_MASTER.md` §8: GLM 5.2, k3, cost-cutter inputs), provider docs + 2026 rate cards checked 2026-09-10. Re-check prices at purchase.
**Legend:** ✅ verified fact · 📢 provider claim · 🔧 our inference.

## All approaches evaluated

### A. Physical SIM / eSIM in a GSM gateway or phone — REJECTED
- What: consumer SIM in a gateway box or Android device, auto-dialed by software.
- Budget: SIM ₹200–500 one-time + gateway hardware ₹15,000–50,000 + monthly recharges per SIM.
- Verdict: ❌ inappropriate. No API control, 1 call per SIM, hardware = downtime, and TRAI treats automated commercial calling over consumer SIMs as gray traffic (blocking risk). Evaluated because the project brief asked; ruled out by every in-repo analysis.

### B. Direct carrier SIP trunk (Airtel / Jio / Tata enterprise) — SCALE ONLY
- What: your own trunk straight into a carrier; you become your own CPaaS (SBC, codecs, DLT plumbing by you).
- Budget: ✅ ~₹0.60–1.20/min at 20L+ min/month; setup = weeks + telecom engineer time + SBC/server costs.
- Verdict: cheapest per minute at massive scale, heaviest setup. Not for demos; revisit past ~10,000 calls/month.

### C. Self-hosted PBX (FreeSWITCH / Asterisk) — REJECTED for now
- What: open-source switch bridging a SIP trunk to your app.
- Budget: server (~₹1,000–4,000/mo VPS) + engineer weeks; still needs a trunk (B) or CPaaS numbers.
- Verdict: ❌ maximum control, maximum work. Nothing to gain until scale forces it.

### D. India-native CPaaS — Exotel / Ozonetel / Knowlarity / Kaleyra
- What: API + virtual numbers (ExoPhones), IVR heritage, strongest DLT hand-holding, Mumbai DCs.
- Budget: trial free (Exotel: 7 days + $5 credit, 1 trial number, 10 whitelisted numbers) · paid outbound ✅ ~₹0.80–1.00/min, inbound ~₹0.30–0.50/min, ExoPhone ~₹200–300/mo, entry bundles ~₹900–2,500/mo · KYC 1–3 days (business email + PAN/GST).
- Catch: core APIs built for legacy IVR; real-time AI streaming (Exotel AgentStream) is newer — verify latency before committing.
- Verdict: best production-India story, but needs new client code in this repo + days of KYC. Not the easiest.

### E. Global CPaaS — Twilio ✅ RECOMMENDED (single approach)
- What: REST API + TwiML Media Streams (`<Stream>`) piping call audio to our backend WS bridge → LiveKit room → existing STT→LLM→TTS pipeline. No new architecture.
- Budget: trial free (75 voice min, verified numbers only max 5, trial greeting plays, 10-min cap, 30-day expiry) · US number ✅ ~$1.15–2/mo · India outbound $0.013–0.07/min depending on route · zero KYC for trial (2-min OTP verification of your number).
- Why it wins on your criterion (easiest config): account exists, credentials + US number already in `.env`, `TwilioClient` + `/twilio/*` bridge already built and closest to ringing today, outbound to India allowed from international numbers per Twilio's own India guidelines.
- Honest downsides: India rates 20–50% above Exotel/Plivo; thinnest India DLT support; US/EU media routing can add 150–300ms (irrelevant for rare demos; mitigated at scale by moving to F).

### F. Developer CPaaS with SIP — Plivo (migration path, not now)
- What: SIP trunking (`*.zt.plivo.com`) + official LiveKit inbound/outbound trunk guides, TLS/SRTP.
- Budget: ✅ $10 free credit, no card · US number $0.50/mo, SIP outbound from ~$0.0046/min US / ~₹0.34+/min India legs · India 080/022 numbers need company KYC (GST/COI/Udyam + seal, auto-review ~5 min IF you hold the docs).
- Verdict: cheapest scale path and the repo's locked long-term pick — but a new signup + untested-live integration makes it slower than E today. `PlivoClient` + `/plivo/*` already abstracted in `telephony.py`, so switching later is config, not rewrite.

### G. Other global CPaaS — Telnyx / Vonage / Sinch — NOT NOW
- Budget: from ~$0.007/min US, numbers ~$1/mo. Great tech, LiveKit SIP guides exist — but no India edge, weak TRAI story. Revisit only if leaving India.

### H. Voice-AI platforms — Vapi / Retell / Bland / ElevenLabs — NOT NOW
- What: managed STT+LLM+TTS+telephony in one box, bring-your-own numbers.
- Budget: 📢 ~$0.10–0.15/min platform fee ON TOP of telephony + model costs.
- Verdict: fastest zero-code demo, but 4–5x our per-minute cost (repo research targets <₹3.5/min all-in: telephony ₹1.00 + STT ₹0.35 + LLM ₹0.30 + TTS ₹0.50 + infra ₹0.20) and we'd throw away our pipeline. Revisit only if build capacity disappears.

## The one approach: E (Twilio), with F as the documented migration

| Step | Action | Cost | Time |
|---|---|---|---|
| 1 | Verify `+917842594002` in Twilio Console (Voice → verified numbers, OTP) | Free | 2 min, you |
| 2 | `ngrok http 8000`, set `PUBLIC_BASE_URL` + `PUBLIC_WS_BASE_URL` in `.env`, restart backend | Free | 5 min |
| 3 | `POST /api/test-call` with your contact card → phone rings, agent talks | ~$0.35 per 5-min demo | me, same session |
| 4 | Production later: Mumbai VPS (~₹500–2,000/mo) + domain/TLS (replaces ngrok), then Plivo India number + DLT when demos become pilots | VPS + ~₹500–1,000/mo numbers | when needed |

Rare-demo quotation (20 calls/mo × 3 min = 60 min): Twilio ≈ $5–7/mo all-in (number + minutes). Nothing else to buy — no SIM, no hardware, no KYC fees.

## Compliance notes (India)
- Test allowlist (`TEST_PHONE_NUMBERS`) + `consent_source=test_allowlist` is the only bypass, and only for your own verified numbers. No campaign traffic from this flow — single consented test calls.
- Production: DLT entity registration (~₹5,000 + GST), generalized transactional voice template (AI scripts can't be word-exact), calling hours 9:00–21:00, 90-day recording retention, Indian CLI on every call.

## Decision required
- [ ] Approve **E now** (Twilio trial → paid per-minute; migrate to F/Plivo at scale), or
- [ ] Pick **D/Exotel** instead (only if company KYC pack is ready today and India-native billing outweighs 1–3 days + new integration work).

After approval I execute steps 2–3 and report the live-call result in-session.
