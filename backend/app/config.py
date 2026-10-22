"""Application settings (pydantic-settings) — all environment variables consumed by the backend.

Every variable name matches the project-level `.env.example` maintained by devops.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)

#: Repository root (backend/app/config.py -> backend/app -> backend -> root).
#: The root .env is authoritative for shared LLM/provider settings so the
#: playground and the Docker campaign cannot silently use different keys or
#: models. backend/.env still supplies backend-only values, but the root file
#: is loaded LAST and therefore wins on overlapping names.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILES = (".env", str(_REPO_ROOT / ".env"))

#: Values that are obviously template leftovers, not real credentials. A
#: placeholder key in the LLM chain would 401 on every turn and mask the real
#: provider failure, so it never occupies a chain slot.
_TEMPLATE_MARKERS = (
    "your_",
    "paste-",
    "paste_",
    "changeme",
    "change-me",
    "placeholder",
    "example",
    "xxx",
    "<",
    "todo",
)


def _looks_like_template(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in _TEMPLATE_MARKERS)


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- infrastructure -------------------------------------------------
    database_url: str = "sqlite:///./voice_agent.db"
    # Redis is optional: nothing in this app uses it (the dialer is
    # Postgres-backed). Empty means "not configured" and /api/health reports
    # it as unknown instead of a permanent red dot.
    redis_url: str = ""
    environment: str = "development"
    log_level: str = "info"
    # Daily Deepgram/Cartesia poll cadence. Zero disables the background task.
    usage_refresh_interval_hours: int = 24

    # --- telephony (provider selection) -----------------------------------
    # "", "twilio", "plivo" or "vobiz". Empty = auto-select (Plivo wins when
    # both credential sets are present; Plivo is the cheaper India leg).
    # Set explicitly to "vobiz" to place calls over Vobiz.
    telephony_provider: str = ""

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_validate_signature: bool = True

    # Vobiz (India CPaaS: REST calls + XML <Stream> bidirectional websockets)
    vobiz_auth_id: str = ""
    vobiz_auth_token: str = ""
    vobiz_phone_number: str = ""
    # Optional shared secret for Vobiz webhook callbacks (X-Vobiz-Signature
    # header must equal this value). Empty = accept + warn (Vobiz offers no
    # native signing); set it on exposed deployments.
    vobiz_webhook_secret: str = ""

    # Plivo
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""
    plivo_phone_number: str = ""
    plivo_validate_signature: bool = True

    # Public https base URL of this backend (e.g. https://x.ngrok-free.app).
    # TwiML webhooks and the Twilio Media Streams WS URL are derived from it.
    public_base_url: str = "http://localhost:8000"
    # Optional explicit override for the media websocket base (wss://host[:port]).
    public_ws_base_url: str = ""
    # Render injects this into every web service. When PUBLIC_BASE_URL is not
    # set explicitly (fresh deploy), deriving it here removes the
    # chicken-and-egg step of editing env vars after the service URL exists.
    render_external_url: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Accept Render/Heroku-style ``postgres://`` URLs.

        SQLAlchemy only understands ``postgresql://``; some providers still
        hand out the legacy scheme.
        """
        if value.startswith("postgres://"):
            return "postgresql://" + value[len("postgres://"):]
        return value

    @model_validator(mode="after")
    def _derive_public_base_url(self) -> "Settings":
        """Use RENDER_EXTERNAL_URL when no explicit public URL was configured."""
        current = (self.public_base_url or "").strip().rstrip("/")
        if not current or current.startswith("http://localhost"):
            fallback = (self.render_external_url or "").strip().rstrip("/")
            if fallback:
                object.__setattr__(self, "public_base_url", fallback)
        return self

    # --- calling hours / dialer -------------------------------------------
    timezone: str = "Asia/Kolkata"
    calling_hours_start: int = 9  # inclusive
    calling_hours_end: int = 21  # exclusive
    default_cps_limit: float = 1.0
    default_concurrency_limit: int = 10
    retry_max_attempts: int = 3
    retry_backoff_minutes: int = 15
    dialer_enabled: bool = True

    # --- compliance --------------------------------------------------------
    consent_enforcement: bool = True
    # Comma-separated allowlist of phone numbers that bypass consent enforcement
    # for test calls and campaign dialing.
    test_phone_numbers: str = ""
    # Test calls are normally capped to TEST_PHONE_NUMBERS plus consenting
    # roster contacts, so a leaked login cannot place billable calls anywhere.
    # Set true on a deployment that genuinely dials real recipients; campaign
    # dialing still requires per-contact consent either way.
    allow_any_outbound_number: bool = False
    recording_retention_days: int = 90
    retention_job_enabled: bool = True

    # --- domain configs ------------------------------------------------------
    # Default: ../domain-configs relative to repo root. In container: /domain-configs.
    domain_configs_dir: str = "../domain-configs"

    # --- auth / tenancy -----------------------------------------------------
    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # one week
    # H5: open registration mints owner-role orgs. Leave true for local
    # demos; set false on any network-exposed deployment.
    allow_public_registration: bool = True
    # Comma-separated allowlist of browser origins for CORS.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # --- internal service API (voice-agent -> backend) -----------------------
    # Header X-Internal-Token must match; empty string disables the internal API.
    internal_api_token: str = ""

    # --- livekit (playground room tokens) ------------------------------------
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Container-facing LiveKit URL for server-side bridges (media gateway).
    # Browser tokens keep using livekit_url.
    livekit_url_internal: str = "ws://livekit:7880"

    # --- voice pipeline provider keys (presence-only checks by /api/health) ---
    # Consumed by the voice-agent worker; the backend never sends these anywhere.
    deepgram_api_key: str = ""
    # Optional: enables the daily Deepgram usage poll. Deepgram's usage API is
    # project-scoped, so the key alone is not enough.
    deepgram_project_id: str = ""
    cartesia_api_key: str = ""
    # Admin-scoped Cartesia key for GET /usage/credits. The standard key is
    # intentionally not used here.
    cartesia_admin_api_key: str = ""
    # Sarvam has no usage API. The key is only used to decide whether the
    # dashboard should show the locally-counted character bucket.
    sarvam_tts_api: str = ""
    groq_api_key: str = ""
    # Extra comma-separated Groq keys. The text-playground path rotates
    # through groq_api_key_list on 429s; the voice worker (voice-agent)
    # builds one client per key. Paste additional keys here when the owner
    # provides them — no code change needed.
    groq_api_keys: str = ""
    openai_api_key: str = ""
    # Any OpenAI-compatible base URL (Groq default; Cerebras
    # https://api.cerebras.ai/v1 is the fastest swap). The voice worker
    # reads the same GROQ_BASE_URL env var.
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Groq chat model for playground TEXT mode (must match GROQ_MODEL used by
    # the voice worker so both modes exercise the same brain).
    # qwen3.8-27b: 6/6 correct tool decisions, multi-field capture, <2.3s.
    # llama-3.1-8b-instant is 404 (decommissioned for dev tiers, Aug 2026).
    groq_model: str = "qwen/qwen3.8-27b"
    # Second Groq MODEL tried after every primary key. Empty disables the tier.
    groq_secondary_model: str = ""

    # --- LLM provider chain (free/cheap tiers, OpenAI-compatible) ---
    # A single Groq key hits 429 after a handful of turns, which is what makes
    # the agent go silent mid-conversation. Each entry below is one
    # OpenAI-compatible endpoint; the chain is tried in order and a member is
    # skipped on 429/5xx/timeouts. Format: name|base_url|key|model, comma
    # separated (use "|", not ":", because OpenRouter model ids end in ":free").
    # Blank entries are ignored, so leaving this unset keeps the historical
    # Groq-only behaviour.
    llm_fallback_chain: str = ""
    openrouter_api_key: str = ""
    cerebras_api_key: str = ""
    # DeepSeek chat (OpenAI-compatible https://api.deepseek.com/v1, model
    # deepseek-chat). NOTE: DeepSeek API is billed, not free - a zero balance
    # answers 402 "Insufficient Balance", which the chain treats as an
    # exhausted provider (fails over, then skips it for the session).
    deepseek_api_key: str = ""

    @property
    def llm_chain(self) -> list[tuple[str, str, str, str]]:
        """Ordered ``(name, base_url, api_key, model)`` provider members.

        Groq-FIRST: the primary pool (qwen on every key) is the fast path,
        then one secondary Groq model (gpt-oss-120b), then explicit
        LLM_FALLBACK_CHAIN overflow entries (Sarvam is the intended one), then
        the remaining shorthands. The old explicit-first order put a slow or
        failing provider in front of every turn; Groq leads so turn one never
        waits on it.
        """
        members: list[tuple[str, str, str, str]] = []
        # 1. Groq primary pool: the bulk, fastest tier.
        for key in self.groq_api_key_list:
            members.append(("groq", self.groq_base_url, key, self.groq_model))
        # 2. Secondary Groq model: quality fallback after the whole primary
        #    pool. Only on Groq's own endpoint; an OpenAI model id on a
        #    Cerebras base URL would 404 (not retryable).
        secondary_model = str(self.groq_secondary_model or "").strip()
        if (
            self.groq_api_key_list
            and secondary_model
            and secondary_model != self.groq_model
            and "groq.com" in self.groq_base_url
        ):
            members.append(
                (
                    "groq-secondary",
                    self.groq_base_url,
                    self.groq_api_key_list[0],
                    secondary_model,
                )
            )
        # 3. Explicit overflow entries (Sarvam, ...), in the owner's listed
        #    order. They only fire after the entire Groq tier.
        for entry in self.llm_fallback_chain.split(","):
            entry = entry.strip()
            if not entry:
                continue
            fields = [f.strip() for f in entry.split("|")]
            if len(fields) != 4:
                # Legacy colon form: base_url contains "://" so the fields are
                # peeled from both ends.
                name, _, rest = entry.partition(":")
                head, _, model = rest.rpartition(":")
                base_url, _, api_key = head.rpartition(":")
                fields = [name, base_url, api_key, model]
            name, base_url, api_key, model = fields
            if not all((name, base_url, api_key, model)) or not base_url.startswith("http"):
                _logger.warning("ignoring malformed LLM_FALLBACK_CHAIN entry: %r", entry)
                continue
            if _looks_like_template(api_key):
                _logger.warning("ignoring template LLM_FALLBACK_CHAIN key for %s", name)
                continue
            if name == "groq" and api_key in self.groq_api_key_list:
                continue  # already added from GROQ_API_KEY(S)
            members.append((name, base_url, api_key, model))
        # 4. DeepSeek shorthand (billed; only when a real key is set).
        if self.deepseek_api_key and not _looks_like_template(self.deepseek_api_key):
            members.append(
                (
                    "deepseek",
                    "https://api.deepseek.com/v1",
                    self.deepseek_api_key,
                    "deepseek-chat",
                )
            )
        # 5. Remaining shorthand keys append to the chain. A template leftover (the
        # shipped OPENAI_API_KEY=your_openai_api_key) must never occupy a slot:
        # it would 401 on every turn and look like a provider outage.
        if self.openai_api_key and not _looks_like_template(self.openai_api_key):
            members.append(
                ("openai", "https://api.openai.com/v1", self.openai_api_key, "gpt-4o-mini")
            )
        if self.cerebras_api_key and not _looks_like_template(self.cerebras_api_key):
            members.append(
                (
                    "cerebras",
                    "https://api.cerebras.ai/v1",
                    self.cerebras_api_key,
                    "llama-3.3-70b",
                )
            )
        if self.openrouter_api_key and not _looks_like_template(self.openrouter_api_key):
            members.append(
                (
                    "openrouter",
                    "https://openrouter.ai/api/v1",
                    self.openrouter_api_key,
                    "meta-llama/llama-3.3-70b-instruct:free",
                )
            )
        seen: set[tuple[str, str]] = set()
        unique: list[tuple[str, str, str, str]] = []
        for name, base_url, api_key, model in members:
            marker = (name, api_key)
            if marker in seen:
                continue
            seen.add(marker)
            unique.append((name, base_url, api_key, model))
        return unique

    @property
    def test_phone_number_list(self) -> list[str]:
        """TEST_PHONE_NUMBERS split into a stripped list."""
        return [p.strip() for p in self.test_phone_numbers.split(",") if p.strip()]

    @property
    def groq_api_key_list(self) -> list[str]:
        """GROQ_API_KEY first, then GROQ_API_KEYS — de-duplicated, non-empty."""
        keys: list[str] = []
        for part in f"{self.groq_api_key},{self.groq_api_keys}".split(","):
            key = part.strip()
            if key and key not in keys:
                keys.append(key)
        return keys

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS split into a stripped list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def provider_presence(self) -> dict[str, bool]:
        """Provider API-key PRESENCE booleans only — never key values."""
        return {
            "deepgram": bool(self.deepgram_api_key),
            "cartesia": bool(self.cartesia_api_key),
            "groq": bool(self.groq_api_key_list),
            "openai": bool(self.openai_api_key),
            "twilio": bool(self.twilio_account_sid and self.twilio_auth_token),
            "plivo": bool(self.plivo_auth_id and self.plivo_auth_token),
            "vobiz": bool(self.vobiz_auth_id and self.vobiz_auth_token),
            "livekit": bool(self.livekit_api_key and self.livekit_api_secret),
        }

    @property
    def media_ws_base_url(self) -> str:
        """Base URL for Twilio Media Streams websockets.

        PUBLIC_WS_BASE_URL wins; otherwise derived from PUBLIC_BASE_URL by
        switching the scheme (https->wss, http->ws).
        """
        if self.public_ws_base_url:
            return self.public_ws_base_url.rstrip("/")
        base = self.public_base_url.strip()
        if base.startswith("https://"):
            return "wss://" + base[len("https://"):].rstrip("/")
        if base.startswith("http://"):
            return "ws://" + base[len("http://"):].rstrip("/")
        return base.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (override via env before first call)."""
    return Settings()
