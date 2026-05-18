"""Tests for sql_knowledge — mining sample SQL."""
from __future__ import annotations

from pathlib import Path

import yaml

from sample_queries import SampleQueryCatalog
from sql_knowledge import (
    build_datasource_knowledge,
    extract_column_names,
    extract_join_conditions,
    extract_qualified_tables,
    overlay_from_knowledge,
)

SAMPLE_YAML = Path(__file__).resolve().parents[1] / "samples" / "sample_queries.yaml"


def test_extract_quoted_fqn():
    sql = 'select * from "hive"."01_stg"."stg_open_po_summary" where vendor_number > 1'
    assert extract_qualified_tables(sql) == ["hive.01_stg.stg_open_po_summary"]


def test_extract_columns_from_sample():
    sql = (
        "select cat_po_aging, count(distinct vendor_number) "
        'from "hive"."01_stg"."stg_open_po_summary" group by cat_po_aging'
    )
    cols = extract_column_names(sql)
    assert "cat_po_aging" in cols
    assert "vendor_number" in cols


def test_build_knowledge_from_repo_samples():
    if not SAMPLE_YAML.exists():
        return
    catalog = SampleQueryCatalog(**yaml.safe_load(SAMPLE_YAML.read_text()))
    knowledge = build_datasource_knowledge(catalog)
    assert knowledge.query_count == len(catalog.queries)
    assert knowledge.primary_table_fqn == "hive.01_stg.stg_open_po_summary"
    assert knowledge.catalogs["hive"]["schemas"]["01_stg"]["tables"]
    table = knowledge.tables[0]
    assert table.query_count >= 1
    assert "vendor_number" in table.columns_used or "vendor_name" in table.columns_used


def test_overlay_from_knowledge_has_aliases():
    catalog = SampleQueryCatalog(
        queries=[
            {
                "id": "q1",
                "question": "count vendors",
                "sql": 'select count(*) from "hive"."01_stg"."stg_open_po_summary"',
                "category": "PO",
            }
        ]
    )
    knowledge = build_datasource_knowledge(catalog)
    overlay = overlay_from_knowledge(knowledge)
    assert "stg_open_po_summary" in overlay.entity_aliases
    assert overlay.entity_aliases["stg_open_po_summary"] == "hive.01_stg.stg_open_po_summary"
