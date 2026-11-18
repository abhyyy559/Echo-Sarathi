# Architecture Review — ai-voice-calling-agent (LiveKit worker)

Wave-1 audit, read-only. Senior Architect perspective. No application code was
changed; findings and suggestions are advisory. Reviewed: `voice-agent/agent.py`,
`voice-agent/app/{config,pipeline,rooms,backend_client}.py`, `requirements.txt`,
and the existing `docs/ARCHITECTURE.md` contract.

## Pipeline map (one call, end to end)

```
PSTN caller -- Vobiz/Twilio --> provider media WS (8 kHz mu-law)
   --> backend bridge --> LiveKit room "phone-<call_id>"
Browser playground mic -------------------------------> room "playground-<id>"
                              |
                              v
agent.py entrypoint -> is_handled_room() -> run_session(ctx, settings)
  1. Metadata: room attrs or joining participant JWT -> parse_room_metadata
     (version_id, call_id, contact). Missing => graceful _degrade + close.
  2. GET /internal/agent-config?version_id= (BackendClient, 30s cache)
     -> prompt + voice_settings (llm_model / tts_voice_id overrides).
  3. Audio input: Hush voice-focus (or optional ai_coustics), RoomOptions.
     Phone rooms pin agent output to 8 kHz; browser rooms keep 24 kHz.
  4. STT: Deepgram Nova-3 (English, endpointing_ms=300)
          OR Sarvam Saaras v4 (Indian languages, codemix, flush_signal,
             turn_detection="stt", no separate VAD). Toggle via STT_PROVIDER /
             STT_LANGUAGE_ROUTING.
  5. Turn taking: Smart Turn v3 ONNX (local, shared ~9 MB weights)
          -> inference.TurnDetector v1-mini -> "vad" (last resort).
     Endpointing floor 0.30 s / ceiling 2.50 s (0.07 s for Sarvam STT);
     VAD interruption with 0.35 s / 1-word gate and resume-on-false-interrupt.
  6. LLM: FallbackLLM ordered chain, in-turn failover with cooldown:
     LLM_PRIMARY_CHAIN (e.g. Sarvam 105B fast path)
       -> Groq pool (one client/key, qwen/qwen3.8-27b,
          max_completion_tokens=300, 90 s per-key cooldown, shared-TPM detection)
       -> Groq secondary (gpt-oss-120b)
       -> overflow (LLM_FALLBACK_CHAIN, DeepSeek, OpenAI, Cerebras, OpenRouter).
     Silent tool calls get one short spoken filler; _speak_chunk_content scrubs
     unpronounceable markdown for phone TTS.
  7. Agent: render_system_prompt (disclosure first, verify-then-continue),
     DomainCallAgent + VoiceAgentTools / ExtractionCoordinator; end_call only
     when required fields covered or caller ends. Preemptive generation is
     LLM-only (preemptive_tts=False), disabled by default on phone rooms.
  8. TTS: Sarvam Bulbul v3 (Indic, mu-law for phone / mp3 for browser, 8 kHz)
          -> Cartesia (English default, voice/pronunciation dict/speed)
          -> Deepgram Aura (same key, fallback on Cartesia 402).
     bundle.tts.prewarm() hides the cold WebSocket handshake.
  9. Egress: audio back the same route to the caller.
 10. Telemetry: TurnTelemetry logs one EOU/STT/LLM/TTS line per exchange,
     publishes captions via data channel, and posts transcript turns,
     extracted fields, activity, completion and diagnostics to the backend
     internal API (best-effort). UsageReporter records LLM quota headers.
     _CallEndWatcher closes the job on disconnect / session close / 1800 s cap.
```

Configuration is immutable `Settings` from env (`.env` loaded), with a cached
snapshot. Missing *required* vars (LiveKit URL/keys, INTERNAL_API_TOKEN) degrade
the call; missing *provider* keys also make `bundle.complete` false and close it.

## Top 3 risks

1. **Free-only deployment is blocked by STT/TTS.** `bundle.complete` requires an
   STT + LLM + TTS provider. STT comes only from Deepgram (paid key) or Sarvam
   (paid key); TTS only from Cartesia, Sarvam or Deepgram — all keyed, usage
   billed. With zero paid keys the worker logs "Provider problem" and calls
   `_degrade()`; no call can complete. Groq's free tier covers the LLM only.
   There is no open/local speech stage in `requirements.txt`.
2. **One 3,423-line `pipeline.py` is a single blast radius.** Provider
   construction, the multi-key FallbackLLM/cooldown state machine, prompt tool
   wiring, telemetry, captions and session lifecycle all live in one module.
   Failover correctness depends on env hygiene (placeholder keys are filtered,
   DeepSeek 402 is treated as an exhausted member, Groq keys share one TPM
   bucket). A small mistake in chain ordering or a per-member httpx pool
   teardown can silence every call; the regression surface is very large.
3. **Backend writes are fire-and-forget, so reporting/billing data can be lost
   silently.** `post_turns`, `post_fields`, `post_activity`, `complete` and
   telemetry events return `False` and only log on failure — no spool, no retry.
   A backend blip during a completed call leaves a transcript/cost gap in the
   DB while the call itself looked healthy. PII masking in logs is listed as a
   Phase-2 reservation, not implemented.

## 3 safe improvements (advisory, no changes made)

1. Introduce an **optional free STT/TTS tier** behind the existing
   `ProviderBundle` interface (e.g. local faster-whisper/Vosk + Piper or
   espeak-ng-class TTS, or an OpenAI-compatible free endpoint), enabled by a
   new opt-in env flag. This leaves the pipeline, turn handling and telemetry
   untouched and lets a zero-paid-key deployment reach `bundle.complete`.
2. **Split `pipeline.py`** into `providers.py`, `turn_handling.py`,
   `telemetry.py` and `session.py` with behavior-preserving moves, guarded by
   the existing ~30 worker tests. Add focused contract tests for
   `FallbackLLM` cooldown/failover and placeholder-key filtering first.
3. Make backend posts **durable**: a small on-disk spool plus bounded retry for
   turns/fields/activity/complete, and a counter/alert for dropped writes, so
   a transient backend failure cannot corrupt call history or cost reporting.

## Paid vs free external services — honest note for a free-only build

Free / self-hosted (no per-minute fee; some need a free signup key):
- LiveKit server — open source, self-hosted here (`LIVEKIT_URL_INTERNAL`);
  LiveKit Cloud is paid.
- Smart Turn v3 (`smart-turn-livekit`), Silero VAD, Hush / ai-coustics
  voice-focus — bundled local models, no usage fee.
- Groq — free rate-limited tier (the 8,000 TPM org bucket is the source of the
  cooldown logic); Cerebras and OpenRouter free models are configured as
  optional overflow. OpenAI-compatible keys are still required.
- Vercel / Render free tiers exist for hosting but are outside the call path.

Paid / requires an API key and is usage billed (free trial credits, not a
standing free tier):
- **Deepgram** (Nova-3 STT + Aura TTS) — key required, billed per audio minute.
- **Cartesia** (English TTS) — key required, billed per character; returns 402
  when the balance is exhausted (the Deepgram Aura fallback exists for this).
- **Sarvam** (Saaras STT + Bulbul TTS + 105B LLM) — key required (`SARVAM_TTS_API`
  is present in this env), India API billed per use.
- **OpenAI** (GPT-4o-mini), **DeepSeek** — paid, key required.
- **Twilio / Vobiz** PSTN — per-minute charges; India numbers need KYC/DLT.
- Current `.env` arms Deepgram, Cartesia, Sarvam, Groq and OpenAI; no free-only
  STT/TTS path is configured. Switching to free-only requires new local speech
  components — a code change, explicitly out of scope for this audit.
