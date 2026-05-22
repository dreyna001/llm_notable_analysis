"""Elasticsearch-dedicated retrieval grounding helpers.

This mirrors the SPL grounding path with a concrete Elastic-focused corpus for
index patterns, field mappings, timestamp fields, and approved query examples.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .config import Config

logger = logging.getLogger(__name__)

ELASTICSEARCH_GROUNDING_CONTEXT_HEADER = "ELASTICSEARCH_GROUNDING_CONTEXT"
ELASTICSEARCH_GROUNDING_FAILURE_MODES = {"suppress", "fallback_to_ungrounded"}


def elasticsearch_grounding_failure_mode(config: Config) -> str:
    """Return a supported failure mode for Elasticsearch query grounding."""
    mode = str(
        getattr(config, "ELASTICSEARCH_GROUNDING_FAILURE_MODE", "suppress")
        or "suppress"
    ).strip().lower()
    if mode not in ELASTICSEARCH_GROUNDING_FAILURE_MODES:
        logger.warning(
            "Unsupported ELASTICSEARCH_GROUNDING_FAILURE_MODE=%r; defaulting to suppress",
            mode,
        )
        return "suppress"
    return mode


def build_elasticsearch_grounding_rag_config(config: Config) -> Any:
    """Build a RAGConfig for the Elasticsearch-focused Postgres KB table."""
    from onprem_rag_notable_analysis.future.rag_config import RAGConfig

    max_snippets = int(getattr(config, "ELASTICSEARCH_GROUNDING_MAX_SNIPPETS", 4))
    context_budget = int(
        getattr(config, "ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS", 1600)
    )
    return RAGConfig(
        enabled=True,
        backend="postgres",
        fail_closed=True,
        postgres_dsn=getattr(config, "RAG_POSTGRES_DSN", ""),
        postgres_schema=getattr(config, "RAG_POSTGRES_SCHEMA", "notable_rag"),
        postgres_chunks_table=getattr(
            config,
            "ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE",
            "elasticsearch_query_chunks",
        ),
        postgres_fts_config=getattr(config, "RAG_POSTGRES_FTS_CONFIG", "english"),
        postgres_statement_timeout_ms=int(
            getattr(config, "RAG_POSTGRES_STATEMENT_TIMEOUT_MS", 5000)
        ),
        vector_dimensions=int(getattr(config, "RAG_VECTOR_DIMENSIONS", 768)),
        embedding_model_name=getattr(
            config, "RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"
        ),
        rerank_enabled=bool(getattr(config, "RAG_RERANK_ENABLED", False)),
        rerank_model_name=getattr(config, "RAG_RERANK_MODEL", "BAAI/bge-reranker-base"),
        max_snippets_120b=max_snippets,
        max_snippets_20b=max_snippets,
        context_budget_chars_120b=context_budget,
        context_budget_chars_20b=context_budget,
        fused_rank_limit_120b=int(getattr(config, "RAG_FUSED_RANK_LIMIT_120B", 8)),
        fused_rank_limit_20b=int(getattr(config, "RAG_FUSED_RANK_LIMIT_20B", 6)),
        near_duplicate_similarity_threshold=float(
            getattr(config, "RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD", 0.80)
        ),
        lexical_top_k=int(getattr(config, "RAG_LEXICAL_TOP_K", 30)),
        vector_top_k=int(getattr(config, "RAG_VECTOR_TOP_K", 30)),
        candidate_pool_limit=int(getattr(config, "RAG_CANDIDATE_POOL_LIMIT", 40)),
        rrf_k=int(getattr(config, "RAG_RRF_K", 60)),
        context_header=ELASTICSEARCH_GROUNDING_CONTEXT_HEADER,
    )


def init_elasticsearch_grounding_provider(config: Config) -> Optional[Any]:
    """Initialize the optional Elasticsearch-focused retrieval provider."""
    if not bool(getattr(config, "ELASTICSEARCH_GROUNDING_ENABLED", False)):
        return None
    try:
        from onprem_rag_notable_analysis.future.postgres_retrieval import (
            PostgresRAGContextProvider,
        )

        rag_config = build_elasticsearch_grounding_rag_config(config)
        provider = PostgresRAGContextProvider.from_config(rag_config)
        if provider is None:
            logger.warning(
                "Elasticsearch grounding is enabled but provider setup was skipped."
            )
        else:
            logger.info(
                "Elasticsearch grounding provider enabled with postgres schema=%s table=%s",
                rag_config.postgres_schema,
                rag_config.postgres_chunks_table,
            )
        return provider
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to initialize Elasticsearch grounding provider: %s", exc)
        return None


def build_elasticsearch_grounding_query(
    *, alert_text: str, hypotheses: List[Dict[str, Any]]
) -> str:
    """Build retrieval query text for the Elasticsearch-focused KB."""
    normalized_hypotheses = []
    for item in hypotheses:
        if not isinstance(item, dict):
            continue
        normalized_hypotheses.append(
            {
                "hypothesis_type": str(item.get("hypothesis_type", "")).strip(),
                "hypothesis": str(item.get("hypothesis", "")).strip(),
                "best_pivots": item.get("best_pivots", []),
            }
        )
    return "\n\n".join(
        part
        for part in (
            "SECURITY ALERT INPUT:",
            alert_text,
            "COMPETING HYPOTHESES:",
            json.dumps(normalized_hypotheses, ensure_ascii=True),
        )
        if str(part).strip()
    )


def build_elasticsearch_grounding_context(
    *,
    provider: Any,
    config: Config,
    alert_text: str,
    hypotheses: List[Dict[str, Any]],
) -> str:
    """Build the rendered ELASTICSEARCH_GROUNDING_CONTEXT block."""
    query_text = build_elasticsearch_grounding_query(
        alert_text=alert_text,
        hypotheses=hypotheses,
    )
    return provider.build_context(
        alert_text=query_text,
        llm_model_name=getattr(config, "LLM_MODEL_NAME", "gemma-4-31B-it"),
    )
