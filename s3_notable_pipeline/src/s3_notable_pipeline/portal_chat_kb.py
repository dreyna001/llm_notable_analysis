"""Advisory Knowledge Base sources for AWS portal chat synthesis."""

from __future__ import annotations

import logging
from typing import Any

from .aws_clients import bedrock_runtime_client
from .bedrock_kb_retrieval import retrieve_soc_context
from .closed_ticket_retrieval import (
    bounded_current_case_snippets,
    closed_ticket_hits_to_chat_sources,
    retrieve_closed_tickets_fail_soft,
)
from .config import Config
from .elasticsearch_query_grounding import retrieve_elasticsearch_grounding
from .spl_query_grounding import retrieve_spl_query_grounding

logger = logging.getLogger(__name__)


def build_chat_knowledge_sources(
    *,
    question: str,
    config: Config,
    bedrock_agent_client: Any | None = None,
) -> list[dict[str, Any]]:
    """Return advisory KB context blocks to merge before chat synthesis."""
    sources: list[dict[str, Any]] = []
    normalized_question = str(question or "").strip()
    if not normalized_question:
        return sources

    if config.RAG_ENABLED:
        try:
            result = retrieve_soc_context(
                normalized_question,
                config,
                client=bedrock_agent_client,
                bedrock_client=bedrock_runtime_client(),
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
            logger.exception("Knowledge Base retrieval failed for portal chat")

    if config.SPL_QUERY_RAG_ENABLED:
        try:
            result = retrieve_spl_query_grounding(
                alert_text=normalized_question,
                hypotheses=[],
                config=config,
                client=bedrock_agent_client,
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
            logger.exception("SPL query grounding retrieval failed for portal chat")

    if config.ELASTICSEARCH_GROUNDING_ENABLED:
        try:
            result = retrieve_elasticsearch_grounding(
                alert_text=normalized_question,
                hypotheses=[],
                config=config,
                client=bedrock_agent_client,
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
            logger.exception("Elasticsearch grounding retrieval failed for portal chat")

    return sources


def build_closed_ticket_chat_sources(
    *,
    question: str,
    config: Config,
    case_sources: list[dict[str, Any]],
    bedrock_client: Any,
    opensearch_client: Any | None = None,
) -> list[dict[str, Any]]:
    """Return closed-ticket advisory sources when the portal lane is enabled."""
    if not config.CASE_QA_CLOSED_TICKET_ENABLED:
        return []
    try:
        outcome = retrieve_closed_tickets_fail_soft(
            config=config,
            question=question,
            current_case_snippets=bounded_current_case_snippets(case_sources),
            bedrock_client=bedrock_client,
            opensearch_client=opensearch_client,
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
