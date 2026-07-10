from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# Postgres schema owned by this service's Alembic (sibling of google-ads' `ads`).
SCHEMA = "meta"


class OAuthToken(Base):
    """Encrypted Meta tokens: System User (campaigns), Page (leads_retrieval),
    dataset (Conversions API). Keyed by (provider, asset_id)."""

    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("provider", "asset_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # meta_system_user | meta_page | meta_dataset
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # act_<id> / page_id / dataset_id the token is scoped to ("" if global)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Non-expiring for System User; long-lived for Page. Null = unknown.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __mapper_args__ = {"eager_defaults": True}


class CampaignMetrics(Base):
    """Daily Meta insights snapshot per campaign — pulled by perf_pull."""

    __tablename__ = "campaign_metrics"
    __table_args__ = (
        UniqueConstraint("ad_account_id", "campaign_id", "metric_date"),
        Index("ix_meta_campaign_metrics_date", "metric_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ad_account_id: Mapped[str] = mapped_column(String(32), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    leads: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    pulled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CampaignExternalMap(Base):
    """external_id → provider campaign_id + spec_hash, for idempotent launches
    (Meta has no idempotency key — dedup on our side)."""

    __tablename__ = "campaign_external_map"
    __table_args__ = (
        UniqueConstraint("external_id", "channel"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="meta")
    ad_account_id: Mapped[str] = mapped_column(String(32), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConversionDatasetMap(Base):
    """Maps a CRM lifecycle event name → Meta Conversions API dataset + default value."""

    __tablename__ = "conversion_dataset_map"
    __table_args__ = (
        UniqueConstraint("event_name", "dataset_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False)  # Meta event_name
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    default_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProcessedOutbox(Base):
    """CRM outbox events already turned into a CAPI event (idempotency for pipeline C)."""

    __tablename__ = "processed_outbox"
    __table_args__ = ({"schema": SCHEMA},)

    crm_outbox_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    lead_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    meta_lead_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # CAPI dedup key
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProcessedInbound(Base):
    """Leadgen leads already resolved + handed to the CRM (idempotency for pipeline B).

    Keyed by Meta `leadgen_id` — webhook (at-least-once) and polling both funnel
    here, so the same lead is never ingested twice."""

    __tablename__ = "processed_inbound"
    __table_args__ = (
        Index("ix_meta_processed_inbound_form", "form_id"),
        {"schema": SCHEMA},
    )

    leadgen_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    form_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    crm_lead_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CreativeUpload(Base):
    """Local creative file → Meta image_hash / video_id, so the same file on disk
    is never uploaded twice (keyed on path + mtime + size)."""

    __tablename__ = "creative_upload"
    __table_args__ = (
        UniqueConstraint("local_path", "mtime_ns", "size_bytes"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    local_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # image | video
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    video_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModerationState(Base):
    """Latest ad review state — kept fresh by the moderation poll job."""

    __tablename__ = "moderation_state"
    __table_args__ = (
        Index("ix_meta_moderation_campaign", "ad_account_id", "campaign_id"),
        {"schema": SCHEMA},
    )

    ad_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ad_account_id: Mapped[str] = mapped_column(String(32), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_feedback: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PendingMutation(Base):
    """A pending mutation awaiting Telegram approval (mirrors google-ads)."""

    __tablename__ = "pending_mutations"
    __table_args__ = (
        Index("ix_meta_pending_mutations_state", "state"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False, default="mcp")
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    diff_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IgBoostState(Base):
    """IG auto-boost ledger — one row per (IG media, zone) with what ig_boost
    decided and the ad it created.

    zone is 'B' / 'A' for per-zone boost rows and '' for media-level terminal
    decisions (skipped_lint / skipped_type / skipped_music). zone is part of
    the PK because a boosted post gets one ad per zone. decision='error' rows
    are retried on later ticks; every other decision is final."""

    __tablename__ = "ig_boost_state"
    __table_args__ = ({"schema": SCHEMA},)

    media_id: Mapped[str] = mapped_column(Text, primary_key=True)
    zone: Mapped[str] = mapped_column(Text, primary_key=True, default="")
    # boosted | skipped_lint | skipped_type | skipped_music | rotated_out | error
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    lint_hits: Mapped[str | None] = mapped_column(Text, nullable=True)
    ad_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    creative_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_product_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    boosted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_meta_alerts_state_created", "state", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="account")
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
