"""MetaChannel — the AdChannel implementation, delegating to the meta submodules.

Thin adapter so the rest of the codebase (and future cross-channel code) can
talk to Meta through the shared `AdChannel` interface. Phase-1 wires the lead
path; campaign/insight methods delegate to the modules as they're implemented.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from meta_ads.channels.base import (
    AdChannel,
    CampaignSpec,
    CampaignStatus,
    ChannelKind,
    ConversionEvent,
    StandardMetrics,
)
from meta_ads.channels.meta import campaigns, reporting


class MetaChannel(AdChannel):
    kind = ChannelKind.META

    async def list_campaigns(self) -> list[dict]:
        raise NotImplementedError("TODO(phase3)")

    async def get_campaign(self, campaign_id: str) -> dict | None:
        raise NotImplementedError("TODO(phase3)")

    async def create_campaign(self, spec: CampaignSpec, *, dry_run: bool = False) -> str:
        raise NotImplementedError("TODO(phase1): delegate to campaigns.create_lead_campaign")

    async def set_campaign_status(
        self, campaign_id: str, status: CampaignStatus, *, dry_run: bool = False
    ) -> None:
        await campaigns.set_status(campaign_id, status.value.upper(), dry_run=dry_run)

    async def update_budget(
        self, campaign_id: str, daily_eur: Decimal, *, dry_run: bool = False
    ) -> None:
        await campaigns.update_budget(campaign_id, daily_eur, dry_run=dry_run)

    async def get_metrics(
        self,
        scope: Literal["account", "campaign", "ad_group", "ad", "keyword"],
        date_from: date,
        date_to: date,
        scope_ids: Sequence[str] | None = None,
    ) -> list[StandardMetrics]:
        _ = await reporting.get_insights(level=scope, date_from=date_from, date_to=date_to)
        raise NotImplementedError("TODO(phase3): map insights → StandardMetrics")

    async def upload_conversion(self, event: ConversionEvent, *, dry_run: bool = False) -> str:
        raise NotImplementedError("TODO(phase2): delegate to MetaCapiUploader")
