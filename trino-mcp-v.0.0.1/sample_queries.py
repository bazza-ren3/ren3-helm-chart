"""Customer sample questions + SQL — loaded from YAML for MCP tools."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bundled playbook (update via scripts/import_sample_queries_xlsx.py).
DEFAULT_SAMPLE_QUERIES_FILE = Path(__file__).resolve().parent / "samples" / "sample_queries.yaml"


class SampleQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    sql: str
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class SampleQueryCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    source: str = ""
    queries: list[SampleQuery] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> SampleQueryCatalog:
        ids = [q.id for q in self.queries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate sample query ids are not allowed")
        return self


def load_builtin_sample_queries() -> Optional[SampleQueryCatalog]:
    """Load the repo's samples/sample_queries.yaml."""
    return load_sample_queries(DEFAULT_SAMPLE_QUERIES_FILE)


def load_sample_queries(path: Optional[Path]) -> Optional[SampleQueryCatalog]:
    """Load and validate. Returns None if path is None or file is missing."""
    if path is None or not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise ValueError("sample queries root must be a YAML mapping")
    return SampleQueryCatalog(**raw)


def list_sample_queries(
    catalog: SampleQueryCatalog, category: str | None = None
) -> list[dict[str, Any]]:
    items = catalog.queries
    if category:
        needle = category.strip().lower()
        items = [q for q in items if q.category.lower() == needle]
    return [
        {
            "id": q.id,
            "question": q.question,
            "category": q.category,
            "tags": q.tags,
        }
        for q in items
    ]


def get_sample_query(catalog: SampleQueryCatalog, query_id: str) -> dict[str, Any]:
    for q in catalog.queries:
        if q.id == query_id:
            return {
                "id": q.id,
                "question": q.question,
                "sql": q.sql,
                "category": q.category,
                "tags": q.tags,
                "notes": q.notes,
            }
    return {"error": f"unknown sample query id: {query_id!r}"}


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"\W+", text.lower()) if len(t) > 1]


def search_sample_queries(catalog: SampleQueryCatalog, term: str, limit: int = 10) -> dict[str, Any]:
    needle = term.strip().lower()
    if not needle:
        return {"matches": []}

    tokens = _tokenize(needle)
    scored: list[tuple[int, SampleQuery]] = []

    for q in catalog.queries:
        hay = f"{q.question} {q.category} {' '.join(q.tags)} {q.notes}".lower()
        score = 0
        if needle in q.question.lower():
            score += 100
        if needle in hay:
            score += 40
        for tok in tokens:
            if tok in hay:
                score += 5
        if score > 0:
            scored.append((score, q))

    scored.sort(key=lambda x: (-x[0], x[1].id))
    matches = [
        {
            "id": q.id,
            "question": q.question,
            "category": q.category,
            "score": score,
            "sql_preview": _sql_preview(q.sql),
        }
        for score, q in scored[:limit]
    ]
    return {"matches": matches}


def _sql_preview(sql: str, max_len: int = 120) -> str:
    one_line = " ".join(sql.split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 3] + "..."
