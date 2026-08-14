"""Retrieval-bound pinned-case Q&A for the Azure analyst portal."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .case_chunk_retrieval import (
    BlobCaseChunkSource,
    CaseChunkSource,
    load_all_case_chunks,
    retrieve_case_chunks_for_question,
    trim_chunks_list_order,
)
from .config import Config
from .portal_chat import (
    ChatTurn,
    PortalAnswer,
    conversation_history_from_config,
    synthesize_case_answer,
    trim_sources,
)
from .portal_chat_images import ValidatedChatImage
from .portal_chat_kb import build_chat_knowledge_sources, build_closed_ticket_chat_sources
from .portal_chat_kb_query import build_case_aware_kb_query


def answer_selected_case_question(
    *,
    case_id: str,
    question: str,
    config: Config,
    case_store: Any,
    chunk_source: CaseChunkSource | None = None,
    chat_gateway: Any | None = None,
    embedding_gateway: Any | None = None,
    search_clients: Mapping[str, Any] | None = None,
    conversation_history: Sequence[ChatTurn] | None = None,
    images: tuple[ValidatedChatImage, ...] = (),
    search_adapter: Any | None = None,
) -> PortalAnswer:
    """Answer one question using native, retrieval-bound selected-case synthesis."""

    selected_case_id = str(case_id or "").strip()
    if not selected_case_id:
        raise ValueError("selected_case_id is required")
    normalized_question = str(question or "").strip()
    if not normalized_question:
        raise ValueError("question is required")
    if len(normalized_question) > config.CASE_QA_MAX_QUESTION_CHARS:
        raise ValueError("question exceeds CASE_QA_MAX_QUESTION_CHARS")
    if not config.CASE_QA_ENABLED:
        return PortalAnswer(answer="Case Q&A is disabled.", answer_status="unknown")

    case_chunks = retrieve_case_chunks_for_question(
        case_id=selected_case_id,
        question=normalized_question,
        config=config,
        case_store=case_store,
        chunk_source=chunk_source,
        embedding_gateway=embedding_gateway,
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
    kb_query = build_case_aware_kb_query(
        normalized_question,
        case_chunks=sources,
        selected_case_id=selected_case_id,
    )
    sources.extend(
        build_chat_knowledge_sources(
            question=kb_query,
            config=config,
            search_clients=search_clients,
        )
    )
    sources = trim_sources(sources, config)
    closed_ticket_sources = build_closed_ticket_chat_sources(
        question=normalized_question,
        config=config,
        case_sources=sources,
        embedding_gateway=embedding_gateway,
        search_adapter=search_adapter,
    )
    if closed_ticket_sources:
        sources.extend(closed_ticket_sources)
        sources = trim_sources(sources, config)

    return synthesize_case_answer(
        question=normalized_question,
        sources=sources,
        config=config,
        chat_gateway=chat_gateway,
        conversation_history=conversation_history,
        images=images,
    )


def answer_portal_chat(
    *,
    selected_case_id: str,
    question: str,
    config: Config,
    cosmos_store: Any,
    blob_store: Any | None = None,
    user_id: str | None = None,
    prior_transcript: Sequence[dict[str, Any]] | None = None,
    chat_gateway: Any | None = None,
    embedding_gateway: Any | None = None,
    search_clients: Mapping[str, Any] | None = None,
    images: tuple[ValidatedChatImage, ...] = (),
    search_adapter: Any | None = None,
) -> PortalAnswer:
    """Handler-facing adapter over native Cosmos, Blob, Search, and OpenAI seams.

    The handler authenticates ``user_id`` and owns transcript persistence. The
    identifier remains explicit here so dependency injection cannot accidentally
    erase that authorization boundary, even though synthesis does not consume it.
    """

    if not str(user_id or "").strip():
        raise ValueError("authenticated user is required for portal chat")
    history = conversation_history_from_config(config, prior_transcript or [])
    source = BlobCaseChunkSource(
        container_name=config.CASE_ARCHIVE_CONTAINER,
        chunks_prefix=config.CASE_ARCHIVE_CHUNKS_PREFIX,
        store=blob_store,
        account_url=config.OUTPUT_STORAGE_ACCOUNT_URL or None,
    )
    return answer_selected_case_question(
        case_id=selected_case_id,
        question=question,
        config=config,
        case_store=cosmos_store,
        chunk_source=source,
        chat_gateway=chat_gateway,
        embedding_gateway=embedding_gateway,
        search_clients=search_clients,
        conversation_history=history,
        images=images,
        search_adapter=search_adapter,
    )


def retrieve_selected_case_chunks(
    *,
    case_id: str,
    config: Config,
    case_store: Any,
    chunk_source: CaseChunkSource | None = None,
) -> list[dict[str, Any]]:
    """Return chunks in storage order without query ranking (deprecated helper)."""

    chunks = load_all_case_chunks(
        case_id=case_id,
        config=config,
        case_store=case_store,
        chunk_source=chunk_source,
    )
    return trim_chunks_list_order(chunks, config)


__all__ = [
    "answer_portal_chat",
    "answer_selected_case_question",
    "retrieve_selected_case_chunks",
]
