"""Pipeline A — build & manage campaigns via the Marketing API.

Money-safety is baked in: everything is created PAUSED, `validate_only=True`
does a server-side dry run of the whole payload, and launches are idempotent via
`meta.campaign_external_map` (spec_hash) because Meta has no idempotency key.
"""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any

from meta_ads.channels.meta.client import SYSTEM_USER, GraphClient
from meta_ads.config import get_settings

logger = logging.getLogger(__name__)


def spec_hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


async def create_lead_campaign(
    *,
    name: str,
    daily_budget_eur: Decimal,
    targeting: dict[str, Any],
    external_id: str | None = None,
    validate_only: bool = True,
) -> dict[str, Any]:
    """Create Campaign(OUTCOME_LEADS)→AdSet(LEAD_GENERATION)→ ready for an Ad.

    Always PAUSED. With validate_only=True nothing is created — Meta just
    validates the objective↔optimization_goal↔billing_event↔promoted_object
    matrix (the usual 400 source). TODO(phase1): implement the 3 POSTs +
    external-map dedup.
    """
    _ = spec_hash  # used once dedup is wired
    raise NotImplementedError(
        "TODO(phase1): POST campaigns (objective=OUTCOME_LEADS, special_ad_categories=[], "
        "status=PAUSED) → adsets (optimization_goal=LEAD_GENERATION, billing_event=IMPRESSIONS, "
        "promoted_object={page_id}, destination_type=ON_AD); honour validate_only + spec_hash."
    )


async def create_ad(
    *, name: str, adset_id: str, creative_id: str, validate_only: bool = True
) -> str:
    """POST /act_<id>/ads (status=PAUSED). TODO(phase1)."""
    raise NotImplementedError("TODO(phase1): create ad")


async def set_status(object_id: str, status: str, *, dry_run: bool = True) -> None:
    """POST /<object_id> status=PAUSED|ACTIVE. TODO(phase1)."""
    raise NotImplementedError("TODO(phase1): set status")


async def update_budget(adset_id: str, daily_eur: Decimal, *, dry_run: bool = True) -> None:
    """POST /<adset_id> daily_budget=<minor units>. TODO(phase1)."""
    raise NotImplementedError("TODO(phase1): update budget")


async def _graph() -> GraphClient:
    _ = get_settings()
    return await GraphClient.for_provider(SYSTEM_USER)
