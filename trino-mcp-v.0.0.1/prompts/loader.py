"""Load MCP server instructions (Trino SME + optional runtime context)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tools.context import ToolContext

_PROMPTS_DIR = Path(__file__).resolve().parent
_SME_PATH = _PROMPTS_DIR / "trino_sme.md"


def load_trino_sme() -> str:
    if not _SME_PATH.exists():
        return "You are a Trino SQL expert. Use fully qualified catalog.schema.table names."
    return _SME_PATH.read_text(encoding="utf-8").strip()


def build_server_instructions(ctx: Optional["ToolContext"] = None) -> str:
    """MCP `instructions` string — travels with the server to any MCP client."""
    parts = [load_trino_sme()]

    if ctx is not None:
        runtime: list[str] = ["## This deployment"]
        if ctx.sample_catalog and ctx.sample_catalog.queries:
            n = len(ctx.sample_catalog.queries)
            runtime.append(
                f"- **{n} customer sample queries** loaded — call `search_sample_queries` "
                "before writing new SQL."
            )
            runtime.append("- Call `get_datasource_knowledge` for tables/columns/joins mined from those samples.")
        else:
            runtime.append(
                "- No sample query playbook (`samples/sample_queries.yaml` missing or empty)."
            )
        if ctx.overlay is not None:
            runtime.append("- Semantic **overlay** loaded (curated joins/metrics/glossary).")
        runtime.append(
            f"- Trino target: `{ctx.cfg.trino_scheme}://{ctx.cfg.trino_host}:{ctx.cfg.trino_port}` "
            f"as user `{ctx.cfg.trino_user}`."
        )
        parts.append("\n".join(runtime))

    return "\n\n".join(parts)
