"""MCP tools — raw Trino catalog access and query execution."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

import trino_client
from tools.context import ToolContext
from tools.json_util import TrinoJsonEncoder


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    cfg = ctx.cfg

    @mcp.tool()
    def list_catalogs() -> str:
        """List Trino catalogs. Use only when list_entities does not cover the data needed."""
        return json.dumps(trino_client.list_catalogs(cfg))

    @mcp.tool()
    def list_schemas(catalog: str) -> str:
        """List schemas in a catalog.

        Args:
            catalog: Catalog name from list_catalogs.
        """
        return json.dumps(trino_client.list_schemas(cfg, catalog))

    @mcp.tool()
    def list_tables(catalog: str, schema: str) -> str:
        """List tables in a catalog.schema.

        Args:
            catalog: Catalog name.
            schema: Schema name.
        """
        return json.dumps(trino_client.list_tables(cfg, catalog, schema))

    @mcp.tool()
    def describe_table(catalog: str, schema: str, table: str) -> str:
        """Describe columns for a physical table not in list_entities.

        Args:
            catalog: Catalog name.
            schema: Schema name.
            table: Table name.
        """
        return json.dumps(trino_client.describe_table(cfg, catalog, schema, table))

    @mcp.tool()
    def execute_query(sql: str) -> str:
        """Execute a SELECT on Trino and return JSON rows. SELECT-only; capped at TRINO_MAX_ROWS.

        Always show the SQL to the user. Format results as a markdown table.

        Args:
            sql: Fully-qualified SELECT, e.g. SELECT col FROM catalog.schema.table LIMIT 10
        """
        result = trino_client.execute_query(cfg, sql)
        return json.dumps(result, cls=TrinoJsonEncoder)
