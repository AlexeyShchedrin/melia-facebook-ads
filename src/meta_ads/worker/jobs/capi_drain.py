"""Job: drain CRM outbox → Meta Conversions API (pipeline C). LISTEN 'ads_outbox'."""

from __future__ import annotations

import asyncio

from meta_ads.conversions.capi_drain import CapiDrain
from meta_ads.worker.listen import listen

_CHANNEL = "ads_outbox"


async def run_capi_drain() -> None:
    await CapiDrain().drain()


async def listen_for_outbox(stop: asyncio.Event) -> None:
    await listen(_CHANNEL, run_capi_drain, stop)
