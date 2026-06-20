"""Retrieval-bound pinned-case Q&A for the AWS portal."""

from __future__ import annotations

from typing import Any, Sequence

from .aws_clients import bedrock_agent_runtime_client
from .case_chunk_retrieval import (
    load_all_case_chunks,
    retrieve_case_chunks_for_question,
    trim_chunks_list_order,
)
from .config import Config
from .portal_chat import (
    ChatTurn,
    PortalAnswer,
    synthesize_case_answer,
    trim_sources,
)
from .portal_chat_kb import build_chat_knowledge_sources


def answer_selected_case_question(
    *,
    case_id: str,
    question: str,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any,
    bedrock_client: Any,
    conversation_history: Sequence[ChatTurn] | None = None,
) -> PortalAnswer:
    """Answer one question using retrieval-bound synthesis for the selected case."""

    selected_case_id = str(case_id or "").strip()
    if not selected_case_id:
        raise ValueError("selected_case_id is required")
    normalized_question = str(question or "").strip()
    if not normalized_question:
        raise ValueError("question is required")
    if len(normalized_question) > config.CASE_QA_MAX_QUESTION_CHARS:
        raise ValueError("question exceeds CASE_QA_MAX_QUESTION_CHARS")
    if not config.CASE_QA_ENABLED:
        return PortalAnswer(
            answer="Case Q&A is disabled.",
            answer_status="unknown",
        )

    case_chunks = retrieve_case_chunks_for_question(
        case_id=selected_case_id,
        question=normalized_question,
        config=config,
        dynamodb_client=dynamodb_client,
        s3_client=s3_client,
        bedrock_client=bedrock_client,
    )
    sources: list[dict[str, Any]] = [
        {
            "source_lane": "current_case",
            "section": str(chunk.get("section") or ""),
            "chunk_id": str(chunk.get("chunk_id") or ""),
            "text": str(chunk.get("search_text") or chunk.get("text") or ""),
            "search_text": str(chunk.get("search_text") or chunk.get("text") or ""),
        }
        for chunk in case_chunks
    ]
    sources.extend(
        build_chat_knowledge_sources(
            question=normalized_question,
            config=config,
            bedrock_agent_client=bedrock_agent_runtime_client(),
        )
    )
    sources = trim_sources(sources, config)

    return synthesize_case_answer(
        question=normalized_question,
        sources=sources,
        config=config,
        bedrock_client=bedrock_client,
        conversation_history=conversation_history,
    )


def retrieve_selected_case_chunks(
    *,
    case_id: str,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any,
) -> list[dict[str, Any]]:
    """Return chunks in storage order without query ranking (deprecated helper)."""

    chunks = load_all_case_chunks(
        case_id=case_id,
        config=config,
        dynamodb_client=dynamodb_client,
        s3_client=s3_client,
    )
    return trim_chunks_list_order(chunks, config)
