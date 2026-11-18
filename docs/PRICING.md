# Pricing (draft — validate against provider invoices)

| Offering | Price | Notes |
|---|---|---|
| Community / self-hosted | **₹0** | MIT-licensed, BYOK: you supply STT/TTS/LLM/telephony keys |
| Managed Standard | **₹2.50 / connected min** | Tenglish + code-switching included, no feature gates |
| Managed Premium | **₹3.00 / connected min** | Lifelike voice, one voice across languages |
| Number + channel | pass-through at cost | No markup over the carrier invoice |

## Why these numbers

Outpero publishes: Standard ₹5/min, Premium ₹6.8/min (their help center says
₹7), Custom "as low as ₹3.5/min" for high volume, plus ₹649/month per dedicated
number+channel. All tiers include all 7 languages and all features. Unanswered
calls are not billed; 1 credit = ₹1.

We can be cheaper because the core is open source and the voice stack is BYOK:
contributors supply their own models, and the managed offering sells
orchestration rather than locked-in model access.

## Unit-cost worksheet (fill from real invoices before publishing rates)

| Component | Cost / min | Source |
|---|---|---|
| STT | ₹ ___ | e.g. Sarvam Saaras / Deepgram invoice |
| TTS | ₹ ___ | e.g. Cartesia / Bulbul invoice |
| LLM | ₹ ___ | provider usage |
| Telephony | ₹ ___ | carrier per-minute rate |
| **Cost** | **₹ ___** | |
| **Managed margin** | **₹ ___** | sell price − cost |

No billing or plan logic is implemented in the application yet; this document
is a pricing proposal only.
