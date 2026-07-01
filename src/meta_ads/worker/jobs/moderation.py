"""Job: poll ad review/moderation state → meta.moderation_state (pipeline A)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_moderation_poll() -> None:
    logger.debug("moderation tick — TODO(phase3): read effective_status + ad_review_feedback")
