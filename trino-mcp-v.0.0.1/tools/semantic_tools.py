"""MCP tools — semantic layer (introspection + overlay + sample SQL knowledge)."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

import semantic_layer
from tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    def _model() -> semantic_layer.SemanticModel:
        return ctx.semantic_cache.get()

    @mcp.tool()
    def get_datasource_knowledge() -> str:
        """Catalogs, tables, columns, and joins mined from customer sample SQL.

        Use with list_entities / describe_entity. Primary table and column usage
        reflect what the customer's validated queries actually touch.
        """
        model = _model()
        if not model.datasource_knowledge:
            return json.dumps(
                {
                    "error": "No sample queries loaded",
                    "hint": "Run scripts/import_sample_queries_xlsx.py to populate samples/sample_queries.yaml",
                }
            )
        return json.dumps(model.datasource_knowledge)

    @mcp.tool()
    def refresh_schema() -> str:
        """Re-introspect Trino catalogs/schemas/tables. Call when list_entities is stale or empty."""
        model = ctx.semantic_cache.refresh()
        return json.dumps(
            {
                "status": model.status,
                "entity_count": len(model.entities),
                "message": model.status_message or "Schema cache refreshed",
            }
        )

    @mcp.tool()
    def list_entities() -> str:
        """List business entities introspected from Trino (name, table, description).

        Populated lazily on first call. Use describe_entity for columns and join_hints.
        """
        return json.dumps(semantic_layer.list_entities(_model()))

    @mcp.tool()
    def describe_entity(name: str) -> str:
        """Columns, overlay relationships, join_hints, and metrics for one entity.

        Args:
            name: Entity name from list_entities or resolve_term.
        """
        return json.dumps(semantic_layer.describe_entity(_model(), name))

    @mcp.tool()
    def get_relationships(entity: str) -> str:
        """Exact join conditions from overlay (outgoing only). Prefer over guessing joins.

        Args:
            entity: Entity name.
        """
        model = _model()
        names = {e.name for e in model.entities}
        if entity not in names:
            return json.dumps({"error": f"unknown entity: {entity!r}"})
        return json.dumps(semantic_layer.get_relationships(model, entity))

    @mcp.tool()
    def list_metrics() -> str:
        """Metrics from semantic overlay (name, description, base_entity)."""
        return json.dumps(semantic_layer.list_metrics(_model()))

    @mcp.tool()
    def get_metric_sql(metric: str) -> str:
        """Canonical SQL aggregate fragment and dimensions for an overlay metric.

        Args:
            metric: Metric name from list_metrics or resolve_term.
        """
        return json.dumps(semantic_layer.get_metric_sql(_model(), metric))

    @mcp.tool()
    def resolve_term(term: str) -> str:
        """Map a business phrase to entities or metrics (glossary + name match).

        Call after search_sample_queries if no playbook match.
        """
        return json.dumps(semantic_layer.resolve_term(_model(), term))
