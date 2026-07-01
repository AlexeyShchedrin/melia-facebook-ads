"""Analytics MCP tools — cross-schema joins (meta.* + ads_contract views), read-only."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

_TODO = {"status": "todo", "phase": 3, "note": "join meta.campaign_metrics + ads_contract.v_leads_meta"}


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def conversion_funnel(days: int = 30) -> dict[str, Any]:
        """Meta leads → qualified → deposit → paid, stage-to-stage rates."""
        return _TODO | {"days": days}

    @mcp.tool()
    def analyze_lead_quality(days: int = 90) -> dict[str, Any]:
        """Per-campaign real cost-per-qualified-lead — the basis for tuning
        toward quality, not raw form-fills."""
        return _TODO | {"days": days}

    @mcp.tool()
    def leads_by_campaign(campaign: str, status: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Drill down into a campaign's leads (name/email/funnel status)."""
        return _TODO | {"campaign": campaign, "status": status, "limit": limit}
