"""Mutation MCP tools — gated by dry_run + confirm + FB_ALLOW_MUTATIONS.

Same posture as google-ads: dry_run first (always allowed, maps to Meta's
execution_options=validate_only), then live with confirm="yes" only if the
server enables mutations. Everything is created PAUSED.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from meta_ads.config import get_settings


def _gate(dry_run: bool, confirm: str) -> str | None:
    if dry_run:
        return None  # validate_only — always safe
    if not get_settings().fb_allow_mutations:
        return "Live mutations disabled (FB_ALLOW_MUTATIONS=0)"
    if confirm != "yes":
        return 'Requires confirm="yes"'
    return None


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def upload_creative(local_path: str, dry_run: bool = True, confirm: str = "") -> dict[str, Any]:
        """Upload a photo/video from LOCAL DISK to Meta (adimages/advideos).
        Returns image_hash / video_id. Cached by path+mtime+size."""
        if (blocked := _gate(dry_run, confirm)) is not None:
            return {"blocked": blocked}
        return {"status": "todo", "phase": 1, "local_path": local_path, "dry_run": dry_run}

    @mcp.tool()
    def create_lead_campaign(
        name: str,
        daily_budget_eur: float,
        targeting: dict[str, Any],
        dry_run: bool = True,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Build Campaign(OUTCOME_LEADS)→AdSet(LEAD_GENERATION), PAUSED.
        dry_run=True → validate_only (no objects created)."""
        if (blocked := _gate(dry_run, confirm)) is not None:
            return {"blocked": blocked}
        return {"status": "todo", "phase": 1, "name": name, "daily_budget_eur": daily_budget_eur}

    @mcp.tool()
    def pause_campaign(campaign_id: str, dry_run: bool = True, confirm: str = "") -> dict[str, Any]:
        """Set a campaign to PAUSED."""
        if (blocked := _gate(dry_run, confirm)) is not None:
            return {"blocked": blocked}
        return {"status": "todo", "phase": 1, "campaign_id": campaign_id}

    @mcp.tool()
    def resume_campaign(campaign_id: str, dry_run: bool = True, confirm: str = "") -> dict[str, Any]:
        """Set a campaign to ACTIVE (spends real money — gated)."""
        if (blocked := _gate(dry_run, confirm)) is not None:
            return {"blocked": blocked}
        return {"status": "todo", "phase": 1, "campaign_id": campaign_id}

    @mcp.tool()
    def update_campaign_budget(
        adset_id: str, daily_eur: float, dry_run: bool = True, confirm: str = ""
    ) -> dict[str, Any]:
        """Update an ad set's daily budget (EUR)."""
        if (blocked := _gate(dry_run, confirm)) is not None:
            return {"blocked": blocked}
        return {"status": "todo", "phase": 1, "adset_id": adset_id, "daily_eur": daily_eur}
