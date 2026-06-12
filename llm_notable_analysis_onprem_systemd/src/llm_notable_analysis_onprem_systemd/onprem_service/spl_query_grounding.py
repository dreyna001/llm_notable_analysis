"""SPL-dedicated retrieval grounding helpers.

This module keeps the SPL-specific KB path concrete and narrow: it reuses the
existing Postgres/pgvector retrieval provider, but points it at a separate table
and renders a separate prompt block for the SPL-generation call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .config import Config

logger = logging.getLogger(__name__)

SPL_QUERY_GROUNDING_CONTEXT_HEADER = "SPL_QUERY_GROUNDING_CONTEXT"
SPL_QUERY_RAG_FAILURE_MODES = {"suppress", "fallback_to_ungrounded"}


def spl_query_rag_failure_mode(config: Config) -> str:
    """Return a supported failure mode for SPL-query RAG."""
    mode = str(
        getattr(config, "SPL_QUERY_RAG_FAILURE_MODE", "suppress") or "suppress"
    ).strip().lower()
    if mode not in SPL_QUERY_RAG_FAILURE_MODES:
        logger.warning(
            "Unsupported SPL_QUERY_RAG_FAILURE_MODE=%r; defaulting to suppress",
            mode,
        )
        return "suppress"
    return mode


def build_spl_query_rag_config(config: Config) -> Any:
    """Build a RAGConfig for the SPL-dedicated Postgres KB table."""
    from onprem_rag_notable_analysis.future.rag_config import RAGConfig

    max_snippets = int(getattr(config, "SPL_QUERY_RAG_MAX_SNIPPETS", 4))
    context_budget = int(getattr(config, "SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS", 1600))
    return RAGConfig(
        enabled=True,
        backend="postgres",
        # Force provider errors to surface so the caller can apply the explicit
        # SPL_QUERY_RAG_FAILURE_MODE instead of silently producing ungrounded SPL.
        fail_closed=True,
        postgres_dsn=getattr(config, "RAG_POSTGRES_DSN", ""),
        postgres_schema=getattr(config, "RAG_POSTGRES_SCHEMA", "notable_rag"),
        postgres_chunks_table=getattr(
            config,
            "SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE",
            "spl_query_chunks",
        ),
        postgres_fts_config=getattr(config, "RAG_POSTGRES_FTS_CONFIG", "english"),
        postgres_statement_timeout_ms=int(
            getattr(config, "RAG_POSTGRES_STATEMENT_TIMEOUT_MS", 5000)
        ),
        vector_dimensions=int(getattr(config, "RAG_VECTOR_DIMENSIONS", 1024)),
        embedding_model_name=getattr(
            config, "RAG_EMBEDDING_MODEL", "mixedbread-ai/mxbai-embed-large-v1"
        ),
        rerank_enabled=bool(getattr(config, "RAG_RERANK_ENABLED", False)),
        rerank_model_name=getattr(
            config, "RAG_RERANK_MODEL", "mixedbread-ai/mxbai-rerank-large-v2"
        ),
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
        context_header=SPL_QUERY_GROUNDING_CONTEXT_HEADER,
    )


def init_spl_query_rag_provider(config: Config) -> Optional[Any]:
    """Initialize the optional SPL-dedicated Postgres retrieval provider."""
    if not bool(getattr(config, "SPL_QUERY_RAG_ENABLED", False)):
        return None
    try:
        from onprem_rag_notable_analysis.future.postgres_retrieval import (
            PostgresRAGContextProvider,
        )

        rag_config = build_spl_query_rag_config(config)
        provider = PostgresRAGContextProvider.from_config(rag_config)
        if provider is None:
            logger.warning("SPL query RAG is enabled but provider setup was skipped.")
        else:
            logger.info(
                "SPL query RAG provider enabled with postgres schema=%s table=%s",
                rag_config.postgres_schema,
                rag_config.postgres_chunks_table,
            )
        return provider
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to initialize SPL query RAG provider: %s", exc)
        return None


def build_spl_query_grounding_query(
    *, alert_text: str, hypotheses: List[Dict[str, Any]]
) -> str:
    """Build retrieval query text for the SPL-focused KB."""
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


def build_spl_query_grounding_context(
    *,
    provider: Any,
    config: Config,
    alert_text: str,
    hypotheses: List[Dict[str, Any]],
) -> str:
    """Build the rendered SPL_QUERY_GROUNDING_CONTEXT block."""
    query_text = build_spl_query_grounding_query(
        alert_text=alert_text,
        hypotheses=hypotheses,
    )
    return provider.build_context(
        alert_text=query_text,
        llm_model_name=getattr(config, "LLM_MODEL_NAME", "gemma-4-31B-it"),
    )

