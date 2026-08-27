"""Pipeline B — resolve leadgen leads and poll for reconciliation (Page token).

The webhook (thin relay in melia-crm) gives only a leadgen_id; the real data is
fetched here. Polling is the safety net for at-least-once / dropped webhooks
(90-day retrieval window).
"""

from __future__ import annotations

import logging
from typing import Any

from meta_ads.channels.meta.client import PAGE, SYSTEM_USER, GraphClient

logger = logging.getLogger(__name__)

_RESOLVE_FIELDS = "field_data,created_time,id,ad_id,adset_id,campaign_id,form_id,platform,is_organic"


async def resolve_ad_names(ad_id: str) -> dict[str, str]:
    """One call → ad/adset/campaign names for a lead's attribution display."""
    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        d = await g.get(ad_id, params={"fields": "name,adset{name},campaign{name}"})
    return {
        "ad_name": d.get("name") or "",
        "adset_name": (d.get("adset") or {}).get("name") or "",
        "campaign_name": (d.get("campaign") or {}).get("name") or "",
    }


async def resolve_form_name(form_id: str, page_id: str | None = None) -> str:
    """`page_id` picks the owning Page's token (multi-page); None = primary."""
    async with await GraphClient.for_provider(PAGE, page_id) as g:
        return (await g.get(form_id, params={"fields": "name"})).get("name") or ""


async def resolve_lead(leadgen_id: str, page_id: str | None = None) -> dict[str, Any]:
    """GET /{leadgen_id}?fields=field_data,... → the full lead.

    A lead is readable only with ITS page's token, so multi-page callers pass
    the page_id the webhook relay recorded; None = the primary Page.
    Returns the raw Graph object; `field_data` is a list of {name, values}."""
    async with await GraphClient.for_provider(PAGE, page_id) as g:
        return await g.get(leadgen_id, params={"fields": _RESOLVE_FIELDS})


# UI-built forms emit Meta's standard field keys (phone_number, email, ...);
# API-built forms carry whatever `key` each question was created with — our
# HI-OTP forms (2026-07) use "phone". The CRM ingest contract reads the
# standard names (lead-ingest/route.ts: fields.phone_number), so normalize
# here at the single flattening point. Original keys are kept alongside —
# they still land in the CRM raw_row for display.
_FIELD_KEY_ALIASES = {
    "phone": "phone_number",
    "work_phone": "work_phone_number",
    "e-mail": "email",
}


def field_data_to_map(field_data: list[dict[str, Any]]) -> dict[str, str]:
    """Flatten Meta's [{name, values:[...]}] into {name: first_value}."""
    out: dict[str, str] = {}
    for f in field_data or []:
        vals = f.get("values") or []
        if vals:
            out[f["name"]] = vals[0]
    for src, dst in _FIELD_KEY_ALIASES.items():
        if src in out and dst not in out:
            out[dst] = out[src]
    return out


async def poll_form_leads(
    form_id: str,
    since_unix: int | None = None,
    *,
    max_pages: int = 100,
    page_id: str | None = None,
) -> list[dict[str, Any]]:
    """GET /{form_id}/leads — reconciliation drain (cursor-paginated).

    Returns full lead objects (same shape as resolve_lead). `since_unix` filters
    server-side on time_created, so the 15-min poll only pulls new rows.

    Meta returns leads newest-first, so `max_pages` is a useful knob and not just a
    runaway guard: a reconciler that only needs to know "did we miss anything
    recently" can cap at a page or two instead of walking the 90-day window."""
    import json  # noqa: PLC0415

    params: dict[str, Any] = {"fields": _RESOLVE_FIELDS, "limit": 50}
    if since_unix:
        params["filtering"] = json.dumps(
            [{"field": "time_created", "operator": "GREATER_THAN", "value": since_unix}]
        )
    leads: list[dict[str, Any]] = []
    pages = 0
    async with await GraphClient.for_provider(PAGE, page_id) as g:
        resp = await g.get(f"{form_id}/leads", params=params)
        while True:
            leads.extend(resp.get("data", []))
            pages += 1
            paging = resp.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not paging.get("next") or not after:
                break
            if pages >= max_pages:
                # Never truncate a time-bounded sweep silently: that one looks
                # exactly like a complete window to the caller and may really have
                # dropped leads. A capped newest-first scan is by design.
                log = logger.warning if since_unix else logger.debug
                log(
                    "poll_form_leads(%s): stopped at the %d-page cap with %d leads",
                    form_id, max_pages, len(leads),
                )
                break
            resp = await g.get(f"{form_id}/leads", params={**params, "after": after})
    return leads
