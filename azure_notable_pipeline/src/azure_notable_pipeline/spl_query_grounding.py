"""SPL-dedicated Azure AI Search grounding helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .azure_search_retrieval import RetrievalResult, result_section, retrieve_grounding
from .config import Config

SPL_QUERY_GROUNDING_CONTEXT_HEADER = "SPL_QUERY_GROUNDING_CONTEXT"
SPL_QUERY_RAG_FAILURE_MODES = {"suppress", "fallback_to_ungrounded"}


@dataclass(frozen=True)
class SplGroundingResult:
    """Rendered SPL grounding context plus status metadata."""

    status: str
    context: str = ""
    snippet_count: int = 0
    message: str = ""


def spl_query_rag_failure_mode(config: Config) -> str:
    """Return a supported failure mode for SPL-query grounding."""

    mode = str(config.SPL_QUERY_RAG_FAILURE_MODE or "suppress").strip().lower()
    return mode if mode in SPL_QUERY_RAG_FAILURE_MODES else "suppress"


def build_spl_query_grounding_query(
    *,
    alert_text: str,
    hypotheses: list[dict[str, Any]],
) -> str:
    """Build bounded retrieval input for the SPL-focused Search index."""

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


def render_spl_query_grounding_context(
    results: list[RetrievalResult],
    *,
    budget_chars: int,
) -> str:
    """Render snippets in the established provenance line format."""

    rendered = [SPL_QUERY_GROUNDING_CONTEXT_HEADER]
    remaining = max(budget_chars - len(SPL_QUERY_GROUNDING_CONTEXT_HEADER) - 1, 0)
    for index, result in enumerate(results, 1):
        if remaining <= 0:
            continue
        prefix = f"[{index}] [{result.source} :: {result_section(result)}] "
        snippet = result.text[: max(remaining - len(prefix), 0)].strip()
        if not snippet:
            continue
        line = f"{prefix}{snippet}"
        rendered.append(line)
        remaining -= len(line) + 1
    return "\n".join(rendered) if len(rendered) > 1 else ""


def retrieve_spl_query_grounding(
    *,
    alert_text: str,
    hypotheses: list[dict[str, Any]],
    config: Config,
    client: Any | None = None,
) -> SplGroundingResult:
    """Retrieve SPL query grounding from the configured Search index."""

    if not config.SPL_QUERY_RAG_ENABLED:
        return SplGroundingResult(status="skipped", message="SPL query RAG disabled")
    index_name = str(config.SPL_QUERY_AZURE_SEARCH_INDEX or "").strip()
    if not index_name:
        return SplGroundingResult(
            status="failed",
            message=(
                "SPL_QUERY_AZURE_SEARCH_INDEX is required when SPL query RAG is enabled"
            ),
        )

    query_text = build_spl_query_grounding_query(
        alert_text=alert_text,
        hypotheses=hypotheses,
    )
    try:
        results = retrieve_grounding(
            query_text,
            index_name=index_name,
            max_results=config.SPL_QUERY_RAG_MAX_SNIPPETS,
            retriever=client,
            semantic_rerank=bool(config.RAG_RERANK_ENABLED),
        )
    except Exception as exc:  # Failure policy is evaluated by the caller.
        return SplGroundingResult(
            status="failed",
            message=f"SPL query Azure AI Search retrieval failed: {exc}",
        )

    context = render_spl_query_grounding_context(
        results,
        budget_chars=config.SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS,
    )
    if not context:
        return SplGroundingResult(
            status="no_match",
            message="No SPL query grounding snippets returned",
        )
    return SplGroundingResult(
        status="success",
        context=context,
        snippet_count=len(results),
    )


__all__ = [
    "SPL_QUERY_GROUNDING_CONTEXT_HEADER",
    "SPL_QUERY_RAG_FAILURE_MODES",
    "SplGroundingResult",
    "build_spl_query_grounding_query",
    "render_spl_query_grounding_context",
    "retrieve_spl_query_grounding",
    "spl_query_rag_failure_mode",
]
