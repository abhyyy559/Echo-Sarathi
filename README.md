# Voice Agent Runtime (LiveKit Workers)

Cascaded real-time voice pipeline: **Deepgram STT (nova-3, en) → LLM tool-calling
(Groq `llama-3.3-70b-versatile`, OpenAI `gpt-4o-mini` fallback) → Cartesia TTS**,
orchestrated by [LiveKit Agents](https://docs.livekit.io/agents/) (Python).

This phase the worker handles **browser playground rooms only**
(`playground-*` prefix). Jobs for any other room prefix are closed gracefully.

> ⚠️ **No telephony happens here this phase. NO Twilio (or Plivo/Exotel) calls
> are placed by this runtime.** The Twilio Media Streams protocol helper
> (`app/twilio_protocol.py`) is kept dormant on purpose.

## Layout

```
agent.py               LiveKit Worker entrypoint (`cli.run_app`)
app/config.py          env-driven settings (.env loaded, no keys in code)
app/backend_client.py  backend internal API client (30s config cache)
app/prompting.py       pure system-prompt renderer (offline unit-tested)
app/extraction_tools.py extraction bookkeeping + tool logic (FR-12 escalation)
app/pipeline.py        AgentSession wiring, latency telemetry, degradation
tests/                 offline pytest suite (no network, FakeBackendClient)
```

## Required environment variables

Copy the repo-root `.env.example` to `.env` and fill in:

| Variable | Required | Notes |
|---|---|---|
| `LIVEKIT_URL` | yes | e.g. `ws://localhost:7880` for local dev |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | yes | dev server defaults: `devkey` / `secret` |
| `DEEPGRAM_API_KEY` | yes* | missing ⇒ STT disabled, session degrades |
| `CARTESIA_API_KEY` | yes* | missing ⇒ TTS disabled, session degrades |
| `GROQ_API_KEY` | one of these* | Groq preferred; if absent, falls back to OpenAI |
| `OPENAI_API_KEY` | one of these* | fallback LLM provider |
| `INTERNAL_API_TOKEN` | yes | must match backend's value; sent as `X-Internal-Token` |
| `BACKEND_INTERNAL_URL` | no | default `http://localhost:8000` |
| `GROQ_MODEL`, `OPENAI_MODEL`, `LOG_LEVEL` | no | sane defaults |

\* "Required" for a *working* conversation. A missing key never crashes the
worker: it logs a clear error, joins the room, speaks an apology line through
whatever TTS is configured, and posts `/internal/calls/{call_id}/complete`
with `status=error`.

## Smoke test against a local LiveKit server

1. **Start a dev LiveKit server** (no cloud account needed):

   ```powershell
   docker run --rm -p 7880:7880 -p 7881:7881 livekit/livekit-server --dev --bind 0.0.0.0
   ```

   (or install the binary and run `livekit-server --dev`).

2. **Start the FastAPI backend** (repo root):

   ```powershell
   uvicorn app.main:app --reload --port 8000   # from backend/, with .env filled
   ```

3. **Run the voice worker**:

   ```powershell
   cd voice-agent
   python agent.py dev        # or: python agent.py start
   ```

4. **Create a playground session** via the frontend (Agents → Playground) or:

   ```powershell
   # POST http://localhost:8000/api/playground/sessions {"agent_version_id": <id>}
   # -> { call_id, room_name ("playground-<org>-<uuid>"), livekit_token }
   ```

   Join with the browser mic; talk to the agent. On disconnect the worker
   posts transcript turns, extracted fields, and completion to the backend.

5. **Verify**: check backend logs / DB rows in `transcripts`,
   `extracted_fields`, `calls`; watch the worker console — every completed
   exchange prints ONE structured line:
   `{"event": "turn_latency", "stt_final_ms": ..., "llm_first_token_ms": ...,
   "tts_first_audio_ms": ..., "e2e_ms": ...}`.

## Latency glossary (per exchange)

| Field | Meaning | Target (NFR-1) |
|---|---|---|
| `stt_final_ms` | end-of-speech → final user transcript = LiveKit **EOU delay only** (P0-1) | — |
| `transcription_delay_ms` | Deepgram STT finalization lag, logged separately from EOU (P0-1) | — |
| `llm_first_token_ms` | LLM time-to-first-token | — |
| `tts_first_audio_ms` | TTS time-to-first-audio-byte | — |
| `e2e_ms` | approximated speech-to-speech = stt + llm + tts above | median ≤900ms, P95 ≤1.5s |

### Deepgram endpointing tuning (P0-1)

Introspected `livekit-plugins-deepgram` 1.7.0 via
`inspect.signature(deepgram.STT)`: there is **no `endpointing` kwarg** — the
plugin spells it **`endpointing_ms`**, and its default (`25` ms) is a
hair-trigger that can fragment speech into premature finals. The pipeline
constructs STT with `endpointing_ms=200`. If a future plugin version renames
the kwarg again, re-check with:

```powershell
voice-agent\.venv\Scripts\python.exe -c "import inspect; from livekit.plugins import deepgram; print(inspect.signature(deepgram.STT))"
```

## Extraction & escalation rules (FR-12)

- The LLM records values only through the `record_extracted_field` tool with an
  honest confidence.
- Confidence `< 0.6`, or a required field unfilled after **3 asks** ⇒ the agent
  wraps up gracefully and flags it. Values are **never fabricated**.

## Tests (offline, no network)

```powershell
python -m pytest voice-agent/tests -v
```

---

## Note: running this worker via docker compose (devops lane)

The repo-root `infra/docker-compose.yml` builds and runs this worker as the
`voice-agent` service with:

- `LIVEKIT_URL=ws://livekit:7880` - inside the compose network the worker must
  use the `livekit` service DNS name. This is intentionally different from the
  browser-facing URL (`ws://localhost:7880`) that the *backend* bakes into
  playground tokens.
- `BACKEND_INTERNAL_URL=http://backend:8000` and `INTERNAL_API_TOKEN` matching
  the backend service (dev default: `change_me_internal`).
- Provider keys passed through from `.env` (`DEEPGRAM_API_KEY`,
  `CARTESIA_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`); missing keys degrade
  sessions exactly as described above.
- Command: `python agent.py` (this entrypoint starts the worker directly - no
  `dev`/`start` subcommand needed).

Full runbook, `.env` checklist, and troubleshooting: see `README_SETUP.md`
at the repo root.
