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
import ssl
import time
import traceback
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

import httpx
from openai import AsyncOpenAI as _OpenAIAsyncClient

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
from livekit.plugins import cartesia, deepgram, openai, sarvam, silero

# LiveKit plugins must be imported/registered on the MAIN thread. The provider
# builders run inside a job thread, so importing Sarvam lazily there raised
# "Plugins must be registered on the main thread" on the first live call.
# Preload the optional noise-cancellation plugins here for the same reason;
# the lazy imports below then reuse the already-registered modules.
try:
    from livekit.plugins import hush as _hush_preload  # noqa: F401
except ImportError:
    _hush_preload = None  # type: ignore[assignment]
try:
    from livekit.plugins import ai_coustics as _ai_coustics_preload  # noqa: F401
except Exception:  # optional heavy install; never block worker startup
    _ai_coustics_preload = None  # type: ignore[assignment]

from app import usage_reporter
from app.backend_client import BackendClient, BackendError
from app.config import Settings
from app.extraction_tools import (
    LOW_CONFIDENCE_THRESHOLD,
    MAX_ASKS_PER_FIELD,
    ExtractionCoordinator,
    VoiceAgentTools,
)
from app.prompting import (
    _AGENT_DERIVED_FIELDS,
    build_opening_line,
    build_token_map,
    render_system_prompt,
    scrub_speech_text,
    speakable_text,
)

logger = logging.getLogger("voice_agent.pipeline")

# Create the TLS context at import, not on the call path. On Windows this
# measured ~432ms of event-loop block; doing it once during worker startup
# keeps it out of the greeting.
_LLM_SSL_CONTEXT: Optional[ssl.SSLContext]
try:
    _LLM_SSL_CONTEXT = ssl.create_default_context()
except Exception:  # noqa: BLE001 - fall back to httpx's default verify
    _LLM_SSL_CONTEXT = None

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
    #: The agent's conversation language ("en" | "te" | "hi"). Carried on the
    #: bundle because the compact mid-call instructions must keep steering the
    #: spoken register, and telemetry is the only thing that rebuilds them.
    language: str = "en"
    # Which TTS backend is armed (cartesia | deepgram | sarvam). Reported in
    # the session-start event so the panel names the REAL pipeline.
    tts_provider: str = "cartesia"
    # Per-member httpx clients, so no plugin/stream closing one client can take
    # down its siblings. The expensive TLS context is shared (created once at
    # import), which was the actual ~2.9s event-loop block. compare=False keeps
    # test equality sane.
    llm_clients: list[Any] = field(default_factory=list, compare=False, repr=False)

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
    "or": "od-IN",
    "od": "od-IN",
}


def _bcp47_language(value: Any) -> str:
    """Map a bare config code ("te") to the BCP-47 code Sarvam requires.

    Already-qualified codes ("te-IN") pass through unchanged. Unknown codes
    are returned as-is so a future Sarvam language works without a code
    change; Sarvam validates them at construction and the session degrades
    to the next provider instead of silently speaking the wrong language.
    """
    code = str(value or "").strip()
    if not code:
        return ""
    return _SARVAM_LANG_ALIASES.get(code.lower(), code)


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


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """Unwrap SDK wrapper exceptions (``APIConnectionError`` -> 429 cause)."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _llm_status_code(exc: BaseException) -> Optional[int]:
    """HTTP status from the first exception in the chain that carries one."""
    for item in _exception_chain(exc):
        status = getattr(item, "status_code", None)
        if status is not None:
            return int(status)
    return None


def _is_shared_tpm_error(exc: Exception) -> bool:
    """True when a 429 names the org-wide tokens-per-minute bucket.

    Groq says: "Rate limit reached ... on tokens per minute (TPM): Limit
    8000". Measured on this key pool: a single request on key #1 dropped key
    #2's remaining tokens to the same level, so TPM/TPD is shared. An RPD
    ("requests per day") or RPM error is per key and must not bench the
    siblings.

    The OpenAI plugin raises ``APIConnectionError`` after retrying, and its
    top-level string only says "failed to generate LLM completion". The 429
    message lives on ``__cause__``; search the whole chain.
    """
    for item in _exception_chain(exc):
        text = str(item).lower()
        for attr in ("message", "body"):
            value = getattr(item, attr, None)
            if value:
                text += " " + str(value).lower()
        if "tokens per minute" in text or "(tpm)" in text:
            return True
    return False


#: Provider labels that share ONE organization-wide token bucket. A shared-TPM
#: 429 on any member must bench every member of the same bucket, because the
#: sibling would answer from the same depleted pool. Measured 2026-10-22: all
#: five Groq keys AND gpt-oss-120b report the same 8000 remaining-tokens value
#: and drain together, so the whole org is one bucket.
_SHARED_TPM_BUCKETS: dict[str, str] = {
    "groq": "groq",
    "groq-secondary": "groq",
}


def _tpm_bucket(provider: str) -> str:
    """Map a chain member label to the shared token bucket it draws from."""
    label = str(provider or "").strip().lower()
    return _SHARED_TPM_BUCKETS.get(label, label)


#: qwen3.8-27b answers a Telugu caller in ungrammatical word-salad
#: ("సరే మీరు చెప్పిన కారణాన్ని నేను ఎంతైనా"). Measured against the production
#: prompt and the real tool schema, the Indic-trained chain member replied in
#: everyday code-mixed Telugu in ~300 ms and called record_extracted_field
#: correctly, so Indic calls start there and Groq becomes the overflow.
#: English stays on Groq, where it was already good and ~150 ms faster.
SPOKEN_INDIC_LLM_PROVIDER = "sarvam"
_INDIC_LANGUAGES = frozenset({"te", "hi", "ta", "kn", "ml", "bn", "mr", "gu", "or", "pa"})


def _preferred_llm_provider(
    language: str, provider_names: list[str], models: list[str]
) -> Optional[str]:
    """Chain label to serve first for this call's language, if the chain has one."""
    if str(language or "").strip().lower() not in _INDIC_LANGUAGES:
        return None
    labels = [str(name or "").strip().lower() for name in provider_names]
    if SPOKEN_INDIC_LLM_PROVIDER in labels:
        return SPOKEN_INDIC_LLM_PROVIDER
    for index, model in enumerate(models):
        if "sarvam" in str(model or "").lower():
            return provider_names[index]
    return None


class FallbackLLM(llm.LLM):
    """Ordered LLM chain with per-member cooldown (ARCHITECTURE.md S5).

    Same-tier, different-provider/key: every member must sound like the same
    agent. ``primary`` is one LLM or an ordered list (e.g. one Groq client
    per API key); ``fallback`` (e.g. OpenAI) is appended last when given.
    The session calls chat() per turn; chat() always serves the first member
    whose cooldown expired (else the first member, better than silence). On
    a retryable serving failure the proxy below marks THAT member down. If no
    content has been emitted yet, it also advances to the next available
    member INSIDE THE SAME TURN; that turns a Groq 429 from ~13s of dead air
    into a normal reply from the secondary model. If content was already
    spoken it re-raises (no duplicated prefixes). The chain definition and
    order are unchanged: 5x Qwen -> GPT-OSS -> Sarvam, except that an Indic
    call tries its preferred member first and keeps that order for failover.

    Backward compatible: ``FallbackLLM(primary, fallback)`` behaves exactly
    as before; ``FallbackLLM([k1, k2], openai_llm)`` rotates Groq keys.
    """

    def __init__(
        self,
        primary: Any,
        fallback: Any = None,
        cooldown_s: float = 90.0,
        provider_names: Optional[list[str]] = None,
        prefer_provider: Optional[str] = None,
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
        #: True time-to-first-content-token for the current exchange, measured
        #: in the stream proxy. Providers whose SDK build emits no
        #: ``LLMMetrics.ttft`` (Sarvam, and Groq through this plugin) otherwise
        #: leave turn telemetry with nothing better than the item-commit time,
        #: which is full generation time: a 20 s "first token" was reported on
        #: a turn whose audio actually started in 0.6 s.
        self.first_token_ms: Optional[float] = None
        # Provider label per member ("groq", "gemini", ...), same order as the
        # chain. Labels drive the shared-TPM skip: request counters were
        # measured to be per key, but the token bucket is org-wide (a 5,012
        # token request on key #1 dropped key #2's remaining tokens from 7,986
        # to 3,098), so only TPM 429s bench a whole provider.
        if provider_names is None:
            provider_names = [f"member-{index}" for index in range(len(members))]
        self._providers: list[str] = list(provider_names)
        self._prefer_index: Optional[int] = None
        want = str(prefer_provider or "").strip().lower()
        if want:
            for index, name in enumerate(self._providers):
                if str(name).strip().lower() == want:
                    self._prefer_index = index
                    break

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

    def begin_exchange(self) -> None:
        """Clear per-exchange streaming measurements (called by telemetry)."""
        self.first_token_ms = None

    def _note_first_content(self, elapsed_ms: float) -> None:
        """Latch the fastest first-token time seen this exchange."""
        if self.first_token_ms is None or elapsed_ms < self.first_token_ms:
            self.first_token_ms = float(elapsed_ms)

    def _member_order(self) -> list[int]:
        """Chain indexes in the order this call should try them.

        An Indic-language call puts the provider trained for spoken Indic
        first; every other member stays in its original position as overflow.
        """
        order = list(range(len(self._down_until)))
        if self._prefer_index is None:
            return order
        order.remove(self._prefer_index)
        return [self._prefer_index, *order]

    def _pick_member(self, exclude: Optional[set[int]] = None) -> int:
        now = time.monotonic()
        for index in self._member_order():
            if exclude and index in exclude:
                continue
            if now >= self._down_until[index]:
                return index
        return -1 if exclude else (self._member_order()[0] if self._down_until else 0)

    def _mark_down(self, index: int) -> None:
        self._down_until[index] = time.monotonic() + self._cooldown_s

    def _mark_provider_down(self, provider: str) -> int:
        """Cool down every member of one shared token bucket. Returns skipped.

        Only for the SHARED tokens-per-minute bucket. Measured with five Groq
        keys: a 5,012-token request on key #1 dropped key #2's remaining
        tokens from 7,986 to 3,098, so the TPM/TPD pool is org-wide and trying
        a sibling key after a TPM 429 only burns the caller's time. Request
        counters are separate per key (five distinct RPD values), so plain
        RPD/RPM 429s still cool ONE member and leave the other keys usable.

        Members are matched by BUCKET, not by label: ``groq`` and
        ``groq-secondary`` (gpt-oss-120b) answer from the same 8000 TPM pool,
        so a TPM 429 on either must bench both. Otherwise the chain spends
        another full member timeout on a model that is guaranteed to 429.
        """
        now = time.monotonic()
        bucket = _tpm_bucket(provider)
        skipped = 0
        for index, name in enumerate(self._providers):
            if _tpm_bucket(name) == bucket and now >= self._down_until[index]:
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
        from livekit.agents.llm import ChatContext, ChatMessage

        brief = (
            "CONTINUITY: you took over this call mid-conversation from another "
            "model that stopped responding. Do NOT introduce yourself again, do "
            "NOT re-disclose, and do NOT re-ask anything already answered. "
            "Anything already recorded stands as established. Continue naturally "
            "as if you had been on the call the whole time."
        )
        items = list(getattr(chat_ctx, "items", []) or [])
        # NOTE: ChatContext.copy() accepts only exclude_* flags (no `items`
        # kwarg) - the old copy(items=[...]) call raised TypeError, which the
        # blanket except swallowed, so the brief was silently never injected.
        return ChatContext([ChatMessage(role="system", content=[brief]), *items])
    except Exception:
        return chat_ctx


class _FallbackStream(llm.LLMStream):
    """LLMStream proxy that fails over inside the current turn when safe.

    A retryable serving-member failure marks that member down. If no content
    chunk has been emitted yet, the proxy opens the next available member's
    stream and continues the same turn. If content was already emitted it
    re-raises, because replaying the next model would duplicate audio.
    """

    def __init__(
        self, owner: FallbackLLM, primary_stream: llm.LLMStream, member_index: int = 0
    ) -> None:
        self._chat_ctx = primary_stream.chat_ctx
        self._tools = list(primary_stream.tools)
        self._conn_options = getattr(primary_stream, "conn_options", None) or (
            APIConnectOptions(max_retry=1, retry_interval=0.5, timeout=8.0)
        )
        super().__init__(
            owner,
            chat_ctx=self._chat_ctx,
            tools=self._tools,
            conn_options=self._conn_options,
        )
        self._owner = owner
        self._active = primary_stream
        self._member_index = member_index
        self._tried: set[int] = {member_index}
        self._yielded_content = False
        self._started_at = time.monotonic()

    async def _run(self) -> None:
        # Abstract hook required by llm.LLMStream. This proxy never drives
        # it — iteration delegates to the wrapped concrete stream.
        return None

    async def __anext__(self) -> Any:
        while True:
            try:
                chunk = await self._active.__anext__()
                _speak_chunk_content(chunk)
                if _chunk_has_content(chunk):
                    if not self._yielded_content:
                        self._owner._note_first_content(
                            (time.monotonic() - self._started_at) * 1000.0
                        )
                    self._yielded_content = True
                return chunk
            except StopAsyncIteration:
                raise
            except Exception as exc:  # noqa: BLE001 — classify, then maybe fail over
                status = _llm_status_code(exc)
                # 402 is a dead account (DeepSeek "Insufficient Balance"), not
                # a dead provider: cool the member and move on exactly like any
                # other per-member failure.
                if status not in _RETRYABLE_LLM_STATUS and status != 402:
                    raise
                if status == 429 and _is_shared_tpm_error(exc):
                    # Shared TPM/TPD bucket: every Groq key draws on it, so a
                    # sibling would 429 identically. Skip the whole tier.
                    provider = self._owner._providers[self._member_index] if (
                        0 <= self._member_index < len(self._owner._providers)
                    ) else "?"
                    skipped = self._owner._mark_provider_down(provider)
                    logger.warning(
                        "LLM chain member %d hit the shared TPM bucket (%s); skipping %d sibling(s)",
                        self._member_index + 1,
                        provider,
                        max(skipped - 1, 0),
                    )
                else:
                    # RPD/RPM or a non-429 failure: cool THIS member only.
                    if status == 429:
                        logger.warning(
                            "LLM chain member %d 429 (per-key request limit); cooling down this key only",
                            self._member_index + 1,
                        )
                    else:
                        logger.warning(
                            "LLM chain member %d failed (%s), cooling down for next member",
                            self._member_index + 1,
                            status or "connection-error",
                        )
                    self._owner._mark_down(self._member_index)

                # Never splice a second model into audio that already started.
                if self._yielded_content:
                    raise

                self._tried.add(self._member_index)
                next_index = self._owner._pick_member(exclude=self._tried)
                if next_index < 0:
                    raise
                previous = self._member_index
                try:
                    await self._active.aclose()
                except Exception:  # noqa: BLE001 — best effort
                    pass
                self._member_index = next_index
                self._owner.last_served_index = next_index
                logger.warning(
                    "LLM chain failing over inside the same turn: member %d -> %d/%d",
                    previous + 1,
                    next_index + 1,
                    len(self._owner._chain),
                )
                next_ctx = _with_handoff_brief(self._chat_ctx, previous, next_index)
                self._active = self._owner._chain[next_index].chat(
                    chat_ctx=next_ctx,
                    tools=self._tools,
                    conn_options=self._conn_options,
                )
                # Loop and read from the new member's stream.

    async def aclose(self) -> None:
        try:
            await self._active.aclose()
        except Exception:  # noqa: BLE001 — best effort
            pass


def _speak_chunk_content(chunk: Any) -> None:
    """Drop from a streamed delta whatever phone TTS cannot pronounce.

    Mutates the chunk in place so a bare "..." or a stray Han character never
    reaches synthesis; Sarvam answers those with a 400 and the framework
    re-sends the whole segment, which is heard as dead air mid-reply.
    """
    deltas = []
    head = getattr(chunk, "delta", None)
    if head is not None:
        deltas.append(head)
    for choice in getattr(chunk, "choices", None) or []:
        tail = getattr(choice, "delta", None)
        if tail is not None:
            deltas.append(tail)
    for delta in deltas:
        content = getattr(delta, "content", None)
        if not isinstance(content, str) or not content:
            continue
        clean = speakable_text(content)
        if clean == content:
            continue
        try:
            delta.content = clean
        except Exception:  # noqa: BLE001 — an immutable chunk is not worth a dropped turn
            logger.debug("Could not rewrite streamed delta", exc_info=True)


def _chunk_has_content(chunk: Any) -> bool:
    """True once a chunk carries text or a tool call (not just a role)."""
    delta = getattr(chunk, "delta", None)
    if delta is not None:
        if getattr(delta, "content", None):
            return True
        if getattr(delta, "tool_calls", None):
            return True
    for choice in getattr(chunk, "choices", None) or []:
        choice_delta = getattr(choice, "delta", None)
        if choice_delta is not None:
            if getattr(choice_delta, "content", None):
                return True
            if getattr(choice_delta, "tool_calls", None):
                return True
    return False


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


class _MemberHttpClient(httpx.AsyncClient):
    """One LLM chain member's connection pool, protected from stray teardown.

    Live call 2026-10-22 (room ``phone-7``): ~0.5s into the FIRST turn every
    member's pool was already closed - members 2-8 answered "Cannot send a
    request, as the client has been closed" and member 1 hit a mid-stream
    ``ReadError`` - so the whole 8-member chain died and the agent stayed silent
    for the remaining 43s of the call. Nothing in this worker closes a pool
    mid-session (only session teardown does), so a framework teardown path does
    it; refusing the close keeps the live call alive, and the one-time stack
    trace names the caller so the real bug can be chased down later.

    Refusing is also the latency-correct choice: rebuilding a pool per turn
    would re-pay DNS + TLS + handshake on every member the turn touches.
    """

    _pool_released = False
    _pool_close_logged = False

    def release(self) -> None:
        """Allow this pool to close for real (session teardown only)."""
        self._pool_released = True

    def _refuse(self, how: str) -> None:
        if not self._pool_close_logged:
            self._pool_close_logged = True
            logger.warning(
                "%s tried to close a live LLM pool; caller stack:\n%s",
                how,
                "".join(traceback.format_stack()[-16:]),
            )

    async def aclose(self) -> None:
        if self._pool_released:
            await super().aclose()
            return
        self._refuse("aclose()")

    async def __aexit__(self, *exc_info: Any) -> None:
        # httpx's __aexit__ sets _state = CLOSED directly, bypassing aclose() -
        # so the guard above would never see a pool closed as a context manager.
        if self._pool_released:
            await super().__aexit__(*exc_info)
            return
        self._refuse("__aexit__()")


def _new_llm_http_client(
    event_hooks: Optional[dict[str, list[Any]]] = None,
) -> httpx.AsyncClient:
    """A fresh connection pool per LLM member, sharing one TLS context.

    The OpenAI plugin otherwise creates a fresh ``httpx.AsyncClient`` **and**
    a fresh TLS context per member. Seven TLS contexts blocked the event loop
    for ~2.9s on the first phone call; the context is now created once at
    import. The pool itself must NOT be shared: one member closing its client
    (or a plugin aclose) would otherwise kill every sibling on the next turn.

    ``event_hooks`` carries the per-member quota-header capture (see
    ``app.usage_reporter``) without giving members a shared pool.

    ``read`` is 15s, not 5s: a slow first token on a long prompt was aborted by
    the tighter read timeout mid-stream, which is indistinguishable from a dead
    provider and wasted a whole failover hop. The per-attempt budget is owned by
    ``APIConnectOptions(timeout=8.0)`` in ``FallbackLLM.chat``.
    """
    return _MemberHttpClient(
        verify=_LLM_SSL_CONTEXT if _LLM_SSL_CONTEXT is not None else True,
        timeout=httpx.Timeout(connect=15.0, read=15.0, write=15.0, pool=10.0),
        follow_redirects=True,
        limits=httpx.Limits(
            max_connections=50,
            max_keepalive_connections=50,
            keepalive_expiry=120,
        ),
        event_hooks=event_hooks,
    )


def _quota_hook(provider: str, api_key: str, model: str) -> Any:
    """httpx response hook that forwards this member's rate-limit headers.

    Groq's TPM/request budget is only observable here, in the worker. The hook
    swallows everything: it runs inside the transport on the call's critical
    path, so a bookkeeping error must never surface as a failed turn.

    MUST be ``async``: ``httpx.AsyncClient`` awaits every response hook
    unconditionally (``await hook(response)``), so a plain function raises
    ``TypeError: object NoneType can't be used in 'await' expression`` inside
    ``send()``. openai wraps that in ``APIConnectionError``, so a sync hook
    killed EVERY LLM request - every member of the chain failed, each turn
    burned the failover budget, and the caller heard silence (live calls
    phone-7/phone-8, and quota headers were never captured either).
    """

    async def _capture(response: Any) -> None:
        try:
            from app.usage_reporter import record_llm_response

            record_llm_response(provider, api_key, model, response)
        except Exception:  # noqa: BLE001 - never raise into httpx
            logger.debug("quota header capture skipped", exc_info=True)

    return _capture


def _llm_connection_kwargs(
    api_key: str, base_url: str, clients: Optional[list[Any]] = None,
    *, provider: str = "", model: str = "",
) -> dict[str, Any]:
    """Build one member's OpenAI client without touching its siblings.

    ``clients`` collects the httpx clients so ``run_session`` can close them at
    session end. Keep ``api_key``/``base_url`` for introspection and for test
    fakes that do not understand ``client``; the real plugin uses ``client``.
    ``provider``/``model`` label the quota hook that reports ``x-ratelimit-*``.
    """
    hooks = None
    if provider:
        hook = _quota_hook(provider, api_key, model)
        hooks = {"response": [hook]}
    try:
        http_client = _new_llm_http_client(hooks)
    except Exception:  # noqa: BLE001 - fall back to the plugin's own client
        return {"api_key": api_key, "base_url": base_url}
    if clients is not None:
        clients.append(http_client)
    return {
        "api_key": api_key,
        "base_url": base_url,
        "client": _OpenAIAsyncClient(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            http_client=http_client,
        ),
    }


def _groq_client_kwargs(model: str) -> dict[str, Any]:
    """Per-model kwargs for one OpenAI-compatible Groq client.

    GPT-OSS rejects ``reasoning_effort="none"`` (400: must be low/medium/high),
    so it gets the minimum. Qwen does not think out loud and must not receive
    the knob at all.
    """
    kwargs: dict[str, Any] = {}
    if "gpt-oss" in str(model or "").lower():
        kwargs["reasoning_effort"] = "low"
    # Voice turns are 1-3 sentences. The cap must be big enough for the model
    # to actually finish: a reasoning model spends its output budget thinking
    # first, and truncation at 160 returned an empty reply (the "agent goes
    # silent mid-call" symptom), while it also has to stay under the output
    # tokens/min tier or the call 429s.
    kwargs["max_completion_tokens"] = _max_completion_tokens_for(model)
    return kwargs


def build_providers(
    settings: Settings,
    voice_settings: Optional[Mapping[str, Any]] = None,
    *,
    is_phone: bool = False,
) -> ProviderBundle:
    """Build STT/LLM/TTS from settings; missing keys degrade, never raise.

    ``voice_settings`` is the agent-version's saved config; when it carries a
    per-agent ``llm_model`` / ``tts_voice_id`` those override the platform
    defaults (GROQ_MODEL env / provider default voice). ``is_phone`` marks a
    PSTN leg so the TTS can emit telephony-native audio (see the Sarvam block).
    """
    bundle = ProviderBundle(stt=None, llm=None, tts=None)
    model_override, tts_voice_override, voices_by_lang, language = _voice_overrides(voice_settings)
    bundle.language = language
    effective_voice = voices_by_lang.get(language) or tts_voice_override

    # STT provider routing. A non-English agent must be transcribed by Sarvam
    # Saaras (Nova has no te/hi/bn models in the streaming plugin), while
    # English stays on Deepgram Nova-3, which is the faster of the two and the
    # locked stack default. STT_PROVIDER=sarvam forces Sarvam everywhere;
    # STT_LANGUAGE_ROUTING=off disables the per-language promotion.
    stt_choice = os.getenv("STT_PROVIDER", "deepgram").strip().lower()
    route_stt = os.getenv("STT_LANGUAGE_ROUTING", "on").strip().lower() not in (
        "off", "0", "no", "false",
    )
    _agent_language = str((voice_settings or {}).get("language", "") or "").strip().lower()
    _indian_language = bool(_agent_language) and _agent_language not in (
        "en", "en-in", "en-us", "en-gb",
    )
    _sarvam_key = os.getenv("SARVAM_TTS_API", "") or os.getenv("SARVAM_API_KEY", "")
    use_sarvam_stt = stt_choice == "sarvam" or (
        route_stt and _indian_language and bool(_sarvam_key)
    )

    if settings.deepgram_api_key and not use_sarvam_stt:
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
    elif use_sarvam_stt:
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
            explicit_language = str(
                (voice_settings or {}).get("language", "") or ""
            ).strip()
            # Explicit stt_language wins; otherwise the agent's own language
            # wins over the platform env default (a Telugu agent must not be
            # transcribed as English just because SARVAM_STT_LANG is unset).
            sarvam_lang = (
                str((voice_settings or {}).get("stt_language", "") or "").strip()
                or _bcp47_language(explicit_language)
                or os.getenv("SARVAM_STT_LANG", "en-IN")
            )
            # Sarvam requires BCP-47 (en-IN, hi-IN); our configs carry bare
            # codes ("en"). A bare code raises ValueError at STT construction
            # and degrades the whole session, so map the common ones.
            sarvam_lang = _bcp47_language(sarvam_lang)
            # Callers code-switch mid-sentence (Tenglish: "school ki vellaledu,
            # he had fever"). ``codemix`` keeps English words in English and the
            # Indian language in its own script, so the LLM reads natural mixed
            # text instead of a forced transliteration it has to translate back.
            # SARVAM_STT_MODE / voice_settings.stt_mode overrides (transcribe |
            # translate | verbatim | translit | codemix).
            sarvam_mode = (
                str((voice_settings or {}).get("stt_mode", "") or "").strip()
                or os.getenv("SARVAM_STT_MODE", "codemix")
            )
            bundle.stt = _sarvam_stt.STT(
                language=sarvam_lang,
                model=os.getenv("SARVAM_STT_MODEL", "saaras:v4"),
                mode=sarvam_mode,
                api_key=sarvam_key,
                flush_signal=True,
            )
            bundle.stt_provider = "sarvam"
            logger.info("STT provider: Sarvam Saaras (%s mode=%s)", sarvam_lang, sarvam_mode)
    else:
        bundle.problems.append(
            "DEEPGRAM_API_KEY missing - speech-to-text disabled"
        )

    selected_tts = os.getenv("TTS_PROVIDER", "cartesia").lower()
    sarvam_key = os.getenv("SARVAM_TTS_API", "") or os.getenv("SARVAM_API_KEY", "")
    explicit_language = str(
        (voice_settings or {}).get("language", "") or ""
    ).strip().lower()
    # Indian-language agents must use Bulbul: Cartesia/Aura voices mangle
    # Indian names and cannot code-switch Telugu-English. English keeps the
    # operator's chosen provider (Cartesia in production, Sarvam when set).
    # TTS_LANGUAGE_ROUTING=off restores a strict TTS_PROVIDER choice.
    route_by_language = os.getenv("TTS_LANGUAGE_ROUTING", "on").strip().lower() not in (
        "off", "0", "no", "false",
    )
    indian_language = bool(explicit_language) and explicit_language not in (
        "en", "en-in", "en-us", "en-gb",
    )
    use_sarvam_tts = bool(sarvam_key) and (
        selected_tts == "sarvam" or (route_by_language and indian_language)
    )
    if use_sarvam_tts:
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
        # Explicit tts_language wins; otherwise follow the agent language so
        # a Telugu prompt is not paired with an English voice.
        sarvam_lang = (
            str((voice_settings or {}).get("tts_language", "") or "").strip()
            or _bcp47_language(explicit_language)
            or os.getenv("SARVAM_TTS_LANG", "en-IN")
        )
        sarvam_lang = _bcp47_language(sarvam_lang)
        # 8000 Hz is telephony narrowband (the platform is a phone agent).
        # Browser-only demos can set SARVAM_TTS_SAMPLE_RATE=22050 for fuller
        # audio; LiveKit resamples PSTN down automatically either way.
        try:
            sarvam_rate = int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "8000"))
        except ValueError:
            sarvam_rate = 8000
        if sarvam_rate not in (8000, 16000, 22050, 24000, 32000, 44100, 48000):
            sarvam_rate = 8000
        # A PSTN leg IS 8 kHz G.711, so ask Bulbul for mu-law directly instead
        # of mp3: mp3 at 8 kHz is an MPEG-2.5 mode with audible grain, and it
        # costs an encoder round trip plus a decoder in the hot path. The
        # plugin decodes the mu-law to PCM for LiveKit, and the bridge re-encodes
        # it for the carrier — same codec in and out, so nothing is added in
        # between. Browser rooms keep mp3 (narrowband would sound muffled).
        _TTS_CODECS = ("mp3", "mulaw", "alaw", "wav", "linear16", "flac", "aac", "opus")
        sarvam_codec = os.getenv("SARVAM_TTS_CODEC", "").strip().lower()
        if sarvam_codec not in _TTS_CODECS:
            sarvam_codec = "mulaw" if is_phone else "mp3"
        if sarvam_codec in ("mulaw", "alaw"):
            sarvam_rate = 8000
        try:
            sarvam_pace = float((voice_settings or {}).get("speaking_rate", 1.0))
        except (TypeError, ValueError):
            sarvam_pace = 1.0
        sarvam_pace = max(0.3, min(3.0, sarvam_pace))
        bundle.tts = _sarvam.TTS(
            target_language_code=sarvam_lang,
            model=sarvam_model,
            speaker=sarvam_speaker,
            speech_sample_rate=sarvam_rate,
            pace=sarvam_pace,
            api_key=sarvam_key,
            output_audio_codec=sarvam_codec,
        )
        bundle.tts_provider = "sarvam"
        logger.info(
            "TTS provider: Sarvam Bulbul (%s/%s/%s rate=%d codec=%s pace=%.2f)",
            sarvam_model,
            sarvam_speaker,
            sarvam_lang,
            sarvam_rate,
            sarvam_codec,
            sarvam_pace,
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
        bundle.tts_provider = "cartesia"
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
        bundle.tts_provider = "deepgram"
        logger.info("TTS provider: Deepgram Aura (%s)", aura_model)
    else:
        bundle.problems.append("CARTESIA_API_KEY missing - text-to-speech disabled")

    # Each chain member gets its own httpx pool so one member/plugin closing its
    # client cannot kill its siblings. The expensive TLS context is shared at
    # import, so this no longer blocks the event loop for ~2.9s.
    llm_clients: list[Any] = []

    # Members that answer BEFORE the Groq pool (LLM_PRIMARY_CHAIN). The
    # benchmarked voice fast path: Sarvam 105B holds ~0.5-0.65s on the full
    # 2.7k-token prompt while Groq's org-wide 8000 TPM bucket caps it at ~2-3
    # turns a minute. Empty primary keeps the historical Groq-first order.
    primary_llms: list[Any] = []
    primary_names: list[str] = []
    # An agent that pins its own llm_model has made the routing decision, so
    # the platform primary would silently override the operator's choice.
    for name, base_url, api_key, model in (
        () if model_override else settings.llm_primary_chain
    ):
        if not base_url:
            continue
        try:
            primary_llms.append(
                openai.LLM(
                    model=model,
                    **_llm_connection_kwargs(
                        api_key, base_url, llm_clients,
                        provider=name, model=model,
                    ),
                    max_completion_tokens=_max_completion_tokens_for(model),
                )
            )
            primary_names.append(name)
        except Exception as exc:  # noqa: BLE001 — never block the chain
            logger.warning("LLM primary member %s rejected: %s", name, exc)
    if primary_llms:
        logger.info(
            "LLM primary members: %s",
            ", ".join(
                f"{name}:{getattr(m, 'model', '?')}"
                for name, m in zip(primary_names, primary_llms)
            ),
        )

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
    groq_secondary_llm: Any = None
    if groq_keys:
        # Groq is an OpenAI-compatible endpoint, so construct it explicitly.
        # GROQ_BASE_URL can point at any compatible provider (Cerebras).
        for key in groq_keys:
            groq_llms.append(
                openai.LLM(
                    model=groq_model,
                    **_llm_connection_kwargs(
                        key, groq_base_url, llm_clients,
                        provider="groq", model=groq_model,
                    ),
                    **_groq_client_kwargs(groq_model),
                )
            )
        # Model-level fallback: after the whole primary pool, try one different
        # Groq model on the first key. This is a QUALITY tier (gpt-oss-120b),
        # not a quota expansion: if the org bucket is empty, this member 429s
        # too and the chain moves on to Sarvam. Only arm it on Groq's endpoint;
        # an OpenAI model id on Cerebras would 404 (not retryable).
        secondary_model = str(
            getattr(settings, "groq_secondary_model", "") or ""
        ).strip()
        if (
            secondary_model
            and secondary_model != groq_model
            and "groq.com" in groq_base_url
        ):
            try:
                groq_secondary_llm = openai.LLM(
                    model=secondary_model,
                    **_llm_connection_kwargs(
                        groq_keys[0], groq_base_url, llm_clients,
                        provider="groq-secondary", model=secondary_model,
                    ),
                    **_groq_client_kwargs(secondary_model),
                )
            except Exception as exc:  # noqa: BLE001 — never block the chain
                logger.warning(
                    "Secondary Groq model %s rejected: %s", secondary_model, exc
                )
    if groq_llms:
        # Primary tier first (Sarvam 105B), then the Groq pool (qwen on every
        # key), then the secondary Groq model (gpt-oss-120b), then overflow
        # providers (Velona). This is the fix for the Groq-first chain, which
        # put a shared 8000 TPM bucket in front of every turn's first token.
        chain: list[Any] = list(primary_llms) + list(groq_llms)
        chain_providers: list[str] = list(primary_names) + ["groq"] * len(groq_llms)
        if groq_secondary_llm is not None:
            chain.append(groq_secondary_llm)
            chain_providers.append("groq-secondary")
        # Extra OpenAI-compatible providers (LLM_FALLBACK_CHAIN / DeepSeek /
        # Cerebras / OpenRouter). Sarvam is the intended overflow: the
        # ToolTurnFiller below covers its silent tool turns, so it is no longer
        # a dead-air liability. It only fires after the whole Groq tier.
        for name, base_url, api_key, model in settings.llm_fallback_chain:
            if not base_url:
                continue
            try:
                chain.append(
                    openai.LLM(
                        model=model,
                        **_llm_connection_kwargs(
                            api_key, base_url, llm_clients,
                            provider=name, model=model,
                        ),
                        max_completion_tokens=_max_completion_tokens_for(model),
                    )
                )
                chain_providers.append(name)
                logger.info("LLM chain member armed: %s (%s)", name, model)
            except Exception as exc:  # noqa: BLE001 — never block the chain
                logger.warning("LLM chain member %s rejected: %s", name, exc)
        if len(chain) > 1:
            logger.info(
                "LLM chain armed (%d members): %s",
                len(chain),
                ", ".join(
                    f"{name}:{getattr(m, 'model', '?')}"
                    for name, m in zip(chain_providers, chain)
                ),
            )
            bundle.llm = FallbackLLM(
                chain,
                provider_names=chain_providers,
                prefer_provider=_preferred_llm_provider(
                    language, chain_providers, [getattr(m, "model", "") for m in chain]
                ),
            )
        else:
            bundle.llm = chain[0]
    elif settings.llm_fallback_chain or primary_llms:
        # No Groq at all, but primary/extra providers are configured: arm ALL
        # of them as a fallback chain (not just the first) with the same output
        # caps, so reasoning models can't truncate to empty replies and a dead
        # member cools down instead of silencing the call.
        extra_llms: list[Any] = list(primary_llms)
        extra_names: list[str] = list(primary_names)
        for name, base_url, api_key, model in settings.llm_fallback_chain:
            if not base_url:
                continue
            try:
                extra_llms.append(
                    openai.LLM(
                        model=model,
                        **_llm_connection_kwargs(
                            api_key, base_url, llm_clients,
                            provider=name, model=model,
                        ),
                        max_completion_tokens=_max_completion_tokens_for(model),
                    )
                )
                extra_names.append(name)
            except Exception as exc:  # noqa: BLE001 — never block the chain
                logger.warning("LLM chain member %s rejected: %s", name, exc)
        if len(extra_llms) > 1:
            logger.info(
                "GROQ_API_KEY missing - using provider chain: %s",
                ", ".join(
                    f"{name}:{getattr(m, 'model', '?')}"
                    for name, m in zip(extra_names, extra_llms)
                ),
            )
            bundle.llm = FallbackLLM(
                extra_llms,
                provider_names=extra_names,
                prefer_provider=_preferred_llm_provider(
                    language, extra_names, [getattr(m, "model", "") for m in extra_llms]
                ),
            )
        elif extra_llms:
            bundle.llm = extra_llms[0]
            logger.info("GROQ_API_KEY missing - using %s (%s)", extra_names[0], getattr(extra_llms[0], "model", "?"))
        if bundle.llm is None:
            bundle.problems.append("No usable LLM chain member (bad LLM_FALLBACK_CHAIN)")
    elif settings.openai_api_key:
        logger.info(
            "GROQ_API_KEY missing - falling back to OpenAI %s",
            settings.openai_model,
        )
        bundle.llm = openai.LLM(
            model=settings.openai_model,
            **_llm_connection_kwargs(
                settings.openai_api_key, settings.openai_base_url, llm_clients,
                provider="openai", model=settings.openai_model,
            ),
            max_completion_tokens=_max_completion_tokens_for(settings.openai_model),
        )
    else:
        bundle.problems.append("No LLM key (GROQ_API_KEY / OPENAI_API_KEY) set")

    bundle.llm_clients = llm_clients
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


#: Short, natural cues for a tool call the model did not verbally acknowledge.
#: Chosen by tool so "Let me note that down" never fires for end_call.
_TOOL_FILLERS: dict[str, str] = {
    "record_extracted_field": "Let me note that down.",
}
_DEFAULT_TOOL_FILLER = "One moment, please."
#: end_call is deliberately exempt: the follow-up closing line is the speech,
#: and a filler after the call is already being torn down only adds noise.
_TOOL_FILLER_EXEMPT: frozenset[str] = frozenset({"end_call"})


def tool_filler_for(function_name: str) -> Optional[str]:
    """Return the spoken filler for a tool call, or None when it should stay silent."""
    name = str(function_name or "").strip()
    if not name or name in _TOOL_FILLER_EXEMPT:
        return None
    return _TOOL_FILLERS.get(name, _DEFAULT_TOOL_FILLER)


class ToolTurnFiller:
    """Speak one short filler when a tool call would otherwise be silent.

    Measured gap across providers: even the best model (qwen3.8-27b) produced
    no speech on 1 of 6 tool turns; Sarvam was silent on 5 of 6. The tool
    result is not the problem - the model simply called the tool without a
    spoken acknowledgement first. This listener fixes that in the PIPELINE,
    for every provider:

    * reset on each final caller transcript;
    * remember whether the assistant generated any text this turn (a message
      may contain both text and tool calls);
    * on the first tool_call_started of a silent turn, say one short cue.

    The cue is not added to the LLM context, so the model never reacts to its
    own filler, and it is interruptible like any other agent speech.
    """

    def __init__(self, session: Any, say: Any = None) -> None:
        self._session = session
        self._say = say
        self._assistant_spoke = False
        self._filler_spoken = False

    def reset(self) -> None:
        self._assistant_spoke = False
        self._filler_spoken = False

    def on_user_input_transcribed(self, ev: Any) -> None:
        if not bool(getattr(ev, "is_final", False)):
            return
        if not str(getattr(ev, "transcript", "") or "").strip():
            return
        self.reset()

    def on_conversation_item_added(self, ev: Any) -> None:
        item = getattr(ev, "item", None)
        if item is None:
            return
        if str(getattr(item, "role", "") or "").lower() != "assistant":
            return
        text = scrub_speech_text(str(getattr(item, "text_content", "") or ""))
        if text.strip():
            self._assistant_spoke = True

    def on_tool_execution_updated(self, ev: Any) -> None:
        update = getattr(ev, "update", None)
        if str(getattr(update, "type", "") or "") != "tool_call_started":
            return
        if self._assistant_spoke or self._filler_spoken:
            return
        # Never stack a cue over audio that is already playing. The text flag
        # above is the primary guard; this covers an event that raced ahead.
        if "speaking" in str(getattr(self._session, "agent_state", "") or "").lower():
            return
        function_call = getattr(update, "function_call", None)
        name = str(getattr(function_call, "name", "") or "")
        phrase = tool_filler_for(name)
        if not phrase:
            return
        try:
            say = self._say or self._session.say
            say(phrase, allow_interruptions=True, add_to_chat_ctx=False)
        except Exception:  # noqa: BLE001 — a missed cue must never break the call
            logger.debug("Tool-turn filler failed", exc_info=True)
            return
        self._filler_spoken = True
        logger.info("Spoke tool-turn filler for %s", name or "?")


class TurnTelemetry:
    """Accumulates one exchange (user utterance + agent reply), posts it.

    Latency definitions (all milliseconds):
    - ``stt_final_ms``: end-of-speech -> final user transcript = LiveKit EOU
      metric ``end_of_utterance_delay`` ONLY (EOU decision time).
    - ``transcription_delay_ms``: Deepgram finalization lag
      (EOU metric ``transcription_delay``), logged separately so the two STT
      levers are distinguishable (P0-1).
    - ``llm_first_token_ms``: LLM time-to-first-token (``LLMMetrics.ttft``, or
      the chain's own in-stream measurement when the SDK reports none).
    - ``tts_first_audio_ms``: TTS time-to-first-audio-byte (``TTSMetrics.ttfb``).
    - ``e2e_ms``: the caller's own latency — their end of speech until the
      agent's audio started, measured on one wall clock. NOT a sum of the
      stage timings: that double-counted a slow stage which had already been
      overlapped by streaming, and turned a 0.6 s reply into a reported 20 s.
    - ``llm_reply_ms``: time until the assistant item committed, i.e. full
      generation length. Kept out of ``llm_first_token_ms`` on purpose.

    Event wiring for livekit-agents 1.8.3: there is NO ``session.metrics``
    collector object on AgentSession — the session EMITS a single
    ``"metrics_collected"`` event whose payload wraps one AgentMetrics object
    per measurement (``MetricsCollectedEvent.metrics``), typed via its
    ``type`` discriminator ("eou_metrics" | "llm_metrics" | "tts_metrics").
    Field names verified against livekit.agents.metrics 1.8.3:
    EOUMetrics.end_of_utterance_delay/.transcription_delay,
    LLMMetrics.ttft (-1 when no token), TTSMetrics.ttfb.
    If the event shape ever changes again, wall-clock fallbacks below keep the
    columns populated; nothing is reported as a first token unless something
    actually measured one.
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
        language: str = "en",
    ) -> None:
        self._session = session
        self._backend = backend
        self._call_id = call_id
        self._room = room
        self._language = language
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
        # When the agent's audio actually started, and when its text item
        # finally committed. The first is what the caller experiences as the
        # agent's response time; the second is generation time, not first
        # token, and must never be reported as one.
        self._first_speech_at: Optional[float] = None
        self._llm_reply_ms: Optional[float] = None
        self._stt_final_ms: Optional[float] = None
        self._transcription_delay_ms: Optional[float] = None
        self._llm_first_token_ms: Optional[float] = None
        self._tts_first_audio_ms: Optional[float] = None
        # A fresh exchange also restarts the LLM's streaming measurement;
        # without this the previous turn's first-token time is reused and
        # every subsequent turn looks as fast (or as slow) as the first.
        try:
            self._llm.begin_exchange()
        except Exception:  # noqa: BLE001 — telemetry must never break a turn
            logger.debug("LLM begin_exchange failed", exc_info=True)
        # Per-stage diagnostic log guards (Fix 4): exactly one INFO line per
        # exchange even though a turn emits one metric per TTS sentence and
        # agent_state may set the latency before the metric event arrives.
        self._llm_metric_logged = False
        self._tts_metric_logged = False
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
            if self._first_speech_at is None:
                self._first_speech_at = time.monotonic()
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
                self._extraction_tools.note_caller_text(transcript)
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

    def _streamed_first_token_ms(self) -> Optional[float]:
        """First content token, from whichever source actually measured it.

        ``LLMMetrics.ttft`` when the provider's SDK reports it, else the LLM
        chain's own in-stream measurement. Deliberately excludes the
        item-commit time: that is generation length, and on a 200-character
        spoken reply it is off by more than an order of magnitude.
        """
        if self._llm_first_token_ms is not None:
            return self._llm_first_token_ms
        try:
            value = getattr(self._llm, "first_token_ms", None)
        except Exception:  # noqa: BLE001 — a missing metric is never fatal
            return None
        return None if value is None else float(value)

    def _watchdog_is_dead(self) -> bool:
        """True only when nothing at all is coming back for this exchange.

        Every earlier version of this guard keyed on the assistant ITEM, which
        commits when generation finishes. A reply that streamed for 19 s (a
        215-character Telugu answer) therefore looked dead at 10 s, and the
        recovery line "Sorry, I didn't quite catch that" landed on top of an
        answer the caller was already hearing. Audio, spoken text and first
        LLM tokens each independently prove the turn is alive.
        """
        if self._got_agent_item or self._agent_text:
            return False
        if self._agent_speaking or self._first_speech_at is not None:
            return False
        return self._streamed_first_token_ms() is None

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
        rooms recover at 10s while browser rooms wait the full 12s.
        """
        try:
            phone_room = "phone-" in str(getattr(self, "_room_name", "") or "")
            # 10s on phone (Vobiz drops silent streams; 7s collided with 5-11s
            # throttled turns and talked over real replies), 12s in browser.
            await asyncio.sleep(10.0 if phone_room else 12.0)
            if generation != self._watchdog_generation:
                return
            if not self._watchdog_is_dead():
                # Something is in flight: give a slow-but-live generation one
                # more window before declaring the turn dead.
                await asyncio.sleep(8.0)
                if (
                    generation != self._watchdog_generation
                    or not self._watchdog_is_dead()
                ):
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
        role = str(getattr(item, "role", "")).lower()
        text = scrub_speech_text(str(getattr(item, "text_content", "") or ""))
        # A message may contain BOTH spoken text and tool calls. The text WAS
        # spoken, so caption it and stop the stall watchdog; only the function
        # call itself must stay out of the transcript. Returning before this
        # check made the watchdog fire on a model that had already replied.
        if role == "assistant" and text:
            if not self._got_agent_item and self._reply_start_at is not None:
                # Generation length, kept separately from first-token: this
                # commit time is when the whole reply finished, which is what
                # let a 0.6 s response get reported as a 19.9 s LLM.
                self._llm_reply_ms = (time.monotonic() - self._reply_start_at) * 1000.0
            if self._llm_first_token_ms is None:
                self._llm_first_token_ms = self._streamed_first_token_ms()
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
            # Per-stage baseline (Fix 4): one line per turn, greppable in
            # `docker compose logs voice-agent`. The structured turn_latency
            # line below aggregates the same numbers for the backend table.
            logger.info(
                "EOU | end_of_utterance_delay=%.0fms transcription_delay=%.0fms",
                eou_s * 1000.0,
                transcription_s * 1000.0,
            )
        elif metric_type == "llm_metrics":
            ttft_seconds = float(getattr(metrics, "ttft", -1.0))
            if ttft_seconds > 0:
                self._llm_first_token_ms = ttft_seconds * 1000.0
            if not self._llm_metric_logged and ttft_seconds > 0:
                self._llm_metric_logged = True
                meta = getattr(metrics, "metadata", None)
                logger.info(
                    "LLM | ttft=%.0fms model=%s/%s",
                    ttft_seconds * 1000.0,
                    getattr(meta, "model_provider", "") or "?",
                    getattr(meta, "model_name", "") or "?",
                )
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
            if not self._tts_metric_logged and ttfb_seconds > 0:
                self._tts_metric_logged = True
                logger.info("TTS | ttfb=%.0fms", ttfb_seconds * 1000.0)
            # livekit-agents 1.8.3 TTSMetrics carries characters_count; older
            # builds named it characters. Accept either.
            characters = getattr(metrics, "characters_count", None)
            if characters is None:
                characters = getattr(metrics, "characters", None)
            if characters is not None:
                self._tts_characters = (self._tts_characters or 0) + int(characters)
        elif metric_type == "stt_metrics":
            logger.info(
                "STT | duration=%.0fms audio=%.0fms",
                float(getattr(metrics, "duration", 0.0) or 0.0) * 1000.0,
                float(getattr(metrics, "audio_duration", 0.0) or 0.0) * 1000.0,
            )

    # -- flushing ------------------------------------------------------------

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def _round(self, value: Optional[float]) -> Optional[int]:
        return None if value is None else round(value)

    async def _maybe_compact_instructions(self) -> None:
        """Swap full instructions for the compact version after the opening.

        The full voice prompt (~8k chars / ~2800 tokens measured) is re-sent on
        every LLM call against Groq's ORGANIZATION-WIDE 8000 tokens/min bucket.
        Measured 2026-10-22: prompt caching does not apply (the same 2850-token
        prompt cost the full 2850 tokens on every repeat, then 429'd), so the
        full prompt permits only ~2 LLM turns/minute before the call stalls on
        a 429 - the 8.3s turn-1 and 14s turn-4 latency seen on a live call.

        The opening exchange already carries the persona, names, disclosure and
        first answer in the history, so from the SECOND LLM turn onward the
        compact rules are enough. VOICE_COMPACT_AFTER_TURNS raises the
        threshold (default 1 = compact as early as possible).
        """
        try:
            threshold = int(_env_float("VOICE_COMPACT_AFTER_TURNS", 1))
            if self._turn_index < threshold:
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
                self._language,
            )
            if await agent.swap_to_compact_instructions(compact):
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
            # The number the caller can actually feel: their voice stopped,
            # then the agent's started. Measured on one wall clock so EOU,
            # STT finalization, LLM and TTS are all inside it. The sum of the
            # three per-stage timings was the fallback and is what made a
            # 0.6 s reply read as 20 s on the dashboard.
            if (
                self._end_of_speech_at is not None
                and self._first_speech_at is not None
                and self._first_speech_at >= self._end_of_speech_at
            ):
                e2e_ms = (self._first_speech_at - self._end_of_speech_at) * 1000.0
            elif (
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
                        "llm_reply_ms": self._round(self._llm_reply_ms),
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

    def __init__(
        self,
        instructions: str,
        tools_impl: VoiceAgentTools,
        on_call_ended: Optional[Callable[[], None]] = None,
    ) -> None:
        self._tools_impl = tools_impl
        self._on_call_ended = on_call_ended
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
        result = await self._tools_impl.end_call(summary)
        # Nothing else ends a phone call: the carrier leg outlives the
        # conversation unless we hang it up, so the session arms its own
        # teardown the moment the model says it is finished.
        if self._on_call_ended is not None:
            try:
                self._on_call_ended()
            except Exception:  # noqa: BLE001 - the summary is already posted
                logger.exception("Could not arm call teardown after end_call")
        return result


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
    """Voice-focus input processor, or None when no plugin is installed.

    Default is Hush (bundled in the image). ``VOICE_NC_PROVIDER=ai_coustics``
    (or ``auto``) prefers ai_coustics QUAIL_VF_L when that optional plugin is
    installed, then falls back to Hush. Runs before turn detection/STT:
    isolates the foreground speaker and suppresses competing voices (TV, car
    passengers) that plain noise cancellation hears as speech. Never raises.

    VOICE_NC=off disables it entirely. Exists because an input-path processor
    is a prime suspect when STT goes silent: if it corrupts or drops frames,
    Deepgram receives garbage and returns nothing while VAD (upstream or
    parallel) still flickers.
    """
    if os.getenv("VOICE_NC", "on").strip().lower() in ("off", "0", "no", "false"):
        return None
    provider = os.getenv("VOICE_NC_PROVIDER", "hush").strip().lower()
    if provider in ("ai_coustics", "auto"):
        try:
            from livekit.plugins import ai_coustics as _ai_coustics

            return _ai_coustics.audio_enhancement(
                model=_ai_coustics.EnhancerModel.QUAIL_VF_L
            )
        except Exception:
            # ai_coustics is an optional, heavier install (model weights +
            # license). Hush is bundled and already voice-focus, so fall
            # back rather than starting the call with no input conditioning.
            logger.warning(
                "ai_coustics unavailable, falling back to Hush", exc_info=True
            )
    try:
        from livekit.plugins import hush as _hush
    except ImportError:
        return None
    try:
        return _hush.noise_suppression()
    except Exception:
        logger.warning("Hush unavailable, continuing without it", exc_info=True)
        return None


def _room_options(*, is_phone: bool = False) -> Any:
    """RoomOptions with voice-focus audio input, or None for a plain start.

    ``is_phone`` additionally pins the agent's OUTPUT to 8 kHz. A PSTN leg is
    8 kHz G.711 and Sarvam already hands us 8 kHz mu-law, so publishing at the
    leg's own rate keeps the call byte-exact: the alternative (default 24 kHz
    output) makes LiveKit upsample 8k -> 24k/48k and the media bridge decimate
    straight back down, i.e. two resampler passes and their filter ringing for
    audio that ends up narrowband anyway. Browser rooms keep the 24 kHz default.
    """
    nc = _get_noise_cancellation()
    if nc is None:
        logger.info("Noise cancellation: none (VOICE_NC=off or plugin missing)")
        if not is_phone:
            return None
    else:
        logger.info("Noise cancellation: %s", type(nc).__name__)
    try:
        from livekit.agents import room_io

        kwargs: dict[str, Any] = {}
        if nc is not None:
            kwargs["audio_input"] = room_io.AudioInputOptions(noise_cancellation=nc)
        if is_phone:
            kwargs["audio_output"] = room_io.AudioOutputOptions(sample_rate=8000)
            logger.info("Agent audio output: 8000 Hz (PSTN leg)")
        return room_io.RoomOptions(**kwargs)
    except Exception:
        logger.warning("RoomOptions unsupported here, plain start", exc_info=True)
        return None


def _preemptive_kwargs(enabled: bool) -> dict[str, Any]:
    """Version-tolerant preemptive-generation option.

    livekit-agents 1.8+ requires a ``PreemptiveGenerationOptions`` MAPPING
    and raises ``TypeError: 'bool' object is not a mapping`` for a plain
    boolean (this killed every phone session with the apology fallback).
    Older versions take the boolean. Disabled means an explicit
    enabled=False mapping - omitting the key fills SDK defaults, which are
    enabled=True, i.e. the exact opposite of "deterministic turn-taking".
    """
    if _PreemptiveOpts is None:
        return {"preemptive_generation": bool(enabled)}
    if not enabled:
        return {"preemptive_generation": _PreemptiveOpts(enabled=False)}
    # Speculate on the STT partial for the LLM, but do NOT start TTS until the
    # turn is confirmed: preemptive TTS synthesizes cancelled turns and burns
    # Sarvam characters/credits for audio nobody hears.
    return {
        "preemptive_generation": _opts(
            _PreemptiveOpts, enabled=True, preemptive_tts=False
        )
    }


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
    """Fields the agent must collect from the caller.

    Agent-derived fields are excluded: call 96 asked the parent "May I know the
    outcome" and then reported call_outcome as an unfilled required field,
    because the schema had validation=required on something only the agent can
    decide when it closes.
    """
    schema = config.get("extraction_schema")
    required: set[str] = set()
    if isinstance(schema, Mapping):
        for name, spec in schema.items():
            if str(name) in _AGENT_DERIVED_FIELDS:
                continue
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


def _env_float(name: str, default: float) -> float:
    """Read a float env var, falling back to ``default`` on garbage/unset.

    Used for the latency knobs so a demo can be re-tuned from the LiveKit
    agent secrets without a code change; a malformed value must never break
    the session, so it silently becomes the default.
    """
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("%s=%r is not a number, using %s", name, raw, default)
        return default


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
    turn_detector = "stt" if sarvam_stt else _turn_detection()
    # Greppable in live logs: a SmartTurn* class is the bundled Smart Turn v3,
    # a TurnDetector is the semantic cloud fallback, "vad" is the last resort.
    logger.info(
        "Turn detection: %s",
        turn_detector if isinstance(turn_detector, str) else type(turn_detector).__name__,
    )
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
            turn_detection=turn_detector,
            # Preemptive generation: start the LLM on partial transcripts so
            # the first sentence is ready the moment the turn ends (TTS
            # already synthesizes sentence-by-sentence as tokens stream in).
            # Playground-only: on PSTN phone audio the partials are too noisy
            # and speculative replies answer stale turns / talk over callers.
            **_preemptive_kwargs(preemptive_generation),
            endpointing=_opts(
                EndpointingOptions,
                mode="fixed",
                # Semantic turn detection decides when the caller is done;
                # endpointing is only the wall-clock bound. The floor is dead
                # time added to EVERY turn, so it is the single cheapest
                # latency knob: 0.3s is responsive (down from 0.4s) while the
                # semantic detector still catches mid-sentence pauses, and the
                # 2.5s ceiling guarantees a turn can never hang for 25s when
                # VAD/STT never emits end-of-speech.
                # Sarvam's STT processes in ~70ms and its integration guide
                # requires 0.07s, so that provider keeps its special case.
                # VOICE_MIN_ENDPOINTING_DELAY / VOICE_MAX_ENDPOINTING_DELAY
                # override both when a demo needs different tuning.
                min_delay=_env_float(
                    "VOICE_MIN_ENDPOINTING_DELAY", 0.07 if sarvam_stt else 0.3
                ),
                max_delay=_env_float("VOICE_MAX_ENDPOINTING_DELAY", 2.5),
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


#: Backstop for the call wait below. The wait ends by itself when the caller
#: leaves; this only exists so a participant that never disconnects (a browser
#: tab left open) cannot pin a job - and its provider pools - forever.
_MAX_CALL_SECONDS = _env_float("VOICE_MAX_CALL_SECONDS", 1800.0)


class _CallEndWatcher:
    """Holds the session open until the call is over.

    ``run_session`` owns the provider pools and closes them in its ``finally``,
    so returning right after the opening killed every later turn with
    "Cannot send a request, as the client has been closed." - live calls
    phone-7..phone-10 played the greeting, then went silent while the caller
    stayed connected. The call is over when the caller leaves, the room closes,
    or the agent session closes; whichever comes first ends the wait.

    Subscribing happens in ``__init__``, before the opening is spoken, because
    a caller who hangs up mid-greeting would otherwise disconnect before we
    ever listened for it (and only the room's empty-timeout would end the job).
    """

    def __init__(self, ctx: JobContext, session: Any, room_name: str) -> None:
        self._room_name = room_name
        self._room = ctx.room
        self._done: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._subscriptions: list[tuple[Any, str, Any]] = []
        self._subscribe(
            self._room, "participant_disconnected", self._on_participant_disconnected
        )
        self._subscribe(self._room, "disconnected", self._on_room_disconnected)
        self._subscribe(session, "close", self._on_session_close)

    def _subscribe(self, emitter: Any, event: str, handler: Any) -> None:
        try:
            emitter.on(event)(handler)
            self._subscriptions.append((emitter, event, handler))
        except Exception:  # noqa: BLE001 - a missing signal must not break the call
            logger.debug("Could not subscribe to %s", event, exc_info=True)

    def _finish(self, reason: str) -> None:
        if not self._done.done():
            logger.info("Call over in %s: %s", self._room_name, reason)
            self._done.set_result(reason)

    def _on_participant_disconnected(self, participant: Any = None, *_args: Any) -> None:
        remaining = list(getattr(self._room, "remote_participants", {}).values())
        if remaining:
            # Another caller/observer is still on the line - the call is not over.
            logger.info(
                "%s left %s; %d participant(s) remain",
                getattr(participant, "identity", "?"),
                self._room_name,
                len(remaining),
            )
            return
        self._finish("caller left the room")

    def _on_room_disconnected(self, *_args: Any) -> None:
        self._finish("room disconnected")

    def _on_session_close(self, *_args: Any) -> None:
        self._finish("agent session closed")

    async def wait(self) -> str:
        """Block for the duration of the call, then drop the listeners."""
        try:
            return await asyncio.wait_for(self._done, timeout=_MAX_CALL_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "Call in %s exceeded VOICE_MAX_CALL_SECONDS (%.0fs)",
                self._room_name,
                _MAX_CALL_SECONDS,
            )
            return f"max call duration reached ({_MAX_CALL_SECONDS:.0f}s)"
        finally:
            for emitter, event, handler in self._subscriptions:
                try:
                    emitter.off(event, handler)
                except Exception:  # noqa: BLE001 - teardown only
                    logger.debug("Could not unsubscribe from %s", event, exc_info=True)


#: The agent says "goodbye" before or after its ``end_call`` tool call, never
#: both, so the hangup waits for the line to start (bounded - it may already be
#: spoken), then for the session to go quiet, then cuts the leg. The hard
#: deadline is what guarantees a stuck call still ends.
_GOODBYE_START_SECONDS = _env_float("VOICE_GOODBYE_START_SECONDS", 4.0)
_GOODBYE_QUIET_SECONDS = _env_float("VOICE_GOODBYE_QUIET_SECONDS", 1.0)
_HANGUP_DEADLINE_SECONDS = _env_float("VOICE_HANGUP_DEADLINE_SECONDS", 20.0)
_GOODBYE_POLL_SECONDS = 0.2


def _agent_is_busy(session: Any) -> bool:
    """True while the agent has a speech queued or a reply generating."""
    try:
        if getattr(session, "current_speech", None) is not None:
            return True
    except Exception:  # noqa: BLE001 - a dead session counts as not busy
        return False
    try:
        state = str(getattr(session, "agent_state", "") or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return state.endswith("speaking") or state.endswith("thinking")


async def close_call_after_goodbye(
    session: Any, backend: BackendClient, call_id: str, room_name: str
) -> None:
    """Hang up once the farewell has been heard. Never raises.

    A phone call has no other ending: our answer XML streams with
    ``keepCallAlive``, so the carrier leg outlives the conversation until the
    caller hangs up or the carrier times out.
    """
    loop = asyncio.get_running_loop()
    began = loop.time()
    deadline = began + _HANGUP_DEADLINE_SECONDS
    started = began + _GOODBYE_START_SECONDS
    try:
        while not _agent_is_busy(session) and loop.time() < started:
            await asyncio.sleep(_GOODBYE_POLL_SECONDS)
        quiet_since: Optional[float] = None
        while loop.time() < deadline:
            if _agent_is_busy(session):
                quiet_since = None
            elif quiet_since is None:
                quiet_since = loop.time()
            elif loop.time() - quiet_since >= _GOODBYE_QUIET_SECONDS:
                break
            await asyncio.sleep(_GOODBYE_POLL_SECONDS)
        logger.info(
            "Ending call %s after end_call (room=%s, waited %.1fs)",
            call_id,
            room_name,
            loop.time() - began,
        )
        if not await backend.post_hangup(call_id, room=room_name):
            # Without the backend the leg stays up; still release our own job so
            # the worker's concurrency slot is free for the next dial.
            logger.warning("hangup request failed for call %s, closing session only", call_id)
        await session.aclose()
    except Exception:  # noqa: BLE001 - teardown must never surface as a turn error
        logger.exception("Could not close call %s after end_call", call_id)


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
    # A "phone-" room is a PSTN leg bridged by the backend media router; the
    # "playground-" rooms are browser sessions. Audio treatment differs (see
    # build_providers' TTS codec choice and the preemptive-generation rule).
    is_phone_room = room_name.startswith(PHONE_PREFIX)
    backend = BackendClient(settings.backend_internal_url, settings.internal_api_token)
    # Quota headers are only visible inside this worker, so point the reporter
    # at the backend before any provider call can happen.
    usage_reporter.configure(
        settings.backend_internal_url, settings.internal_api_token
    )
    parsed: Optional[ParsedJob] = parse_room_metadata(_room_metadata(ctx))
    call_id: Optional[str] = parsed.call_id if parsed else None
    session: Optional[AgentSession] = None
    telemetry: Optional[TurnTelemetry] = None
    end_call_task: Optional["asyncio.Task[None]"] = None

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

        bundle = build_providers(
            settings, config.get("voice_settings"), is_phone=is_phone_room
        )
        for problem in bundle.problems:
            logger.error("Provider problem: %s", problem)
        if not bundle.complete:
            await _degrade(
                ctx, backend, call_id, settings, "; ".join(bundle.problems)
            )
            return
        assert bundle.stt is not None and bundle.llm is not None
        assert bundle.tts is not None

        # Warm the TTS connection now, before prompt rendering and session setup.
        # The first live greeting otherwise waited ~5.7s for a cold Sarvam
        # WebSocket handshake (measured). ``prewarm`` starts a background task;
        # the next await (call context fetch) gives it time to run. Applied to
        # every provider, not just Sarvam: Cartesia and Deepgram Aura also open
        # their connection lazily on the first synthesis.
        try:
            bundle.tts.prewarm()
            logger.info("TTS prewarm requested (%s)", bundle.tts_provider)
        except Exception:  # noqa: BLE001 - prewarm is an optimization
            logger.debug("TTS prewarm failed to start", exc_info=True)

        # Fetch per-call context (institution_name + contact) once at session
        # start; {} on failure is fine — tokens resolve to empty and are dropped.
        call_context = await backend.fetch_call_context(call_id)
        tokens = build_token_map(
            contact=parsed.contact,
            context=call_context,
            agent_name=str(config.get("agent_name") or ""),
            company_context=config.get("company_context"),
        )
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

        # Phone rooms get deterministic turn-taking by default: PSTN partials
        # are noisier than browser audio, and a speculative reply to a stale
        # partial both talks over the caller and burns the shared Groq token
        # bucket on a turn nobody hears. Playground keeps preemptive
        # generation for speed. VOICE_PREEMPTIVE_GENERATION=on|off forces it
        # either way (the "auto" default is the per-room rule).
        preemptive_choice = os.getenv("VOICE_PREEMPTIVE_GENERATION", "auto").strip().lower()
        if preemptive_choice in ("on", "1", "yes", "true"):
            preemptive = True
        elif preemptive_choice in ("off", "0", "no", "false"):
            preemptive = False
        else:
            preemptive = not is_phone_room
        logger.info(
            "Preemptive generation: %s (room=%s, VOICE_PREEMPTIVE_GENERATION=%s)",
            preemptive,
            room_name,
            preemptive_choice,
        )
        session = _build_agent_session(bundle, preemptive_generation=preemptive)

        async def _say_cue(text: str) -> None:
            # add_to_chat_ctx=False: a listener cue is not a turn. With the
            # default True, "mm-hmm" became an assistant chat message, fired
            # conversation_item_added, and got flushed as the exchange's reply.
            await session.say(text, allow_interruptions=True, add_to_chat_ctx=False)

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
            language=bundle.language,
        )
        telemetry.attach()

        # Cover silent tool turns for EVERY provider: the model may call a
        # tool without speaking first, and the caller hears dead air while the
        # tool runs + the follow-up reply generates. One short cue per silent
        # turn (never for end_call, never over model speech).
        tool_filler = ToolTurnFiller(session)
        session.on("user_input_transcribed")(tool_filler.on_user_input_transcribed)
        session.on("conversation_item_added")(tool_filler.on_conversation_item_added)
        session.on("tool_execution_updated")(tool_filler.on_tool_execution_updated)

        # Sarvam Bulbul bills per character and exposes no usage API, so count
        # exactly what we asked it to speak. Assistant items cover every
        # utterance including the opening line — the largest single one.
        if bundle.tts_provider == "sarvam":
            sarvam_tts_key = os.getenv("SARVAM_TTS_API", "") or os.getenv(
                "SARVAM_API_KEY", ""
            )
            sarvam_tts_model = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")

            def _count_tts_characters(event: Any) -> None:
                try:
                    item = getattr(event, "item", None)
                    if item is None or getattr(item, "role", "") != "assistant":
                        return
                    text = getattr(item, "text_content", None) or ""
                    if text:
                        usage_reporter.record_tts_characters(
                            text,
                            model=sarvam_tts_model,
                            api_key=sarvam_tts_key,
                        )
                except Exception:  # noqa: BLE001 - accounting never kills a call
                    logger.debug("tts character count failed", exc_info=True)

            session.on("conversation_item_added")(_count_tts_characters)

        # Announce the REAL pipeline this session is running. "Voice mode is
        # not working" is most often a provider that silently degraded, and
        # this is where it becomes visible in the Diagnostics panel.
        telemetry._emit_event(
            "voice_session_start",
            message=(
                f"STT={bundle.stt_provider if bundle.stt else 'DISABLED'} "
                f"LLM={type(bundle.llm).__name__ if bundle.llm else 'DISABLED'}"
                f"{'(chain of %d)' % bundle.llm.chain_size if isinstance(bundle.llm, FallbackLLM) else ''} "
                f"TTS={bundle.tts_provider if bundle.tts else 'DISABLED'} "
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

        def _arm_call_teardown() -> None:
            """Fire once: end_call may be called twice, the leg drops once.

            Phone legs only - a browser playground session is ended by the
            tab that owns it, and deleting its room would hang up the user.
            """
            nonlocal end_call_task
            if end_call_task is not None or not (is_phone_room and call_id):
                return
            end_call_task = asyncio.ensure_future(
                close_call_after_goodbye(session, backend, call_id, room_name)
            )

        agent = DomainCallAgent(
            instructions=instructions,
            tools_impl=tools_impl,
            on_call_ended=_arm_call_teardown,
        )
        # Give telemetry the agent handle so it can swap full instructions for
        # the compact continuation version after the opening exchanges.
        telemetry._agent = agent
        await _start_agent_session(
            session, telemetry, ctx.room, agent,
            room_options=_room_options(is_phone=is_phone_room),
        )
        # Subscribe to the call's end BEFORE the greeting: this task owns the
        # provider pools, so it must stay alive until the caller hangs up (see
        # _CallEndWatcher).
        call_end = _CallEndWatcher(ctx, session, room_name)
        # Agent speaks first: the composed opening remains token-substituted,
        # and the caller can barge in while it is being delivered.
        await _speak_opening(session, config, tokens, parsed.contact)
        await call_end.wait()
        # Close the session here, while the pools are still open: the framework's
        # own teardown would otherwise run after our finally closed them.
        await session.aclose()
    except Exception:
        logger.exception("Unhandled error in voice session (room=%s)", room_name)
        try:
            await _degrade(
                ctx, backend, call_id, settings, "unexpected voice-agent error"
            )
        except Exception:  # pragma: no cover - last resort
            logger.exception("Degradation path also failed (room=%s)", room_name)
    finally:
        if end_call_task is not None and not end_call_task.done():
            # The call already ended another way (caller hung up); the leg is
            # gone, so the farewell wait is pointless.
            end_call_task.cancel()
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
        try:
            # Send whatever quota/character rows are still buffered. The
            # reporter's client is process-wide (several sessions can run in
            # one worker), so it is flushed but never closed here.
            await usage_reporter.flush()
        except Exception:
            logger.exception("Final usage flush failed")
        await backend.aclose()
        bundle_for_close = locals().get("bundle")
        _closing = (
            list(getattr(bundle_for_close, "llm_clients", []) or [])
            if bundle_for_close is not None
            else []
        )
        if _closing:
            # Visible on purpose: this list is exactly the session's LLM pools, so
            # an unexpected early close here used to be indistinguishable from a
            # framework teardown (turns then fail with "client has been closed").
            logger.info("Closing %d LLM pool(s) at session teardown", len(_closing))
        for http_client in _closing:
            try:
                # The pool refuses to close while the session is live, so the
                # session-teardown path is the one place that releases it.
                release = getattr(http_client, "release", None)
                if callable(release):
                    release()
                await http_client.aclose()
            except Exception:  # noqa: BLE001 - session is already over
                logger.debug("LLM HTTP client close failed", exc_info=True)


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
    apology_session = None
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
    finally:
        # A leaked session keeps providers/room refs alive and the room never
        # tears down on this path.
        if apology_session is not None:
            try:
                await apology_session.aclose()
            except Exception:
                logger.debug("apology session close failed", exc_info=True)
        bundle_for_close = locals().get("bundle")
        _closing = (
            list(getattr(bundle_for_close, "llm_clients", []) or [])
            if bundle_for_close is not None
            else []
        )
        if _closing:
            logger.info("Closing %d LLM pool(s) on the degrade path", len(_closing))
        for http_client in _closing:
            try:
                release = getattr(http_client, "release", None)
                if callable(release):
                    release()
                await http_client.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("Apology LLM HTTP client close failed", exc_info=True)

    if call_id:
        posted = await backend.post_complete(
            call_id, status="error", error=reason
        )
        if not posted:
            logger.error("Could not post error completion for call %s", call_id)
