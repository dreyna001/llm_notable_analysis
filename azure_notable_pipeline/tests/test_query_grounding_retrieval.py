"""Offline behavior tests for SPL and Elasticsearch Search grounding."""

from __future__ import annotations

from typing import Any

from azure_notable_pipeline.config import Config
from azure_notable_pipeline.elasticsearch_query_grounding import (
    retrieve_elasticsearch_grounding,
)
from azure_notable_pipeline.spl_query_grounding import retrieve_spl_query_grounding


class FakeSearchClient:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return self.documents


def test_spl_grounding_preserves_query_shape_provenance_and_budget() -> None:
    client = FakeSearchClient(
        [
            {
                "content": "index=main sourcetype=XmlWinEventLog",
                "source_file": "spl.md",
                "section_path": "indexes/windows",
            }
        ]
    )
    config = Config(
        SPL_QUERY_RAG_ENABLED=True,
        SPL_QUERY_AZURE_SEARCH_INDEX="spl-grounding",
        SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS=200,
    )

    result = retrieve_spl_query_grounding(
        alert_text="suspicious powershell",
        hypotheses=[
            {
                "hypothesis_type": "true_positive",
                "hypothesis": "encoded execution",
                "best_pivots": ["host"],
            }
        ],
        config=config,
        client=client,
    )

    assert result.status == "success"
    assert result.snippet_count == 1
    assert "[spl.md :: indexes/windows]" in result.context
    assert "SECURITY ALERT INPUT:" in client.calls[0]["search_text"]
    assert "encoded execution" in client.calls[0]["search_text"]


def test_elasticsearch_grounding_maps_source_section_and_no_match() -> None:
    success_client = FakeSearchClient(
        [
            {
                "content": "event.category:process and host.name",
                "metadata": {"title": "elastic.md", "section": "ecs"},
            }
        ]
    )
    config = Config(
        ELASTICSEARCH_GROUNDING_ENABLED=True,
        ELASTICSEARCH_GROUNDING_AZURE_SEARCH_INDEX="elastic-grounding",
    )

    result = retrieve_elasticsearch_grounding(
        alert_text="suspicious process",
        hypotheses=[],
        config=config,
        client=success_client,
    )
    no_match = retrieve_elasticsearch_grounding(
        alert_text="suspicious process",
        hypotheses=[],
        config=config,
        client=FakeSearchClient([]),
    )

    assert result.status == "success"
    assert "[elastic.md :: ecs]" in result.context
    assert no_match.status == "no_match"


def test_missing_lane_indexes_fail_soft_without_a_search_call() -> None:
    spl = retrieve_spl_query_grounding(
        alert_text="alert",
        hypotheses=[],
        config=Config(SPL_QUERY_RAG_ENABLED=True),
    )
    elastic = retrieve_elasticsearch_grounding(
        alert_text="alert",
        hypotheses=[],
        config=Config(ELASTICSEARCH_GROUNDING_ENABLED=True),
    )

    assert spl.status == "failed"
    assert "SPL_QUERY_AZURE_SEARCH_INDEX" in spl.message
    assert elastic.status == "failed"
    assert "ELASTICSEARCH_GROUNDING_AZURE_SEARCH_INDEX" in elastic.message
