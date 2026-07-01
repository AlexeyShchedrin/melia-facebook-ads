"""Pipeline A — build & manage campaigns via the Marketing API.

Money-safety is baked in: everything is created PAUSED; `validate_only=True`
does a full server-side dry run of the campaign→adset chain and tears down the
throwaway PAUSED campaign afterwards (a PAUSED campaign never delivers, so no
spend); launches are idempotent via `meta.campaign_external_map` (spec_hash),
because Meta has no idempotency key.
"""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from meta_ads.channels.meta.client import SYSTEM_USER, GraphClient
from meta_ads.config import get_settings

logger = logging.getLogger(__name__)


def spec_hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()


def eur_to_minor(eur: Decimal) -> int:
    """EUR → account minor units (cents). Meta budgets are integer minor units."""
    return int((Decimal(eur) * 100).to_integral_value())


def _validate_opts() -> dict[str, str]:
    return {"execution_options": json.dumps(["validate_only"])}


async def _lookup_external(external_id: str) -> str | None:
    from meta_ads.db import async_session_maker  # noqa: PLC0415

    async with async_session_maker() as s:
        row = (
            await s.execute(
                text(
                    "SELECT campaign_id FROM meta.campaign_external_map "
                    "WHERE external_id=:e AND channel='meta'"
                ),
                {"e": external_id},
            )
        ).first()
    return row.campaign_id if row else None


async def _store_external(external_id: str, act: str, campaign_id: str, sh: str) -> None:
    from meta_ads.db import async_session_maker  # noqa: PLC0415

    async with async_session_maker() as s:
        await s.execute(
            text(
                "INSERT INTO meta.campaign_external_map "
                "(external_id, channel, ad_account_id, campaign_id, spec_hash) "
                "VALUES (:e,'meta',:a,:c,:h) "
                "ON CONFLICT (external_id, channel) DO UPDATE SET "
                "campaign_id=EXCLUDED.campaign_id, spec_hash=EXCLUDED.spec_hash"
            ),
            {"e": external_id, "a": act, "c": campaign_id, "h": sh},
        )
        await s.commit()


async def create_lead_campaign(
    *,
    name: str,
    daily_budget_eur: Decimal,
    targeting: dict[str, Any],
    page_id: str | None = None,
    special_ad_categories: list[str] | None = None,
    external_id: str | None = None,
    validate_only: bool = True,
) -> dict[str, Any]:
    """Create Campaign(OUTCOME_LEADS)→AdSet(LEAD_GENERATION), both PAUSED.

    validate_only=True → create the campaign PAUSED, validate the ad set against
    it (execution_options=validate_only), then delete the throwaway campaign. No
    object survives and nothing ever delivers. Returns {"validated": True}.
    """
    s = get_settings()
    act = s.meta_ad_account_id
    page_id = page_id or s.meta_page_id
    cats = [] if special_ad_categories is None else special_ad_categories
    if not act or not page_id:
        raise RuntimeError("META_AD_ACCOUNT_ID / META_PAGE_ID not set")

    existing = await _lookup_external(external_id) if (external_id and not validate_only) else None
    if existing is not None:
        logger.info("campaign external_id=%s already launched -> %s", external_id, existing)
        return {"campaign_id": existing, "adset_id": None, "reused": True}

    sh = spec_hash({"name": name, "budget": str(daily_budget_eur), "targeting": targeting, "page_id": page_id, "cats": cats})

    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        campaign_id = (
            await g.post(
                f"{act}/campaigns",
                data={
                    "name": name,
                    "objective": "OUTCOME_LEADS",
                    "status": "PAUSED",
                    "special_ad_categories": json.dumps(cats),
                },
            )
        )["id"]

        try:
            adset_fields: dict[str, Any] = {
                "name": f"{name} — adset",
                "campaign_id": campaign_id,
                "optimization_goal": "LEAD_GENERATION",
                "billing_event": "IMPRESSIONS",
                "daily_budget": str(eur_to_minor(daily_budget_eur)),
                "targeting": json.dumps(targeting),
                "promoted_object": json.dumps({"page_id": page_id}),
                "destination_type": "ON_AD",
                "status": "PAUSED",
            }
            if validate_only:
                adset_fields |= _validate_opts()
            adset = await g.post(f"{act}/adsets", data=adset_fields)
            adset_id = adset.get("id")
        finally:
            if validate_only:
                try:
                    await g.delete(campaign_id)
                except Exception:  # noqa: BLE001
                    logger.warning("cleanup of validate campaign %s failed", campaign_id)

    if validate_only:
        return {"validated": True}

    if external_id:
        await _store_external(external_id, act, campaign_id, sh)
    return {"campaign_id": campaign_id, "adset_id": adset_id}


async def create_ad(
    *, name: str, adset_id: str, creative_id: str, validate_only: bool = True
) -> str:
    """POST /act_<id>/ads (status=PAUSED). Returns ad_id (empty on validate_only)."""
    act = get_settings().meta_ad_account_id
    fields: dict[str, Any] = {
        "name": name,
        "adset_id": adset_id,
        "creative": json.dumps({"creative_id": creative_id}),
        "status": "PAUSED",
    }
    if validate_only:
        fields |= _validate_opts()
    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        resp = await g.post(f"{act}/ads", data=fields)
    return resp.get("id", "")


async def set_status(object_id: str, status: str, *, dry_run: bool = True) -> None:
    """POST /<object_id> status=PAUSED|ACTIVE. dry_run never calls the API (ACTIVE spends)."""
    if dry_run:
        logger.info("[dry_run] would set %s status=%s", object_id, status)
        return
    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        await g.post(object_id, data={"status": status})


async def update_budget(adset_id: str, daily_eur: Decimal, *, dry_run: bool = True) -> None:
    """POST /<adset_id> daily_budget=<minor units>."""
    minor = eur_to_minor(daily_eur)
    if dry_run:
        logger.info("[dry_run] would set %s daily_budget=%d", adset_id, minor)
        return
    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        await g.post(adset_id, data={"daily_budget": str(minor)})
