"""Read side — insights, moderation state, budget pacing (System User token).

Runs on the SERVER worker (continuous), unlike creative/campaign writes which
run locally. Insights use the async report pattern for large pulls.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


async def get_insights(
    *, level: str = "campaign", date_from: date | None = None, date_to: date | None = None
) -> list[dict[str, Any]]:
    """GET /act_<id>/insights (sync) or async report for big windows. TODO(phase3)."""
    raise NotImplementedError("TODO(phase3): insights pull")


async def fetch_moderation(ad_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Read ad effective_status + ad_review_feedback/issues_info. TODO(phase3)."""
    raise NotImplementedError("TODO(phase3): moderation fetch")


async def budget_pacing() -> list[dict[str, Any]]:
    """Today's spend vs daily budget per campaign (drift → alert). TODO(phase3)."""
    raise NotImplementedError("TODO(phase3): budget pacing")
