"""Semantic layer — introspect Trino schemas + optional overlay for joins/metrics/glossary."""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import Config

logger = logging.getLogger(__name__)

_TABLE_COMMENTS_SQL = """
SELECT catalog_name, schema_name, table_name, comment
FROM system.metadata.table_comments
WHERE table_type = 'BASE TABLE'
"""

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    description: str = ""


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    table: str  # catalog.schema.table
    description: str = ""
    primary_key: Optional[str] = None
    columns: list[Column] = Field(default_factory=list)


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    from_entity: str
    to_entity: str
    join_type: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    condition: str


class TimeGrain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    grains: list[str] = Field(default_factory=lambda: ["day", "week", "month", "quarter", "year"])


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    base_entity: str
    expression: str
    default_dimensions: list[str] = Field(default_factory=list)
    time_grain: Optional[TimeGrain] = None


class GlossaryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str
    maps_to: dict[str, str]
    aliases: list[str] = Field(default_factory=list)


class Overlay(BaseModel):
    """Curated facts not inferable from introspection alone."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    entity_aliases: dict[str, str] = Field(default_factory=dict)
    relationships: list[Relationship] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_overlay(self) -> Overlay:
        rel_names = [r.name for r in self.relationships]
        if len(rel_names) != len(set(rel_names)):
            raise ValueError("duplicate relationship names in overlay")

        metric_names = [m.name for m in self.metrics]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("duplicate metric names in overlay")

        glossary_terms = [g.term.lower() for g in self.glossary]
        if len(glossary_terms) != len(set(glossary_terms)):
            raise ValueError("duplicate glossary terms in overlay")

        for alias, table in self.entity_aliases.items():
            if not _is_three_part_table(table):
                raise ValueError(
                    f"entity_aliases[{alias!r}]: table {table!r} must be catalog.schema.table"
                )

        for g in self.glossary:
            keys = set(g.maps_to.keys())
            if keys != {"entity"} and keys != {"metric"}:
                raise ValueError(
                    f"glossary term {g.term!r}: maps_to must have exactly one key: 'entity' or 'metric'"
                )

        return self


class SemanticModel(BaseModel):
    """Merged introspected entities + overlay relationships/metrics/glossary."""

    model_config = ConfigDict(extra="forbid")

    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    status: Literal["ready", "loading", "error", "empty"] = "empty"
    status_message: str = ""
    datasource_knowledge: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Overlay load
# ---------------------------------------------------------------------------


def _is_three_part_table(table: str) -> bool:
    parts = table.split(".")
    return len(parts) == 3 and all(p.strip() for p in parts)


def load_overlay(path: Optional[Path]) -> Optional[Overlay]:
    if path is None or not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise ValueError("overlay root must be a YAML mapping")
    return Overlay(**raw)


def _filter_overlay(overlay: Overlay, entity_names: set[str]) -> Overlay:
    """Drop overlay refs that don't resolve to introspected/aliased entities."""
    valid_metrics = [m for m in overlay.metrics if m.base_entity in entity_names]
    for m in overlay.metrics:
        if m.base_entity not in entity_names:
            logger.warning("overlay metric %r: unknown base_entity %r — skipped", m.name, m.base_entity)

    valid_rels: list[Relationship] = []
    for r in overlay.relationships:
        if r.from_entity in entity_names and r.to_entity in entity_names:
            valid_rels.append(r)
        else:
            logger.warning(
                "overlay relationship %r: unknown entity — skipped (from=%r to=%r)",
                r.name,
                r.from_entity,
                r.to_entity,
            )

    valid_glossary: list[GlossaryEntry] = []
    metric_names = {m.name for m in valid_metrics}
    for g in overlay.glossary:
        if "entity" in g.maps_to and g.maps_to["entity"] not in entity_names:
            logger.warning("overlay glossary %r: unknown entity — skipped", g.term)
            continue
        if "metric" in g.maps_to and g.maps_to["metric"] not in metric_names:
            logger.warning("overlay glossary %r: unknown metric — skipped", g.term)
            continue
        valid_glossary.append(g)

    return Overlay(
        version=overlay.version,
        entity_aliases=overlay.entity_aliases,
        relationships=valid_rels,
        metrics=valid_metrics,
        glossary=valid_glossary,
    )


def merge_overlay(
    entities: list[Entity],
    overlay: Optional[Overlay],
    *,
    datasource_knowledge: Optional[dict[str, Any]] = None,
) -> SemanticModel:
    entity_by_table = {e.table: e for e in entities}
    name_used = {e.name for e in entities}

    if overlay:
        for alias, table in overlay.entity_aliases.items():
            if table not in entity_by_table:
                logger.warning("entity_aliases[%r]: table %r not in introspection — skipped", alias, table)
                continue
            base = entity_by_table[table]
            if alias in name_used:
                continue
            aliased = base.model_copy(update={"name": alias})
            entities.append(aliased)
            name_used.add(alias)

    entity_names = {e.name for e in entities}
    filtered = _filter_overlay(overlay, entity_names) if overlay else None

    return SemanticModel(
        entities=entities,
        relationships=filtered.relationships if filtered else [],
        metrics=filtered.metrics if filtered else [],
        glossary=filtered.glossary if filtered else [],
        status="ready" if entities else "empty",
        datasource_knowledge=datasource_knowledge or {},
    )


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


def _derive_entity_name(table: str, schema: str, catalog: str, used: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]+", "_", table).strip("_").lower() or "table"
    if base not in used:
        return base
    candidate = f"{schema}_{table}".lower()
    candidate = re.sub(r"[^a-zA-Z0-9_]+", "_", candidate).strip("_")
    if candidate not in used:
        return candidate
    full = f"{catalog}_{schema}_{table}".lower()
    return re.sub(r"[^a-zA-Z0-9_]+", "_", full).strip("_")


def _guess_primary_key(columns: list[Column]) -> Optional[str]:
    names = {c.name.lower() for c in columns}
    for candidate in ("id", "uuid", "pk"):
        if candidate in names:
            return candidate
    for c in columns:
        if c.name.lower().endswith("_id"):
            return c.name
    return None


def build_introspected_entities(cfg: Config) -> list[Entity]:
    import trino_client

    tables = _fetch_tables_via_metadata(cfg, trino_client)
    if tables is None:
        tables = _fetch_tables_via_walk(cfg, trino_client)

    entities: list[Entity] = []
    used_names: set[str] = set()

    for t in tables:
        catalog, schema, table = t["catalog"], t["schema"], t["table"]
        fqn = f"{catalog}.{schema}.{table}"
        cols_raw = trino_client.describe_table(cfg, catalog, schema, table)
        columns = [
            Column(
                name=c["column"],
                type=c["type"],
                description=(c.get("comment") or "").strip(),
            )
            for c in cols_raw
        ]
        name = _derive_entity_name(table, schema, catalog, used_names)
        used_names.add(name)
        entities.append(
            Entity(
                name=name,
                table=fqn,
                description=(t.get("comment") or "").strip(),
                primary_key=_guess_primary_key(columns),
                columns=columns,
            )
        )

    return entities


def _fetch_tables_via_metadata(cfg: Config, trino_client: Any) -> list[dict[str, str]] | None:
    result = trino_client.run_select(cfg, _TABLE_COMMENTS_SQL)
    if "error" in result:
        logger.info("system.metadata.table_comments unavailable: %s", result["error"])
        return None

    rows = result["rows"]
    tables: list[dict[str, str]] = []
    for row in rows:
        catalog, schema, table = str(row[0]), str(row[1]), str(row[2])
        if not cfg.should_introspect_catalog(catalog):
            continue
        if schema.lower() in cfg.introspect_excluded_schemas:
            continue
        comment = str(row[3]) if len(row) > 3 and row[3] is not None else ""
        tables.append({"catalog": catalog, "schema": schema, "table": table, "comment": comment})
    return tables


def _fetch_tables_via_walk(cfg: Config, trino_client: Any) -> list[dict[str, str]]:
    tables: list[dict[str, str]] = []
    catalogs = trino_client.list_catalogs(cfg)
    for cat_info in catalogs:
        catalog = cat_info["name"] if isinstance(cat_info, dict) else cat_info
        if not cfg.should_introspect_catalog(catalog):
            continue
        try:
            schemas = trino_client.list_schemas(cfg, catalog)
        except Exception as e:  # noqa: BLE001
            logger.warning("list_schemas(%r) failed: %s", catalog, e)
            continue
        for schema in schemas:
            if schema.lower() in cfg.introspect_excluded_schemas:
                continue
            try:
                table_names = trino_client.list_tables(cfg, catalog, schema)
            except Exception as e:  # noqa: BLE001
                logger.warning("list_tables(%r.%r) failed: %s", catalog, schema, e)
                continue
            for table in table_names:
                tables.append({"catalog": catalog, "schema": schema, "table": table, "comment": ""})
    return tables


# ---------------------------------------------------------------------------
# Cached semantic model (lazy load)
# ---------------------------------------------------------------------------


class SemanticModelCache:
    def __init__(
        self,
        cfg: Config,
        overlay: Optional[Overlay],
        sample_catalog: Any = None,
    ) -> None:
        self._cfg = cfg
        self._overlay = overlay
        self._sample_catalog = sample_catalog
        self._lock = threading.Lock()
        self._model: Optional[SemanticModel] = None
        self._loading = False

    def get(self) -> SemanticModel:
        with self._lock:
            if self._model is not None:
                return self._model
            if self._loading:
                return SemanticModel(status="loading", status_message="Schema introspection in progress")
        return self._load()

    def refresh(self) -> SemanticModel:
        with self._lock:
            self._model = None
            self._loading = False
        return self._load()

    def _load(self) -> SemanticModel:
        from sql_knowledge import (
            build_datasource_knowledge,
            enrich_entities_from_knowledge,
            knowledge_summary_dict,
            merge_overlays,
            overlay_from_knowledge,
            stub_entities_from_knowledge,
        )

        knowledge = None
        sample_overlay = None
        if self._sample_catalog and self._sample_catalog.queries:
            knowledge = build_datasource_knowledge(self._sample_catalog)
            sample_overlay = overlay_from_knowledge(knowledge)
            logger.info(
                "Mined sample SQL: %d tables, %d joins from %d queries",
                len(knowledge.tables),
                len(knowledge.joins),
                knowledge.query_count,
            )

        merged_overlay = merge_overlays(self._overlay, sample_overlay)
        knowledge_dict = knowledge_summary_dict(knowledge) if knowledge else {}

        with self._lock:
            self._loading = True
        try:
            entities = build_introspected_entities(self._cfg)
            if knowledge:
                entities = enrich_entities_from_knowledge(entities, knowledge)
            model = merge_overlay(
                entities, merged_overlay, datasource_knowledge=knowledge_dict
            )
            logger.info("Introspected %d entities from Trino", len(model.entities))
        except Exception as e:  # noqa: BLE001
            logger.exception("Schema introspection failed")
            if knowledge:
                entities = stub_entities_from_knowledge(knowledge)
                model = merge_overlay(
                    entities,
                    merged_overlay,
                    datasource_knowledge=knowledge_dict,
                )
                model.status = "ready"
                model.status_message = f"Trino unreachable; using sample SQL only: {e}"
            else:
                model = SemanticModel(
                    status="error",
                    status_message=str(e),
                    relationships=merged_overlay.relationships if merged_overlay else [],
                    metrics=merged_overlay.metrics if merged_overlay else [],
                    glossary=merged_overlay.glossary if merged_overlay else [],
                )
        with self._lock:
            self._model = model
            self._loading = False
        return model


# ---------------------------------------------------------------------------
# Public API (unchanged tool surface)
# ---------------------------------------------------------------------------


def _entity_by_name(model: SemanticModel) -> dict[str, Entity]:
    return {e.name: e for e in model.entities}


def list_entities(model: SemanticModel) -> dict[str, Any]:
    if model.status == "loading":
        return {"status": "loading", "entities": [], "message": model.status_message}
    if model.status == "error":
        return {"status": "error", "entities": [], "message": model.status_message}
    return {
        "status": model.status,
        "entities": [
            {"name": e.name, "description": e.description, "table": e.table}
            for e in model.entities
        ],
    }


def describe_entity(model: SemanticModel, name: str) -> dict[str, Any]:
    if model.status == "loading":
        return {"status": "loading", "message": "Schema introspection in progress"}
    entities = _entity_by_name(model)
    if name not in entities:
        return {"error": f"unknown entity: {name!r}"}

    e = entities[name]
    rels_out = [
        {
            "name": r.name,
            "direction": "out",
            "other_entity": r.to_entity,
            "join_type": r.join_type,
            "condition": r.condition,
        }
        for r in model.relationships
        if r.from_entity == name
    ]
    rels_in = [
        {
            "name": r.name,
            "direction": "in",
            "other_entity": r.from_entity,
            "join_type": r.join_type,
            "condition": r.condition,
        }
        for r in model.relationships
        if r.to_entity == name
    ]
    metrics_here = [m.name for m in model.metrics if m.base_entity == name]
    cols = [{"name": c.name, "type": c.type, "description": c.description} for c in e.columns]
    join_hints = _column_join_hints(e, model)

    sample_meta: dict[str, Any] = {}
    for t in model.datasource_knowledge.get("tables", []):
        if t.get("fqn") == e.table:
            sample_meta = {
                "sample_query_count": t.get("query_count", 0),
                "sample_query_ids": t.get("sample_query_ids", []),
                "columns_used_in_samples": t.get("columns_used", []),
                "categories": t.get("categories", []),
            }
            break

    return {
        "name": e.name,
        "table": e.table,
        "description": e.description,
        "primary_key": e.primary_key,
        "columns": cols,
        "join_hints": join_hints,
        "relationships": rels_out + rels_in,
        "metrics_using_this": metrics_here,
        "from_sample_queries": sample_meta,
    }


def _column_join_hints(entity: Entity, model: SemanticModel) -> list[dict[str, str]]:
    """Heuristic FK hints when overlay relationships are absent."""
    hints: list[dict[str, str]] = []
    others = [o for o in model.entities if o.name != entity.name]
    for col in entity.columns:
        lower = col.name.lower()
        if not lower.endswith("_id"):
            continue
        stem = lower[:-3]
        for other in others:
            if other.primary_key and other.primary_key.lower() == lower:
                hints.append(
                    {
                        "column": col.name,
                        "likely_entity": other.name,
                        "hint": f"{entity.table}.{col.name} may join {other.table}.{other.primary_key}",
                    }
                )
                break
            if stem and stem in other.name.lower().replace("_", ""):
                pk = other.primary_key or "id"
                hints.append(
                    {
                        "column": col.name,
                        "likely_entity": other.name,
                        "hint": f"{entity.table}.{col.name} may join {other.table}.{pk}",
                    }
                )
                break
    return hints


def get_relationships(model: SemanticModel, entity: str) -> list[dict[str, Any]] | dict[str, Any]:
    if model.status == "loading":
        return {"status": "loading", "message": "Schema introspection in progress"}
    if entity not in _entity_by_name(model):
        return {"error": f"unknown entity: {entity!r}"}
    return [
        {
            "name": r.name,
            "to_entity": r.to_entity,
            "join_type": r.join_type,
            "condition": r.condition,
        }
        for r in model.relationships
        if r.from_entity == entity
    ]


def list_metrics(model: SemanticModel) -> list[dict[str, Any]] | dict[str, Any]:
    if model.status == "loading":
        return {"status": "loading", "message": "Schema introspection in progress"}
    return [
        {"name": m.name, "description": m.description, "base_entity": m.base_entity}
        for m in model.metrics
    ]


def get_metric_sql(model: SemanticModel, metric: str) -> dict[str, Any]:
    if model.status == "loading":
        return {"status": "loading", "message": "Schema introspection in progress"}
    for m in model.metrics:
        if m.name == metric:
            tg = None
            if m.time_grain is not None:
                tg = {"column": m.time_grain.column, "grains": m.time_grain.grains}
            return {
                "expression": m.expression,
                "base_entity": m.base_entity,
                "time_grain": tg,
                "dimensions": m.default_dimensions,
            }
    return {"error": f"unknown metric: {metric!r}"}


def resolve_term(model: SemanticModel, term: str) -> dict[str, Any]:
    if model.status == "loading":
        return {"status": "loading", "matches": [], "message": "Schema introspection in progress"}

    needle = term.strip().lower()
    if not needle:
        return {"matches": []}

    matches: list[dict[str, Any]] = []
    entities = _entity_by_name(model)

    for e in model.entities:
        if e.name.lower() == needle or e.table.lower().endswith(f".{needle}"):
            matches.append({"kind": "entity", "name": e.name, "table": e.table, "via": "entity_name"})

    for m in model.metrics:
        if m.name.lower() == needle:
            matches.append({"kind": "metric", "name": m.name, "via": "metric_name"})

    for g in model.glossary:
        candidates = [g.term.lower(), *[a.lower() for a in g.aliases]]
        if needle in candidates:
            if "entity" in g.maps_to:
                en = g.maps_to["entity"]
                ent = entities.get(en)
                matches.append(
                    {
                        "kind": "entity",
                        "name": en,
                        "table": ent.table if ent else "",
                        "via": f"glossary:{g.term}",
                    }
                )
            else:
                mn = g.maps_to["metric"]
                matches.append({"kind": "metric", "name": mn, "via": f"glossary:{g.term}"})

    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for m in matches:
        key = (m["kind"], m["name"])
        if key not in seen:
            seen.add(key)
            deduped.append(m)

    return {"matches": deduped}
