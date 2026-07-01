"""Shared LISTEN/NOTIFY helper (raw psycopg3 async).

Both live consumers — 'meta_leadgen' (new lead queued by the CRM relay) and
'ads_outbox' (lead status changed) — use this. The scheduler's 30 s poll is the
fallback; this makes most work fire within ~1 s of the CRM insert.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import psycopg

from meta_ads.config import get_settings

logger = logging.getLogger(__name__)


def libpq_dsn() -> str:
    """SQLAlchemy URL → libpq DSN (drop the +driver; ?options=... stays valid)."""
    return get_settings().fb_database_url.replace("+psycopg", "").replace("+asyncpg", "")


async def listen(channel: str, on_notify: Callable[[], Awaitable[None]], stop: asyncio.Event) -> None:
    """LISTEN on `channel`, calling `on_notify` per notification until `stop` is set.
    Reconnects with backoff on any connection error."""
    dsn = libpq_dsn()
    while not stop.is_set():
        try:
            async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
                await conn.execute(f"LISTEN {channel}")
                logger.info("LISTEN %s", channel)
                gen = conn.notifies()
                async for _note in gen:
                    if stop.is_set():
                        break
                    try:
                        await on_notify()
                    except Exception:
                        logger.exception("on_notify(%s) failed", channel)
        except Exception:
            if stop.is_set():
                break
            logger.exception("LISTEN %s dropped — reconnecting in 5s", channel)
            await asyncio.sleep(5)
