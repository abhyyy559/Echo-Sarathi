"""Pydantic v2 request/response schemas for the admin, internal and test-call APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# --- domain configs ---------------------------------------------------------


class DomainConfigOut(BaseModel):
    id: int
    name: str
    display_name: str
    version: int


class DomainConfigSyncOut(BaseModel):
    synced: int
    names: list[str]


# --- campaigns ---------------------------------------------------------------


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Legacy read-only path (pre-platform data). New campaigns pin agent_version_id.
    domain_config_id: Optional[int] = None
    agent_version_id: Optional[int] = None


class CampaignOut(BaseModel):
    id: int
    name: str
    status: str
    org_id: Optional[int] = None
    domain_config_id: Optional[int]
    domain_config_name: Optional[str] = None
    agent_version_id: Optional[int] = None
    schedule_window_start: Optional[datetime] = None
    schedule_window_end: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ContactCounts(BaseModel):
    total: int = 0
    pending_review: int = 0
    invalid: int = 0
    queued: int = 0
    calling: int = 0
    completed: int = 0
    no_answer: int = 0
    busy: int = 0
    failed: int = 0
    opted_out: int = 0


class CampaignListItem(BaseModel):
    id: int
    name: str
    status: str
    org_id: Optional[int] = None
    domain_config_id: Optional[int]
    domain_config_name: Optional[str] = None
    agent_version_id: Optional[int] = None
    counts: ContactCounts
    created_at: Optional[datetime] = None


class CampaignDetail(CampaignOut):
    counts: ContactCounts


class DashboardOut(BaseModel):
    campaign_id: int
    campaign_status: str
    counts: ContactCounts
    calls_in_flight: int
    recent_calls: list[dict[str, Any]]


# --- contacts ----------------------------------------------------------------


class ContactPatch(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None
    status: Optional[str] = None
    consent: Optional[bool] = None


class ContactOut(BaseModel):
    id: int
    campaign_id: int
    name: Optional[str]
    phone: str
    external_id: Optional[str]
    custom_fields: dict[str, Any]
    status: str
    consent: bool
    consent_source: Optional[str]
    attempt_count: int
    next_attempt_at: Optional[datetime]
    last_call_id: Optional[int]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ContactPage(BaseModel):
    items: list[ContactOut]
    total: int
    page: int
    page_size: int


class ImportResult(BaseModel):
    imported: int
    invalid: int
    errors: list[dict[str, Any]]


# --- calls -------------------------------------------------------------------


class CallOut(BaseModel):
    id: int
    # NULL for playground calls (no campaign/contact lineage).
    campaign_id: Optional[int] = None
    contact_id: Optional[int] = None
    provider_call_id: Optional[str]
    status: str
    started_at: Optional[datetime]
    answered_at: Optional[datetime]
    ended_at: Optional[datetime]
    duration_seconds: Optional[float]
    recording_url: Optional[str]
    summary: Optional[str]
    outcome: Optional[str]
    flagged_for_human: bool
    cost: Optional[dict[str, Any]]
    latency: Optional[dict[str, Any]]
    created_at: Optional[datetime] = None


class CampaignCallOut(CallOut):
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


class TranscriptTurnOut(BaseModel):
    turn_index: int
    speaker: str
    text: str
    timestamp: Optional[datetime] = None


class ExtractedFieldOut(BaseModel):
    field_name: str
    field_value: Optional[str]
    source_turn_index: Optional[int]
    confidence: Optional[float]


CallActivityState = Literal[
    "agent_connecting", "listening", "understanding", "agent_speaking"
]


class CallActivityIn(BaseModel):
    sequence: int = Field(gt=0, allow_inf_nan=False)
    state: CallActivityState
    event_type: str = Field(min_length=1)
    occurred_at: float = Field(allow_inf_nan=False)
    source: str = Field(min_length=1)
    from_state: Optional[str] = None
    to_state: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def infer_state_from_legacy_event_type(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value.get("state"):
            event_type = value.get("event_type")
            if event_type in {
                "agent_connecting",
                "listening",
                "understanding",
                "agent_speaking",
            }:
                value = dict(value)
                value["state"] = event_type
        return value

    @field_validator("sequence", "occurred_at", mode="before")
    @classmethod
    def reject_non_numeric_activity_values(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("activity numbers must not be booleans")
        return value

    @field_validator("event_type", "source")
    @classmethod
    def strip_activity_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("activity text fields must not be blank")
        return value

    @field_validator("from_state", "to_state")
    @classmethod
    def strip_optional_activity_state(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("activity state fields must not be blank")
        return value


class CallActivityOut(BaseModel):
    state: CallActivityState
    event_type: str
    sequence: int
    occurred_at: float
    source: str
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CallActivityResponse(BaseModel):
    ok: bool = True
    call_id: int
    activity: CallActivityOut


class CallDetailOut(CallOut):
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    transcript: list[TranscriptTurnOut]
    extracted_fields: list[ExtractedFieldOut]
    activity: Optional[CallActivityOut] = None
    activity_history: list[CallActivityOut] = Field(default_factory=list)
    pickup_to_first_audio_seconds: Optional[float] = None
    opening_duration_seconds: Optional[float] = None


class RecentCallOut(BaseModel):
    id: int
    status: str
    kind: str = "phone"
    duration_seconds: Optional[float] = None
    started_at: Optional[datetime] = None
    agent_name: Optional[str] = None


class CallsDayOut(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    count: int


class AnalyticsSummaryOut(BaseModel):
    total_calls: int
    completed_calls: int
    success_rate_pct: float
    avg_e2e_ms: Optional[float] = None
    median_e2e_ms: Optional[float] = None
    p95_e2e_ms: Optional[float] = None
    total_extracted_fields: int
    calls_last_7d: list[CallsDayOut]
    recent_calls: list[RecentCallOut]


class PerCallCostOut(BaseModel):
    call_id: int
    minutes: float
    est_cost_usd: float


class MonthlyCostOut(BaseModel):
    minutes: float
    est_cost_usd: float


class AnalyticsCostsOut(BaseModel):
    """Estimated spend (P1 cost dashboard). Rates live in analytics.PRICING_USD_PER_MINUTE."""

    total_minutes: float
    est_cost_usd: float
    per_call: list[PerCallCostOut]
    monthly: dict[str, MonthlyCostOut]  # "YYYY-MM" -> totals


# --- call index (cross-campaign history) --------------------------------------


class CallListItemOut(BaseModel):
    id: int
    status: str
    kind: str
    duration_seconds: Optional[float]
    started_at: Optional[datetime]
    created_at: Optional[datetime] = None
    agent_version_id: Optional[int] = None
    agent_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    avg_e2e_ms: Optional[float] = None
    flagged_for_human: bool


# --- test call ----------------------------------------------------------------


class TestCallRequest(BaseModel):
    to: Optional[str] = None
    domain_config_id: Optional[int] = None
    agent_version_id: Optional[int] = None  # phone leg: which agent version speaks
    # Per-contact details the agent should know before it dials (student name,
    # parent name, class, etc.). Stored into the contact's custom_fields and
    # packed into the call room metadata so the agent greets the right person.
    contact: Optional[dict[str, Any]] = None


class TestCallOut(BaseModel):
    call_id: int
    provider_call_id: str
    status: str
    room_name: str


# --- internal (voice-agent) ----------------------------------------------------


class InternalOk(BaseModel):
    ok: bool = True


class RetentionRunOut(BaseModel):
    cutoff: datetime
    calls_older_than_cutoff: int
    transcripts_deleted: int
    recording_urls_cleared: int


# --- campaign dry-run (text-mode simulation) ---------------------------------


class DryRunCreate(BaseModel):
    persona: Optional[str] = None  # one of dry_run.PERSONA_ORDER; None = round-robin
    contact_limit: int = Field(default=20, gt=0, le=100)


class DryRunTranscriptTurn(BaseModel):
    role: str
    text: str


class DryRunContactResult(BaseModel):
    contact_id: int
    name: str
    phone: str  # masked
    persona: str
    transcript: list[DryRunTranscriptTurn]
    extracted_fields: list[dict[str, Any]]
    status: str
    outcome: Optional[str] = None
    turns: int


class DryRunReport(BaseModel):
    campaign_id: int
    persona: Optional[str] = None
    contacts_total: int
    contacts_run: int
    results: list[DryRunContactResult]
