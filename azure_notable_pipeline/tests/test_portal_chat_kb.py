"""Offline portal advisory Search lane tests."""

from __future__ import annotations

from typing import Any

from azure_notable_pipeline.config import Config
from azure_notable_pipeline.portal_chat_kb import build_chat_knowledge_sources


class FakeSearchClient:
    def __init__(self, content: str, source: str) -> None:
        self.content = content
        self.source = source

    def search(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [{"content": self.content, "source_file": self.source}]


class FailingSearchClient:
    def search(self, **_kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("search unavailable")


def test_builds_enabled_index_specific_advisory_sources() -> None:
    config = Config(
        RAG_ENABLED=True,
        RAG_AZURE_SEARCH_INDEX="rag-index",
        SPL_QUERY_RAG_ENABLED=True,
        SPL_QUERY_AZURE_SEARCH_INDEX="spl-index",
        ELASTICSEARCH_GROUNDING_ENABLED=True,
        ELASTICSEARCH_GROUNDING_AZURE_SEARCH_INDEX="elastic-index",
    )

    sources = build_chat_knowledge_sources(
        question="How should this alert be investigated?",
        config=config,
        search_clients={
            "rag-index": FakeSearchClient("general SOP", "soc.md"),
            "spl-index": FakeSearchClient("index=main", "spl.md"),
            "elastic-index": FakeSearchClient("event.category:process", "ecs.md"),
        },
    )

    assert [source["section"] for source in sources] == [
        "knowledge_base.rag",
        "knowledge_base.spl_query_grounding",
        "knowledge_base.elasticsearch_grounding",
    ]
    assert all(source["source_lane"] == "knowledge_base" for source in sources)


def test_one_failed_lane_does_not_remove_other_advisory_sources() -> None:
    config = Config(
        RAG_ENABLED=True,
        RAG_AZURE_SEARCH_INDEX="rag-index",
        SPL_QUERY_RAG_ENABLED=True,
        SPL_QUERY_AZURE_SEARCH_INDEX="spl-index",
    )

    sources = build_chat_knowledge_sources(
        question="question",
        config=config,
        search_clients={
            "rag-index": FailingSearchClient(),
            "spl-index": FakeSearchClient("index=main", "spl.md"),
        },
    )

    assert [source["section"] for source in sources] == [
        "knowledge_base.spl_query_grounding"
    ]


def test_blank_question_skips_all_search_lanes() -> None:
    assert build_chat_knowledge_sources(question="  ", config=Config()) == []
