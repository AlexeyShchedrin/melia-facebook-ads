"""Planning MCP tools — targeting research (read-only, no API mutation)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

_TODO = {"status": "todo", "phase": 3, "note": "GET /search + delivery_estimate"}


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def interest_search(query: str) -> dict[str, Any]:
        """Search Meta detailed-targeting interests (GET /search?type=adinterest)."""
        return _TODO | {"query": query}

    @mcp.tool()
    def audience_estimate(targeting: dict[str, Any]) -> dict[str, Any]:
        """Reach/delivery estimate for a targeting spec (delivery_estimate)."""
        return _TODO
