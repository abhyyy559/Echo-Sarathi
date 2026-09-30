"""Sarvam Bulbul TTS as a LiveKit Agents provider.

WHY SARVAM: Cartesia (the previous TTS) returns HTTP 402 when its balance runs
out, which silenced the agent entirely. Sarvam is India-first (en-IN voices
including a ``priya`` voice that matches our agent persona), runs on a
separate key/quota from every other provider, and was verified live
(bulbul:v3, 16kHz WAV with real audio energy) before this was written.

Sarvam's API is request/response REST, not a streaming websocket, so this is a
non-streaming (chunked) TTS: one REST call per sentence. That adds ~300-600ms
versus streaming TTS, but it is honest audio on every turn instead of silence.
The framework adapts chunked TTS for streaming playback automatically.

Selection: TTS_PROVIDER=sarvam (or SARVAM_TTS_API set with no Cartesia key).
Model/voice/language come from SARVAM_TTS_MODEL, SARVAM_TTS_SPEAKER,
SARVAM_TTS_LANG, overridable per agent via voice_settings.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass

import aiohttp

from livekit.agents import tts
from livekit.agents.llm.llm import APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS

logger = logging.getLogger("voice_agent.tts_sarvam")

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
DEFAULT_MODEL = "bulbul:v3"
DEFAULT_SPEAKER = "priya"
DEFAULT_LANG = "en-IN"
DEFAULT_SAMPLE_RATE = 16000


def _strip_wav_header(raw: bytes) -> bytes:
    """Sarvam returns a WAV container; LiveKit wants raw PCM."""
    if raw[:4] == b"RIFF":
        marker = raw.find(b"data")
        if marker > 0:
            return raw[marker + 8 :]
    return raw


@dataclass
class SarvamTTSOptions:
    api_key: str
    model: str = DEFAULT_MODEL
    speaker: str = DEFAULT_SPEAKER
    language: str = DEFAULT_LANG
    sample_rate: int = DEFAULT_SAMPLE_RATE


class SarvamTTS(tts.TTS):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        speaker: str = DEFAULT_SPEAKER,
        language: str = DEFAULT_LANG,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        if not api_key:
            raise ValueError("Sarvam API key required (SARVAM_TTS_API).")
        self._opts = SarvamTTSOptions(
            api_key=api_key,
            model=model,
            speaker=speaker,
            language=language,
            sample_rate=sample_rate,
        )
        self._session = http_session
        self._owns_session = http_session is None

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "SarvamChunkedStream":
        return SarvamChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None


class SarvamChunkedStream(tts.ChunkedStream):
    def __init__(
        self, *, tts: SarvamTTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._sarvam: SarvamTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        opts = self._sarvam._opts
        text = (self._input_text or "").strip()
        if not text:
            return
        session = self._sarvam._session
        owned = False
        if session is None:
            session = aiohttp.ClientSession()
            owned = True
        try:
            last_error: Exception | None = None
            for attempt in range(1 + self._conn_options.max_retry):
                try:
                    async with session.post(
                        SARVAM_TTS_URL,
                        headers={
                            "api-subscription-key": opts.api_key,
                            "Content-Type": "application/json",
                        },
                        json={
                            "inputs": [text],
                            "target_language_code": opts.language,
                            "speaker": opts.speaker,
                            "model": opts.model,
                            "speech_sample_rate": opts.sample_rate,
                            "enable_preprocessing": True,
                        },
                        timeout=aiohttp.ClientTimeout(total=self._conn_options.timeout),
                    ) as resp:
                        if resp.status != 200:
                            body = (await resp.text())[:200]
                            raise tts.TTSError(
                                f"Sarvam TTS failed ({resp.status}): {body}"
                            )
                        payload = await resp.json()
                    audios = payload.get("audios") or []
                    if not audios:
                        raise tts.TTSError("Sarvam TTS returned no audio")
                    pcm = _strip_wav_header(base64.b64decode(audios[0]))
                    if not pcm:
                        raise tts.TTSError("Sarvam TTS returned empty audio")
                    output_emitter.push(pcm)
                    output_emitter.flush()
                    return
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    logger.warning(
                        "Sarvam TTS attempt %d failed: %s", attempt + 1, exc
                    )
                    await asyncio.sleep(self._conn_options.retry_interval)
            raise tts.TTSError(f"Sarvam TTS unreachable: {last_error}")
        finally:
            if owned:
                await session.close()
