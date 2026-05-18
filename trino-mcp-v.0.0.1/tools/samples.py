"""MCP tools — customer sample query playbook."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

import sample_queries
from tools.context import ToolContext


def _unconfigured() -> str:
    return json.dumps({"error": "Sample queries not configured"})


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool()
    def search_sample_queries(term: str) -> str:
        """FIRST: find customer-curated questions similar to the user's request.

        If a strong match exists, call get_sample_query before writing SQL from scratch.

        Args:
            term: Natural-language phrase or keywords from the user.
        """
        if ctx.sample_catalog is None:
            return _unconfigured()
        return json.dumps(sample_queries.search_sample_queries(ctx.sample_catalog, term))

    @mcp.tool()
    def get_sample_query(query_id: str) -> str:
        """Return the canonical SQL template for a matched sample question.

        Adapt table/column names to the live schema (verify with describe_entity).

        Args:
            query_id: Id from search_sample_queries.
        """
        if ctx.sample_catalog is None:
            return _unconfigured()
        return json.dumps(sample_queries.get_sample_query(ctx.sample_catalog, query_id))

    @mcp.tool()
    def list_sample_queries(category: str = "") -> str:
        """List all customer sample questions (id, question, category)."""
        if ctx.sample_catalog is None:
            return _unconfigured()
        cat = category.strip() or None
        return json.dumps(sample_queries.list_sample_queries(ctx.sample_catalog, cat))
