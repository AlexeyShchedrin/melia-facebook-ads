"""Pipeline B — resolve queued leadgen_ids and hand them to the CRM.

The CRM relay route inserts `leadgen_id` into public.meta_inbound_leadgen and
NOTIFYs 'meta_leadgen'. We read that queue via `ads_contract.v_meta_inbound`,
resolve the full lead over Graph (Page token), and POST it (HMAC-signed) to the
CRM ingest route — the CRM stays the sole writer of public.leads.

Idempotency: `meta.processed_inbound` keyed on leadgen_id (webhook + polling
both funnel here).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from meta_ads.channels.meta.leads import (
    field_data_to_map,
    resolve_ad_names,
    resolve_form_name,
    resolve_lead,
)
from meta_ads.config import get_settings
from meta_ads.security import sign_ingest

logger = logging.getLogger(__name__)

# In-process caches — ads/forms repeat across leads, names rarely change, and
# the worker restarts on every deploy.
_ad_names_cache: dict[str, dict[str, str]] = {}
_form_name_cache: dict[str, str] = {}


async def _names_for(ad_id: str | None, form_id: str | None) -> dict[str, str]:
    """Best-effort display names for the lead's attribution (never fatal)."""
    out: dict[str, str] = {}
    if ad_id:
        try:
            if ad_id not in _ad_names_cache:
                _ad_names_cache[ad_id] = await resolve_ad_names(ad_id)
            out.update(_ad_names_cache[ad_id])
        except Exception:  # noqa: BLE001
            logger.warning("could not resolve ad names for %s", ad_id)
    if form_id:
        try:
            if form_id not in _form_name_cache:
                _form_name_cache[form_id] = await resolve_form_name(form_id)
            if _form_name_cache[form_id]:
                out["form_name"] = _form_name_cache[form_id]
        except Exception:  # noqa: BLE001
            logger.warning("could not resolve form name for %s", form_id)
    return out


@dataclass
class ResolveOutcome:
    fetched: int = 0
    ingested: int = 0
    failed: int = 0


@dataclass
class _Inbound:
    id: int
    leadgen_id: str
    form_id: str | None


class InboundResolver:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def _fetch_unprocessed(self, session: AsyncSession, limit: int) -> list[_Inbound]:
        rows = await session.execute(
            text(
                "SELECT i.id, i.leadgen_id, i.form_id "
                "FROM ads_contract.v_meta_inbound i "
                "LEFT JOIN meta.processed_inbound p ON p.leadgen_id = i.leadgen_id "
                "WHERE p.leadgen_id IS NULL "
                "ORDER BY i.id ASC LIMIT :lim"
            ),
            {"lim": limit},
        )
        return [_Inbound(id=r.id, leadgen_id=r.leadgen_id, form_id=r.form_id) for r in rows]

    async def _record(
        self, session: AsyncSession, item: _Inbound, *, crm_lead_id: int | None, error: str | None
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO meta.processed_inbound "
                "(leadgen_id, form_id, crm_lead_id, error, attempts, processed_at) "
                "VALUES (:lid, :fid, :clid, :err, 1, now()) "
                "ON CONFLICT (leadgen_id) DO UPDATE SET "
                "error = EXCLUDED.error, attempts = meta.processed_inbound.attempts + 1, processed_at = now()"
            ),
            {"lid": item.leadgen_id, "fid": item.form_id, "clid": crm_lead_id, "err": error},
        )

    async def _post_to_crm(self, lead: dict[str, Any]) -> int | None:
        """HMAC-sign and POST the resolved lead to the CRM ingest route."""
        body = json.dumps(lead, separators=(",", ":")).encode()
        headers = {"content-type": "application/json", "x-fb-signature": sign_ingest(body)}
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(self._settings.crm_ingest_url, content=body, headers=headers)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            return data.get("leadId") or data.get("lead_id")  # CRM route answers camelCase

    async def run(self, *, limit: int = 100) -> ResolveOutcome:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        outcome = ResolveOutcome()
        async with async_session_maker() as session:
            items = await self._fetch_unprocessed(session, limit)
            outcome.fetched = len(items)
            for item in items:
                try:
                    raw = await resolve_lead(item.leadgen_id)
                    form_id = raw.get("form_id") or item.form_id
                    names = await _names_for(raw.get("ad_id"), form_id)
                    lead = {
                        "leadgen_id": item.leadgen_id,
                        "form_id": form_id,
                        "created_time": raw.get("created_time"),
                        "campaign_id": raw.get("campaign_id"),
                        "adset_id": raw.get("adset_id"),
                        "ad_id": raw.get("ad_id"),
                        "platform": raw.get("platform"),
                        "is_organic": raw.get("is_organic"),
                        **names,  # campaign_name / adset_name / ad_name / form_name
                        "fields": field_data_to_map(raw.get("field_data", [])),
                    }
                    crm_lead_id = await self._post_to_crm(lead)
                    await self._record(session, item, crm_lead_id=crm_lead_id, error=None)
                    outcome.ingested += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("resolve failed for leadgen_id=%s", item.leadgen_id)
                    await self._record(session, item, crm_lead_id=None, error=str(exc))
                    outcome.failed += 1
            await session.commit()
        logger.info(
            "inbound resolve: fetched=%d ingested=%d failed=%d",
            outcome.fetched, outcome.ingested, outcome.failed,
        )
        return outcome
