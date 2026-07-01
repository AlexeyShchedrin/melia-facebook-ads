"""fb-mcp — MCP server over stdio for Claude Code.

Launch: `python -m meta_ads.mcp` (registered in kvadra-workspace/.mcp.json).

Tool catalogue:
  meta      — health
  read      — account_summary, campaign_perf, ad_status, budget_pacing
  analytics — conversion_funnel, analyze_lead_quality, leads_by_campaign
  planning  — interest_search, audience_estimate
  mutation  — upload_creative, create_lead_campaign, pause_campaign,
              resume_campaign, update_campaign_budget  (dry_run + confirm gated)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

# psycopg3 async cannot run on Windows' ProactorEventLoop (3.8+ default). The
# MCP server is launched locally from .mcp.json, so force a SelectorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from mcp.server.fastmcp import FastMCP

from meta_ads import __version__
from meta_ads.config import get_settings
from meta_ads.mcp.tools import analytics, mutation, planning, read

logger = logging.getLogger(__name__)
settings = get_settings()

mcp = FastMCP(
    "kvadra-facebook-ads",
    instructions="""
Manage Meta (Facebook/Instagram) ads for kvadra.me / Melia Budva residences.

Posture: read freely. For mutations always run with dry_run=true first, show the
result, then re-run with dry_run=false and confirm="yes" — and only if the server
has FB_ALLOW_MUTATIONS=1. Everything is created PAUSED; account spend_cap is the
hard kill-switch.

Creatives come from LOCAL DISK (melia-montage renders) — upload_creative takes a
local path. Optimise on QUALIFIED leads (analyze_lead_quality), not raw form-fills.
""",
)


@mcp.tool()
def health() -> dict[str, Any]:
    """Server health: version, whether Meta / Telegram are configured, mutation state."""
    return {
        "version": __version__,
        "meta_configured": settings.meta_configured,
        "telegram_configured": settings.telegram_configured,
        "mutations_allowed": settings.fb_allow_mutations,
        "ad_account_id": settings.meta_ad_account_id or None,
        "api_version": settings.meta_api_version,
        "dry_run_default": settings.fb_dry_run_default,
    }


read.register(mcp)
analytics.register(mcp)
planning.register(mcp)
mutation.register(mcp)


def main() -> None:
    logging.basicConfig(
        level=settings.fb_log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    logger.info("fb-mcp starting (version=%s)", __version__)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
