"""Job: reconcile missed leadgen webhooks by polling each form (pipeline B).

Safety net for at-least-once / dropped webhooks — enumerate active forms, poll
/{form_id}/leads within the 90-day window, feed any new leadgen_ids into the
same resolve→ingest path. TODO(phase1): enumerate forms + since-cursor.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_lead_poll() -> None:
    logger.debug("lead_poll tick — TODO(phase1): poll /{form_id}/leads and reconcile")
