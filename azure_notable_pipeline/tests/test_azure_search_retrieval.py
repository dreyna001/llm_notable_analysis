"""Offline tests for the native Azure AI Search retrieval boundary."""

from __future__ import annotations

from typing import Any

import pytest
from azure.core.exceptions import HttpResponseError

from azure_notable_pipeline.azure_search_retrieval import (
    AzureSearchConfigurationError,
    AzureSearchRequestError,
    render_soc_context,
    retrieve_grounding,
    retrieve_soc_context,
)
from azure_notable_pipeline.config import Config


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.reason = "fake"
        self.headers: dict[str, str] = {}
        self.request = None
        self.content_type = "application/json"
        self._text = text

    def text(self) -> str:
        return self._text


class FakeSearchClient:
    def __init__(
        self,
        documents: list[dict[str, Any]],
        *,
        semantic_error: Exception | None = None,
    ) -> None:
        self.documents = documents
        self.semantic_error = semantic_error
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        if kwargs.get("query_type") == "semantic" and self.semantic_error is not None:
            raise self.semantic_error
        return self.documents


class LazySemanticFailureSearchClient(FakeSearchClient):
    def search(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("query_type") != "semantic":
            return self.documents

        def _failed_page() -> Any:
            if self.semantic_error is not None:
                raise self.semantic_error
            yield from self.documents

        return _failed_page()


def test_maps_native_documents_to_bounded_stable_results() -> None:
    client = FakeSearchClient(
        [
            {
                "content": "Reset the compromised account password.",
                "metadata": '{"source_file":"sop.md","section_path":"identity"}',
                "@search.score": 1.25,
                "@search.reranker_score": 3.5,
                "embedding": [1.0, 2.0],
            },
            {"text": "Second", "title": "runbook.md"},
            {"content": "third", "source": "extra.md"},
        ]
    )

    results = retrieve_grounding(
        "credential compromise",
        index_name="soc-rag",
        max_results=2,
        retriever=client,
    )

    assert len(results) == 2
    assert results[0].source == "sop.md"
    assert results[0].score == 1.25
    assert results[0].reranker_score == 3.5
    assert results[0].metadata == {
        "source_file": "sop.md",
        "section_path": "identity",
        "source": "sop.md",
    }
    assert client.calls == [
        {
            "search_text": "credential compromise",
            "top": 2,
            "include_total_count": False,
            "timeout": 30,
        }
    ]


def test_semantic_rerank_is_only_sent_when_enabled() -> None:
    client = FakeSearchClient([{"content": "SOP", "source": "sop.md"}])

    retrieve_grounding(
        "alert",
        index_name="soc-rag",
        max_results=1,
        retriever=client,
        semantic_rerank=True,
    )

    assert client.calls[0]["query_type"] == "semantic"
    assert client.calls[0]["semantic_error_mode"] == "partial"


def test_semantic_sku_or_billing_error_falls_back_to_plain_search(caplog: Any) -> None:
    error = HttpResponseError(
        message="Free Query Semantic Usage exceeded for the month",
        response=FakeResponse(402, "semantic billing quota exhausted"),
    )
    client = FakeSearchClient(
        [{"content": "SOP", "source": "sop.md"}],
        semantic_error=error,
    )

    results = retrieve_grounding(
        "alert",
        index_name="soc-rag",
        max_results=1,
        retriever=client,
        semantic_rerank=True,
    )

    assert [result.text for result in results] == ["SOP"]
    assert len(client.calls) == 2
    assert client.calls[0]["query_type"] == "semantic"
    assert "query_type" not in client.calls[1]
    assert "rerank_status=skipped" in caplog.text


def test_lazy_semantic_pager_failure_also_falls_back() -> None:
    error = HttpResponseError(
        message="semantic ranker is not enabled for this SKU",
        response=FakeResponse(400, "semantic feature not enabled"),
    )
    client = LazySemanticFailureSearchClient(
        [{"content": "SOP", "source": "sop.md"}],
        semantic_error=error,
    )

    results = retrieve_grounding(
        "alert",
        index_name="soc-rag",
        max_results=1,
        retriever=client,
        semantic_rerank=True,
    )

    assert [result.text for result in results] == ["SOP"]
    assert len(client.calls) == 2


def test_non_semantic_request_error_does_not_fall_back() -> None:
    error = HttpResponseError(
        message="Unknown field in search request",
        response=FakeResponse(400, "unknown field"),
    )
    client = FakeSearchClient([], semantic_error=error)

    with pytest.raises(AzureSearchRequestError):
        retrieve_grounding(
            "alert",
            index_name="soc-rag",
            max_results=1,
            retriever=client,
            semantic_rerank=True,
        )

    assert len(client.calls) == 1


@pytest.mark.parametrize("max_results", [0, 21, True])
def test_rejects_unbounded_result_limits(max_results: Any) -> None:
    with pytest.raises(AzureSearchConfigurationError):
        retrieve_grounding(
            "alert",
            index_name="soc-rag",
            max_results=max_results,
            retriever=FakeSearchClient([]),
        )


def test_rendered_context_respects_budget_and_source_attribution() -> None:
    client = FakeSearchClient(
        [{"content": "a" * 100, "source_file": "large.txt"}]
    )
    results = retrieve_grounding(
        "alert",
        index_name="soc-rag",
        max_results=1,
        retriever=client,
    )

    context = render_soc_context(results, budget_chars=40)

    assert len(context) <= 40
    assert "Source: large.txt" in context


def test_general_rag_preserves_fail_soft_and_fail_closed_modes() -> None:
    suppressed = retrieve_soc_context("alert", Config(RAG_ENABLED=True))
    assert suppressed.status == "failed"
    assert "RAG_AZURE_SEARCH_INDEX" in suppressed.message

    with pytest.raises(ValueError, match="RAG_AZURE_SEARCH_INDEX"):
        retrieve_soc_context(
            "alert",
            Config(RAG_ENABLED=True, RAG_FAILURE_MODE="fail_closed"),
        )
