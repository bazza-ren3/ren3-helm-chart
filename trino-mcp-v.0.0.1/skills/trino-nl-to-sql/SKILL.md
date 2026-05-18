---
name: trino-nl-to-sql
description: >-
  Natural language to SQL via the Trino MCP server. Use when the user asks data
  questions against Trino/SEP, or when trino MCP tools are available.
---

# Trino MCP — Natural Language to SQL

Use this skill when answering data questions via the Trino MCP server.

**Trino SQL dialect & federation rules** live in the MCP server's `instructions` (`prompts/trino_sme.md`) — clients that support MCP server instructions get that automatically. This skill covers **which tools to call and in what order**.

## Tool priority

1. **`search_sample_queries`** — customer playbook; highest priority. On match → **`get_sample_query`** → adapt SQL → verify with **`describe_entity`** → **`execute_query`**.
2. **`get_datasource_knowledge`** — catalogs/tables/columns/joins extracted from sample SQL (what the customer actually uses).
3. **`resolve_term`** + **`list_entities`** — business vocabulary, glossary from samples + introspection.
4. **`get_relationships`** / **`get_metric_sql`** — joins from sample SQL + overlay.
5. **`describe_entity`** — introspected columns + **`from_sample_queries`** (columns_used_in_samples, sample_query_ids).
6. **`list_catalogs`** / **`describe_table`** — only for tables missing from **`list_entities`**.

## Workflow

```
User question
  → search_sample_queries(phrase)
  → if hit: get_sample_query(id), adapt, execute_query
  → else: resolve_term → describe_entity → get_relationships or join_hints
  → compose SELECT → execute_query
```

## Rules

- **SELECT only.** Never INSERT/UPDATE/DELETE/DROP.
- **Never invent table names.** Confirm via `list_entities` or `describe_table`.
- **Always show the SQL** you ran.
- Format results as a **markdown table**.
- If `list_entities` is empty or stale → call **`refresh_schema`**.
- If `list_entities` returns `"status": "loading"`, wait and retry or call **`refresh_schema`**.
- Adapt sample-query SQL to live catalog/schema names from introspection.
- Prefer overlay **`condition`** strings verbatim for joins; do not guess cross-catalog FKs.

## Connection

Configured via `.env` or env: `TRINO_HOST`, `TRINO_PORT`, `TRINO_SCHEME`, `TRINO_USER`, `TRINO_PASSWORD`, `TRINO_AUTH`, `TRINO_VERIFY`.

Optional: `SEMANTIC_OVERLAY_PATH`, `INTROSPECT_CATALOGS`, `INTROSPECT_EXCLUDE_SCHEMAS`. Sample playbook is always `samples/sample_queries.yaml` in the repo.
