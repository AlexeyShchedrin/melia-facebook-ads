"""Job: resolve queued leadgen leads → CRM (pipeline B). LISTEN 'meta_leadgen'."""

from __future__ import annotations

import asyncio

from meta_ads.ingest.resolver import InboundResolver
from meta_ads.worker.listen import listen

_CHANNEL = "meta_leadgen"


async def run_lead_resolve() -> None:
    await InboundResolver().run()


async def listen_for_leadgen(stop: asyncio.Event) -> None:
    await listen(_CHANNEL, run_lead_resolve, stop)
