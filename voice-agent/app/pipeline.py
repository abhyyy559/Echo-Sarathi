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
        if index > 0 or len(self._chain) > 1:
            logger.info(
                "LLM chain serving member %d/%d", index + 1, len(self._chain)
            )
        member = self._chain[index]
        # Fail FAST on every member (max 1 quick attempt): the session calls
        # chat() again on failure and the chain advances to the next key. The
        # SDK default (3 retries x 2s + gateway retries) turned one Groq 429
        # into ~13s of dead air before the fallback was even tried.
        conn_options = APIConnectOptions(
            max_retry=1, retry_interval=0.5, timeout=15.0
        )
        member_stream = member.chat(
            **self._chat_kwargs(chat_ctx, tools, conn_options, kwargs)
        )
        return _FallbackStream(self, member_stream, index)


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
            if getattr(exc, "status_code", None) not in _RETRYABLE_LLM_STATUS:
                raise
            logger.warning(
                "LLM chain member %d failed (%s), cooling down for next member",
                self._member_index + 1,
                getattr(exc, "status_code", "connection-error"),
            )
            self._owner._mark_down(self._member_index)
            raise

    async def aclose(self) -> None:
        try:
            await self._active.aclose()
        except Exception:  # noqa: BLE001 — best effort
            pass


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

    if settings.deepgram_api_key:
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
    else:
        bundle.problems.append(
            "DEEPGRAM_API_KEY missing - speech-to-text disabled"
        )

    if settings.cartesia_api_key:
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
        if "qwen" in groq_model.lower():
            # Qwen3 is a hybrid reasoning model — thinking tokens add seconds
            # of voice latency. Disable reasoning entirely (NFR-1).
            kwargs["reasoning_effort"] = "none"
        elif "gpt-oss" in groq_model.lower():
            # GPT-OSS rejects "none" (400: must be low/medium/high) — use the
            # minimum. Combined with max_completion_tokens=300, thinking
            # stays a short prefix before the spoken reply.
            kwargs["reasoning_effort"] = "low"
        # Voice turns are 1-3 sentences: cap output well under Groq's
        # on_demand 1000 output-tokens/min tier (an uncapped request asks for
        # ~1215 and gets 429 rate_limited, which wedges the whole call).
        kwargs["max_completion_tokens"] = 300
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
        if settings.openai_api_key:
            # Same-tier fallback, different provider: Groq on_demand caps
            # (~8000 TPM shared with retries) wedging calls after ~3 turns.
            # The wrapper re-issues the identical request once on OpenAI.
            chain.append(
                openai.LLM(
                    model=settings.openai_model,
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    max_completion_tokens=300,
                )
            )
        if len(chain) > 1:
            logger.info(
                "LLM chain armed (%d members): %s (Groq x%d)%s",
                len(chain),
                groq_model,
                len(groq_llms),
                f" -> {settings.openai_model} (OpenAI)" if settings.openai_api_key else "",
            )
            bundle.llm = FallbackLLM(chain)
        else:
            bundle.llm = groq_llms[0]
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
    ) -> None:
        self._session = session
        self._backend = backend
        self._call_id = call_id
        self._room = room
        self._on_final_user = on_final_user
        self._backchannel = backchannel
        self._turn_index = 0
        self._flush_lock = asyncio.Lock()
        self._activity_sequence = 1
        self._activity_post_lock = asyncio.Lock()
        self._activity_seen_events: set[tuple[str, str, str, float]] = set()
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

    def _on_user_input_transcribed(self, ev: Any) -> None:
        transcript = str(getattr(ev, "transcript", "") or "").strip()
        is_final = bool(getattr(ev, "is_final", False))
        if transcript:
            # Stream PARTIAL captions too so the browser transcript feels live.
            self._publish_caption("user", transcript, final=is_final)
        if not is_final:
            return
        if not transcript:
            return
        self._user_text = f"{self._user_text} {transcript}".strip()
        # The is_final event already published the caption above; publishing
        # again here duplicated the final caption in the browser transcript.
        if self._reply_start_at is None:
            self._reply_start_at = time.monotonic()
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

    async def flush_pending(self) -> None:
        """Post the current exchange (if any) as turn rows and log once."""
        async with self._flush_lock:
            if not self._user_text and not self._agent_text:
                return
            self._turn_index += 1
            turn_index = self._turn_index
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
        # NOTE: do NOT pass tools= here — livekit-agents auto-collects the
        # @function_tool-decorated methods below; passing them again raises
        # "duplicate function name".
        super().__init__(instructions=instructions)

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
    """
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
    return AgentSession(
        stt=bundle.stt,
        llm=bundle.llm,
        tts=bundle.tts,
        vad=_get_vad(),
        aec_warmup_duration=0.0,
        turn_handling=_opts(
            TurnHandlingOptions,
            turn_detection=_turn_detection(),
            # Preemptive generation: start the LLM on partial transcripts so
            # the first sentence is ready the moment the turn ends (TTS
            # already synthesizes sentence-by-sentence as tokens stream in).
            # Playground-only: on PSTN phone audio the partials are too noisy
            # and speculative replies answer stale turns / talk over callers.
            **_preemptive_kwargs(preemptive_generation),
            endpointing=_opts(
                EndpointingOptions,
                mode="fixed",
                # 600ms patience: hesitant speakers pause mid-thought — jumping
                # in at 350ms is what callers feel as "the agent interrupts me".
                min_delay=0.6,
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


async def _start_agent_session(
    session: Any,
    telemetry: TurnTelemetry,
    room: Any,
    agent: Any,
    room_options: Any = None,
) -> None:
    telemetry.queue_agent_connecting()
    if room_options is None:
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
        )
        telemetry.attach()

        async def _backchannel_loop() -> None:
            try:
                while True:
                    await asyncio.sleep(0.5)
                    await backchannel.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — cues never kill sessions
                logger.exception("Backchannel loop failed")

        backchannel_task = asyncio.ensure_future(_backchannel_loop())

        if not await _is_connected(ctx):
            await ctx.connect()

        agent = DomainCallAgent(instructions=instructions, tools_impl=tools_impl)
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
        if telemetry is not None:
            try:
                await telemetry.flush_pending()
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
