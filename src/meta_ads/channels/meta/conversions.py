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
        if ev.hashed_fn:
            user_data["fn"] = [ev.hashed_fn]
        if ev.hashed_ln:
            user_data["ln"] = [ev.hashed_ln]
        if ev.hashed_external_id:
            user_data["external_id"] = [ev.hashed_external_id]
        event: dict[str, Any] = {
            "event_name": ev.action_name,
            "event_time": int(ev.event_time.timestamp()),
            "action_source": "system_generated",
            "user_data": user_data,
        }
        if ev.order_id:
            event["event_id"] = ev.order_id  # CAPI dedup key
        custom: dict[str, Any] = {}
        if ev.value_eur is not None:
            custom = {"value": float(ev.value_eur), "currency": ev.currency}
        if ev.properties:
            custom.update(ev.properties)  # e.g. loss_reason on lead_lost
        if custom:
            event["custom_data"] = custom
        return event

    async def upload(
        self, events: list[ConversionEvent], *, dry_run: bool = False
    ) -> dict[str, Any]:
        """POST the batch to /{dataset_id}/events; returns the Graph response
        ({"events_received": N, "fbtrace_id": ...}).

        Every event MUST carry meta_lead_id (enforced upstream by the drain)."""
        import json  # noqa: PLC0415

        payload = [self._to_meta_event(e) for e in events]
        if dry_run:
            logger.info("CAPI dry_run: %d event(s) for dataset %s (not sent)", len(payload), self._dataset_id)
            return {"dry_run": True, "events": len(payload)}
        async with await GraphClient.for_provider(DATASET, self._dataset_id) as g:
            resp = await g.post(f"{self._dataset_id}/events", data={"data": json.dumps(payload)})
        logger.info(
            "CAPI: dataset %s accepted events_received=%s (sent %d)",
            self._dataset_id, resp.get("events_received"), len(payload),
        )
        return resp
