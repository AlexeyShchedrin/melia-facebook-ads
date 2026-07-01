"""Read-only MCP tools (no confirmation needed)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

_TODO = {"status": "todo", "phase": 3, "note": "wire to meta.campaign_metrics / reporting"}


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def account_summary(days: int = 30) -> dict[str, Any]:
        """Account-level spend / impressions / leads / CPL over the last `days`."""
        return _TODO | {"days": days}

    @mcp.tool()
    def campaign_perf(days: int = 30) -> dict[str, Any]:
        """Per-campaign performance table (sorted by spend)."""
        return _TODO | {"days": days}

    @mcp.tool()
    def ad_status() -> dict[str, Any]:
        """Ads in review / disapproved, with review feedback (meta.moderation_state)."""
        return _TODO

    @mcp.tool()
    def budget_pacing() -> dict[str, Any]:
        """Today's spend vs daily budget per campaign; flags drift."""
        return _TODO
