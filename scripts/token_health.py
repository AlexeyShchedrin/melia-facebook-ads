"""Meta token-health check — mirrors google-ads' daily cron.

Run daily (cron 09:05) on the box:
  0 9 * * * cd /opt/facebook-ads && .venv/bin/python scripts/token_health.py >> token-health-cron.log 2>&1

Validates each stored token via GET /debug_token and warns (Telegram) on
expiry/invalidation (subcodes 458/463/467). A dead token = silent full outage,
so this is the early-warning. TODO(phase4): wire the /debug_token call + alerts.
"""

from __future__ import annotations

import asyncio
import logging

from meta_ads.channels.meta.client import DATASET, PAGE, SYSTEM_USER, get_token

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s :: %(message)s")
log = logging.getLogger("token_health")


async def _check() -> None:
    for provider in (SYSTEM_USER, PAGE, DATASET):
        try:
            token = await get_token(provider)
            log.info("%s: present (%d chars) — TODO: GET /debug_token", provider, len(token))
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: MISSING/ERROR — %s", provider, exc)


if __name__ == "__main__":
    asyncio.run(_check())
