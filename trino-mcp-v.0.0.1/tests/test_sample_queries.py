"""Unit tests for sample_queries.py."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sample_queries import (
    SampleQueryCatalog,
    get_sample_query,
    list_sample_queries,
    load_sample_queries,
    search_sample_queries,
)


def _write_catalog(tmp_path: Path, queries: list[dict]) -> Path:
    p = tmp_path / "samples.yaml"
    p.write_text(
        yaml.safe_dump({"version": 1, "queries": queries}, sort_keys=False),
        encoding="utf-8",
    )
    return p


def test_load_and_list(tmp_path: Path):
    p = _write_catalog(
        tmp_path,
        [
            {
                "id": "q001",
                "question": "Revenue by region",
                "sql": "SELECT region, SUM(x) FROM t GROUP BY region",
                "category": "Sales",
            }
        ],
    )
    cat = load_sample_queries(p)
    assert cat is not None
    listed = list_sample_queries(cat)
    assert listed[0]["id"] == "q001"
    assert list_sample_queries(cat, category="sales")[0]["id"] == "q001"
    assert list_sample_queries(cat, category="inventory") == []


def test_get_and_search(tmp_path: Path):
    p = _write_catalog(
        tmp_path,
        [
            {
                "id": "q001",
                "question": "Top stores by foot traffic",
                "sql": "SELECT id FROM stores ORDER BY foot_traffic DESC",
            },
            {
                "id": "q002",
                "question": "Inventory below reorder",
                "sql": "SELECT sku FROM inventory WHERE on_hand < reorder_level",
            },
        ],
    )
    cat = load_sample_queries(p)
    assert cat is not None
    full = get_sample_query(cat, "q002")
    assert "reorder" in full["sql"]
    assert get_sample_query(cat, "missing")["error"]

    hits = search_sample_queries(cat, "foot traffic")
    assert hits["matches"][0]["id"] == "q001"


def test_duplicate_ids_raise(tmp_path: Path):
    p = _write_catalog(
        tmp_path,
        [
            {"id": "dup", "question": "A", "sql": "SELECT 1"},
            {"id": "dup", "question": "B", "sql": "SELECT 2"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_sample_queries(p)


def test_load_missing_returns_none(tmp_path: Path):
    assert load_sample_queries(tmp_path / "nope.yaml") is None
    assert load_sample_queries(None) is None
