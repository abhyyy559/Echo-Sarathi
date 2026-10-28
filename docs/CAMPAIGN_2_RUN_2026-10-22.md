# Campaign run — Team Dial Test, 22 Oct 2026

- **Campaign:** Team Dial Test 2026-10-22 (id 2) — status `running`
- **Agent:** Absent Student Check-in (agent 3, version 5) — the CMR College absence check-in script
- **Mode:** sequential outbound dialing, one live call at a time (`DEFAULT_CONCURRENCY_LIMIT=1`, `DEFAULT_CPS_LIMIT=1`)
- **Window:** quiet hours temporarily extended to 23:00 IST for this test (operator-approved; revert to 21:00)
- **Dials placed:** 5 across 3 contacts
- **Conversations captured:** 2
- **Refused by the network:** 2
- **Structured fields extracted:** 0
- **Build under test:** `cf54fa4` (carrier-refused legs now close instantly) deployed to Render at 22:09 IST

## Every dial, in the order it happened

| # | Call | Contact | Number | Dialed (IST) | Status | Billed | Turns | Fields |
|---|---|---|---|---|---|---|---|---|
| 1 | 25 | jeevana | +917842594002 | 21:51:38 | `failed` | 218s | 0 | 0 |
| 2 | 27 | jeevana | +917842594002 | 22:09:36 | `busy` | 0s | 0 | 0 |
| 3 | 28 | Shashi varun | +917569594285 | 22:10:00 | `completed` | 60s | 5 | 0 |
| 4 | 29 | rithika | +919133615211 | 22:10:56 | `completed` | 60s | 3 | 0 |
| 5 | 30 | jeevana | +917842594002 | 22:25:00 | `busy` | 0s | 0 | 0 |

## Contact roster outcome

| Contact | Number | Final status | Attempts | Next attempt | Consent |
|---|---|---|---|---|---|
| jeevana | +917842594002 | `queued` | 2 | 22:40:23 | True |
| Shashi varun | +917569594285 | `completed` | 0 | — | True |
| Dhanunjay | *(no number — marked invalid)* | `invalid` | 0 | — | True |
| rithika | +919133615211 | `completed` | 0 | — | True |

## Transcripts

Verbatim from the `transcripts` table. `caller` is the person who picked up; `agent` is the voice agent. Times are IST.

### Dial 1 — call 25: jeevana (+917842594002)

- status `failed`, billed 218s, agent version 5, outcome agent_never_joined, flagged for human: True
- **no transcript** — the leg never reached a conversation (network refusal, or the pre-fix run where the carrier said busy and our own status handler stamped the call as answered).

- **extracted fields: none**

### Dial 2 — call 27: jeevana (+917842594002)

- status `busy`, billed 0s, agent version 5, outcome —, flagged for human: False
- **no transcript** — the leg never reached a conversation (network refusal, or the pre-fix run where the carrier said busy and our own status handler stamped the call as answered).

- **extracted fields: none**

### Dial 3 — call 28: Shashi varun (+917569594285)

- status `completed`, billed 60s, agent version 5, outcome —, flagged for human: False

- `22:10:28` **caller**: Bol rahe.
- `22:10:28` **agent**: Hello, this is an AI assistant calling from CMR College of Engineering and Technology. This call is
- `22:10:32` **agent**: Can you please confirm the employee's name and department
- `22:10:47` **caller**: My name is Tanand ji.
- `22:10:47` **agent**: Thank

- **extracted fields: none**

### Dial 4 — call 29: rithika (+919133615211)

- status `completed`, billed 60s, agent version 5, outcome —, flagged for human: False

- `22:11:28` **agent**: Hello, this is an AI assistant calling from CMR College of Engineering and Technology. This call is being recorded. Am I speaking with Balakrishna, parent of rithika, who was absent from college today?
- `22:12:04` **caller**: Hello.
- `22:12:04` **agent**: This is an AI

- **extracted fields: none**

### Dial 5 — call 30: jeevana (+917842594002)

- status `busy`, billed 0s, agent version 5, outcome —, flagged for human: False
- **no transcript** — the leg never reached a conversation (network refusal, or the pre-fix run where the carrier said busy and our own status handler stamped the call as answered).

- **extracted fields: none**

## What this run proved

1. **The dialer really does dial one after another.** Five legs across three contacts, each one starting the second the previous ended: jeevana (22:09:36) → Shashi varun (22:10:00) → rithika (22:10:56) → jeevana's scheduled retry (22:25:00).
2. **A refusal no longer fakes a live call.** Call 27 came back `CallStatus=busy` / `HangupCause=USER_BUSY`; the new handler closed it as `busy`, re-queued jeevana with the 15-minute retry policy, and freed the single dial slot in the same second — the next contact started at 22:10:03. Before this fix the same call sat `in_progress` for 218 seconds (call 25) and blocked the campaign. The scheduled retry then fired on time at 22:25:00 and closed just as fast (call 30).
3. **The agent joins a real carrier leg.** Calls 28 and 29 both show `vobiz_stream:StartStream` followed by LiveKit voice-activity events: the worker connected to the `phone-<id>` room, spoke, listened, and answered.
4. **Consent and roster rules hold.** Dhanunjay had no number and was marked `invalid` without a dial attempt; every dialled contact carries `consent=True`.

## What is still broken

1. **The carrier cuts every campaign call at 60 seconds.** Calls 28 and 29 both ended at exactly `BillDuration: "60"`, mid-sentence (`"This is an AI"`, `"Thank"`). Nothing was extracted and no summary was written because the agent never reached the reason → return-date → goodbye flow; the final webhook finalized the call first. This is the blocker for the "information extracted and shown in the platform" part of the test. The cap is not ours: `VobizClient.place_call()` sends only `from`/`to`/`answer_url` and nothing in the repo limits a call to 60s, so it is Vobiz's account/trunk limit — either pass an explicit `maxDuration` on Call-create or have Vobiz raise the limit.
2. **Script drift on call 28.** The agent asked *"Can you please confirm the employee's name and department"* — "employee" and "department" appear nowhere in version 5's prompt or in `domain-configs`, so the model improvised after the caller spoke first. It is the same absence agent, just off-script.
3. **Transcript text arrives truncated.** Several agent turns are stored as partial sentences even before the 60-second cut, so the platform's transcript is not a faithful record of what was said.
4. **Outcome/summary columns are empty on the completed calls** — the campaign dashboard can show `completed` but nothing about what was learned.

---

*Generated from the production database (Neon) on 22 Oct 2026, 22:27 IST. Event trails per call: call 25: vobiz_answer, hangup_request_early, hangup, worker_error, completed; call 27: vobiz_answer, vobiz_answer_terminal:busy; call 28: vobiz_answer, vobiz_stream:StartStream, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, vobiz_answer, vobiz_answer_terminal:completed; call 29: vobiz_answer, vobiz_stream:StartStream, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, voice_activity, vobiz_answer, vobiz_answer_terminal:completed, voice_activity; call 30: vobiz_answer, vobiz_answer_terminal:busy.
