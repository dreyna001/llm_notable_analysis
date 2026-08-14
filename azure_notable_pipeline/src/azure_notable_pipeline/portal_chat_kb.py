"""Advisory Azure AI Search sources for portal chat synthesis."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from .azure_search_retrieval import retrieve_soc_context
from .closed_ticket_retrieval import (
    bounded_current_case_snippets,
    closed_ticket_hits_to_chat_sources,
    retrieve_closed_tickets_fail_soft,
)
from .config import Config
from .elasticsearch_query_grounding import retrieve_elasticsearch_grounding
from .spl_query_grounding import retrieve_spl_query_grounding

logger = logging.getLogger(__name__)


def _client_for(index_name: str, clients: Mapping[str, Any] | None) -> Any | None:
    if clients is None:
        return None
    return clients.get(str(index_name or "").strip())


def build_chat_knowledge_sources(
    *,
    question: str,
    config: Config,
    search_clients: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return fail-soft advisory Search context blocks for chat synthesis.

    ``search_clients`` is an index-name-to-client map used for dependency
    injection. Production callers omit it so every lane receives a native
    client bound to its configured Search index.
    """

    sources: list[dict[str, Any]] = []
    normalized_question = str(question or "").strip()
    if not normalized_question:
        return sources

    if config.RAG_ENABLED:
        try:
            result = retrieve_soc_context(
                normalized_question,
                config,
                client=_client_for(config.RAG_AZURE_SEARCH_INDEX, search_clients),
            )
            text = str(result.context or "").strip()
            if text:
                sources.append(
                    {
                        "source_lane": "knowledge_base",
                        "section": "knowledge_base.rag",
                        "text": text,
                        "search_text": text,
                    }
                )
        except Exception:
            logger.exception("Azure AI Search RAG retrieval failed for portal chat")

    if config.SPL_QUERY_RAG_ENABLED:
        try:
            result = retrieve_spl_query_grounding(
                alert_text=normalized_question,
                hypotheses=[],
                config=config,
                client=_client_for(config.SPL_QUERY_AZURE_SEARCH_INDEX, search_clients),
            )
            text = str(result.context or "").strip()
            if text:
                sources.append(
                    {
                        "source_lane": "knowledge_base",
                        "section": "knowledge_base.spl_query_grounding",
                        "text": text,
                        "search_text": text,
                    }
                )
        except Exception:
            logger.exception("SPL query Search retrieval failed for portal chat")

    if config.ELASTICSEARCH_GROUNDING_ENABLED:
        try:
            result = retrieve_elasticsearch_grounding(
                alert_text=normalized_question,
                hypotheses=[],
                config=config,
                client=_client_for(
                    config.ELASTICSEARCH_GROUNDING_AZURE_SEARCH_INDEX,
                    search_clients,
                ),
            )
            text = str(result.context or "").strip()
            if text:
                sources.append(
                    {
                        "source_lane": "knowledge_base",
                        "section": "knowledge_base.elasticsearch_grounding",
                        "text": text,
                        "search_text": text,
                    }
                )
        except Exception:
            logger.exception("Elasticsearch Search retrieval failed for portal chat")

    return sources


def build_closed_ticket_chat_sources(
    *,
    question: str,
    config: Config,
    case_sources: list[dict[str, Any]],
    embedding_gateway: Any | None = None,
    search_adapter: Any | None = None,
) -> list[dict[str, Any]]:
    """Return closed-ticket advisory sources when the portal lane is enabled."""
    if not config.CASE_QA_CLOSED_TICKET_ENABLED:
        return []
    try:
        outcome = retrieve_closed_tickets_fail_soft(
            config=config,
            question=question,
            current_case_snippets=bounded_current_case_snippets(case_sources),
            embedding_gateway=embedding_gateway,
            search_adapter=search_adapter,
        )
        if outcome.error:
            logger.warning(
                "Closed-ticket chat retrieval failed soft: %s",
                outcome.error,
            )
        return closed_ticket_hits_to_chat_sources(outcome.hits)
    except Exception:
        logger.exception("Closed-ticket retrieval failed for portal chat")
        return []


__all__ = ["build_chat_knowledge_sources", "build_closed_ticket_chat_sources"]
