"""Application settings (pydantic-settings) — all environment variables consumed by the backend.

Every variable name matches the project-level `.env.example` maintained by devops.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- infrastructure -------------------------------------------------
    database_url: str = "sqlite:///./voice_agent.db"
    redis_url: str = "redis://localhost:6379/0"
    environment: str = "development"
    log_level: str = "info"

    # --- telephony (provider selection) -----------------------------------
    # "", "twilio", "plivo" or "vobiz". Empty = auto-select (Plivo wins when
    # both credential sets are present; Plivo is the cheaper India leg).
    # Set explicitly to "vobiz" to place calls over Vobiz.
    telephony_provider: str = ""

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_validate_signature: bool = False

    # Vobiz (India CPaaS: REST calls + XML <Stream> bidirectional websockets)
    vobiz_auth_id: str = ""
    vobiz_auth_token: str = ""
    vobiz_phone_number: str = ""

    # Plivo
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""
    plivo_phone_number: str = ""
    plivo_validate_signature: bool = False

    # Public https base URL of this backend (e.g. https://x.ngrok-free.app).
    # TwiML webhooks and the Twilio Media Streams WS URL are derived from it.
    public_base_url: str = "http://localhost:8000"
    # Optional explicit override for the media websocket base (wss://host[:port]).
    public_ws_base_url: str = ""

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
    # Comma-separated allowlist of phone numbers that bypass consent enforcement.
    test_phone_numbers: str = ""
    recording_retention_days: int = 90
    retention_job_enabled: bool = True

    # --- domain configs ------------------------------------------------------
    # Default: ../domain-configs relative to repo root. In container: /domain-configs.
    domain_configs_dir: str = "../domain-configs"

    # --- auth / tenancy -----------------------------------------------------
    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # one week
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
    cartesia_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    # Groq chat model for playground TEXT mode (must match GROQ_MODEL used by
    # the voice worker so both modes exercise the same brain).
    groq_model: str = "openai/gpt-oss-20b"

    @property
    def test_phone_number_list(self) -> list[str]:
        """TEST_PHONE_NUMBERS split into a stripped list."""
        return [p.strip() for p in self.test_phone_numbers.split(",") if p.strip()]

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
            "groq": bool(self.groq_api_key),
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
