"""Job: reconcile missed leadgen webhooks by polling each form (pipeline B).

Safety net for at-least-once / dropped webhooks — enumerate active forms, poll
/{form_id}/leads within the 90-day window, feed any new leadgen_ids into the
same resolve→ingest path, and re-try rows that never reached the CRM. The work
itself lives in meta_ads.ingest.poller.
"""

from __future__ import annotations

import logging

from meta_ads.ingest.poller import LeadPoller

logger = logging.getLogger(__name__)


async def run_lead_poll() -> None:
    await LeadPoller().run()
