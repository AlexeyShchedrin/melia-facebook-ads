"""Pipeline B — resolve leadgen leads and poll for reconciliation (Page token).

The webhook (thin relay in melia-crm) gives only a leadgen_id; the real data is
fetched here. Polling is the safety net for at-least-once / dropped webhooks
(90-day retrieval window).
"""

from __future__ import annotations

import logging
from typing import Any

from meta_ads.channels.meta.client import PAGE, GraphClient

logger = logging.getLogger(__name__)

_RESOLVE_FIELDS = "field_data,created_time,id,ad_id,adset_id,campaign_id,form_id,platform,is_organic"


async def resolve_lead(leadgen_id: str) -> dict[str, Any]:
    """GET /{leadgen_id}?fields=field_data,... → the full lead.

    Returns the raw Graph object; `field_data` is a list of {name, values}."""
    async with await GraphClient.for_provider(PAGE) as g:
        return await g.get(leadgen_id, params={"fields": _RESOLVE_FIELDS})


def field_data_to_map(field_data: list[dict[str, Any]]) -> dict[str, str]:
    """Flatten Meta's [{name, values:[...]}] into {name: first_value}."""
    out: dict[str, str] = {}
    for f in field_data or []:
        vals = f.get("values") or []
        if vals:
            out[f["name"]] = vals[0]
    return out


async def poll_form_leads(form_id: str, since_unix: int | None = None) -> list[dict[str, Any]]:
    """GET /{form_id}/leads — reconciliation drain (cursor-paginated).

    Returns full lead objects (same shape as resolve_lead). `since_unix` filters
    server-side on time_created, so the 15-min poll only pulls new rows."""
    import json  # noqa: PLC0415

    params: dict[str, Any] = {"fields": _RESOLVE_FIELDS, "limit": 50}
    if since_unix:
        params["filtering"] = json.dumps(
            [{"field": "time_created", "operator": "GREATER_THAN", "value": since_unix}]
        )
    leads: list[dict[str, Any]] = []
    async with await GraphClient.for_provider(PAGE) as g:
        resp = await g.get(f"{form_id}/leads", params=params)
        while True:
            leads.extend(resp.get("data", []))
            paging = resp.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not paging.get("next") or not after:
                break
            resp = await g.get(f"{form_id}/leads", params={**params, "after": after})
    return leads
