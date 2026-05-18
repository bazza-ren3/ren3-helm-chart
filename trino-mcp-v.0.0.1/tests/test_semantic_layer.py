"""Unit tests for semantic_layer — introspection + overlay merge."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from semantic_layer import (
    Entity,
    Metric,
    Overlay,
    Relationship,
    SemanticModel,
    SemanticModelCache,
    build_introspected_entities,
    describe_entity,
    get_metric_sql,
    get_relationships,
    list_entities,
    list_metrics,
    load_overlay,
    merge_overlay,
    resolve_term,
)


def _write_overlay(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "overlay.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


def test_load_overlay_minimal(tmp_path: Path):
    p = _write_overlay(
        tmp_path,
        {"version": 1, "entity_aliases": {}, "relationships": [], "metrics": [], "glossary": []},
    )
    o = load_overlay(p)
    assert o is not None
    assert o.relationships == []


def test_load_overlay_missing_returns_none(tmp_path: Path):
    assert load_overlay(tmp_path / "nope.yaml") is None
    assert load_overlay(None) is None


def test_merge_overlay_applies_aliases():
    entities = [Entity(name="orders", table="lake.retail.orders", columns=[])]
    overlay = Overlay(
        entity_aliases={"order": "lake.retail.orders"},
        relationships=[],
        metrics=[],
        glossary=[],
    )
    model = merge_overlay(entities, overlay)
    names = {e.name for e in model.entities}
    assert "orders" in names
    assert "order" in names


def test_merge_overlay_filters_unknown_relationship():
    entities = [Entity(name="a", table="c.s.t", columns=[])]
    overlay = Overlay(
        relationships=[
            Relationship(
                name="r1",
                from_entity="a",
                to_entity="ghost",
                join_type="many_to_one",
                condition="1=1",
            )
        ],
    )
    model = merge_overlay(entities, overlay)
    assert model.relationships == []


def test_build_introspected_entities_walk():
    from config import Config

    cfg = Config(trino_host="h", trino_user="u", trino_auth="none", trino_password="")
    with (
        patch("trino_client.run_select", return_value={"error": "no metadata"}),
        patch("trino_client.list_catalogs", return_value=[{"name": "crm"}]),
        patch("trino_client.list_schemas", return_value=["public"]),
        patch("trino_client.list_tables", return_value=["stores"]),
        patch(
            "trino_client.describe_table",
            return_value=[
                {"column": "id", "type": "integer", "extra": "", "comment": "pk"},
                {"column": "name", "type": "varchar", "extra": "", "comment": ""},
            ],
        ),
    ):
        entities = build_introspected_entities(cfg)
    assert len(entities) == 1
    assert entities[0].table == "crm.public.stores"
    assert entities[0].name == "stores"
    assert entities[0].primary_key == "id"


def test_describe_entity_with_overlay_relationships():
    model = SemanticModel(
        entities=[
            Entity(name="a", table="c1.s1.t1", columns=[]),
            Entity(name="b", table="c2.s2.t2", columns=[]),
        ],
        relationships=[
            Relationship(
                name="ab",
                from_entity="a",
                to_entity="b",
                join_type="many_to_one",
                condition="c1.s1.t1.id = c2.s2.t2.a_id",
            ),
        ],
        status="ready",
    )
    d = describe_entity(model, "b")
    assert d["name"] == "b"
    assert any(r["other_entity"] == "a" and r["direction"] == "in" for r in d["relationships"])


def test_get_metric_sql_and_resolve_term():
    model = SemanticModel(
        entities=[Entity(name="orders", table="lake.retail.orders", columns=[])],
        metrics=[Metric(name="revenue", base_entity="orders", expression="SUM(amount)")],
        glossary=[],
        status="ready",
    )
    out = get_metric_sql(model, "revenue")
    assert out["expression"] == "SUM(amount)"
    r = resolve_term(model, "revenue")
    assert any(m["kind"] == "metric" for m in r["matches"])


def test_list_entities_loading_state():
    model = SemanticModel(status="loading", status_message="in progress")
    out = list_entities(model)
    assert out["status"] == "loading"
    assert out["entities"] == []


def test_semantic_model_cache_uses_merge():
    from config import Config

    cfg = Config(trino_host="h", trino_user="u", trino_auth="none", trino_password="")
    overlay = Overlay(
        metrics=[Metric(name="m", base_entity="x", expression="COUNT(*)")],
    )

    with patch("semantic_layer.build_introspected_entities") as mock_build:
        mock_build.return_value = [Entity(name="x", table="a.b.c", columns=[])]
        cache = SemanticModelCache(cfg, overlay)
        model = cache.get()
        assert model.status == "ready"
        assert len(model.entities) == 1
        assert len(model.metrics) == 1


def test_get_relationships_unknown_entity():
    model = SemanticModel(
        entities=[Entity(name="a", table="c.s.t", columns=[])],
        status="ready",
    )
    result = get_relationships(model, "ghost")
    assert "error" in result


def test_list_metrics_roundtrip():
    model = SemanticModel(
        entities=[Entity(name="x", table="a.b.c", columns=[])],
        metrics=[Metric(name="m", description="dm", base_entity="x", expression="SUM(1)")],
        status="ready",
    )
    assert list_metrics(model) == [{"name": "m", "description": "dm", "base_entity": "x"}]
