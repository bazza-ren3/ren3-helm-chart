"""
Trino MCP Server — thin entrypoint.

Domain logic: config, trino_client, sample_queries, semantic_layer, sql_knowledge
MCP tools: tools/
MCP instructions (Trino SME): prompts/trino_sme.md via prompts/loader.py
Agent skill (tool workflow): skills/trino-nl-to-sql/SKILL.md
"""
import logging

from mcp.server.fastmcp import FastMCP

from prompts.loader import build_server_instructions
from tools import build_context, register_tools

logging.basicConfig(level=logging.INFO)

ctx = build_context()
mcp = FastMCP("trino", instructions=build_server_instructions(ctx))
register_tools(mcp, ctx)

if __name__ == "__main__":
    mcp.run(transport="stdio")
