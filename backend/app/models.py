"""SQLAlchemy ORM models — refined schema from PRD §6.

Notes:
- All timestamps are timezone-naive UTC (see app.timeutil).
- ``contacts.last_call_id`` is a *logical* FK to ``calls.id``. The DB-level
  constraint is created in the Alembic migration (Postgres) but omitted from
  the model metadata so ``Base.metadata.create_all`` also works on SQLite,
  which cannot ALTER TABLE ADD CONSTRAINT. The only ORM-level circular
  dependency is avoided this way.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# --- status vocabularies ---------------------------------------------------
CAMPAIGN_STATUSES = ("draft", "running", "paused", "completed", "canceled")
CONTACT_STATUSES = (
    "pending_review",
    "invalid",
    "queued",
    "calling",
    "completed",
    "no_answer",
    "busy",
    "failed",
    "opted_out",
    # Faculty-excluded: uploaded but deliberately not called this run
    # (e.g. present students). Launch and the dialer ignore it; flipping
    # back to pending_review re-includes the contact on the next launch.
    "skipped",
)
CALL_STATUSES = (
    "queued",
    "ringing",
    "in_progress",
    "completed",
    "no_answer",
    "busy",
    "failed",
    "canceled",
)
# call states counted as "in flight" for concurrency limiting
IN_FLIGHT_CALL_STATUSES = ("queued", "ringing", "in_progress")

# call kinds (enterprise platform): real outbound vs in-browser playground test
CALL_KINDS = ("phone", "playground")
AGENT_STATUSES = ("draft", "testing", "live", "archived")
USER_ROLES = ("owner", "admin", "member")


class Base(DeclarativeBase):
    """Declarative base for all models."""


class Organization(Base):
    """A tenant: every other entity hangs off an organization."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    # Prepaid wallet. Stored in paise so every debit/credit is exact integer
    # arithmetic; the retail rate lives in app/services/billing.py.
    credit_balance_paise: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Snapshot used on GST invoices. Empty values fall back to the org name
    # and owner email at invoice time, so a customer can be invoiced before
    # they fill this in.
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    gstin: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    billing_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    billing_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    billing_state: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # Cooldown for the low-wallet email (see services/billing.py).
    low_balance_alerted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base):
    """A member of an organization (email/password or Google Sign-In, JWT auth)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # NULL for accounts created through Google Sign-In that never set a
    # password; password login rejects those rows instead of hashing None.
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Google's stable OIDC subject id. Set when the account is linked to a
    # Google identity; one identity maps to at most one user.
    google_sub: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    organization: Mapped[Organization] = relationship(back_populates="users")


class Agent(Base):
    """A configurable voice agent owned by an organization.

    ``current_version_id`` is a *logical* FK to ``agent_versions.id`` (no ORM
    constraint, mirroring ``contacts.last_call_id``) to avoid circular DDL —
    versions reference their agent.
    """

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    current_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["AgentVersion"]] = relationship(back_populates="agent")


class AgentVersion(Base):
    """An immutable snapshot of an agent's configuration ("training" = saving one).

    Rows are never mutated through the API; a new version row is appended and
    the agent's current_version_id advances.
    """

    __tablename__ = "agent_versions"
    __table_args__ = (
        Index("ix_agent_versions_agent_version", "agent_id", "version", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    company_context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    question_flow: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    extraction_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    disclosure_script: Mapped[str] = mapped_column(Text, nullable=False)
    escalation_rules: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    voice_settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Logical FK to users.id (creator).
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agent: Mapped[Agent] = relationship(back_populates="versions")


class KnowledgeDocument(Base):
    """Reserved for RAG ingestion (spec §3): no runtime logic this phase."""

    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    storage_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")


class DomainConfig(Base):
    """A versioned call-domain configuration (question flow, extraction schema, ...)."""

    __tablename__ = "domain_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="domain_config")


class Campaign(Base):
    """A calling campaign: contacts + agent version + schedule.

    ``agent_version_id`` pins the immutable agent config a campaign runs;
    legacy ``domain_config_id`` stays read-only for pre-existing data.
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain_config_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("domain_configs.id"), nullable=True
    )
    agent_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    schedule_window_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    schedule_window_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    domain_config: Mapped[Optional[DomainConfig]] = relationship(back_populates="campaigns")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    calls: Mapped[list["Call"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class Contact(Base):
    """A call recipient within a campaign."""

    __tablename__ = "contacts"
    __table_args__ = (Index("ix_contacts_campaign_status", "campaign_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_review")
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Logical FK to calls.id (constraint added by the Alembic migration only).
    last_call_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    campaign: Mapped[Campaign] = relationship(back_populates="contacts")
    consent_records: Mapped[list["ConsentRecord"]] = relationship(back_populates="contact", cascade="all, delete-orphan")


class Call(Base):
    """An outbound call attempt against a contact.

    Enterprise delta (spec §3): ``kind`` distinguishes real phone calls from
    in-browser playground sessions; playground rows have NULL campaign/contact
    and carry ``org_id`` + ``agent_version_id`` directly.
    """

    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("campaigns.id"), nullable=True, index=True
    )
    contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contacts.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="phone", server_default="phone"
    )
    # Denormalized tenancy column (spec §3) — playground calls have no campaign
    # lineage to inherit an org from.
    org_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    agent_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    provider_call_id: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recording_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    flagged_for_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    latency: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Runtime context packed into LiveKit room/token metadata at session
    # creation (P0-2): {"contact": {...custom_fields}} personalizes the prompt.
    context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    campaign: Mapped[Campaign] = relationship(back_populates="calls")
    contact: Mapped[Contact] = relationship(backref="calls")
    events: Mapped[list["CallEvent"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    transcripts: Mapped[list["Transcript"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    extracted_fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )


class CallEvent(Base):
    """Raw provider/webhook event log for a call."""

    __tablename__ = "call_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    call: Mapped[Call] = relationship(back_populates="events")


class Transcript(Base):
    """One conversational turn of a call.

    Latency columns (NFR-1, logged from day one) are per-turn pipeline
    timings reported by the voice-agent worker via the internal API.
    """

    __tablename__ = "transcripts"
    __table_args__ = (Index("ix_transcripts_call_turn", "call_id", "turn_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(10), nullable=False)  # agent | caller
    text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stt_final_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    llm_first_token_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tts_first_audio_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    e2e_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    call: Mapped[Call] = relationship(back_populates="transcripts")


class ExtractedField(Base):
    """A structured field extracted from a call, traceable to a transcript turn."""

    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(200), nullable=False)
    field_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_turn_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    call: Mapped[Call] = relationship(back_populates="extracted_fields")


class CreditLedger(Base):
    """Append-only wallet history for one organization.

    ``amount_paise`` is the signed wallet delta (+ top-up, - call usage);
    ``paid_paise`` records what the customer actually paid, which differs from
    the credited value on discounted packs. ``balance_after_paise`` snapshots
    the running balance so the ledger is readable without re-summing it.
    Usage rows carry ``call_id`` and are unique per call at the service layer,
    making the debit idempotent across duplicate webhooks.
    """

    __tablename__ = "credit_ledger"
    __table_args__ = (Index("ix_credit_ledger_org_created", "org_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_paise: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    balance_after_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    call_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Payment(Base):
    """One checkout attempt for a credit pack, keyed by the provider order.

    Credits are granted only when ``status`` flips to ``paid`` after the
    gateway signature verifies or its webhook confirms capture. The unique
    provider ids make both paths idempotent: a retried verify call or a
    webhook arriving after the browser callback can never credit twice.
    """

    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_org_created", "org_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    pack_id: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="razorpay")
    provider_order_id: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True, index=True
    )
    provider_payment_id: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class UsageSnapshot(Base):
    """One provider quota/credit observation.
    Rows are append-only observations, not counters: the latest row for a
    ``(provider, key_id, model, metric)`` tuple is the current value. Keeping
    history makes a sudden drop (or a 429) visible without a second table.
    ``key_id`` is masked before insertion; no raw credential is ever stored.
    """

    __tablename__ = "usage_snapshots"
    __table_args__ = (
        Index("ix_usage_provider_timestamp", "provider", "timestamp"),
        Index("ix_usage_key_model_metric", "key_id", "model", "metric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    key_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    metric: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )


class ConsentRecord(Base):
    """Recorded consent basis for a contact/phone (PRD §8)."""

    __tablename__ = "consent_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contacts.id"), nullable=True, index=True
    )
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False, default="calling")
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    contact: Mapped[Optional[Contact]] = relationship(back_populates="consent_records")


class Subscription(Base):
    """One purchased plan period (monthly pass) for an organization.

    Rows are historical: a renewal or plan change expires the previous row and
    appends a new one. ``status`` is ``active`` until the period ends, then the
    lifecycle job marks it ``expired`` (``active_subscription`` already ignores
    periods whose end has passed, so expiry is never load-bearing for gating).
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_org_period", "org_id", "period_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    included_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    provider_order_id: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True, index=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Invoice(Base):
    """A GST invoice issued when a plan or top-up payment succeeds.

    Customer fields are snapshotted so a later profile edit never rewrites
    history. Prices are GST-inclusive: ``subtotal_paise + gst_paise`` equals
    ``total_paise``.
    """

    __tablename__ = "invoices"
    __table_args__ = (Index("ix_invoices_org_issued", "org_id", "issued_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    subscription_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    subtotal_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    gst_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_gstin: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    customer_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    customer_state: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    issued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Invite(Base):
    """A pending team invitation; the raw token only ever travels by email/link."""

    __tablename__ = "invites"
    __table_args__ = (Index("ix_invites_org_email", "org_id", "email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PasswordReset(Base):
    """Single-use password-reset token (hashed at rest)."""

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
