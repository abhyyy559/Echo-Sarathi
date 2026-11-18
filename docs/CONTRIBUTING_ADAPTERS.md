# Adding a provider adapter

EchoSarathi is BYOK: speech-to-text, text-to-speech, the LLM and telephony are
all swappable. No model is trained or bundled here.

## 1. Implement the protocol

Create `voice-agent/app/providers/<role>/<name>.py` and implement the matching
protocol from `app/providers/base.py`:

- `STTProvider` — `name: str`, `build() -> Any` returning a LiveKit-compatible STT.
- `TTSProvider` — `name: str`, optional `multilingual_voice_id: str | None`,
  `build() -> Any`. Set `multilingual_voice_id` when one voice id speaks every
  language your agent uses; this is what keeps Tenglish code-switching in one voice.
- `LLMProvider` — `name: str`, `build() -> Any`.
- `TelephonyProvider` — `name: str`, `build() -> Any`.

## 2. Register it

In `app/pipeline.py`, add your `ProviderSpec` to `_register_builtin_providers()`
(or call `register_provider(ProviderSpec(...))` from your module at import).

## 3. Select it

```
STT_PROVIDER=<name>          TTS_PROVIDER=<name>
LLM_PROVIDER=<name>          TELEPHONY_PROVIDER=<name>
```

Per-language overrides are additive: `TTS_PROVIDER_TE=<name>`,
`STT_PROVIDER_HI=<name>`. Existing variables (`SARVAM_API_KEY`,
`DEEPGRAM_API_KEY`, `GROQ_API_KEY`, …) keep working.

## 4. Test it

Add a contract test under `voice-agent/tests/` using a fake `build()` that
returns a sentinel object. Assert `isinstance(adapter, STTProvider)` (or the
matching protocol) and that `select_provider(...)` resolves to your name with
the right reason (`global`, `language-override`, `default`).

## 5. Rules

- Never put API keys in code, tests, docs or commits. Read them from `Settings`
  / environment only.
- Do not change the call-finalization or billing contracts.
- Keep a failing provider degradable: the session speaks an apology and posts
  `status=error` instead of crashing.
