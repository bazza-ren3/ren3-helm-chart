"""Shared runtime state for MCP tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from config import Config
import sample_queries
import semantic_layer

if TYPE_CHECKING:
    from sample_queries import SampleQueryCatalog

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    cfg: Config
    overlay: Optional[semantic_layer.Overlay]
    sample_catalog: Optional["SampleQueryCatalog"]
    semantic_cache: semantic_layer.SemanticModelCache


def build_context() -> ToolContext:
    cfg = Config()

    overlay = semantic_layer.load_overlay(cfg.semantic_overlay_path)
    if overlay is not None:
        logger.info("Loaded semantic overlay from %s", cfg.semantic_overlay_path)
    else:
        logger.info("No semantic overlay (SEMANTIC_OVERLAY_PATH unset or file missing)")

    catalog = sample_queries.load_builtin_sample_queries()
    if catalog is not None:
        logger.info(
            "Loaded %d sample queries from %s",
            len(catalog.queries),
            sample_queries.DEFAULT_SAMPLE_QUERIES_FILE,
        )
    else:
        logger.info(
            "No sample queries at %s",
            sample_queries.DEFAULT_SAMPLE_QUERIES_FILE,
        )

    cache = semantic_layer.SemanticModelCache(cfg, overlay, catalog)
    return ToolContext(cfg=cfg, overlay=overlay, sample_catalog=catalog, semantic_cache=cache)
