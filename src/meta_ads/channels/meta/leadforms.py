"""Instant (lead) forms — create & read via the Page (Page token).

Quality knobs that reduce junk (see research/05): is_optimized_for_quality,
is_phone_sms_verify_enabled, custom questions. `privacy_policy` is mandatory.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from meta_ads.channels.meta.client import PAGE, GraphClient
from meta_ads.config import get_settings

logger = logging.getLogger(__name__)


async def create_leadgen_form(
    *,
    name: str,
    questions: list[dict[str, Any]],
    privacy_policy: dict[str, str],
    is_optimized_for_quality: bool = True,
    is_phone_sms_verify_enabled: bool = False,
    locale: str | None = None,
    follow_up_action_url: str | None = None,
    context_card: dict[str, Any] | None = None,
    thank_you_page: dict[str, Any] | None = None,
    page_id: str | None = None,
) -> str:
    """POST /{page_id}/leadgen_forms (Page token). Returns form_id.

    - `locale` (e.g. "en_US", "sr_RS", "ru_RU", "de_DE") + localized question
      labels → one form per language/geo.
    - `is_phone_sms_verify_enabled=True` → the lead must confirm their phone via
      SMS OTP before the form submits (cuts fake numbers). Availability is
      per-market on Meta's side.
    """
    page_id = page_id or get_settings().meta_page_id
    if not page_id:
        raise RuntimeError("META_PAGE_ID not set")
    fields: dict[str, Any] = {
        "name": name,
        "questions": json.dumps(questions),
        "privacy_policy": json.dumps(privacy_policy),
        "is_optimized_for_quality": str(is_optimized_for_quality).lower(),
        "is_phone_sms_verify_enabled": str(is_phone_sms_verify_enabled).lower(),
    }
    if locale:
        fields["locale"] = locale
    if follow_up_action_url:
        # Website the lead is sent to after submitting (thank-you CTA). Meta
        # requires it for this form config.
        fields["follow_up_action_url"] = follow_up_action_url
    if context_card:
        fields["context_card"] = json.dumps(context_card)
    if thank_you_page:
        fields["thank_you_page"] = json.dumps(thank_you_page)
    async with await GraphClient.for_provider(PAGE) as g:
        resp = await g.post(f"{page_id}/leadgen_forms", data=fields)
    logger.info("created leadgen form %s -> %s", name, resp.get("id"))
    return resp["id"]


async def list_forms(page_id: str | None = None) -> list[dict[str, Any]]:
    """GET /{page_id}/leadgen_forms — enumerate forms (for the polling reconciler)."""
    page_id = page_id or get_settings().meta_page_id
    async with await GraphClient.for_provider(PAGE) as g:
        resp = await g.get(f"{page_id}/leadgen_forms", params={"fields": "id,name,status,leads_count"})
    return resp.get("data", [])
