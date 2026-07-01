"""Job: pull Meta insights → meta.campaign_metrics (pipeline A monitoring)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_perf_pull() -> None:
    logger.debug("perf_pull tick — TODO(phase3): insights → meta.campaign_metrics")
