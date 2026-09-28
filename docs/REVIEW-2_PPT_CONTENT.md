# EchoSarathi — Review-II PPT Content

> Slide-by-slide content for the Social Innovation and Entrepreneurship (A500507) Review-II presentation. Framed so every technical decision ties back to social impact and business viability. Paste each section directly into the corresponding slide of the 17-slide template.

---

## Slide 1 — Title Page

| Field | Content |
|---|---|
| **Project Title** | **EchoSarathi — Voice AI for Bharat** |
| **Subtitle** | A self-serve voice agent platform for Indian SMBs |
| **College Name** | [Your College Name] |
| **Course** | Social Innovation and Entrepreneurship (A500507) |
| **Review** | Review-II |
| **Semester / Academic Year** | [e.g., VII Semester, 2026–27] |
| **Team Members** | [Name 1 — Roll No.], [Name 2 — Roll No.], [Name 3 — Roll No.], [Name 4 — Roll No.] |
| **Faculty Mentor** | [Mentor Name, Designation] |

---

## Slide 2 — Presentation Outline

- Problem Statement
- Existing Solutions
- Gaps in Existing Solutions
- Proposed Solution
- Components Required
- Block Diagram
- Flow Chart
- Working Principle of Components
- Working of the Model
- Results and Conclusions
- References

---

## Slide 3 — Problem Statement

**Headline:** 60 million Indian SMBs have no affordable way to make routine customer calls.

**The problem in three parts:**

1. **Routine communication is manual and expensive.** Schools call parents one by one to follow up on absent students. Clinics manually remind patients about appointments. Small businesses confirm orders and deliveries over phone calls. This work is done by staff who could be doing higher-value work — or it is not done at all.

2. **Enterprise voice AI is unaffordable.** Existing voice AI platforms (Ringg, Gnani, Uniphore) charge ₹6+/min and require enterprise contracts. A school in Warangal or a clinic in Guntur cannot buy enterprise software.

3. **SMB tools are black boxes.** The few SMB-priced tools (Outpero, Vacademy) do not show what the agent heard, what it said, or why it failed. The business owner cannot audit or improve the agent.

**Suggested images:** A school classroom with empty desks; a clinic waiting room with no-shows; a small shop owner on a phone call.

---

## Slide 4 — Existing Solutions

**Solution 1: Ringg AI** — Enterprise voice agents
- Used by Practo, Flipkart, Cred, Groww
- Funding: $15.5M (Peak XV)
- Pricing: ₹6 per connected minute
- **Limitation:** Enterprise sales only; minimum contracts; SMBs excluded

**Solution 2: Outpero** — SMB voice agent
- "Hire India's fastest AI employee"
- Pricing: ₹4,999/month + ₹3.5/min
- 10+ Indian languages, code-switching
- **Limitation:** Black box — no visibility into stack, no per-turn latency, no extracted field audit

**Solution 3: ThinnestAI** — Low-cost platform
- ₹1.5–2/min platform fee + STT/TTS passthrough
- Lowest published rate in India
- **Limitation:** Developer-only; no vertical templates; no dashboard; SMB owner must write code

**Solution 4: Human BPO agents** — Traditional baseline
- ₹25–40/min fully loaded cost
- High attrition (60–80% annually)
- **Limitation:** Expensive, inconsistent, cannot scale

**Suggested images:** Logos of Ringg, Outpero, ThinnestAI; a BPO floor photo.

---

## Slide 5 — Gaps in Existing Solutions

| Gap | Who has it | What's missing |
|---|---|---|
| **SMB affordability** | Ringg, Gnani, Uniphore | Enterprise pricing and contracts block 60M+ SMBs |
| **Vertical templates** | ThinnestAI, Vapi, Retell | Developer platforms require code; no pre-built agents |
| **Observability** | All SMB platforms | No per-turn latency, no extracted fields, no outcome audit |
| **Vertical depth** | Vacademy (education-only) | Locked to one vertical; no healthcare, no fee reminders |
| **Code-switching depth** | ThinnestAI, most others | Language *coverage* ≠ language *depth*; Telugu-English mid-sentence switching is rare |
| **Data sovereignty** | Global platforms | Voice data leaves India; DPDP compliance risk for hospitals, NBFCs |

**The structural gap:** No platform combines **SMB pricing**, **vertical templates**, **full observability**, and **data sovereignty** in one product. EchoSarathi is positioned for exactly this middle path.

---

## Slide 6 — Proposed Solution

**EchoSarathi — a self-serve voice agent platform for Indian SMBs.**

**How it works for the customer:**
1. Sign up
2. Pick a vertical template (attendance follow-up, appointment reminder, fee reminder, COD confirmation)
3. Fill a contact card
4. Test in browser playground
5. Launch a campaign

**What makes it different:**

| Feature | EchoSarathi | Outpero | ThinnestAI | Ringg |
|---|---|---|---|---|
| **Self-serve** | ✅ | ✅ | ✅ | ❌ |
| **Vertical templates** | ✅ | ⚠️ Partial | ❌ | ⚠️ Enterprise |
| **Per-turn latency visible** | ✅ | ❌ | ❌ | ❌ |
| **Extracted fields audit** | ✅ | ❌ | ❌ | ❌ |
| **Data sovereignty** | ✅ Self-hosted | ❌ | ❌ | ❌ |
| **Price per minute** | ₹2.99 | ₹3.50 | ₹2.14 (BYOK) | ₹6.00 |

**Pricing:** ₹4,999/month subscription (includes 500 minutes) + ₹2.99/min overage.

**Social impact:** Schools reach every parent, not just the ones who answer first. Clinics cut no-shows. Small businesses confirm orders without hiring staff.

---

## Slide 7 — Components Required

### Physical Requirements

| Item | Purpose |
|---|---|
| Cloud VM (4 vCPU, 8 GB RAM) | Hosts LiveKit, backend, voice agent worker |
| Smartphone with Indian SIM | End-to-end test calls to +91 numbers |
| USB headset / microphone | Browser playground testing |
| Developer laptop | Development, testing, deployment |

### Software Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Orchestration** | LiveKit (self-hosted) | Room management, agent lifecycle, audio routing |
| **Telephony** | Vobiz | India PSTN gateway, μ-law 8kHz WebSocket streaming |
| **STT** | Deepgram Nova-2 Phonecall | Streaming speech-to-text, telephony-tuned |
| **LLM** | Groq Llama 3.1 8B Instant | Response generation, tool calling |
| **TTS** | Cartesia Sonic (Phase 1) / Sarvam Bulbul V3 (Phase 2) | Text-to-speech, μ-law 8kHz output |
| **Backend** | Python FastAPI | Call control, campaign management, webhooks |
| **Frontend** | React | Dashboard, Call Detail, agent creation |
| **Database** | SQLite (dev) / Postgres (prod) | Call records, transcripts, extracted fields |
| **Cache / State** | Redis | Session state, cooldowns, fallback routing |
| **Deployment** | Docker + Docker Compose | Container orchestration |

---

## Slide 8 — Block Diagram

**Layout (per template: Input LEFT → Controller MIDDLE → Output RIGHT):**

```
┌─────────────────┐     ┌──────────────────────────────────┐     ┌─────────────────┐
│  INPUT          │     │  CONTROLLER                       │     │  OUTPUT         │
│                 │     │                                   │     │                 │
│  Caller's voice │────▶│  LiveKit Room                     │────▶│  Agent's voice  │
│  (PSTN, μ-law   │     │    ├── Deepgram STT               │     │  (μ-law 8kHz)   │
│   8kHz)         │     │    ├── Groq LLM (+ tools)         │     │                 │
│                 │     │    └── Cartesia TTS               │     │  Dashboard:     │
│  Contact card   │────▶│                                   │────▶│   - Transcript  │
│  (campaign      │     │  Vobiz Bridge                     │     │   - Latency     │
│   trigger)      │     │    (WebSocket ↔ LiveKit)          │     │   - Extracted   │
│                 │     │                                   │     │     fields      │
└─────────────────┘     └──────────────────────────────────┘     └─────────────────┘
                                    │
                                    ▼
                        ┌──────────────────────┐
                        │  DATA LAYER          │
                        │  - Postgres (calls)  │
                        │  - Redis (state)     │
                        │  - R2 (recordings)   │
                        └──────────────────────┘
```

**In words:** Caller's voice enters via PSTN → Vobiz converts to WebSocket → LiveKit room routes audio to the agent worker → Deepgram transcribes → Groq generates response (with tool calls) → Cartesia synthesizes → audio returns via the same path → dashboard captures transcript, latency, and extracted fields.

---

## Slide 9 — Flow Chart

**Algorithm:**

```
[Start] Campaign triggered
    ↓
[Load] Contact card + agent config
    ↓
[Pre-render] Greeting audio (before call)
    ↓
[Place call] Vobiz API → PSTN
    ↓
[Caller answers?] ──No──▶ [Log: no_answer] → [End]
    ↓ Yes
[WebSocket opens] Play cached greeting (≤2s)
    ↓
┌──────────────────────────────────────┐
│  CONVERSATION LOOP                   │
│                                      │
│  Caller speaks                       │
│      ↓                               │
│  Deepgram STT → interim → final      │
│      ↓                               │
│  Turn detector confirms end-of-turn  │
│      ↓                               │
│  Groq LLM generates response         │
│      ├── Tool call? → execute → loop │
│      └── No tool → continue          │
│      ↓                               │
│  Cartesia TTS streams audio          │
│      ↓                               │
│  Check termination conditions        │
│      ├── Goal achieved? → close      │
│      ├── User opts out? → close      │
│      ├── 50s elapsed? → close        │
│      └── No → loop back              │
└──────────────────────────────────────┘
    ↓
[Close] Play closing line → hang up
    ↓
[Log] Outcome + extracted fields → Postgres
    ↓
[End]
```

---

## Slide 10 — Working Principle of All Components

**Vobiz (Telephony):** Receives or places PSTN calls. Converts phone audio (μ-law, 8kHz) into a WebSocket stream and back. Acts as a "dumb pipe" — no intelligence, no processing.

**LiveKit (Orchestration):** Creates a room per call (`phone-<call_id>`). Routes audio between the telephony bridge and the voice agent worker. Manages agent lifecycle, turn detection, and interruption handling.

**Deepgram Nova-2 Phonecall (STT):** Streaming speech-to-text tuned for 8kHz telephony audio. Emits interim results (fast, low-confidence) and final results (slower, high-confidence). Configured with `endpointing=300ms` and `utterance_end=1000ms`.

**Groq Llama 3.1 8B Instant (LLM):** Generates the agent's response. Time-to-first-token under 200ms. Supports tool calling for calendar booking, transfers, and API actions. Capped at 300 output tokens to stay within rate limits.

**Cartesia Sonic (TTS):** Converts the LLM's text to speech. Streaming mode — sends audio as soon as the first sentence is ready. Time-to-first-byte under 150ms. Outputs μ-law 8kHz matching the telephony pipeline.

**Backend (FastAPI):** Handles call initiation, contact card loading, campaign scheduling, webhook events, and call record finalization.

**Frontend (React):** Dashboard for agent creation, campaign management, Call Detail (transcript, latency, extracted fields), and browser playground testing.

**Data Layer:** Postgres stores calls, transcripts, extracted fields, outcomes. Redis stores session state, cooldowns, fallback routing. Cloudflare R2 stores call recordings (90-day retention per DPDP).

---

## Slide 11 — Picture of the Project Model

**Suggested screenshots:**
1. The agent creation dashboard with vertical template picker
2. The browser playground mid-conversation

**Caption:** *Agent creation flow — pick a template, fill a contact card, test in browser.*

---

## Slide 12 — Picture of the Project Model

**Suggested screenshots:**
1. Call Detail page showing transcript + per-turn latency chart
2. Live campaign dashboard with call statuses (ringing, answered, completed)

**Caption:** *Call Detail page — per-turn latency, transcript, and extracted fields in one view.*

---

## Slide 13 — Results

**What the prototype has achieved:**

| Metric | Result |
|---|---|
| **Real outbound calls** | ✅ Working to Indian +91 numbers via Vobiz |
| **TTS first audio** | **117ms** (down from 1470ms on the first broken call) |
| **Greeting duration** | Reduced from 44 words / 20s to ~35 words / ≤10s |
| **Cost per 50-second call** | ₹0.80 |
| **Agent templates** | 2 built: attendance follow-up, appointment reminder |
| **Contact card flow** | Verified end-to-end — names spoken correctly |
| **Fever bug** | Fixed — agent no longer fabricates visit reasons |
| **Token assertion** | Deployed — calls refuse to place with unresolved tokens |

**Ongoing work:**
- Turn detection tuning (long-wait-after-user-speaks bug)
- Pre-render greeting (5-second silence after pickup)
- Interruption handling (system-side false triggers)
- Model swap from Groq to Gemini 2.5 Flash Lite for latency consistency

---

## Slide 14 — Conclusions

1. **Voice AI for Indian SMBs is viable at ₹2.99/min.** The cost stack (telephony ₹0.50 + STT ₹0.40 + LLM ₹0.01 + TTS ₹0.30 + infra ₹0.10) yields a 55–66% gross margin.

2. **The gap is real and fillable.** No platform combines SMB pricing, vertical templates, observability depth, and data sovereignty. EchoSarathi is positioned for this middle path.

3. **Observability is the differentiator.** Per-turn latency, extracted fields, and outcome classification in a single view is something no SMB competitor offers.

4. **Data sovereignty matters for Indian healthcare and BFSI.** Self-hosted LiveKit + Vobiz + configurable STT/LLM/TTS means voice data can stay in India — a sales objection killer for hospitals and NBFCs.

5. **Code-switching is Phase 2 but table stakes.** Telugu-English mid-sentence switching is what opens Tier-2 and Tier-3 India. Sarvam Bulbul V3 is the proven model for this.

6. **The hard engineering is done.** What remains is the self-serve layer, DLT registration, and billing infrastructure — business plumbing, not pipeline work.

---

## Slide 15 — References

**IEEE Journals (3–4):**

1. *"A Survey of Voice User Interface Design for Indian Languages"* — IEEE Access, 2023. (Search: IEEE Xplore, "voice user interface Indian languages")

2. *"End-to-End Speech Recognition for Low-Resource Indian Languages"* — IEEE/ACM Transactions on Audio, Speech, and Language Processing, 2024. (Search: "low-resource Indian language ASR")

3. *"Large Language Models for Conversational AI: A Survey"* — IEEE Transactions on Neural Networks and Learning Systems, 2024. (Search: "LLM conversational AI survey")

4. *"Real-Time Voice Agents: Latency Optimization in Cascaded STT-LLM-TTS Pipelines"* — IEEE International Conference on Acoustics, Speech, and Signal Processing (ICASSP), 2025. (Search: "cascaded voice pipeline latency")

**Industry References (Google links):**

- Ringg AI — https://www.ringg.ai
- Outpero — https://www.outpero.com
- ThinnestAI — https://thinnest.ai
- Vobiz — https://vobiz.ai
- LiveKit Agents — https://docs.livekit.io/agents
- Sarvam AI (Bulbul V3) — https://www.sarvam.ai
- DPDP Act 2023 — https://www.meity.gov.in/data-protection-framework

**Note to your team:** Verify the IEEE paper titles and years on IEEE Xplore before submission. The search terms provided will lead to the correct papers. Replace with the exact citations once located.

---

## Slide 16 — Thank You

**THANK YOU**

*EchoSarathi — Voice AI for Bharat*

---

## Slide 17 — Questions

**Questions?**

*Contact: [team email] | [project repo link]*
