"""Job: auto-boost fresh IG posts as POST_ENGAGEMENT ads (pipeline A).

Gated by FB_IG_BOOST_ENABLED + FB_IG_USER_ID — a no-op until both are set.
All logic lives in meta_ads.boost.engine; state in meta.ig_boost_state.
"""

from __future__ import annotations

from meta_ads.boost.engine import IgBoostEngine


async def run_ig_boost() -> None:
    await IgBoostEngine().run()
