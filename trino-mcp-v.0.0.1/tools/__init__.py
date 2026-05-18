"""MCP tool registration — one module per concern."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from tools.context import ToolContext, build_context
from tools import samples, schema_tools, semantic_tools


def register_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    samples.register(mcp, ctx)
    semantic_tools.register(mcp, ctx)
    schema_tools.register(mcp, ctx)


__all__ = ["ToolContext", "build_context", "register_tools"]
