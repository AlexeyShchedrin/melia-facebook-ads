"""Channel-agnostic ad-platform interface, shared with google-ads by design.

Kept identical to melia-google-ads' `ads.channels.base` so both services speak
the same vocabulary (ChannelKind already includes META). The Meta implementation
lives in `channels/meta/`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field


class ChannelKind(StrEnum):
    GOOGLE = "google"
    YANDEX = "yandex"
    META = "meta"


class CampaignStatus(StrEnum):
    ENABLED = "enabled"
    PAUSED = "paused"
    REMOVED = "removed"


class BidStrategy(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["manual_cpc", "maximize_clicks", "maximize_conversions", "tcpa", "troas"]
    target_cpa_eur: Decimal | None = None
    target_roas: Decimal | None = None
    max_cpc_eur: Decimal | None = None


class CampaignSpec(BaseModel):
    name: str
    channel: ChannelKind
    type: Literal["search", "display", "demand_gen", "performance_max", "video"]
    geo_targets: Sequence[str]
    languages: Sequence[str]
    daily_budget_eur: Decimal
    bid_strategy: BidStrategy
    primary_conversion_action: str
    audience_ids: Sequence[str] = Field(default_factory=list)
    final_url_template: str | None = None
    external_id: str | None = None


class StandardMetrics(BaseModel):
    scope: Literal["account", "campaign", "ad_group", "ad", "keyword"]
    scope_id: str | None = None
    date_from: date
    date_to: date
    impressions: int = 0
    clicks: int = 0
    cost_eur: Decimal = Decimal(0)
    conversions: Decimal = Decimal(0)
    conversions_value_eur: Decimal = Decimal(0)
    ctr: Decimal | None = None
    avg_cpc_eur: Decimal | None = None
    cpl_eur: Decimal | None = None

    @classmethod
    def empty(cls, scope: str, date_from: date, date_to: date) -> Self:
        return cls(scope=scope, date_from=date_from, date_to=date_to)  # type: ignore[arg-type]


class ConversionEvent(BaseModel):
    """Channel-agnostic conversion event ready for upload to an ad platform."""

    action_name: str
    event_time: datetime
    # Click identifier (gclid for Google, fbclid for Meta) — rarely used for Meta CRM.
    click_id: str | None = None
    value_eur: Decimal | None = None
    currency: str = "EUR"
    # SHA-256 normalized email/phone for Enhanced Conversions / Advanced Matching.
    hashed_email: str | None = None
    hashed_phone: str | None = None
    # Meta lead_id — THE join key for Conversions API for CRM (see PLAN.md §5).
    meta_lead_id: str | None = None
    # Internal CRM lead reference for idempotency / outbox dedup.
    lead_id: int | None = None
    order_id: str | None = None
    # Extra event properties merged into the platform's custom data
    # (e.g. {"loss_reason": "misclick"} on lead_lost).
    properties: dict[str, str] | None = None


class AdChannel(ABC):
    """Channel-agnostic interface; Google/Yandex/Meta implement this surface."""

    kind: ChannelKind

    @abstractmethod
    async def list_campaigns(self) -> list[dict]: ...

    @abstractmethod
    async def get_campaign(self, campaign_id: str) -> dict | None: ...

    @abstractmethod
    async def create_campaign(self, spec: CampaignSpec, *, dry_run: bool = False) -> str: ...

    @abstractmethod
    async def set_campaign_status(
        self, campaign_id: str, status: CampaignStatus, *, dry_run: bool = False
    ) -> None: ...

    @abstractmethod
    async def update_budget(
        self, campaign_id: str, daily_eur: Decimal, *, dry_run: bool = False
    ) -> None: ...

    @abstractmethod
    async def get_metrics(
        self,
        scope: Literal["account", "campaign", "ad_group", "ad", "keyword"],
        date_from: date,
        date_to: date,
        scope_ids: Sequence[str] | None = None,
    ) -> list[StandardMetrics]: ...

    @abstractmethod
    async def upload_conversion(self, event: ConversionEvent, *, dry_run: bool = False) -> str: ...
