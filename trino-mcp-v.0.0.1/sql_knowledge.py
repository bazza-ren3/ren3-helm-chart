"""Extract catalogs, tables, columns, and joins from customer sample SQL."""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from sample_queries import SampleQuery, SampleQueryCatalog
from semantic_layer import GlossaryEntry, Overlay, Relationship, _derive_entity_name, _is_three_part_table

logger = logging.getLogger(__name__)

_SQL_KEYWORDS = frozenset(
    {
        "select", "from", "where", "join", "inner", "left", "right", "full", "cross",
        "on", "and", "or", "not", "in", "is", "null", "as", "with", "group", "by",
        "order", "having", "limit", "offset", "union", "all", "distinct", "case",
        "when", "then", "else", "end", "over", "partition", "cast", "decimal",
        "trim", "upper", "lower", "like", "between", "true", "false", "asc", "desc",
        "count", "sum", "avg", "min", "max", "note", "return",
    }
)

_QUOTED_FQN = re.compile(
    r'"([^"]+)"\s*\.\s*"([^"]+)"\s*\.\s*"([^"]+)"',
    re.IGNORECASE,
)
_UNQUOTED_FQN = re.compile(
    r'\b([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\b',
)
_JOIN_ON = re.compile(
    r"(?is)\b(?:inner\s+|left\s+(?:outer\s+)?|right\s+(?:outer\s+)?|full\s+(?:outer\s+)?|cross\s+)?join\s+"
    r"(.+?)\s+on\s+(.+?)(?=\s+(?:inner|left|right|full|cross|join|where|group|order|having|limit)\b|$)",
)
_SELECT_LIST = re.compile(r"(?is)select\s+(.*?)\s+from\s")


class TableUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fqn: str
    catalog: str
    schema_name: str
    table: str
    query_count: int = 0
    sample_query_ids: list[str] = Field(default_factory=list)
    columns_used: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class JoinPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    condition: str
    tables: list[str] = Field(default_factory=list)
    sample_query_ids: list[str] = Field(default_factory=list)


class DatasourceKnowledge(BaseModel):
    """Aggregated facts mined from sample_queries.yaml SQL."""

    model_config = ConfigDict(extra="forbid")

    source: str = ""
    query_count: int = 0
    catalogs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    tables: list[TableUsage] = Field(default_factory=list)
    joins: list[JoinPattern] = Field(default_factory=list)
    primary_table_fqn: str = ""
    entity_aliases: dict[str, str] = Field(default_factory=dict)
    glossary_terms: list[dict[str, Any]] = Field(default_factory=list)


def _strip_sql_noise(sql: str) -> str:
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    return s


def _normalize_fqn(catalog: str, schema: str, table: str) -> str:
    return f"{catalog}.{schema}.{table}"


def extract_qualified_tables(sql: str) -> list[str]:
    clean = _strip_sql_noise(sql)
    found: list[str] = []
    seen: set[str] = set()
    for m in _QUOTED_FQN.finditer(clean):
        fqn = _normalize_fqn(m.group(1), m.group(2), m.group(3))
        if fqn not in seen:
            seen.add(fqn)
            found.append(fqn)
    for m in _UNQUOTED_FQN.finditer(clean):
        fqn = _normalize_fqn(m.group(1), m.group(2), m.group(3))
        if fqn.lower() not in {s.lower() for s in _SQL_KEYWORDS} and fqn not in seen:
            seen.add(fqn)
            found.append(fqn)
    return found


def extract_join_conditions(sql: str) -> list[str]:
    clean = _strip_sql_noise(sql)
    return [m.group(2).strip() for m in _JOIN_ON.finditer(clean) if m.group(2).strip()]


def extract_column_names(sql: str) -> list[str]:
    """Best-effort column identifiers from SELECT / WHERE / GROUP BY (unqualified)."""
    clean = _strip_sql_noise(sql)
    cols: list[str] = []
    seen: set[str] = set()

    sel = _SELECT_LIST.search(clean)
    chunks = [sel.group(1)] if sel else []
    for key in ("where", "group by", "order by", "having"):
        parts = re.split(rf"(?i)\b{key}\b", clean, maxsplit=1)
        if len(parts) > 1:
            chunks.append(parts[1].split("limit")[0].split("order by")[0])

    for chunk in chunks:
        for m in re.finditer(r'"([^"]+)"', chunk):
            name = m.group(1)
            if name.lower() not in _SQL_KEYWORDS and name not in seen:
                seen.add(name)
                cols.append(name)
        for m in re.finditer(r"\b([a-zA-Z_][\w]*)\b", chunk):
            name = m.group(1)
            low = name.lower()
            if low in _SQL_KEYWORDS or name in seen or name.isdigit():
                continue
            if low.startswith("sum_") or low.startswith("cnt_") or low.startswith("avg_"):
                seen.add(name)
                cols.append(name)
                continue
            if len(name) > 2:
                seen.add(name)
                cols.append(name)
    return cols


def build_datasource_knowledge(catalog: SampleQueryCatalog) -> DatasourceKnowledge:
    table_hits: dict[str, dict[str, Any]] = {}
    join_map: dict[str, JoinPattern] = {}
    col_counts: dict[str, Counter[str]] = defaultdict(Counter)
    category_by_table: dict[str, set[str]] = defaultdict(set)

    for q in catalog.queries:
        tables = extract_qualified_tables(q.sql)
        joins = extract_join_conditions(q.sql)
        columns = extract_column_names(q.sql)

        for fqn in tables:
            if fqn not in table_hits:
                parts = fqn.split(".", 2)
                table_hits[fqn] = {
                    "fqn": fqn,
                    "catalog": parts[0],
                    "schema": parts[1],
                    "table": parts[2],
                    "query_count": 0,
                    "sample_query_ids": [],
                    "categories": set(),
                }
            table_hits[fqn]["query_count"] += 1
            table_hits[fqn]["sample_query_ids"].append(q.id)
            if q.category:
                table_hits[fqn]["categories"].add(q.category)
                category_by_table[fqn].add(q.category)

        for fqn in tables:
            for col in columns:
                col_counts[fqn][col] += 1

        for i, cond in enumerate(joins):
            tables_in_join = extract_qualified_tables(cond)
            key = re.sub(r"\s+", " ", cond.lower())
            if key not in join_map:
                join_map[key] = JoinPattern(
                    name=f"sample_join_{len(join_map) + 1}",
                    condition=cond.strip(),
                    tables=tables_in_join,
                    sample_query_ids=[],
                )
            join_map[key].sample_query_ids.append(q.id)

    usages: list[TableUsage] = []
    for fqn, data in sorted(table_hits.items(), key=lambda x: -x[1]["query_count"]):
        top_cols = [c for c, _ in col_counts[fqn].most_common(40)]
        usages.append(
            TableUsage(
                fqn=fqn,
                catalog=data["catalog"],
                schema_name=data["schema"],
                table=data["table"],
                query_count=data["query_count"],
                sample_query_ids=list(dict.fromkeys(data["sample_query_ids"])),
                columns_used=top_cols,
                categories=sorted(data["categories"]),
            )
        )

    primary = usages[0].fqn if usages else ""

    catalogs: dict[str, dict[str, Any]] = {}
    for u in usages:
        cat = catalogs.setdefault(
            u.catalog,
            {"schemas": {}, "tables": [], "query_count": 0},
        )
        cat["query_count"] += u.query_count
        sch = cat["schemas"].setdefault(u.schema_name, {"tables": [], "query_count": 0})
        sch["tables"].append(u.table)
        sch["query_count"] += u.query_count
        cat["tables"].append(u.fqn)

    entity_aliases: dict[str, str] = {}
    glossary: list[dict[str, Any]] = []

    for u in usages:
        short = re.sub(r"[^a-zA-Z0-9_]+", "_", u.table.lower()).strip("_")
        if short and short not in entity_aliases:
            entity_aliases[short] = u.fqn
        schema_table = f"{u.schema_name}_{u.table}".lower()
        schema_table = re.sub(r"[^a-zA-Z0-9_]+", "_", schema_table)
        if schema_table not in entity_aliases:
            entity_aliases[schema_table] = u.fqn

    if primary:
        primary_entity = _derive_entity_name(
            usages[0].table, usages[0].schema_name, usages[0].catalog, set()
        )
        seen_gloss: set[str] = set()
        for cat in category_by_table.get(primary, set()):
            term = cat.strip().lower()
            if term and term not in seen_gloss:
                seen_gloss.add(term)
                glossary.append(
                    {
                        "term": term,
                        "maps_to": {"entity": primary_entity},
                        "aliases": [cat],
                    }
                )
        for token in ("vendor", "vendors", "purchase order", "gr", "goods receipt", "open po"):
            if token not in seen_gloss:
                seen_gloss.add(token)
                glossary.append(
                    {
                        "term": token,
                        "maps_to": {"entity": primary_entity},
                        "aliases": [],
                    }
                )

    return DatasourceKnowledge(
        source=catalog.source or "sample_queries",
        query_count=len(catalog.queries),
        catalogs=catalogs,
        tables=usages,
        joins=list(join_map.values()),
        primary_table_fqn=primary,
        entity_aliases=entity_aliases,
        glossary_terms=glossary,
    )


def overlay_from_knowledge(knowledge: DatasourceKnowledge) -> Overlay:
    """Turn mined knowledge into an Overlay merged with file-based overlay."""
    relationships: list[Relationship] = []
    entity_names: dict[str, str] = {}  # fqn -> entity name

    used_ent: set[str] = set()
    for u in knowledge.tables:
        entity_names[u.fqn] = _derive_entity_name(u.table, u.schema_name, u.catalog, used_ent)
        used_ent.add(entity_names[u.fqn])

    used_ent_names: set[str] = set(entity_names.values())
    for j in knowledge.joins:
        if len(j.tables) >= 2:
            from_fqn, to_fqn = j.tables[0], j.tables[1]

            def _ent_for(fqn: str) -> str:
                if fqn in entity_names:
                    return entity_names[fqn]
                c, s, t = fqn.split(".", 2)
                name = _derive_entity_name(t, s, c, used_ent_names)
                used_ent_names.add(name)
                entity_names[fqn] = name
                return name

            from_ent = _ent_for(from_fqn)
            to_ent = _ent_for(to_fqn)
            relationships.append(
                Relationship(
                    name=j.name,
                    from_entity=from_ent,
                    to_entity=to_ent,
                    join_type="many_to_one",
                    condition=j.condition,
                )
            )

    glossary: list[GlossaryEntry] = []
    seen_terms: set[str] = set()
    for g in knowledge.glossary_terms:
        term = g["term"].lower()
        if term in seen_terms:
            continue
        seen_terms.add(term)
        ent = g["maps_to"].get("entity")
        if ent:
            glossary.append(
                GlossaryEntry(
                    term=g["term"],
                    maps_to={"entity": ent},
                    aliases=g.get("aliases", []),
                )
            )

    return Overlay(
        entity_aliases=knowledge.entity_aliases,
        relationships=relationships,
        metrics=[],
        glossary=glossary,
    )


def merge_overlays(*overlays: Optional[Overlay]) -> Optional[Overlay]:
    """Combine multiple overlays; later entries do not override earlier keys."""
    aliases: dict[str, str] = {}
    rels: dict[str, Relationship] = {}
    metrics: dict[str, Any] = {}
    glossary: dict[str, GlossaryEntry] = {}

    for overlay in overlays:
        if overlay is None:
            continue
        aliases.update(overlay.entity_aliases)
        for r in overlay.relationships:
            rels[r.name] = r
        for m in overlay.metrics:
            metrics[m.name] = m
        for g in overlay.glossary:
            glossary[g.term.lower()] = g

    if not aliases and not rels and not metrics and not glossary:
        return None

    from semantic_layer import Metric

    return Overlay(
        entity_aliases=aliases,
        relationships=list(rels.values()),
        metrics=list(metrics.values()),
        glossary=list(glossary.values()),
    )


def knowledge_summary_dict(knowledge: DatasourceKnowledge) -> dict[str, Any]:
    return {
        "source": knowledge.source,
        "sample_query_count": knowledge.query_count,
        "primary_table": knowledge.primary_table_fqn,
        "catalogs": knowledge.catalogs,
        "tables": [t.model_dump() for t in knowledge.tables],
        "joins": [j.model_dump() for j in knowledge.joins],
        "entity_aliases": knowledge.entity_aliases,
        "glossary_terms": knowledge.glossary_terms,
    }


def stub_entities_from_knowledge(knowledge: DatasourceKnowledge) -> list[Any]:
    """Entities for tables referenced in samples but not yet introspected from Trino."""
    from semantic_layer import Column, Entity

    entities: list[Entity] = []
    used: set[str] = set()
    for u in knowledge.tables:
        name = _derive_entity_name(u.table, u.schema_name, u.catalog, used)
        used.add(name)
        cols = [
            Column(name=c, type="unknown", description="seen in customer sample SQL")
            for c in u.columns_used[:50]
        ]
        desc = f"Used in {u.query_count} customer sample queries"
        if u.categories:
            desc += f" (categories: {', '.join(u.categories)})"
        entities.append(
            Entity(
                name=name,
                table=u.fqn if _is_three_part_table(u.fqn) else u.fqn,
                description=desc,
                columns=cols,
            )
        )
    return entities


def enrich_entities_from_knowledge(entities: list[Any], knowledge: DatasourceKnowledge) -> list[Any]:
    """Merge sample column usage + descriptions into introspected entities."""
    from semantic_layer import Column, Entity  # noqa: F811

    by_table = {e.table: e for e in entities}
    usage_by_fqn = {u.fqn: u for u in knowledge.tables}

    for fqn, usage in usage_by_fqn.items():
        if fqn in by_table:
            ent = by_table[fqn]
            existing_cols = {c.name.lower() for c in ent.columns}
            extra = [
                Column(name=c, type="unknown", description="seen in customer sample SQL")
                for c in usage.columns_used
                if c.lower() not in existing_cols
            ]
            note = f"Referenced in {usage.query_count} sample queries"
            desc = ent.description or note
            if note not in desc:
                desc = f"{desc}. {note}".strip(". ")
            by_table[fqn] = ent.model_copy(
                update={"columns": ent.columns + extra, "description": desc}
            )
        else:
            used: set[str] = {e.name for e in by_table.values()}
            name = _derive_entity_name(usage.table, usage.schema_name, usage.catalog, used)
            cols = [
                Column(name=c, type="unknown", description="seen in customer sample SQL")
                for c in usage.columns_used[:50]
            ]
            by_table[fqn] = Entity(
                name=name,
                table=fqn,
                description=f"Used in {usage.query_count} customer sample queries",
                columns=cols,
            )

    return list(by_table.values())
