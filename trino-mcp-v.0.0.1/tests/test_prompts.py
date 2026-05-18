"""Tests for MCP server instructions loader."""

from __future__ import annotations

from prompts.loader import build_server_instructions, load_trino_sme


def test_load_trino_sme_contains_federation():
    text = load_trino_sme()
    assert "catalog.schema.table" in text
    assert "fully qualified" in text.lower()


def test_build_server_instructions_includes_runtime():
    from tools.context import build_context

    inst = build_server_instructions(build_context())
    assert "customer sample queries" in inst
    assert "search_sample_queries" in inst
