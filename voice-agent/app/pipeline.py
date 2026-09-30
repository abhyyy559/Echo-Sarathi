"""Cascaded STT -> LLM -> TTS AgentSession pipeline (LiveKit Agents 1.x).

Flow for an accepted job:

1. Parse room metadata ``{"version_id": ..., "call_id": ...}``.
2. Build Deepgram STT / Groq-or-OpenAI LLM / Cartesia TTS providers
   (graceful degradation with clear logs if a key is missing).
3. Fetch the agent-version config from the backend internal API (30s cache)
   and render the system prompt (disclosure first).
4. Run the AgentSession with VAD barge-in, per-turn latency instrumentation,
   function tools for extraction and call end.
5. Post transcript/latency turns per completed exchange and finalize the call.

This module is only importable where ``livekit-agents`` is installed; the
offline-tested logic lives in ``app.prompting`` / ``app.extraction_tools``.
"""

from __future__ import annotations

import asyncio
import os
import inspect
import json
import logging
import math
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from livekit.agents import (
    Agent,
    AgentSession,
    EndpointingOptions,
    InterruptionOptions,
    JobContext,
    TurnHandlingOptions,
    function_tool,
    llm,
    stt as stt_module,
    tts as tts_module,
)
from livekit.agents.llm.llm import APIConnectOptions
from livekit.plugins import cartesia, deepgram, openai, silero

from app.backend_client import BackendClient, BackendError
from app.config import Settings
from app.extraction_tools import (
    LOW_CONFIDENCE_THRESHOLD,
    MAX_ASKS_PER_FIELD,
    ExtractionCoordinator,
    VoiceAgentTools,
)
from app.prompting import build_opening_line, build_token_map, render_system_prompt, scrub_speech_text

logger = logging.getLogger("voice_agent.pipeline")

try:  # livekit-agents >= 1.8: preemptive generation takes an options mapping
    from livekit.agents.voice.turn import (
        PreemptiveGenerationOptions as _PreemptiveOpts,
    )
except ImportError:  # 1.7.x and older: plain boolean flag
    _PreemptiveOpts = None  # type: ignore[assignment]

try:
    from livekit.agents import inference as _inference
except ImportError:  # very old SDKs without the inference module
    _inference = None  # type: ignore[assignment]

try:
    from smart_turn_livekit import SmartTurnDetector as _SmartTurnDetector
except ImportError:  # offline tests / minimal installs: v1-mini fallback below
    _SmartTurnDetector = None  # type: ignore[assignment]

PLAYGROUND_PREFIX = "playground-"
PHONE_PREFIX = "phone-"
APOLOGY_TEXT = (
    "Hello, this is an automated assistant. We're sorry, but we're unable to "
    "continue this call right now due to a technical problem. Goodbye."
)
ACTIVITY_SOURCE = "livekit-1.8.3"


# --------------------------------------------------------------------------
# Job parsing / provider construction
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedJob:
    """Identity of the call behind a LiveKit room."""

    version_id: Any
    call_id: str
    # P0-2: flat contact card packed by the backend at session/call creation;
    # rendered into the system prompt's CALLER CONTEXT section.
    contact: Optional[Mapping[str, Any]] = None


def parse_room_metadata(raw: Any) -> Optional[ParsedJob]:
    """Parse ``{"version_id", "call_id", "contact": {...}}`` room metadata defensively."""
    if not raw:
        return None
    meta: Any = raw
    if isinstance(raw, str):
        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Room metadata is not valid JSON: %r", raw[:200])
            return None
    if not isinstance(meta, Mapping):
        return None
    version_id = meta.get("version_id")
    call_id = str(meta.get("call_id") or "").strip()
    if version_id is None or not call_id:
        return None
    contact = meta.get("contact")
    return ParsedJob(
        version_id=version_id,
        call_id=call_id,
        contact=contact if isinstance(contact, Mapping) else None,
    )


@dataclass
class ProviderBundle:
    """Constructed providers plus human-readable degradation problems."""

    stt: Optional[stt_module.STT]
    llm: Optional[llm.LLM]
    tts: Optional[tts_module.TTS]
    problems: list[str] = field(default_factory=list)
    # Which STT backend is armed (deepgram | sarvam). The session is tuned
    # differently per provider (Sarvam handles VAD/turn-taking internally).
    stt_provider: str = "deepgram"

    @property
    def complete(self) -> bool:
        return self.stt is not None and self.llm is not None and self.tts is not None


def _voice_overrides(voice_settings: Optional[Mapping[str, Any]]) -> tuple[str, str, dict[str, str], str]:
    """Extract (llm_model, tts_voice_id, voices_by_language, language) from saved settings.

    Falls back to empty strings / empty dict / "en" for missing keys.
    """
    vs = voice_settings or {}
    get = vs.get if isinstance(vs, Mapping) else (lambda k, d=None: getattr(vs, k, d))
    llm_model = str(get("llm_model", "") or "").strip()
    tts_voice = str(get("tts_voice_id", "") or "").strip()
    vbl = dict(get("voices_by_language", {}) or {})
    lang = str(get("language", "en") or "en").lower()
    return llm_model, tts_voice, vbl, lang


def _cartesia_speed(speaking_rate: Any) -> Optional[float]:
    """Map the platform speaking_rate onto Cartesia's speed multiplier.

    Platform range is 0.5-2.0 (1.0 = normal); Cartesia accepts 0.6-1.5, so
    clamp. Returns None at ~normal so the API default applies untouched.
    """
    try:
        rate = float(speaking_rate)
    except (TypeError, ValueError):
        return None
    if abs(rate - 1.0) < 0.05:
        return None
    return min(1.5, max(0.6, rate))


#: HTTP statuses worth failing over for (rate limits, overload, timeouts).
#: Anything else (400s like bad-model/shape, 401s) is a config bug — retrying
#: on another provider would just fail differently.
_RETRYABLE_LLM_STATUS: frozenset = frozenset({None, 408, 425, 429, 500, 502, 503, 504})


class FallbackLLM(llm.LLM):
    """Ordered LLM chain with per-member cooldown (ARCHITECTURE.md S5).

    Same-tier, different-provider/key: every member must sound like the same
    agent. ``primary`` is one LLM or an ordered list (e.g. one Groq client
    per API key); ``fallback`` (e.g. OpenAI) is appended last when given.
    The session calls chat() per turn and retries it on failure; chat()
    always serves the first member whose cooldown expired (else the first
    member, better than silence). On a retryable serving failure the proxy
    below marks THAT member down and re-raises, so the session retry
    transparently moves to the next key/provider. This object never retries
    inside a stream: no duplicated prefixes, no re-implemented machinery.

    Backward compatible: ``FallbackLLM(primary, fallback)`` behaves exactly
    as before; ``FallbackLLM([k1, k2], openai_llm)`` rotates Groq keys.
    """

    def __init__(
        self,
        primary: Any,
        fallback: Any = None,
        cooldown_s: float = 90.0,
        provider_names: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        if isinstance(fallback, (int, float)) and not isinstance(fallback, bool):
            cooldown_s = float(fallback)
            fallback = None
        if fallback is not None:
            members = [primary, fallback]
        elif isinstance(primary, (list, tuple)):
            members = list(primary)
        else:
            members = [primary]
        if not members:
            raise ValueError("FallbackLLM needs at least one chain member")
        self._chain: list[Any] = members
        self._cooldown_s = cooldown_s
        self._down_until: list[float] = [0.0] * len(members)
        self.last_served_index: int = 0
        # Provider label per member ("groq", "gemini", ...), same order as the
        # chain. A 429 on one member usually means the whole PROVIDER bucket is
        # empty (Groq's TPM is org-wide), so the remaining keys of that
        # provider are skipped instead of burned one by one. Members WITHOUT an
        # explicit label each get a unique one, so they keep the old per-key
        # cooldown behaviour instead of being lumped into one bucket.
        if provider_names is None:
            provider_names = [f"member-{index}" for index in range(len(members))]
        self._providers: list[str] = list(provider_names)

    @property
    def last_served_model(self) -> str:
        """Model name of the member that served the most recent turn."""
        try:
            return str(getattr(self._chain[self.last_served_index], "model", "?"))
        except Exception:
            return "?"

    @property
    def model(self) -> str:
        return getattr(self._chain[0], "model", "fallback-llm")

    @property
    def chain_size(self) -> int:
        """Number of keys/providers in the rotation (observability)."""
        return len(self._chain)

    def _pick_member(self) -> int:
        now = time.monotonic()
        for index, down_until in enumerate(self._down_until):
            if now >= down_until:
                return index
        return 0  # all cooling down: serve the first rather than silence

    def _mark_down(self, index: int) -> None:
        self._down_until[index] = time.monotonic() + self._cooldown_s

    def _mark_provider_down(self, provider: str) -> int:
        """Cool down every member of one provider. Returns how many skipped.

        A 429 on one key almost always means the provider's shared bucket
        (org-wide TPM) is empty; the sibling keys would fail identically, so
        trying them burns seconds of the caller's time for nothing.
        """
        now = time.monotonic()
        skipped = 0
        for index, name in enumerate(self._providers):
            if name == provider and now >= self._down_until[index]:
                self._down_until[index] = now + self._cooldown_s
                skipped += 1
        return skipped

    def _chat_kwargs(
        self, chat_ctx: llm.ChatContext, tools: Optional[list],
        conn_options: Optional[Any], kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {"chat_ctx": chat_ctx, "tools": tools}
        if conn_options is not None:
            merged["conn_options"] = conn_options
        merged.update(kwargs)
        return merged

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: Optional[list] = None,
        conn_options: Optional[Any] = None,
        **kwargs: Any,
    ) -> llm.LLMStream:
        index = self._pick_member()
        member = self._chain[index]
        # Remember who served, so turn telemetry can attribute the reply the
        # same way text mode does ("served by" per turn).
        try:
            previous = getattr(self, "last_served_index", 0)
            self.last_served_index = index
        except Exception:
            previous = 0
        # Cross-model continuity (mirrors text mode's handoff brief). When
        # failover moves the call to another provider/model, that model has
        # none of the previous model's context and restarts the conversation.
        # Inject a brief as the leading system message so the new model
        # continues instead of re-introducing itself. Same-model turns are
        # untouched.
        if index != previous:
            chat_ctx = _with_handoff_brief(chat_ctx, previous, index)
        if index > 0 or len(self._chain) > 1:
            logger.info(
                "LLM chain serving member %d/%d", index + 1, len(self._chain)
            )
        # Fail FAST on every member (max 1 quick attempt): the session calls
        # chat() again on failure and the chain advances to the next key. The
        # SDK default (3 retries x 2s + gateway retries) turned one Groq 429
        # into ~13s of dead air before the fallback was even tried.
        conn_options = APIConnectOptions(
            # Fail fast: a hung provider must surface in seconds, not tens of
            # seconds. The stall watchdog speaks a filler at 4s, so the member
            # timeout must be well under that for the chain to have moved on.
            max_retry=1, retry_interval=0.5, timeout=8.0
        )
        member_stream = member.chat(
            **self._chat_kwargs(chat_ctx, tools, conn_options, kwargs)
        )
        return _FallbackStream(self, member_stream, index)


def _with_handoff_brief(
    chat_ctx: Any, previous_index: int, current_index: int
) -> Any:
    """Prepend a continuity brief when failover switches models mid-call.

    Without this the new model re-introduces itself and re-asks answered
    questions, because it genuinely does not know the conversation. The brief
    is one system message stating the switch happened and that captured fields
    (carried in the shared extraction coordinator, not in any one model) stand
    as established. Never raises: a failed brief must not break the turn.
    """
    try:
        from livekit.agents.llm import ChatMessage

        brief = (
            "CONTINUITY: you took over this call mid-conversation from another "
            "model that stopped responding. Do NOT introduce yourself again, do "
            "NOT re-disclose, and do NOT re-ask anything already answered. "
            "Anything already recorded stands as established. Continue naturally "
            "as if you had been on the call the whole time."
        )
        items = list(getattr(chat_ctx, "items", []) or [])
        return chat_ctx.copy(items=[ChatMessage(role="system", content=[brief]), *items])
    except Exception:
        return chat_ctx


class _FallbackStream(llm.LLMStream):
    """LLMStream proxy that observes failures; never retries itself.

    On a retryable serving-member failure it marks THAT member down for
    cooldown and re-raises, so the session retry gets a concrete stream
    from the next key/provider in the chain.
    """

    def __init__(
        self, owner: FallbackLLM, primary_stream: llm.LLMStream, member_index: int = 0
    ) -> None:
        super().__init__(
            owner,
            chat_ctx=primary_stream.chat_ctx,
            tools=list(primary_stream.tools),
            conn_options=APIConnectOptions(),
        )
        self._owner = owner
        self._active = primary_stream
        self._member_index = member_index

    async def _run(self) -> None:
        # Abstract hook required by llm.LLMStream. This proxy never drives
        # it — iteration delegates to the wrapped concrete stream.
        return None

    async def __anext__(self) -> Any:
        try:
            return await self._active.__anext__()
        except StopAsyncIteration:
            raise
        except Exception as exc:  # noqa: BLE001 — classify, then maybe fail over
            status = getattr(exc, "status_code", None)
            if status not in _RETRYABLE_LLM_STATUS:
                raise
            if status == 429:
                # Shared bucket: skip the provider's remaining keys now.
                provider = self._owner._providers[self._member_index] if (
                    0 <= self._member_index < len(self._owner._providers)
                ) else "?"
                skipped = self._owner._mark_provider_down(provider)
                logger.warning(
                    "LLM chain member %d 429 (%s); skipping %d sibling(s) on the exhausted bucket",
                    self._member_index + 1,
                    provider,
                    max(skipped - 1, 0),
                )
            else:
                logger.warning(
                    "LLM chain member %d failed (%s), cooling down for next member",
                    self._member_index + 1,
                    status or "connection-error",
                )
                self._owner._mark_down(self._member_index)
            raise

    async def aclose(self) -> None:
        try:
            await self._active.aclose()
        except Exception:  # noqa: BLE001 — best effort
            pass


#: Output caps. A REASONING model (gpt-oss) spends its output budget thinking
#: before it emits anything; measured with the real system prompt and the tool
#: schema, gpt-oss-20b truncated at 160 returned completion=160 with EMPTY
#: content and no tool call, which is the "agent goes silent mid-call" symptom.
#: Non-reasoning models (qwen3.8-27b: 60 tokens, 686ms) need far less, which
#: also matters because Groq caps output tokens per minute per organization.
#: NOTE: qwen3 is deliberately NOT listed - it does not think out loud.
_REASONING_MODEL_MARKERS = ("gpt-oss", "deepseek-r1", "reasoner", "o1-", "o3-")
_DEFAULT_MAX_COMPLETION_TOKENS = 300
_REASONING_MAX_COMPLETION_TOKENS = 500


def _max_completion_tokens_for(model: str) -> int:
    """Output budget that lets the model finish instead of truncating."""
    lowered = str(model or "").lower()
    if any(marker in lowered for marker in _REASONING_MODEL_MARKERS):
        return _REASONING_MAX_COMPLETION_TOKENS
    return _DEFAULT_MAX_COMPLETION_TOKENS


def build_providers(
    settings: Settings,
    voice_settings: Optional[Mapping[str, Any]] = None,
) -> ProviderBundle:
    """Build STT/LLM/TTS from settings; missing keys degrade, never raise.

    ``voice_settings`` is the agent-version's saved config; when it carries a
    per-agent ``llm_model`` / ``tts_voice_id`` those override the platform
    defaults (GROQ_MODEL env / provider default voice).
    """
    bundle = ProviderBundle(stt=None, llm=None, tts=None)
    model_override, tts_voice_override, voices_by_lang, language = _voice_overrides(voice_settings)
    effective_voice = voices_by_lang.get(language) or tts_voice_override

    if settings.deepgram_api_key and os.getenv("STT_PROVIDER", "deepgram").lower() == "deepgram":
        stt_lang = str(
            (voice_settings or {}).get("stt_language", "en")
        ).strip().lower() or "en"
        # P0-1 endpointing tuning: the livekit-plugins-deepgram 1.8.3 kwarg is
        # ``endpointing_ms`` (introspected signature has NO ``endpointing``);
        # plugin default is a hair-trigger 25 ms which fragments speech.
        # 300ms (echo hardening): the agent's own looped-back TTS audio must
        # not hair-trigger a retrigger at the old 200ms.
        bundle.stt = deepgram.STT(
            model="nova-3",
            language=stt_lang,
            endpointing_ms=300,
            api_key=settings.deepgram_api_key,
        )
        bundle.stt_provider = "deepgram"
    elif os.getenv("STT_PROVIDER", "deepgram").lower() == "sarvam":
        # Sarvam Saaras STT (official LiveKit plugin, streaming). Indian-accent
        # accuracy is its strength over Nova; en-IN plus auto-detect via
        # language="unknown". flush_signal emits the speech start/end markers
        # the session needs for turn-taking. Requires SARVAM_TTS_API (same key
        # as TTS) - the plugin also accepts SARVAM_API_KEY.
        from livekit.plugins import sarvam as _sarvam_stt

        sarvam_key = os.getenv("SARVAM_TTS_API", "") or os.getenv("SARVAM_API_KEY", "")
        if not sarvam_key:
            bundle.problems.append("SARVAM_TTS_API missing - Sarvam STT disabled")
        else:
            sarvam_lang = str(
                (voice_settings or {}).get("stt_language", "")
            ).strip() or os.getenv("SARVAM_STT_LANG", "en-IN")
            # Sarvam requires BCP-47 (en-IN, hi-IN); our configs carry bare
            # codes ("en"). A bare code raises ValueError at STT construction
            # and degrades the whole session, so map the common ones.
            _SARVAM_LANG_ALIASES = {
                "en": "en-IN",
                "hi": "hi-IN",
                "ta": "ta-IN",
                "te": "te-IN",
                "bn": "bn-IN",
                "ml": "ml-IN",
                "mr": "mr-IN",
                "kn": "kn-IN",
                "gu": "gu-IN",
                "pa": "pa-IN",
            }
            sarvam_lang = _SARVAM_LANG_ALIASES.get(sarvam_lang.lower(), sarvam_lang)
            bundle.stt = _sarvam_stt.STT(
                language=sarvam_lang,
                model=os.getenv("SARVAM_STT_MODEL", "saaras:v4"),
                mode="transcribe",
                api_key=sarvam_key,
                flush_signal=True,
            )
            bundle.stt_provider = "sarvam"
            logger.info("STT provider: Sarvam Saaras (%s)", sarvam_lang)
    else:
        bundle.problems.append(
            "DEEPGRAM_API_KEY missing - speech-to-text disabled"
        )

    selected_tts = os.getenv("TTS_PROVIDER", "cartesia").lower()
    sarvam_key = os.getenv("SARVAM_TTS_API", "") or os.getenv("SARVAM_API_KEY", "")
    if selected_tts == "sarvam" and sarvam_key:
        # Official Sarvam LiveKit plugin (streaming Bulbul v3 over websocket,
        # pronunciation dicts, Indian voices). Replaces the earlier hand-rolled
        # REST TTS, which could not stream and raised "AudioEmitter isn't
        # started" inside the framework's adapter.
        from livekit.plugins import sarvam as _sarvam

        sarvam_model = (
            str((voice_settings or {}).get("tts_model", "") or "").strip()
            or os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
        )
        sarvam_speaker = (
            str((voice_settings or {}).get("tts_speaker", "") or "").strip()
            or os.getenv("SARVAM_TTS_SPEAKER", "priya")
        )
        sarvam_lang = (
            str((voice_settings or {}).get("tts_language", "") or "").strip()
            or os.getenv("SARVAM_TTS_LANG", "en-IN")
        )
        bundle.tts = _sarvam.TTS(
            target_language_code=sarvam_lang,
            model=sarvam_model,
            speaker=sarvam_speaker,
            api_key=sarvam_key,
        )
        logger.info(
            "TTS provider: Sarvam Bulbul (%s/%s/%s)", sarvam_model, sarvam_speaker, sarvam_lang
        )
    elif selected_tts == "cartesia" and settings.cartesia_api_key:
        tts_kwargs: dict[str, Any] = {}
        if effective_voice:
            tts_kwargs["voice"] = effective_voice
        # speaking_rate was previously collected but never applied; wire it
        # so slower/clearer speech (e.g. 0.9 for names) actually takes effect.
        speed = _cartesia_speed((voice_settings or {}).get("speaking_rate", 1.0))
        if speed is not None:
            tts_kwargs["speed"] = speed
        # Custom pronunciations (e.g. Indian names): per-agent voice setting
        # wins, platform env default applies to every agent without one.
        pron_dict = str((voice_settings or {}).get("pronunciation_dict_id", "") or "").strip()
        pron_dict = pron_dict or str(settings.cartesia_pronunciation_dict_id or "").strip()
        if pron_dict:
            tts_kwargs["pronunciation_dict_id"] = pron_dict
        bundle.tts = cartesia.TTS(api_key=settings.cartesia_api_key, **tts_kwargs)
    elif settings.deepgram_api_key:
        # Deepgram Aura fallback. Cartesia returns 402 when its balance runs
        # out (seen live: "Invalid response status", retryable=False), which
        # silences the agent even though everything else works. Aura runs on
        # the same Deepgram key as STT, so voice keeps working with zero new
        # accounts. TTS_PROVIDER=deepgram forces it; otherwise it is used
        # whenever Cartesia is not selected.
        aura_model = (
            str((voice_settings or {}).get("tts_model", "") or "").strip()
            or os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-thalia-en")
        )
        bundle.tts = deepgram.TTS(model=aura_model, api_key=settings.deepgram_api_key)
        logger.info("TTS provider: Deepgram Aura (%s)", aura_model)
    else:
        bundle.problems.append("CARTESIA_API_KEY missing - text-to-speech disabled")

    groq_model = model_override or settings.groq_model
    # Multi-key rotation: one client per API key (GROQ_API_KEY first,
    # then GROQ_API_KEYS). A 429/quota failure on one key cools THAT key
    # down for 90s while turns keep flowing on the next key — the call never
    # sits in silence because a single key hit its TPM cap.
    groq_keys = list(getattr(settings, "groq_api_keys", ()) or ())
    if not groq_keys and settings.groq_api_key:
        groq_keys = [settings.groq_api_key]
    groq_base_url = getattr(settings, "groq_base_url", None) or "https://api.groq.com/openai/v1"
    groq_llms: list[Any] = []
    if groq_keys:
        # Groq is an OpenAI-compatible endpoint, so construct it explicitly.
        # GROQ_BASE_URL can point at any compatible provider (Cerebras).
        kwargs: dict[str, Any] = {}
        if "gpt-oss" in groq_model.lower():
            # GPT-OSS rejects "none" (400: must be low/medium/high) — use the
            # minimum. Combined with a large-enough output budget, thinking
            # stays a short prefix before the spoken reply.
            kwargs["reasoning_effort"] = "low"
        # Voice turns are 1-3 sentences. The cap must be big enough for the
        # model to actually finish: a REASONING model spends its output budget
        # thinking first, and truncation at 160 returned an empty reply (that
        # is the "agent goes silent mid-call" symptom), while it also has to
        # stay under Groq's on_demand output-tokens/min tier or the call 429s.
        kwargs["max_completion_tokens"] = _max_completion_tokens_for(groq_model)
        for key in groq_keys:
            groq_llms.append(
                openai.LLM(
                    model=groq_model,
                    api_key=key,
                    base_url=groq_base_url,
                    **kwargs,
                )
            )
    if groq_llms:
        chain: list[Any] = list(groq_llms)
        chain_providers: list[str] = ["groq"] * len(groq_llms)
        # Extra OpenAI-compatible providers (LLM_FALLBACK_CHAIN, Cerebras,
        # OpenRouter). Same-tier, different provider: Groq's free tier caps
        # out mid-call, and the wrapper re-issues the identical request on the
        # next member instead of leaving the caller in silence.
        for name, base_url, api_key, model in settings.llm_fallback_chain:
            if not base_url:
                continue
            try:
                chain.append(
                    openai.LLM(
                        model=model,
                        api_key=api_key,
                        base_url=base_url,
                        max_completion_tokens=_max_completion_tokens_for(model),
                    )
                )
                chain_providers.append(name)
                logger.info("LLM chain member armed: %s (%s)", name, model)
            except Exception as exc:  # noqa: BLE001 — never block the chain
                logger.warning("LLM chain member %s rejected: %s", name, exc)
        if len(chain) > 1:
            logger.info(
                "LLM chain armed (%d members): %s (Groq x%d) + %s",
                len(chain),
                groq_model,
                len(groq_llms),
                ", ".join(
                    f"{name}:{model}" for name, _u, _k, model in settings.llm_fallback_chain
                )
                or "no extra members",
            )
            bundle.llm = FallbackLLM(chain, provider_names=chain_providers)
        else:
            bundle.llm = groq_llms[0]
    elif settings.llm_fallback_chain:
        # No Groq at all, but extra providers are configured: serve the call
        # rather than degrading to an apology.
        for name, base_url, api_key, model in settings.llm_fallback_chain:
            if not base_url:
                continue
            bundle.llm = openai.LLM(
                model=model, api_key=api_key, base_url=base_url
            )
            logger.info("GROQ_API_KEY missing - using %s (%s)", name, model)
            break
        if bundle.llm is None:
            bundle.problems.append("No usable LLM chain member (bad LLM_FALLBACK_CHAIN)")
    elif settings.openai_api_key:
        logger.info(
            "GROQ_API_KEY missing - falling back to OpenAI %s",
            settings.openai_model,
        )
        bundle.llm = openai.LLM(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    else:
        bundle.problems.append("No LLM key (GROQ_API_KEY / OPENAI_API_KEY) set")

    return bundle


# --------------------------------------------------------------------------
# Per-exchange latency + transcript telemetry
# --------------------------------------------------------------------------


#: Fire-and-forget tasks must stay referenced, or the event loop may
#: garbage-collect them mid-flight (asyncio.create_task docs). This set holds
#: every background task until it completes.
_BACKGROUND_TASKS: set["asyncio.Task[Any]"] = set()


def _spawn_task(coro: Coroutine[Any, Any, Any]) -> "asyncio.Task[Any]":
    """Schedule a coroutine as a strong-referenced background task."""
    task = asyncio.ensure_future(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


#: Backchannel utterances: brief "I'm listening" cues that take no turn.
BACKCHANNEL_PHRASES: tuple[str, ...] = ("mm-hmm", "right", "got it")
#: Minimum gap between cues — more frequent sounds mechanical, not human.
BACKCHANNEL_MIN_GAP_S = 6.0
#: Caller must hold the floor this long before the first cue is earned.
BACKCHANNEL_SPEAK_THRESHOLD_S = 2.5


class BackchannelController:
    """Injects listener cues ("mm-hmm") while the caller holds the floor.

    Pure timing logic over an injectable clock and say-callable, so it unit
    tests without LiveKit. Takes no turn: cues are short, interruptible, and
    never enter the LLM context — the model never knows they happened.
    """

    def __init__(self, say: Any, clock: Any = None) -> None:
        self._say = say
        self._clock = clock or time.monotonic
        self._speaking_since: Optional[float] = None
        self._last_at = float("-inf")
        self._idx = 0

    def on_user_speaking(self, speaking: bool) -> None:
        """Feed user-speech transitions from the session state events."""
        if speaking:
            if self._speaking_since is None:
                self._speaking_since = self._clock()
        else:
            self._speaking_since = None

    async def tick(self) -> bool:
        """Speak one cue if earned. Returns True when spoken."""
        now = self._clock()
        if self._speaking_since is None:
            return False
        if now - self._last_at < BACKCHANNEL_MIN_GAP_S:
            return False
        if now - self._speaking_since < BACKCHANNEL_SPEAK_THRESHOLD_S:
            return False
        phrase = BACKCHANNEL_PHRASES[self._idx % len(BACKCHANNEL_PHRASES)]
        self._idx += 1
        self._last_at = now
        try:
            await self._say(phrase)
        except Exception:  # noqa: BLE001 — a missed cue is harmless
            logger.debug("Backchannel cue failed", exc_info=True)
            return False
        return True


class TurnTelemetry:
    """Accumulates one exchange (user utterance + agent reply), posts it.

    Latency definitions (all milliseconds):
    - ``stt_final_ms``: end-of-speech -> final user transcript = LiveKit EOU
      metric ``end_of_utterance_delay`` ONLY (EOU decision time).
    - ``transcription_delay_ms``: Deepgram finalization lag
      (EOU metric ``transcription_delay``), logged separately so the two STT
      levers are distinguishable (P0-1).
    - ``llm_first_token_ms``: LLM time-to-first-token (``LLMMetrics.ttft``).
    - ``tts_first_audio_ms``: TTS time-to-first-audio-byte (``TTSMetrics.ttfb``).
    - ``e2e_ms``: approximated speech-to-speech =
      stt_final + llm_ttfb + tts_ttfb.

    Event wiring for livekit-agents 1.8.3: there is NO ``session.metrics``
    collector object on AgentSession — the session EMITS a single
    ``"metrics_collected"`` event whose payload wraps one AgentMetrics object
    per measurement (``MetricsCollectedEvent.metrics``), typed via its
    ``type`` discriminator ("eou_metrics" | "llm_metrics" | "tts_metrics").
    Field names verified against livekit.agents.metrics 1.8.3:
    EOUMetrics.end_of_utterance_delay/.transcription_delay,
    LLMMetrics.ttft (-1 when no token), TTSMetrics.ttfb.
    If the event shape ever changes again, wall-clock fallbacks below keep the
    columns populated (marked APPROXIMATION).
    """

    def __init__(
        self,
        session: AgentSession,
        backend: BackendClient,
        call_id: str,
        room: Any = None,
        on_final_user: Any = None,
        backchannel: Optional[BackchannelController] = None,
        extraction_tools: Any = None,
        llm: Any = None,
        agent: Any = None,
    ) -> None:
        self._session = session
        self._backend = backend
        self._call_id = call_id
        self._room = room
        self._on_final_user = on_final_user
        self._backchannel = backchannel
        self._extraction_tools = extraction_tools
        self._llm = llm
        self._agent = agent
        self._room_name = str(getattr(room, "name", "") or "")
        self._turn_index = 0
        self._flush_lock = asyncio.Lock()
        self._activity_sequence = 1
        self._activity_post_lock = asyncio.Lock()
        self._activity_seen_events: set[tuple[str, str, str, float]] = set()
        # Buffered for the backend Diagnostics feed; flushed in batches so a
        # telemetry hiccup never blocks audio.
        self._pending_events: list[dict[str, Any]] = []
        # Throttle for sampled partial-transcript events.
        self._last_partial_event_at: float = 0.0
        # Stall watchdog generation. Incremented on every final user turn and
        # on reset so a stale watchdog can never speak into a later turn.
        self._watchdog_generation: int = 0
        self._agent_connecting_posted = False
        self._agent_speaking = False
        self._reset()

    def _publish_data(self, payload: dict[str, Any]) -> None:
        """Publish one JSON event to the room data channel (best-effort)."""
        if self._room is None:
            return
        try:
            raw = json.dumps(payload).encode("utf-8")
            _spawn_task(self._room.local_participant.publish_data(raw))
        except Exception:
            logger.debug("Data publish failed", exc_info=True)

    def _publish_caption(self, speaker: str, text: str, final: bool = True) -> None:
        """Stream a live caption to the browser over the room data channel."""
        if not text.strip():
            return
        self._publish_data(
            {"type": "caption", "speaker": speaker, "text": text, "final": final}
        )

    def _reset(self) -> None:
        self._user_text = ""
        self._agent_text = ""
        # A new exchange begins: any watchdog from the previous turn is stale
        # and must never speak.
        self._watchdog_generation += 1
        self._end_of_speech_at: Optional[float] = None
        self._reply_start_at: Optional[float] = None
        self._got_agent_item = False
        self._stt_final_ms: Optional[float] = None
        self._transcription_delay_ms: Optional[float] = None
        self._llm_first_token_ms: Optional[float] = None
        self._tts_first_audio_ms: Optional[float] = None
        # Cost basis per exchange (CLAUDE.md: log cost from day one).
        self._prompt_tokens: Optional[int] = None
        self._completion_tokens: Optional[int] = None
        self._tts_characters: Optional[int] = None

    def attach(self) -> None:
        """Wire LiveKit Agents 1.8.3 session events."""
        self._session.on("user_state_changed")(self._on_user_state_changed)
        self._session.on("agent_state_changed")(self._on_agent_state_changed)
        self._session.on("user_input_transcribed")(self._on_user_input_transcribed)
        self._session.on("conversation_item_added")(self._on_conversation_item_added)
        self._session.on("metrics_collected")(self._on_metrics_collected)

    @staticmethod
    def _event_value(event: Any, name: str, default: Any = None) -> Any:
        if isinstance(event, Mapping):
            value = event.get(name, default)
        else:
            value = getattr(event, name, default)
        return getattr(value, "value", value)

    @classmethod
    def _event_state(cls, event: Any, name: str) -> Optional[str]:
        value = cls._event_value(event, name)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _finite_time(value: Any) -> float:
        try:
            occurred_at = float(value)
        except (TypeError, ValueError, OverflowError):
            occurred_at = time.time()
        if math.isfinite(occurred_at):
            return occurred_at
        fallback = time.time()
        return fallback if math.isfinite(fallback) else 0.0

    @classmethod
    def _event_time(cls, event: Any) -> float:
        return cls._finite_time(cls._event_value(event, "created_at"))

    def _reserve_activity_sequence(self) -> int:
        sequence = self._activity_sequence
        self._activity_sequence += 1
        return sequence

    async def _post_reserved_activity(
        self,
        *,
        state: str,
        sequence: int,
        event_type: str,
        occurred_at: float,
        from_state: Optional[str],
        to_state: Optional[str],
    ) -> bool:
        async with self._activity_post_lock:
            try:
                return await self._backend.post_activity(
                    self._call_id,
                    state,
                    sequence,
                    event_type,
                    occurred_at,
                    ACTIVITY_SOURCE,
                    from_state,
                    to_state,
                )
            except Exception:
                logger.exception(
                    "activity post failed for call %s state=%s sequence=%s",
                    self._call_id,
                    state,
                    sequence,
                )
                return False

    async def post_activity(
        self,
        state: str,
        event_type: str,
        occurred_at: float,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
    ) -> bool:
        """Publish one activity state with a reserved sequence number."""
        sequence = self._reserve_activity_sequence()
        return await self._post_reserved_activity(
            state=state,
            sequence=sequence,
            event_type=event_type,
            occurred_at=self._finite_time(occurred_at),
            from_state=from_state,
            to_state=to_state,
        )

    def queue_agent_connecting(self) -> None:
        """Reserve and schedule the pre-start state without awaiting HTTP."""
        if self._agent_connecting_posted:
            return
        self._agent_connecting_posted = True
        self._queue_activity(
            state="agent_connecting",
            event_type="session_pre_start",
            occurred_at=self._finite_time(time.time()),
            from_state="initializing",
            to_state="agent_connecting",
        )

    async def post_agent_connecting(self) -> bool:
        self.queue_agent_connecting()
        return True

    def _queue_activity(
        self,
        *,
        state: str,
        event_type: str,
        occurred_at: float,
        from_state: Optional[str],
        to_state: Optional[str],
    ) -> None:
        event_key = (event_type, from_state or "", to_state or "", occurred_at)
        if event_key in self._activity_seen_events:
            return
        self._activity_seen_events.add(event_key)
        sequence = self._reserve_activity_sequence()
        try:
            _spawn_task(
                self._post_reserved_activity(
                    state=state,
                    sequence=sequence,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    from_state=from_state,
                    to_state=to_state,
                )
            )
        except Exception:
            logger.exception(
                "activity scheduling failed for call %s state=%s sequence=%s",
                self._call_id,
                state,
                sequence,
            )

    def _on_user_state_changed(self, ev: Any) -> None:
        old_state = self._event_state(ev, "old_state")
        new_state = self._event_state(ev, "new_state")
        # Caller status feed: speaking/listening transitions, including the
        # barge-in moment (user starts speaking while the agent speaks).
        if new_state and new_state != old_state:
            barge = " (BARGE-IN: caller talking over the agent)" if (
                new_state == "speaking" and self._agent_speaking
            ) else ""
            self._emit_event(
                "user_state",
                provider="caller",
                message=f"caller {old_state or '?'} -> {new_state}{barge}",
            )
        if self._backchannel is not None and new_state is not None:
            try:
                self._backchannel.on_user_speaking(new_state == "speaking")
            except Exception:  # noqa: BLE001 — cues must never break turns
                logger.debug("Backchannel feed failed", exc_info=True)
        if new_state == "speaking" and old_state != "speaking":
            if self._agent_speaking:
                # Genuine barge-in: tell the phone bridge to drop stale
                # queued agent audio NOW (it can't tell new speech from
                # old buffered frames). LiveKit stops TTS; this stops our
                # bridge queue from replaying the cut-off reply.
                self._publish_data({"type": "barge_in", "call_id": self._call_id})
            self._queue_activity(
                state="listening",
                event_type="user_state_changed",
                occurred_at=self._event_time(ev),
                from_state=old_state,
                to_state=new_state,
            )
        if old_state == "speaking" and new_state is not None and new_state != "speaking":
            now = time.monotonic()
            self._end_of_speech_at = now
            if self._reply_start_at is None:
                self._reply_start_at = now
            self._queue_activity(
                state="understanding",
                event_type="user_state_changed",
                occurred_at=self._event_time(ev),
                from_state=old_state,
                to_state=new_state,
            )

    def _on_agent_state_changed(self, ev: Any) -> None:
        old_state = self._event_state(ev, "old_state")
        new_state = self._event_state(ev, "new_state")
        # Agent status feed: listening / thinking / speaking transitions are
        # what the playground console renders as the live agent status. Emit
        # on every real transition so "what is the agent doing right now" is
        # answerable without tailing docker logs.
        if new_state and new_state != old_state:
            self._emit_event(
                "agent_state",
                provider="agent",
                message=f"agent {old_state or '?'} -> {new_state}",
            )
        if new_state == "speaking":
            self._agent_speaking = True
        elif old_state == "speaking":
            self._agent_speaking = False
        if old_state == "speaking" and new_state is not None and new_state != "speaking":
            _spawn_task(self._safe_flush())
        if new_state == "thinking":
            if self._reply_start_at is None:
                self._reply_start_at = time.monotonic()
            self._queue_activity(
                state="understanding",
                event_type="agent_state_changed",
                occurred_at=self._event_time(ev),
                from_state=old_state,
                to_state=new_state,
            )
        elif new_state == "speaking":
            if self._tts_first_audio_ms is None and self._reply_start_at is not None:
                self._tts_first_audio_ms = (
                    time.monotonic() - self._reply_start_at
                ) * 1000.0
                # TTS audibility proof: without this, "the agent is silent"
                # cannot distinguish TTS failure from "it never tried to speak".
                self._emit_event(
                    "tts_first_audio",
                    provider="tts",
                    latency_ms=round(self._tts_first_audio_ms),
                    message="agent started speaking (first audio out)",
                )
            self._queue_activity(
                state="agent_speaking",
                event_type="agent_state_changed",
                occurred_at=self._event_time(ev),
                from_state=old_state,
                to_state=new_state,
            )
        elif old_state == "speaking" and new_state == "listening":
            self._queue_activity(
                state="listening",
                event_type="agent_state_changed",
                occurred_at=self._event_time(ev),
                from_state=old_state,
                to_state=new_state,
            )

    def _emit_event(
        self,
        kind: str,
        *,
        level: str = "info",
        provider: str = "",
        status: Any = None,
        latency_ms: Any = None,
        message: str = "",
    ) -> None:
        """Queue a pipeline event for the backend Diagnostics feed."""
        self._pending_events.append(
            {
                "kind": kind,
                "level": level,
                "provider": provider,
                "status": status,
                "latency_ms": latency_ms,
                "message": message,
                "call_id": self._call_id,
            }
        )

    def _on_user_input_transcribed(self, ev: Any) -> None:
        transcript = str(getattr(ev, "transcript", "") or "").strip()
        is_final = bool(getattr(ev, "is_final", False))
        if transcript:
            # Stream PARTIAL captions too so the browser transcript feels live.
            self._publish_caption("user", transcript, final=is_final)
            if not is_final:
                # Sampled partials: proves audio is reaching Deepgram even when
                # nothing ever finalises. Without this, "no finals" is
                # ambiguous between a silent microphone and a turn-detection
                # problem, and those need opposite fixes.
                now = time.monotonic()
                if now - self._last_partial_event_at > 2.0:
                    self._last_partial_event_at = now
                    self._emit_event(
                        "stt_partial",
                        provider="deepgram",
                        message=f"partial: {transcript[:100]!r}",
                    )
        if is_final:
            # Telemetry: proves audio actually reached Deepgram and was
            # transcribed. "My speech is not being transcribed" is
            # unanswerable from the UI without this - no stt_final event at
            # all means audio never arrived, not that the model ignored it.
            self._emit_event(
                "stt_final",
                provider="deepgram",
                message=f"transcribed: {transcript[:120]!r}",
            )
        if not is_final:
            return
        if not transcript:
            return
        self._user_text = f"{self._user_text} {transcript}".strip()
        # Feed the extraction tools the latest caller words for the
        # transcript-grounding check (M13).
        if self._extraction_tools is not None:
            try:
                self._extraction_tools.recent_caller_text = transcript
            except Exception:  # noqa: BLE001 — defensive
                pass
        # The is_final event already published the caption above; publishing
        # again here duplicated the final caption in the browser transcript.
        if self._reply_start_at is None:
            self._reply_start_at = time.monotonic()
        self._watchdog_generation += 1
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No event loop (unit tests drive the handler synchronously):
            # there is nothing to watch over, so skip the watchdog.
            pass
        else:
            _spawn_task(
                self._stall_watchdog(self._watchdog_generation, transcript)
            )
        if self._on_final_user is not None:
            try:
                result = self._on_final_user(transcript)
                if asyncio.iscoroutine(result):
                    _spawn_task(result)
                else:
                    logger.info("heuristic_extract captured=%s", result)
            except Exception:
                logger.exception("on_final_user callback failed")
        if self._end_of_speech_at is not None:
            elapsed_ms = (time.monotonic() - self._end_of_speech_at) * 1000.0
            # Keep the first measurement for this exchange; EOU metric refines it.
            if self._stt_final_ms is None:
                self._stt_final_ms = elapsed_ms

    async def _stall_watchdog(self, generation: int, transcript: str) -> None:
        """Break silence only when a turn is truly dead - never filler.

        A 4s "One moment, please." filler was added for stalled turns, but on a
        throttled provider EVERY turn is slow, so the filler fired after every
        reply. Worse, callers answer the filler ("Hello."), creating extra
        turns that cost more tokens and more latency - the filler amplified the
        exact problem it covered. Removed: slow-but-working turns stay silent
        while the reply generates, and only a turn with NO reply at all after
        12s gets the recovery line asking the caller to repeat.

        On PHONE rooms the recovery doubles as a keep-alive: Vobiz drops a
        media stream that goes silent too long (seen live: our bridge left
        phone-155 with no hangup signal, mid-thought, during an LLM stall).
        Speaking anything keeps audio flowing and the call alive, so phone
        rooms recover at 7s while browser rooms wait the full 12s.
        """
        try:
            phone_room = "phone-" in str(getattr(self, "_room_name", "") or "")
            # 10s on phone (Vobiz drops silent streams; 7s collided with 5-11s
            # throttled turns and talked over real replies), 12s in browser.
            await asyncio.sleep(10.0 if phone_room else 12.0)
            if generation != self._watchdog_generation or self._got_agent_item:
                return
            # If the LLM has already produced its first token, a reply IS
            # coming - speaking now would talk over it ("Sorry, I didn't" cut
            # off mid-sentence, then the real reply). Only recover when there
            # is genuinely nothing: no agent speech AND no LLM output.
            if self._llm_first_token_ms is not None:
                await asyncio.sleep(8.0)
                if generation != self._watchdog_generation or self._got_agent_item:
                    return
                if self._llm_first_token_ms is not None and self._agent_text:
                    return
            try:
                await self._session.say(
                    "Sorry, I didn't quite catch that. Could you say it once more?"
                )
            except Exception:
                logger.warning("Recovery utterance failed", exc_info=True)
                return
            self._emit_event(
                "stall_recovery",
                level="warn",
                message=f"no agent reply 12s after {transcript[:60]!r}; asked the caller to repeat",
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — diagnostics must never break a call
            logger.warning("Stall watchdog failed", exc_info=True)

    def _on_conversation_item_added(self, ev: Any) -> None:
        item = getattr(ev, "item", None)
        if item is None:
            return
        # Only real assistant MESSAGE items carry spoken text. Function calls
        # and tool results (item.type in {"function_call", "tool_call", ...})
        # must never enter captions/_agent_text/transcript (B).
        item_type = str(getattr(item, "type", "") or "").lower()
        if item_type and item_type not in {"message", "assistant_message", "text"}:
            return
        tool_calls = getattr(item, "tool_calls", None)
        if tool_calls:
            return
        role = str(getattr(item, "role", "")).lower()
        text = scrub_speech_text(getattr(item, "text_content", ""))
        if role == "assistant" and text:
            if not self._got_agent_item and self._llm_first_token_ms is None and self._reply_start_at is not None:
                # APPROXIMATION fallback: item commit time - reply start upper-
                # bounds true TTFT; used only if llm_metrics never arrived.
                self._llm_first_token_ms = (
                    time.monotonic() - self._reply_start_at
                ) * 1000.0
            self._got_agent_item = True
            self._agent_text = f"{self._agent_text} {text}".strip()
            self._publish_caption("agent", text)
            self._schedule_flush()

    def _schedule_flush(self, delay_s: float = 2.5) -> None:
        """Debounced safety flush so turns persist if the caller hangs up
        before the agent leaves speaking."""
        try:
            running = asyncio.get_running_loop()
            running.call_later(
                delay_s,
                lambda: _spawn_task(self._safe_flush()),
            )
        except Exception:
            logger.debug("Flush scheduling failed", exc_info=True)

    async def _safe_flush(self) -> None:
        try:
            await self.flush_pending()
        except Exception:
            logger.exception("Scheduled flush failed")

    # -- metrics handlers ---------------------------------------------------

    def _on_metrics_collected(self, ev: Any) -> None:
        """Single dispatcher for the wrapped AgentMetrics objects (1.8.3)."""
        metrics = getattr(ev, "metrics", ev)  # unwrap MetricsCollectedEvent
        metric_type = str(getattr(metrics, "type", "") or "")
        if metric_type == "eou_metrics":
            # P0-1 split: stt_final_ms = EOU decision only; Deepgram
            # finalization lag is logged separately as transcription_delay_ms.
            eou_s = float(
                getattr(metrics, "end_of_utterance_delay", 0.0) or 0.0
            )
            if eou_s > 0:
                self._stt_final_ms = eou_s * 1000.0
            transcription_s = float(
                getattr(metrics, "transcription_delay", 0.0) or 0.0
            )
            if transcription_s > 0:
                self._transcription_delay_ms = transcription_s * 1000.0
        elif metric_type == "llm_metrics":
            ttft_seconds = float(getattr(metrics, "ttft", -1.0))
            if ttft_seconds > 0:
                self._llm_first_token_ms = ttft_seconds * 1000.0
            # Usage accumulates per metric event within one exchange; the
            # flush log turns this into a per-turn cost basis.
            prompt_tokens = getattr(metrics, "prompt_tokens", None)
            completion_tokens = getattr(metrics, "completion_tokens", None)
            if prompt_tokens is not None:
                self._prompt_tokens = (self._prompt_tokens or 0) + int(prompt_tokens)
            if completion_tokens is not None:
                self._completion_tokens = (
                    self._completion_tokens or 0
                ) + int(completion_tokens)
        elif metric_type == "tts_metrics":
            ttfb_seconds = float(getattr(metrics, "ttfb", 0.0) or 0.0)
            if ttfb_seconds > 0:
                self._tts_first_audio_ms = ttfb_seconds * 1000.0
            # livekit-agents 1.8.3 TTSMetrics carries characters_count; older
            # builds named it characters. Accept either.
            characters = getattr(metrics, "characters_count", None)
            if characters is None:
                characters = getattr(metrics, "characters", None)
            if characters is not None:
                self._tts_characters = (self._tts_characters or 0) + int(characters)

    # -- flushing ------------------------------------------------------------

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def _round(self, value: Optional[float]) -> Optional[int]:
        return None if value is None else round(value)

    async def _maybe_compact_instructions(self) -> None:
        """Swap full instructions for the compact version after the opening.

        Same arithmetic as text mode: the full voice prompt (~8k chars) is
        re-sent on every LLM call against an org-wide 7000 input-tokens/min
        bucket. After 3 exchanges the history carries the persona, so later
        turns only need the compact rules. Runs once; failures are silent
        because instructions must never break a live call.
        """
        try:
            if self._turn_index < 3:
                return
            agent = getattr(self, "_agent", None)
            tools = self._extraction_tools
            if agent is None or tools is None:
                return
            coordinator = getattr(tools, "_coordinator", None)
            if coordinator is None:
                return
            recorded = list(getattr(coordinator, "recorded", {}).keys())
            required = list(getattr(coordinator, "required_fields", []) or [])
            from app.prompting import render_compact_instructions

            import datetime

            today = datetime.datetime.now(
                datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            ).strftime("%A %d %B %Y")
            compact = render_compact_instructions(
                [f for f in recorded],
                [f for f in required if f not in recorded],
                today,
            )
            if agent.swap_to_compact_instructions(compact):
                logger.info(
                    "voice instructions compacted at turn %d (%d chars)",
                    self._turn_index,
                    len(compact),
                )
                self._emit_event(
                    "instructions_compacted",
                    message=(
                        f"full prompt swapped for compact continuation at turn {self._turn_index}"
                    ),
                )
        except Exception:  # noqa: BLE001 — instructions must never break a call
            logger.debug("Instruction compaction skipped", exc_info=True)

    async def flush_pending(self) -> None:
        """Post the current exchange (if any) as turn rows and log once."""
        async with self._flush_lock:
            if not self._user_text and not self._agent_text:
                return
            self._turn_index += 1
            turn_index = self._turn_index
            await self._maybe_compact_instructions()
            timestamp = self._utc_now_iso()

            e2e_ms: Optional[float] = None
            if (
                self._stt_final_ms is not None
                and self._llm_first_token_ms is not None
                and self._tts_first_audio_ms is not None
            ):
                e2e_ms = (
                    self._stt_final_ms
                    + self._llm_first_token_ms
                    + self._tts_first_audio_ms
                )

            rows: list[dict[str, Any]] = []
            # A VAD-only exchange (noise/silence) may have no user words at
            # all - an empty user row would corrupt transcript records.
            if self._user_text:
                rows.append(
                    {
                        "turn_index": turn_index,
                        "speaker": "user",
                        "text": self._user_text,
                        "timestamp": timestamp,
                        "stt_final_ms": self._round(self._stt_final_ms),
                        "llm_first_token_ms": None,
                        "tts_first_audio_ms": None,
                        "e2e_ms": None,
                    }
                )
            if self._agent_text:
                # Attribute the reply to its serving model, the same way text
                # mode persists per-turn providers for the latency table.
                served_model = None
                try:
                    if self._llm is not None and hasattr(self._llm, "last_served_model"):
                        served_model = self._llm.last_served_model
                except Exception:
                    served_model = None
                rows.append(
                    {
                        "turn_index": turn_index,
                        "speaker": "agent",
                        "text": self._agent_text,
                        "timestamp": timestamp,
                        "stt_final_ms": None,
                        "llm_first_token_ms": self._round(self._llm_first_token_ms),
                        "tts_first_audio_ms": self._round(self._tts_first_audio_ms),
                        "e2e_ms": self._round(e2e_ms),
                        "served_by": {"model": served_model} if served_model else None,
                    }
                )

            ok = await self._backend.post_turns(self._call_id, rows)
            # One structured log line per completed exchange.
            logger.info(
                "%s",
                json.dumps(
                    {
                        "event": "turn_latency",
                        "call_id": self._call_id,
                        "turn_index": turn_index,
                        "posted": ok,
                        "stt_final_ms": self._round(self._stt_final_ms),
                        "transcription_delay_ms": self._round(
                            self._transcription_delay_ms
                        ),
                        "llm_first_token_ms": self._round(self._llm_first_token_ms),
                        "tts_first_audio_ms": self._round(self._tts_first_audio_ms),
                        "e2e_ms": self._round(e2e_ms),
                        "prompt_tokens": self._prompt_tokens,
                        "completion_tokens": self._completion_tokens,
                        "tts_characters": self._tts_characters,
                        "user_chars": len(self._user_text),
                        "agent_chars": len(self._agent_text),
                        "llm_model": (
                            self._llm.last_served_model
                            if self._llm is not None
                            and hasattr(self._llm, "last_served_model")
                            else getattr(self._llm, "model", None)
                        ),
                    },
                    ensure_ascii=False,
                ),
            )
            self._reset()


# --------------------------------------------------------------------------
# The conversational agent
# --------------------------------------------------------------------------


class DomainCallAgent(Agent):
    """Config-driven interview agent with extraction + end-call tools."""

    def __init__(self, instructions: str, tools_impl: VoiceAgentTools) -> None:
        self._tools_impl = tools_impl
        # NOTE: do NOT pass tools= here - livekit-agents auto-collects the
        # @function_tool-decorated methods below; passing them again raises
        # "duplicate function name".
        super().__init__(instructions=instructions)

    async def swap_to_compact_instructions(self, compact: str) -> bool:
        """Replace full instructions with the compact continuation version.

        Called after the opening exchanges: the full 8k-char prompt is re-sent
        on every LLM call against an org-wide 7000 input-tokens/min bucket.
        Uses update_instructions (Agent.instructions is a read-only property,
        and update_instructions is a coroutine - calling it without await was
        why the swap silently never happened). Returns True on the swap so it
        is logged once, not per turn.
        """
        try:
            if getattr(self, "_compact_swapped", False):
                return False
            await self.update_instructions(compact)
            self._compact_swapped = True
            return True
        except Exception:
            return False

    @function_tool
    async def record_extracted_field(
        self, field_name: str, value: str, confidence: float
    ) -> str:
        """Record a structured value extracted from the caller's answer.

        Always report your HONEST confidence between 0.0 and 1.0. Never guess:
        if you are unsure, ask a clarifying question instead of calling this.

        Args:
            field_name: Exact field name from the extraction schema.
            value: The value exactly as the caller stated it.
            confidence: Your honest confidence in the value (0.0 to 1.0).
        """
        return await self._tools_impl.record_extracted_field(
            field_name, value, confidence
        )

    @function_tool
    async def end_call(self, summary: str) -> str:
        """Politely finish the call and post its summary.

        Call this when all questions are handled, the caller wants to stop,
        or escalation rules say to wrap up. Summarize captured fields and any
        flagged/unfilled required fields factually - never invent values.

        Args:
            summary: Factual wrap-up summary of the conversation.
        """
        return await self._tools_impl.end_call(summary)


# --------------------------------------------------------------------------
# Session orchestration
# --------------------------------------------------------------------------


#: Process-wide Silero VAD. Model load costs seconds — doing it per session
#: puts dead air at the head of every phone call. Loaded once, reused.
_VAD_INSTANCE: Any = None


def _get_vad() -> Any:
    """Return the shared VAD instance, loading the model on first use."""
    global _VAD_INSTANCE
    if _VAD_INSTANCE is None:
        _VAD_INSTANCE = silero.VAD.load()
    return _VAD_INSTANCE


def _reset_vad_cache() -> None:
    """Drop the shared VAD (tests that stub silero.VAD)."""
    global _VAD_INSTANCE
    _VAD_INSTANCE = None


#: Process-wide Smart Turn detector. Weights (~9MB) download once, then run
#: from cache; constructing per session would re-warm the model every call.
_SMART_TURN_INSTANCE: Any = None


def _get_smart_turn() -> Any:
    """Return the shared Smart Turn detector (None when uninstallable)."""
    global _SMART_TURN_INSTANCE
    if _SMART_TURN_INSTANCE is None:
        if _SmartTurnDetector is None:
            return None
        _SMART_TURN_INSTANCE = _SmartTurnDetector()
    return _SMART_TURN_INSTANCE


def _reset_smart_turn_cache() -> None:
    """Drop the shared detector (tests)."""
    global _SMART_TURN_INSTANCE
    _SMART_TURN_INSTANCE = None


def _get_noise_cancellation() -> Any:
    """Hush voice-focus processor, or None when the plugin is missing.

    Runs before turn detection/STT: isolates the foreground speaker and
    suppresses competing voices (TV, car passengers) that plain noise
    cancellation hears as speech. Never raises.

    VOICE_NC=off disables it entirely. Exists because an input-path processor
    is a prime suspect when STT goes silent: if it corrupts or drops frames,
    Deepgram receives garbage and returns nothing while VAD (upstream or
    parallel) still flickers.
    """
    if os.getenv("VOICE_NC", "on").strip().lower() in ("off", "0", "no", "false"):
        return None
    try:
        from livekit.plugins import hush as _hush
    except ImportError:
        return None
    try:
        return _hush.noise_suppression()
    except Exception:
        logger.warning("Hush unavailable, continuing without it", exc_info=True)
        return None


def _room_options() -> Any:
    """RoomOptions with voice-focus audio input, or None for a plain start."""
    nc = _get_noise_cancellation()
    if nc is None:
        return None
    try:
        from livekit.agents import room_io

        return room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(noise_cancellation=nc)
        )
    except Exception:
        logger.warning("RoomOptions unsupported here, plain start", exc_info=True)
        return None


def _preemptive_kwargs(enabled: bool) -> dict[str, Any]:
    """Version-tolerant preemptive-generation option.

    livekit-agents 1.8+ requires a ``PreemptiveGenerationOptions`` MAPPING
    and raises ``TypeError: 'bool' object is not a mapping`` for a plain
    boolean (this killed every phone session with the apology fallback).
    Older versions take the boolean. Disabled means the key is omitted
    entirely — deterministic turn-taking on PSTN rooms.
    """
    if _PreemptiveOpts is None:
        return {"preemptive_generation": bool(enabled)}
    if not enabled:
        return {}
    return {"preemptive_generation": _opts(_PreemptiveOpts)}


def _room_metadata(ctx: JobContext) -> Any:
    return getattr(ctx.room, "metadata", None)


def _job_metadata(ctx: JobContext) -> Any:
    """Job identity metadata: room metadata first, then any remote participant.

    The backend embeds ``{"version_id": ..., "call_id": ...}`` in the joining
    user's JWT *and* (best-effort) on the room itself. Token metadata lands on
    the participant, so fall back to scanning remote participants.
    """
    raw = _room_metadata(ctx)
    if raw:
        return raw
    participants = list(getattr(ctx.room, "remote_participants", {}).values())
    for participant in participants:
        meta = getattr(participant, "metadata", None)
        if meta:
            return meta
    return None


async def _wait_for_job_metadata(
    ctx: JobContext, timeout_s: float = 8.0, interval_s: float = 1.0
) -> Any:
    """Poll both room and participant metadata until it shows up or times out."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        raw = _job_metadata(ctx)
        if raw:
            return raw
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(interval_s)


async def _is_connected(ctx: JobContext) -> bool:
    state = getattr(ctx.room, "connection_state", None)
    try:
        from livekit import rtc

        return state == rtc.ConnectionState.CONN_CONNECTED
    except Exception:  # pragma: no cover - defensive
        return bool(state)


async def _shutdown_ctx(ctx: JobContext) -> None:
    result = ctx.shutdown()
    if inspect.isawaitable(result):
        await result


def _required_fields_from_schema(config: Mapping[str, Any]) -> frozenset[str]:
    schema = config.get("extraction_schema")
    required: set[str] = set()
    if isinstance(schema, Mapping):
        for name, spec in schema.items():
            if isinstance(spec, Mapping):
                validation = str(spec.get("validation") or "").strip().lower()
                if validation == "required":
                    required.add(str(name))
    return frozenset(required)


def _opts(cls: Any, **kwargs: Any) -> Any:
    """Construct a LiveKit options object with only this version's fields.

    The worker runs against whatever livekit-agents is installed (1.7.0 in
    the local venv, 1.8.3 in the compose image) and unknown kwargs raise
    TypeError — which would kill the whole session. Unknown fields are
    dropped with a warning; if construction still fails, fall back to
    defaults rather than silence.
    """
    annotations = getattr(cls, "__annotations__", None) or {}
    if annotations:
        dropped = sorted(set(kwargs) - set(annotations))
        if dropped:
            logger.warning(
                "%s unsupported here, dropping: %s",
                getattr(cls, "__name__", cls), dropped,
            )
        kwargs = {k: v for k, v in kwargs.items() if k in annotations}
    try:
        return cls(**kwargs)
    except TypeError:
        logger.exception(
            "%s construction failed, falling back to defaults",
            getattr(cls, "__name__", cls),
        )
        return cls()


def _turn_detection() -> Any:
    """End-of-turn detector: Smart Turn v3 first, local mini fallback.

    Smart Turn reads prosody (not just silence) to tell "paused to think"
    from "finished speaking" — the core fix for waits-after-user-speaks and
    mid-thought interruptions. It runs on CPU via ONNX with weights cached
    at image build time. Any failure (missing dep, no weights, offline box)
    falls back to the pinned v1-mini cloud detector, then plain "vad".
    Nothing here may ever raise into the session path.
    """
    # TURN_DETECTOR override (smart | v1-mini | vad, default smart). Exists so
    # a turn-detection failure can be bisected without a code change: if STT
    # works on "vad" but not "smart", the detector - not Deepgram, the mic,
    # or the room - is swallowing the audio.
    forced = os.getenv("TURN_DETECTOR", "smart").strip().lower()
    if forced == "vad":
        return "vad"
    if forced == "v1-mini":
        detector_cls = getattr(_inference, "TurnDetector", None) if _inference else None
        if detector_cls is not None:
            return _opts(detector_cls, version="v1-mini")
        return "vad"
    if _SmartTurnDetector is not None:
        try:
            return _get_smart_turn()
        except Exception:
            logger.warning("Smart Turn unavailable, trying v1-mini", exc_info=True)
    detector_cls = getattr(_inference, "TurnDetector", None) if _inference else None
    if detector_cls is None:
        return "vad"
    return _opts(detector_cls, version="v1-mini")


def _build_agent_session(
    bundle: ProviderBundle, preemptive_generation: bool = True
) -> AgentSession:
    # Sarvam's own integration guide is explicit: when Saaras STT is active,
    # do NOT pass VAD (handled internally), use turn_detection="stt", and set
    # min_endpointing_delay=0.07 (their STT processes in ~70ms). Anything else
    # fights their pipeline and adds seconds.
    sarvam_stt = bundle.stt_provider == "sarvam"
    session_kwargs: dict[str, Any] = {}
    if not sarvam_stt:
        session_kwargs["vad"] = _get_vad()
    return AgentSession(
        stt=bundle.stt,
        llm=bundle.llm,
        tts=bundle.tts,
        aec_warmup_duration=0.0,
        **session_kwargs,
        turn_handling=_opts(
            TurnHandlingOptions,
            turn_detection="stt" if sarvam_stt else _turn_detection(),
            # Preemptive generation: start the LLM on partial transcripts so
            # the first sentence is ready the moment the turn ends (TTS
            # already synthesizes sentence-by-sentence as tokens stream in).
            # Playground-only: on PSTN phone audio the partials are too noisy
            # and speculative replies answer stale turns / talk over callers.
            **_preemptive_kwargs(preemptive_generation),
            endpointing=_opts(
                EndpointingOptions,
                mode="fixed",
                # Sarvam processes STT in ~70ms, so the session moves on
                # almost immediately; otherwise 600ms patience for hesitant
                # speakers (jumping in at 350ms is what callers feel as
                # "the agent interrupts me").
                min_delay=0.07 if bundle.stt_provider == "sarvam" else 0.6,
                max_delay=1.5,
            ),
            interruption=_opts(
                InterruptionOptions,
                enabled=True,
                mode="vad",
                discard_audio_if_uninterruptible=True,
                # 350ms: a real "wait/stop/yes" stops the agent fast, while
                # sub-word noise blips (handled below by min_words) do not.
                min_duration=0.35,
                # Word gate against noise: VAD-only blips that STT cannot
                # turn into even one word never interrupt; a single spoken
                # word ("stop", "wait", "hello?") always does.
                min_words=1,
                false_interruption_timeout=2.0,
                # Echo/reverb on phone lines trips false interruptions: pause
                # briefly, then RESUME the reply instead of going silent
                # (silence is what prompts "hello? are you there?").
                resume_false_interruption=True,
            ),
        ),
    )


async def _speak_opening(
    session: Any,
    config: Mapping[str, Any],
    tokens: Mapping[str, str],
    contact: Optional[Mapping[str, Any]],
) -> bool:
    """Speak the composed opening with caller interruptions enabled.

    Returns True when spoken; False (fall back to the prompt-driven
    auto-turn) when there is no disclosure script to anchor it.
    """
    opening = build_opening_line(config, tokens, contact)
    if not opening:
        return False
    await session.say(opening, allow_interruptions=True)
    return True


def _attach_audio_probe(room: Any, telemetry: Any) -> None:
    """Report which audio tracks the AGENT can actually see.

    "The agent cannot hear me" has three causes that look identical from the
    browser: the browser never published audio, LiveKit never delivered it to
    the worker, or Deepgram never transcribed it. Only the middle one is
    visible here. An ``audio_track_subscribed`` for the caller's microphone
    proves the audio arrived; its absence points at the browser's publish side
    (permission or device), which is the most common cause and cannot be fixed
    from this side.
    """
    if room is None:
        return

    def _on_subscribed(
        track: Any = None, publication: Any = None, participant: Any = None
    ) -> None:
        kind = str(getattr(track, "kind", "") or getattr(publication, "kind", ""))
        source = str(getattr(publication, "source", "") or getattr(track, "source", ""))
        identity = str(getattr(participant, "identity", "") or "?")
        is_audio = kind == "audio" or "microphone" in source.lower() or source == "1"
        telemetry._emit_event(
            "audio_track_subscribed",
            provider="livekit",
            message=(
                f"AUDIO track from {identity} (source={source or '?'}) - audio is reaching the agent"
                if is_audio
                else f"non-audio track from {identity} (source={source or '?'})"
            ),
        )

    def _on_unsubscribed(track: Any = None, *_args: Any) -> None:
        telemetry._emit_event(
            "audio_track_unsubscribed",
            level="warn",
            provider="livekit",
            message=f"track {getattr(track, 'sid', '?')} went away",
        )

    try:
        room.on("track_subscribed")(lambda *a: _on_subscribed(*a))
        room.on("track_unsubscribed")(_on_unsubscribed)
        # Report what is ALREADY subscribed (the caller usually joins first).
        for participant in list(getattr(room, "remote_participants", {}).values()):
            for publication in getattr(participant, "track_publications", {}).values():
                _on_subscribed(
                    getattr(publication, "track", None), publication, participant
                )
    except Exception:  # noqa: BLE001 - diagnostics must never break a session
        logger.warning("Could not attach audio probe", exc_info=True)


async def _start_agent_session(
    session: Any,
    telemetry: TurnTelemetry,
    room: Any,
    agent: Any,
    room_options: Any = None,
) -> None:
    telemetry.queue_agent_connecting()
    if room_options is None:
        _attach_audio_probe(room, telemetry)
        await session.start(room=room, agent=agent)
    else:
        await session.start(room=room, agent=agent, room_options=room_options)


async def run_session(ctx: JobContext, settings: Settings) -> None:
    """Full lifecycle for one accepted playground job. Never raises."""
    room_name = ctx.room.name or ""
    backend = BackendClient(settings.backend_internal_url, settings.internal_api_token)
    parsed: Optional[ParsedJob] = parse_room_metadata(_room_metadata(ctx))
    call_id: Optional[str] = parsed.call_id if parsed else None
    session: Optional[AgentSession] = None
    telemetry: Optional[TurnTelemetry] = None

    try:
        # Metadata may arrive via the room, or slightly later on the joining
        # participant's JWT — poll both sources before giving up.
        if parsed is None:
            await ctx.connect()
            raw = await _wait_for_job_metadata(ctx)
            parsed = parse_room_metadata(raw)

        if parsed is None:
            reason = (
                f"room '{room_name}' metadata missing version_id/call_id "
                "- closing gracefully"
            )
            logger.error("%s", reason)
            await _degrade(ctx, backend, call_id, settings, reason)
            return

        call_id = parsed.call_id
        logger.info(
            "Accepted playground job: room=%s version=%s call=%s",
            room_name,
            parsed.version_id,
            call_id,
        )

        missing_required = settings.missing_required()
        if missing_required:
            reason = f"required env vars unset: {', '.join(missing_required)}"
            logger.error("%s", reason)
            await _degrade(ctx, backend, call_id, settings, reason)
            return

        # Load config (cached 30s server-side here via BackendClient) BEFORE
        # constructing providers: a saved voice_settings.llm_model /
        # tts_voice_id must override the platform defaults.
        try:
            config: Mapping[str, Any] = await backend.get_agent_config(parsed.version_id)
        except BackendError as exc:
            await _degrade(
                ctx, backend, call_id, settings, f"failed to load agent config: {exc}"
            )
            return

        bundle = build_providers(settings, config.get("voice_settings"))
        for problem in bundle.problems:
            logger.error("Provider problem: %s", problem)
        if not bundle.complete:
            await _degrade(
                ctx, backend, call_id, settings, "; ".join(bundle.problems)
            )
            return
        assert bundle.stt is not None and bundle.llm is not None
        assert bundle.tts is not None

        # Fetch per-call context (institution_name + contact) once at session
        # start; {} on failure is fine — tokens resolve to empty and are dropped.
        call_context = await backend.fetch_call_context(call_id)
        tokens = build_token_map(contact=parsed.contact, context=call_context)
        instructions = render_system_prompt(config, contact=parsed.contact, tokens=tokens)
        schema = config.get("extraction_schema") or {}
        coordinator = ExtractionCoordinator(
            required_fields=_required_fields_from_schema(config),
            low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
            max_asks_per_field=MAX_ASKS_PER_FIELD,
            schema=schema,
        )
        tools_impl = VoiceAgentTools(
            coordinator,
            backend,
            call_id,
            schema=schema,
        )

        # Phone rooms get deterministic turn-taking: PSTN partials are too
        # noisy for speculative replies (they answer stale turns and talk
        # over callers). Playground keeps preemptive generation for speed.
        is_phone_room = room_name.startswith(PHONE_PREFIX)
        session = _build_agent_session(
            bundle, preemptive_generation=not is_phone_room
        )

        async def _say_cue(text: str) -> None:
            await session.say(text, allow_interruptions=True)

        backchannel = BackchannelController(_say_cue)
        telemetry = TurnTelemetry(
            session=session,
            backend=backend,
            call_id=call_id,
            room=ctx.room,
            on_final_user=tools_impl.heuristic_extract,
            backchannel=backchannel,
            extraction_tools=tools_impl,
            llm=bundle.llm,
        )
        telemetry.attach()

        # Announce the REAL pipeline this session is running. "Voice mode is
        # not working" is most often a provider that silently degraded, and
        # this is where it becomes visible in the Diagnostics panel.
        telemetry._emit_event(
            "voice_session_start",
            message=(
                f"STT={'deepgram' if bundle.stt else 'DISABLED'} "
                f"LLM={type(bundle.llm).__name__ if bundle.llm else 'DISABLED'}"
                f"{'(chain of %d)' % bundle.llm.chain_size if isinstance(bundle.llm, FallbackLLM) else ''} "
                f"TTS={'cartesia' if bundle.tts else 'DISABLED'} "
                f"room={room_name}"
            ),
        )
        for problem in bundle.problems:
            telemetry._emit_event(
                "voice_provider_problem",
                level="error",
                message=problem,
            )

        async def _backchannel_loop() -> None:
            try:
                while True:
                    await asyncio.sleep(0.5)
                    await backchannel.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — cues never kill sessions
                logger.exception("Backchannel loop failed")

        async def _telemetry_loop() -> None:
            # Batch-flush pipeline events to the backend so the Diagnostics
            # panel shows STT/TTS/LLM activity live. Failures are swallowed:
            # telemetry must never disturb a live call.
            try:
                while True:
                    await asyncio.sleep(1.0)
                    pending = list(telemetry._pending_events)
                    if not pending:
                        continue
                    telemetry._pending_events.clear()
                    await backend.post_telemetry(pending)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — diagnostics never kill a call
                logger.exception("Telemetry loop failed")

        backchannel_task = asyncio.ensure_future(_backchannel_loop())
        telemetry_task = asyncio.ensure_future(_telemetry_loop())

        if not await _is_connected(ctx):
            await ctx.connect()

        agent = DomainCallAgent(instructions=instructions, tools_impl=tools_impl)
        # Give telemetry the agent handle so it can swap full instructions for
        # the compact continuation version after the opening exchanges.
        telemetry._agent = agent
        await _start_agent_session(
            session, telemetry, ctx.room, agent,
            room_options=_room_options(),
        )
        # Agent speaks first: the composed opening remains token-substituted,
        # and the caller can barge in while it is being delivered.
        await _speak_opening(session, config, tokens, parsed.contact)
    except Exception:
        logger.exception("Unhandled error in voice session (room=%s)", room_name)
        try:
            await _degrade(
                ctx, backend, call_id, settings, "unexpected voice-agent error"
            )
        except Exception:  # pragma: no cover - last resort
            logger.exception("Degradation path also failed (room=%s)", room_name)
    finally:
        task = locals().get("backchannel_task")
        if task is not None:
            task.cancel()
        telemetry_task = locals().get("telemetry_task")
        if telemetry_task is not None:
            telemetry_task.cancel()
        if telemetry is not None:
            try:
                # Send whatever is still buffered before the client closes.
                pending = list(telemetry._pending_events)
                telemetry._pending_events.clear()
                if pending:
                    await backend.post_telemetry(pending)
            except Exception:
                logger.exception("Final telemetry flush failed")
        await backend.aclose()


async def _degrade(
    ctx: JobContext,
    backend: BackendClient,
    call_id: Optional[str],
    settings: Settings,
    reason: str,
) -> None:
    """Graceful failure path: join, apologize if possible, flag, never crash."""
    logger.error("Degrading session: %s", reason)
    try:
        if not await _is_connected(ctx):
            await ctx.connect()
    except Exception:
        logger.exception("Could not connect while degrading")

    # Speak the apology through whatever TTS is configured, best-effort.
    try:
        bundle = build_providers(settings)
        if bundle.tts is not None:
            apology_session = AgentSession(
                stt=bundle.stt,
                llm=bundle.llm,
                tts=bundle.tts,
            )
            if not await _is_connected(ctx):
                await ctx.connect()
            await apology_session.start(room=ctx.room, agent=Agent(instructions=""))
            await apology_session.say(APOLOGY_TEXT, allow_interruptions=False)
    except Exception:
        logger.exception("Apology playback failed (best-effort)")

    if call_id:
        posted = await backend.post_complete(
            call_id, status="error", error=reason
        )
        if not posted:
            logger.error("Could not post error completion for call %s", call_id)
