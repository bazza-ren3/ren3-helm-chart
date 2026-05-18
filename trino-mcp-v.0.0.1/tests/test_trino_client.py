"""Unit tests for trino_client.py — all Trino calls are mocked."""
import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Set required env vars before importing config/trino_client
os.environ.setdefault("TRINO_HOST", "localhost")
os.environ.setdefault("TRINO_USER", "test")
os.environ.setdefault("TRINO_PASSWORD", "test")

from config import Config
from trino_client import describe_table, execute_query, list_catalogs, list_schemas, list_tables


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(**overrides: Any) -> Config:
    defaults = {
        "trino_host": "localhost",
        "trino_user": "test",
        "trino_password": "secret",
        "trino_auth": "basic",
        "trino_scheme": "https",
        "trino_verify": True,
        "trino_max_rows": 10,
        "trino_default_catalog": None,
        "trino_default_schema": None,
        "catalog_descriptions_raw": "{}",
    }
    defaults.update(overrides)
    return Config(**defaults)


def mock_cursor(rows: list[list[Any]], description: list[tuple] | None = None) -> MagicMock:
    """Return a mock cursor that yields the given rows.

    Wires both `fetchall` (used by list_/describe_ helpers) and `fetchmany`
    (used by execute_query's streaming path) so tests cover either codepath.
    """
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.fetchmany.side_effect = lambda n: rows[:n]
    if description is not None:
        cur.description = description
    return cur


def mock_conn(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    def test_basic_auth_requires_password(self):
        with pytest.raises(Exception, match="TRINO_PASSWORD"):
            Config(
                trino_host="h",
                trino_user="u",
                trino_password="",
                trino_auth="basic",
            )

    def test_jwt_auth_requires_token(self):
        with pytest.raises(Exception, match="TRINO_JWT_TOKEN"):
            Config(
                trino_host="h",
                trino_user="u",
                trino_password="",
                trino_auth="jwt",
                trino_jwt_token="",
            )

    def test_invalid_auth_type(self):
        with pytest.raises(Exception, match="TRINO_AUTH"):
            Config(
                trino_host="h",
                trino_user="u",
                trino_password="p",
                trino_auth="oauth",
            )

    def test_none_auth_requires_no_password(self):
        cfg = Config(
            trino_host="h",
            trino_user="u",
            trino_auth="none",
            trino_password="",
        )
        assert cfg.trino_auth == "none"

    def test_verify_true(self):
        cfg = make_config(trino_verify="true")
        assert cfg.trino_verify is True

    def test_verify_false(self):
        cfg = make_config(trino_verify="false")
        assert cfg.trino_verify is False

    def test_verify_ca_path(self):
        cfg = make_config(trino_verify="/etc/ssl/ca.crt")
        assert cfg.trino_verify == "/etc/ssl/ca.crt"

    def test_catalog_descriptions_valid(self):
        # Use CATALOG_DESCRIPTIONS alias (the documented env var name)
        cfg = Config(
            trino_host="h",
            trino_user="u",
            trino_auth="none",
            CATALOG_DESCRIPTIONS='{"hive": "data lake"}',
        )
        assert cfg.catalog_descriptions == {"hive": "data lake"}

    def test_catalog_descriptions_via_field_name(self):
        cfg = make_config(catalog_descriptions_raw='{"hive": "data lake"}')
        assert cfg.catalog_descriptions == {"hive": "data lake"}

    def test_catalog_descriptions_invalid_json_falls_back(self):
        cfg = make_config(catalog_descriptions_raw="not valid json")
        assert cfg.catalog_descriptions == {}

    def test_catalog_descriptions_non_dict_falls_back(self):
        cfg = make_config(catalog_descriptions_raw='["a", "b"]')
        assert cfg.catalog_descriptions == {}

    def test_catalog_descriptions_missing_falls_back(self):
        cfg = make_config(catalog_descriptions_raw="{}")
        assert cfg.catalog_descriptions == {}


# ---------------------------------------------------------------------------
# get_connection tests
# ---------------------------------------------------------------------------


class TestGetConnection:
    @patch("trino_client.trino.dbapi.connect")
    def test_none_auth_does_not_pass_auth_kwarg(self, mock_connect):
        cfg = Config(
            trino_host="localhost",
            trino_user="admin",
            trino_auth="none",
            trino_scheme="http",
            trino_verify=False,
        )
        from trino_client import get_connection

        get_connection(cfg)
        call_kwargs = mock_connect.call_args.kwargs
        assert "auth" not in call_kwargs

    @patch("trino_client.trino.dbapi.connect")
    def test_basic_auth_passes_auth_kwarg(self, mock_connect):
        cfg = make_config()
        from trino_client import get_connection

        get_connection(cfg)
        call_kwargs = mock_connect.call_args.kwargs
        assert "auth" in call_kwargs


# ---------------------------------------------------------------------------
# list_catalogs tests
# ---------------------------------------------------------------------------


class TestListCatalogs:
    @patch("trino_client.get_connection")
    def test_returns_catalogs_with_descriptions(self, mock_get_conn):
        cfg = make_config(catalog_descriptions_raw='{"hive": "S3 lake", "pg": "CRM"}')
        cur = mock_cursor([["hive"], ["pg"], ["iceberg"]])
        mock_get_conn.return_value = mock_conn(cur)

        result = list_catalogs(cfg)

        assert result == [
            {"name": "hive", "description": "S3 lake"},
            {"name": "pg", "description": "CRM"},
            {"name": "iceberg", "description": ""},
        ]

    @patch("trino_client.get_connection")
    def test_returns_empty_descriptions_when_not_configured(self, mock_get_conn):
        cfg = make_config(catalog_descriptions_raw="{}")
        cur = mock_cursor([["hive"]])
        mock_get_conn.return_value = mock_conn(cur)

        result = list_catalogs(cfg)
        assert result == [{"name": "hive", "description": ""}]


# ---------------------------------------------------------------------------
# list_schemas / list_tables tests
# ---------------------------------------------------------------------------


class TestListSchemas:
    @patch("trino_client.get_connection")
    def test_returns_schema_names(self, mock_get_conn):
        cur = mock_cursor([["sales"], ["finance"]])
        mock_get_conn.return_value = mock_conn(cur)

        result = list_schemas(make_config(), "hive")

        assert result == ["sales", "finance"]
        cur.execute.assert_called_once_with('SHOW SCHEMAS FROM "hive"')

    @patch("trino_client.get_connection")
    def test_identifiers_are_quoted(self, mock_get_conn):
        cur = mock_cursor([])
        mock_get_conn.return_value = mock_conn(cur)

        list_schemas(make_config(), "my-catalog")
        cur.execute.assert_called_once_with('SHOW SCHEMAS FROM "my-catalog"')


class TestListTables:
    @patch("trino_client.get_connection")
    def test_returns_table_names(self, mock_get_conn):
        cur = mock_cursor([["orders"], ["customers"]])
        mock_get_conn.return_value = mock_conn(cur)

        result = list_tables(make_config(), "hive", "sales")

        assert result == ["orders", "customers"]
        cur.execute.assert_called_once_with('SHOW TABLES FROM "hive"."sales"')


# ---------------------------------------------------------------------------
# describe_table tests
# ---------------------------------------------------------------------------


class TestDescribeTable:
    @patch("trino_client.get_connection")
    def test_returns_column_metadata(self, mock_get_conn):
        cur = mock_cursor([
            ["region", "VARCHAR", "", ""],
            ["amount", "DOUBLE", "", "sales amount"],
        ])
        mock_get_conn.return_value = mock_conn(cur)

        result = describe_table(make_config(), "hive", "sales", "orders")

        assert result == [
            {"column": "region", "type": "VARCHAR", "extra": "", "comment": ""},
            {"column": "amount", "type": "DOUBLE", "extra": "", "comment": "sales amount"},
        ]
        cur.execute.assert_called_once_with('DESCRIBE "hive"."sales"."orders"')


# ---------------------------------------------------------------------------
# execute_query tests
# ---------------------------------------------------------------------------


class TestExecuteQuery:
    @patch("trino_client.get_connection")
    def test_select_query_succeeds(self, mock_get_conn):
        cur = mock_cursor(
            [["East", 1000.0], ["West", 2000.0]],
            description=[("region", None, None, None, None, None, None),
                         ("total", None, None, None, None, None, None)],
        )
        mock_get_conn.return_value = mock_conn(cur)

        result = execute_query(make_config(), "SELECT region, SUM(amount) FROM t GROUP BY region")

        assert result["row_count"] == 2
        assert result["rows"] == [{"region": "East", "total": 1000.0},
                                   {"region": "West", "total": 2000.0}]
        assert result["truncated"] is False

    def test_non_select_is_blocked(self):
        result = execute_query(make_config(), "INSERT INTO t VALUES (1)")
        assert "error" in result
        assert "SELECT" in result["error"]

    def test_non_select_case_insensitive_allows_select(self):
        # "select" lowercase should still be allowed
        with patch("trino_client.get_connection") as mock_get_conn:
            cur = mock_cursor([], description=[])
            mock_get_conn.return_value = mock_conn(cur)
            result = execute_query(make_config(), "select * from t")
        assert "error" not in result

    def test_non_select_with_leading_whitespace(self):
        with patch("trino_client.get_connection") as mock_get_conn:
            cur = mock_cursor([], description=[])
            mock_get_conn.return_value = mock_conn(cur)
            result = execute_query(make_config(), "  SELECT * FROM t")
        assert "error" not in result

    def test_drop_is_blocked(self):
        result = execute_query(make_config(), "DROP TABLE t")
        assert "error" in result

    @patch("trino_client.get_connection")
    def test_limit_appended_when_absent(self, mock_get_conn):
        cur = mock_cursor([], description=[])
        mock_get_conn.return_value = mock_conn(cur)
        cfg = make_config(trino_max_rows=50)

        execute_query(cfg, "SELECT * FROM t")

        called_sql = cur.execute.call_args[0][0]
        assert "LIMIT 50" in called_sql.upper()

    @patch("trino_client.get_connection")
    def test_limit_not_appended_when_present(self, mock_get_conn):
        cur = mock_cursor([], description=[])
        mock_get_conn.return_value = mock_conn(cur)

        execute_query(make_config(), "SELECT * FROM t LIMIT 5")

        called_sql = cur.execute.call_args[0][0]
        # Should not have a second LIMIT
        assert called_sql.upper().count("LIMIT") == 1

    @patch("trino_client.get_connection")
    def test_limit_case_insensitive_detection(self, mock_get_conn):
        cur = mock_cursor([], description=[])
        mock_get_conn.return_value = mock_conn(cur)

        execute_query(make_config(), "select * from t limit 5")

        called_sql = cur.execute.call_args[0][0]
        assert called_sql.lower().count("limit") == 1

    @patch("trino_client.get_connection")
    def test_truncated_flag_false_when_below_max(self, mock_get_conn):
        cur = mock_cursor(
            [["a"], ["b"]],
            description=[("col", None, None, None, None, None, None)],
        )
        mock_get_conn.return_value = mock_conn(cur)
        cfg = make_config(trino_max_rows=10)

        result = execute_query(cfg, "SELECT col FROM t")
        assert result["truncated"] is False

    @patch("trino_client.get_connection")
    def test_truncated_flag_true_when_exceeds_max(self, mock_get_conn):
        # 11 rows returned from Trino, max=10 → truncated=True, only 10 returned
        rows = [["x"]] * 11
        cur = mock_cursor(
            rows,
            description=[("col", None, None, None, None, None, None)],
        )
        mock_get_conn.return_value = mock_conn(cur)
        cfg = make_config(trino_max_rows=10)

        result = execute_query(cfg, "SELECT col FROM t")
        assert result["truncated"] is True
        assert result["row_count"] == 10

    @patch("trino_client.get_connection")
    def test_max_rows_enforced_even_when_sql_has_explicit_limit(self, mock_get_conn):
        # SQL says LIMIT 1000 but max_rows=5 — we still cap at 5
        rows = [["x"]] * 10
        cur = mock_cursor(
            rows,
            description=[("col", None, None, None, None, None, None)],
        )
        mock_get_conn.return_value = mock_conn(cur)
        cfg = make_config(trino_max_rows=5)

        result = execute_query(cfg, "SELECT col FROM t LIMIT 1000")
        assert result["truncated"] is True
        assert result["row_count"] == 5

    @patch("trino_client.get_connection")
    def test_fetch_never_materializes_beyond_cap(self, mock_get_conn):
        # DoS guard: even when the caller writes LIMIT 1_000_000 and Trino
        # would happily stream a million rows, we must only pull max_rows + 1.
        cur = mock_cursor(
            [["x"]] * 1_000_000,
            description=[("col", None, None, None, None, None, None)],
        )
        mock_get_conn.return_value = mock_conn(cur)
        cfg = make_config(trino_max_rows=10)

        result = execute_query(cfg, "SELECT col FROM t LIMIT 1000000")

        cur.fetchall.assert_not_called()
        cur.fetchmany.assert_called_once_with(11)
        assert result["truncated"] is True
        assert result["row_count"] == 10

    @patch("trino_client.get_connection")
    def test_duplicate_column_names_are_deduped(self, mock_get_conn):
        # Cross-catalog join: both tables have an "id" column
        cur = mock_cursor(
            [[1, 99]],
            description=[("id", None, None, None, None, None, None),
                         ("id", None, None, None, None, None, None)],
        )
        mock_get_conn.return_value = mock_conn(cur)

        result = execute_query(make_config(), "SELECT c.id, o.id FROM crm.customers c JOIN orders o ON c.id = o.customer_id")
        assert result["rows"] == [{"id": 1, "id_1": 99}]

    def test_cte_with_select_is_allowed(self):
        with patch("trino_client.get_connection") as mock_get_conn:
            cur = mock_cursor([], description=[])
            mock_get_conn.return_value = mock_conn(cur)
            result = execute_query(make_config(), "WITH regional AS (SELECT region FROM t) SELECT * FROM regional")
        assert "error" not in result

    def test_with_keyword_lowercase_is_allowed(self):
        with patch("trino_client.get_connection") as mock_get_conn:
            cur = mock_cursor([], description=[])
            mock_get_conn.return_value = mock_conn(cur)
            result = execute_query(make_config(), "with cte as (select 1) select * from cte")
        assert "error" not in result

    @patch("trino_client.get_connection")
    def test_trino_query_error_returns_error_dict(self, mock_get_conn):
        from trino.exceptions import TrinoQueryError

        cur = MagicMock()
        cur.execute.side_effect = TrinoQueryError(
            {"errorCode": 1, "errorName": "SYNTAX_ERROR", "message": "bad SQL", "errorType": "USER_ERROR"}
        )
        mock_get_conn.return_value = mock_conn(cur)

        result = execute_query(make_config(), "SELECT * FROM nonexistent")
        assert "error" in result

    @patch("trino_client.get_connection")
    def test_connection_error_returns_error_dict(self, mock_get_conn):
        from trino.exceptions import TrinoConnectionError

        conn = MagicMock()
        conn.cursor.side_effect = TrinoConnectionError("cannot connect")
        mock_get_conn.return_value = conn

        result = execute_query(make_config(), "SELECT 1")
        assert "error" in result
        assert "connect" in result["error"].lower()
