"""Pipeline C — Conversions API for CRM uploader.

POST /{dataset_id}/events with action_source="system_generated". THE join key is
the Meta lead_id (see PLAN.md §5 invariant); hashed email/phone are only
secondary matching signals for leads already confirmed to be Meta-origin.
"""

from __future__ import annotations

import logging
from typing import Any

from meta_ads.channels.base import ConversionEvent
from meta_ads.channels.meta.client import DATASET, GraphClient

logger = logging.getLogger(__name__)


class MetaCapiUploader:
    """Uploads down-funnel stage events to a Conversions API dataset."""

    def __init__(self, dataset_id: str) -> None:
        self._dataset_id = dataset_id

    def _to_meta_event(self, ev: ConversionEvent) -> dict[str, Any]:
        user_data: dict[str, Any] = {}
        if ev.meta_lead_id:
            user_data["lead_id"] = ev.meta_lead_id  # unhashed 15–16 digit Meta lead id
        if ev.hashed_email:
            user_data["em"] = [ev.hashed_email]
        if ev.hashed_phone:
            user_data["ph"] = [ev.hashed_phone]
        event: dict[str, Any] = {
            "event_name": ev.action_name,
            "event_time": int(ev.event_time.timestamp()),
            "action_source": "system_generated",
            "user_data": user_data,
        }
        if ev.order_id:
            event["event_id"] = ev.order_id  # CAPI dedup key
        if ev.value_eur is not None:
            event["custom_data"] = {"value": float(ev.value_eur), "currency": ev.currency}
        return event

    async def upload(
        self, events: list[ConversionEvent], *, dry_run: bool = False
    ) -> list[dict[str, Any]]:
        """POST the batch to /{dataset_id}/events. TODO(phase2): send + parse result.

        Every event MUST carry meta_lead_id (enforced upstream by the drain)."""
        payload = [self._to_meta_event(e) for e in events]
        if dry_run:
            logger.info("CAPI dry_run: %d events for dataset %s", len(payload), self._dataset_id)
            return [{"dry_run": True} for _ in payload]
        async with await GraphClient.for_provider(DATASET, self._dataset_id) as g:
            _ = g  # TODO(phase2): g.post(f"{self._dataset_id}/events", data={"data": json.dumps(payload)})
        raise NotImplementedError("TODO(phase2): send events to Conversions API")
