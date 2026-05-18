"""
Trino client — thin wrapper around trino-python-client.

Data flow for a single tool call:
  get_connection(cfg)
       │
       ▼
  trino.dbapi.connect(host, auth, scheme, ...)
       │
       ├── list_catalogs()  → SHOW CATALOGS
       ├── list_schemas()   → SHOW SCHEMAS FROM "{catalog}"
       ├── list_tables()    → SHOW TABLES FROM "{catalog}"."{schema}"
       ├── describe_table() → DESCRIBE "{catalog}"."{schema}"."{table}"
       └── execute_query()  → SELECT check → LIMIT injection → execute

One connection per tool call (no pooling — MCP server is long-lived but low QPS).
"""
import logging
import re
from typing import Any

import trino
from trino.auth import BasicAuthentication, JWTAuthentication
from trino.exceptions import TrinoQueryError

try:
    import requests.exceptions as _req_exc

    _NETWORK_ERRORS = (_req_exc.Timeout, _req_exc.ConnectionError)
except ImportError:
    _NETWORK_ERRORS = ()

from config import Config

logger = logging.getLogger(__name__)

# Matches LIMIT anywhere in the query (case-insensitive, word boundary).
# Used to decide whether to append LIMIT {TRINO_MAX_ROWS}.
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------


def get_connection(cfg: Config) -> trino.dbapi.Connection:
    if cfg.trino_auth == "basic":
        auth = BasicAuthentication(cfg.trino_user, cfg.trino_password)
    elif cfg.trino_auth == "jwt":
        auth = JWTAuthentication(cfg.trino_jwt_token)
    else:
        auth = None  # "none" — no-auth Trino (local dev, trusted network)

    kwargs: dict[str, Any] = {
        "host": cfg.trino_host,
        "port": cfg.trino_port,
        "user": cfg.trino_user,
        "http_scheme": cfg.trino_scheme,
        "verify": cfg.trino_verify,
        "request_timeout": 30,
        # socket/connection timeout — NOT Trino query execution time.
        # Long queries hang until Trino's own query.max-execution-time fires.
    }
    if auth is not None:
        kwargs["auth"] = auth
    if cfg.trino_default_catalog:
        kwargs["catalog"] = cfg.trino_default_catalog
    if cfg.trino_default_schema:
        kwargs["schema"] = cfg.trino_default_schema

    return trino.dbapi.connect(**kwargs)


# ---------------------------------------------------------------------------
# Schema discovery tools
# ---------------------------------------------------------------------------


def list_catalogs(cfg: Config) -> list[dict[str, str]]:
    """Return all catalogs, merged with descriptions from CATALOG_DESCRIPTIONS."""
    descriptions = cfg.catalog_descriptions
    conn = get_connection(cfg)
    try:
        cur = conn.cursor()
        cur.execute("SHOW CATALOGS")
        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {"name": row[0], "description": descriptions.get(row[0], "")}
        for row in rows
    ]


def list_schemas(cfg: Config, catalog: str) -> list[str]:
    """Return schema names in the given catalog."""
    conn = get_connection(cfg)
    try:
        cur = conn.cursor()
        cur.execute(f'SHOW SCHEMAS FROM "{catalog}"')
        rows = cur.fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def list_tables(cfg: Config, catalog: str, schema: str) -> list[str]:
    """Return table names in the given catalog.schema."""
    conn = get_connection(cfg)
    try:
        cur = conn.cursor()
        cur.execute(f'SHOW TABLES FROM "{catalog}"."{schema}"')
        rows = cur.fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def describe_table(cfg: Config, catalog: str, schema: str, table: str) -> list[dict[str, str]]:
    """Return column metadata for the given table.

    Trino DESCRIBE returns: Column, Type, Extra, Comment.
    """
    conn = get_connection(cfg)
    try:
        cur = conn.cursor()
        cur.execute(f'DESCRIBE "{catalog}"."{schema}"."{table}"')
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {"column": row[0], "type": row[1], "extra": row[2], "comment": row[3]}
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


def execute_query(cfg: Config, sql: str) -> dict[str, Any]:
    """
    Execute a SQL query and return results.

    execute_query codepath:
      ┌─ SQL starts with SELECT? ─────────────────────────────────┐
      │ No  → return error (SELECT-only enforcement)              │
      │ Yes → inject LIMIT if absent                              │
      │          │                                                │
      │          ▼                                                │
      │       execute → fetchmany(max+1)                          │
      │          │                                                │
      │          ▼                                                │
      │       len ≤ max → truncated=False, return all             │
      │       len > max → truncated=True,  return first `max`     │
      │       TrinoQueryError → error dict                        │
      │       Network error  → error dict                         │
      └───────────────────────────────────────────────────────────┘

    Streaming note: `fetchmany(max_rows + 1)` caps result materialization at
    max_rows + 1 rows regardless of what the caller put in `LIMIT`. Trino
    stops producing once the cursor reads enough pages to satisfy the call.

    Returns:
        On success: {"rows": [...], "row_count": N, "truncated": bool}
        On error:   {"error": str, "error_code": str}  (or just "error" for network)
    """
    # Server-side SELECT enforcement — defense in depth beyond the system prompt.
    # Also allow WITH...SELECT (CTEs), which are read-only but start with "WITH".
    _normalized = sql.strip().upper()
    if not (_normalized.startswith("SELECT") or _normalized.startswith("WITH")):
        return {"error": "Only SELECT queries are allowed. Please rephrase your request."}

    # Inject LIMIT if no LIMIT clause present (regex is sufficient for LLM-generated SQL).
    if not _LIMIT_RE.search(sql):
        sql = f"{sql.rstrip().rstrip(';')} LIMIT {cfg.trino_max_rows}"

    conn = get_connection(cfg)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        # Stream at most max_rows + 1 so we can signal truncation without ever
        # materializing the full result set. The extra row is the truncation
        # sentinel; if the caller wrote `LIMIT 1_000_000`, we still only pull
        # max_rows + 1 from Trino.
        fetched = cur.fetchmany(cfg.trino_max_rows + 1)
        truncated = len(fetched) > cfg.trino_max_rows
        rows = fetched[: cfg.trino_max_rows]
        column_names = [desc[0] for desc in cur.description] if cur.description else []
        # Deduplicate column names for joins that return same label twice (e.g. SELECT c.id, o.id)
        seen: dict[str, int] = {}
        deduped: list[str] = []
        for col in column_names:
            if col in seen:
                seen[col] += 1
                deduped.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                deduped.append(col)
        result_rows = [dict(zip(deduped, row)) for row in rows]
        return {"rows": result_rows, "row_count": len(result_rows), "truncated": truncated}
    except TrinoQueryError as e:
        return {"error": str(e), "error_code": getattr(e, "error_code", "UNKNOWN")}
    except trino.exceptions.TrinoConnectionError as e:
        return {"error": f"Could not connect to Trino: {e}"}
    except Exception as e:  # noqa: BLE001 — catch network errors from requests
        if _NETWORK_ERRORS and isinstance(e, _NETWORK_ERRORS):
            return {"error": "Query timed out or connection dropped. Try a more specific WHERE clause."}
        raise
    finally:
        conn.close()


def run_select(cfg: Config, sql: str, max_rows: int = 50_000) -> dict[str, Any]:
    """Run a SELECT for internal introspection. Returns raw rows or an error dict."""
    _normalized = sql.strip().upper()
    if not (_normalized.startswith("SELECT") or _normalized.startswith("WITH")):
        return {"error": "Only SELECT queries are allowed."}

    conn = get_connection(cfg)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchmany(max_rows)
        return {"rows": rows, "columns": [d[0] for d in cur.description] if cur.description else []}
    except TrinoQueryError as e:
        return {"error": str(e), "error_code": getattr(e, "error_code", "UNKNOWN")}
    except trino.exceptions.TrinoConnectionError as e:
        return {"error": f"Could not connect to Trino: {e}"}
    except Exception as e:  # noqa: BLE001
        if _NETWORK_ERRORS and isinstance(e, _NETWORK_ERRORS):
            return {"error": "Query timed out or connection dropped."}
        raise
    finally:
        conn.close()
