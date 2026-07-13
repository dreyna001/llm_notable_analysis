"""Application-oriented Azure AI Search retrieval boundary."""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)

from .azure_clients import AzureClientConfigurationError, azure_search_client

logger = logging.getLogger(__name__)

MAX_RETRIEVAL_RESULTS = 20
MAX_QUERY_CHARS = 8_000
_SEARCH_TIMEOUT_SECONDS = 30
_TEXT_FIELDS = ("content", "text", "chunk", "chunk_text")
_SOURCE_FIELDS = ("source_file", "source", "uri", "title")
_SECTION_FIELDS = ("section_path", "section")
_SYSTEM_FIELDS = {"@search.score", "@search.reranker_score", "@search.highlights"}
_OMITTED_METADATA_FIELDS = {
    *_TEXT_FIELDS,
    "embedding",
    "embeddings",
    "content_vector",
    "vector",
}


class AzureSearchRetrievalError(RuntimeError):
    """A stable Azure AI Search boundary failure."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AzureSearchConfigurationError(AzureSearchRetrievalError):
    """Search input or runtime configuration is invalid."""


class AzureSearchAuthenticationError(AzureSearchRetrievalError):
    """The managed identity cannot read the configured Search index."""


class AzureSearchRequestError(AzureSearchRetrievalError):
    """Azure AI Search rejected the application query or index schema."""


class AzureSearchUnavailableError(AzureSearchRetrievalError):
    """Azure AI Search is temporarily unavailable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class AzureSearchResponseError(AzureSearchRetrievalError):
    """Azure AI Search returned a result outside the retrieval contract."""


@dataclass(frozen=True)
class RetrievalResult:
    """One normalized Search result with explicit source attribution."""

    text: str
    source: str
    score: float | None = None
    reranker_score: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class GroundingContextResult:
    """Rendered advisory context plus status metadata."""

    status: str
    context: str = ""
    snippet_count: int = 0
    message: str = ""


def _required_text(value: str, *, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise AzureSearchConfigurationError(f"{name} is required")
    return normalized


def _max_results(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AzureSearchConfigurationError("max_results must be an integer")
    if not 1 <= value <= MAX_RETRIEVAL_RESULTS:
        raise AzureSearchConfigurationError(
            f"max_results must be from 1 to {MAX_RETRIEVAL_RESULTS}"
        )
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    try:
        converted = dict(value)
    except (TypeError, ValueError) as exc:
        raise AzureSearchResponseError("Azure AI Search result is not an object") from exc
    return converted


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return {str(key): item for key, item in decoded.items()}
    return {}


def _first_text(document: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = document.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


def _result(document_value: Any) -> RetrievalResult | None:
    document = _mapping(document_value)
    text = _first_text(document, _TEXT_FIELDS)
    if not text:
        return None

    explicit_metadata = _metadata(document.get("metadata"))
    source = _first_text(document, _SOURCE_FIELDS) or _first_text(
        explicit_metadata, _SOURCE_FIELDS
    )
    if not source:
        source = "azure_ai_search"

    metadata = dict(explicit_metadata)
    for key, value in document.items():
        normalized_key = str(key)
        if (
            normalized_key == "metadata"
            or normalized_key in _SYSTEM_FIELDS
            or normalized_key.lower() in _OMITTED_METADATA_FIELDS
        ):
            continue
        metadata.setdefault(normalized_key, value)
    metadata.setdefault("source", source)

    return RetrievalResult(
        text=text,
        source=source,
        score=_score(document.get("@search.score")),
        reranker_score=_score(document.get("@search.reranker_score")),
        metadata=metadata,
    )


def _error_text(exc: HttpResponseError) -> str:
    parts = [str(exc)]
    error = getattr(exc, "error", None)
    parts.extend(
        str(value)
        for value in (getattr(error, "code", None), getattr(error, "message", None))
        if value
    )
    return " ".join(parts).lower()


def _semantic_ranker_unavailable(exc: Exception) -> bool:
    if not isinstance(exc, HttpResponseError):
        return False
    if getattr(exc, "status_code", None) == 402:
        return True
    message = _error_text(exc)
    semantic_marker = "semantic" in message or "rerank" in message
    unavailable_marker = any(
        marker in message
        for marker in (
            "not enabled",
            "not available",
            "not supported",
            "free query semantic usage exceeded",
            "quota",
            "billing",
            "sku",
        )
    )
    return semantic_marker and unavailable_marker


def _raise_search_error(exc: Exception) -> None:
    message = "Azure AI Search grounding query failed"
    if isinstance(exc, ClientAuthenticationError):
        raise AzureSearchAuthenticationError(message) from exc
    if isinstance(exc, (ServiceRequestError, ServiceResponseError)):
        raise AzureSearchUnavailableError(message) from exc
    if isinstance(exc, HttpResponseError):
        status_code = getattr(exc, "status_code", None)
        if status_code in {401, 403}:
            raise AzureSearchAuthenticationError(message) from exc
        if status_code in {408, 429, 500, 502, 503, 504}:
            raise AzureSearchUnavailableError(message) from exc
        raise AzureSearchRequestError(message) from exc
    if isinstance(exc, AzureError):
        raise AzureSearchRetrievalError(message) from exc
    raise exc


def _search(
    client: Any,
    *,
    query: str,
    max_results: int,
    semantic_rerank: bool,
    semantic_configuration_name: str | None,
) -> Any:
    kwargs: dict[str, Any] = {
        "search_text": query,
        "top": max_results,
        "include_total_count": False,
        "timeout": _SEARCH_TIMEOUT_SECONDS,
    }
    if semantic_rerank:
        kwargs.update(
            {
                "query_type": "semantic",
                "semantic_query": query,
                "semantic_error_mode": "partial",
                "semantic_max_wait_in_milliseconds": 2_000,
            }
        )
        semantic_configuration = str(semantic_configuration_name or "").strip()
        if semantic_configuration:
            kwargs["semantic_configuration_name"] = semantic_configuration
    return client.search(**kwargs)


def _execute_search(
    client: Any,
    *,
    query: str,
    max_results: int,
    semantic_rerank: bool,
    semantic_configuration_name: str | None,
) -> list[RetrievalResult]:
    """Execute and consume the lazy native Search pager within one failure scope."""

    raw_results = _search(
        client,
        query=query,
        max_results=max_results,
        semantic_rerank=semantic_rerank,
        semantic_configuration_name=semantic_configuration_name,
    )
    results: list[RetrievalResult] = []
    for raw_result in raw_results:
        if len(results) >= max_results:
            break
        mapped = _result(raw_result)
        if mapped is not None:
            results.append(mapped)
    return results


def retrieve_grounding(
    query: str,
    *,
    index_name: str,
    max_results: int,
    retriever: Any | None = None,
    semantic_rerank: bool = False,
    semantic_configuration_name: str | None = None,
) -> list[RetrievalResult]:
    """Run one bounded native Search query and return normalized results.

    Semantic ranking is attempted only when explicitly enabled. A known
    semantic feature/SKU/billing rejection is logged and retried once without
    semantic ranking; other query failures remain explicit.
    """

    normalized_query = _required_text(query, name="query")
    if len(normalized_query) > MAX_QUERY_CHARS:
        raise AzureSearchConfigurationError(
            f"query must not exceed {MAX_QUERY_CHARS} characters"
        )
    normalized_index = _required_text(index_name, name="index_name")
    bounded_results = _max_results(max_results)
    try:
        client = retriever or azure_search_client(
            os.getenv("AZURE_SEARCH_ENDPOINT", ""),
            normalized_index,
        )
    except AzureClientConfigurationError as exc:
        raise AzureSearchConfigurationError(str(exc)) from exc

    rerank_skipped = False
    try:
        results = _execute_search(
            client,
            query=normalized_query,
            max_results=bounded_results,
            semantic_rerank=bool(semantic_rerank),
            semantic_configuration_name=semantic_configuration_name,
        )
    except Exception as exc:
        if semantic_rerank and _semantic_ranker_unavailable(exc):
            logger.warning(
                "Azure AI Search semantic ranker unavailable; rerank_status=skipped"
            )
            rerank_skipped = True
            try:
                results = _execute_search(
                    client,
                    query=normalized_query,
                    max_results=bounded_results,
                    semantic_rerank=False,
                    semantic_configuration_name=None,
                )
            except Exception as fallback_exc:
                _raise_search_error(fallback_exc)
                raise AssertionError("unreachable")
        else:
            if isinstance(exc, AzureSearchRetrievalError):
                raise
            _raise_search_error(exc)
            raise AssertionError("unreachable")
    if (
        semantic_rerank
        and not rerank_skipped
        and results
        and all(result.reranker_score is None for result in results)
    ):
        logger.warning(
            "Azure AI Search returned no semantic scores; rerank_status=skipped"
        )
    return results


def render_soc_context(
    results: list[RetrievalResult],
    *,
    budget_chars: int,
) -> str:
    """Render advisory snippets with bounded, explicit source labels."""

    rendered: list[str] = []
    remaining = max(int(budget_chars), 0)
    for index, result in enumerate(results, 1):
        text = str(result.text or "").strip()
        if not text or remaining <= 0:
            continue
        prefix = f"[{index}] Source: {result.source}\n"
        snippet = text[: max(remaining - len(prefix), 0)].strip()
        if not snippet:
            continue
        block = f"{prefix}{snippet}"
        rendered.append(block)
        remaining -= len(block) + 2
    return "\n\n".join(rendered)


def retrieve_soc_context(
    alert_text: str,
    config: Any,
    *,
    client: Any | None = None,
) -> GroundingContextResult:
    """Retrieve the general advisory RAG lane using Azure AI Search."""

    if not config.RAG_ENABLED:
        return GroundingContextResult(status="skipped", message="RAG disabled")
    index_name = str(config.RAG_AZURE_SEARCH_INDEX or "").strip()
    if not index_name:
        message = "RAG_AZURE_SEARCH_INDEX is required when RAG is enabled"
        if config.RAG_FAILURE_MODE == "fail_closed":
            raise ValueError(message)
        return GroundingContextResult(status="failed", message=message)
    try:
        results = retrieve_grounding(
            alert_text,
            index_name=index_name,
            max_results=config.RAG_MAX_SNIPPETS,
            retriever=client,
            semantic_rerank=bool(config.RAG_RERANK_ENABLED),
        )
    except Exception as exc:  # Boundary failures obey the configured RAG policy.
        message = f"Azure AI Search RAG retrieval failed: {exc}"
        if config.RAG_FAILURE_MODE == "fail_closed":
            raise RuntimeError(message) from exc
        return GroundingContextResult(status="failed", message=message)

    context = render_soc_context(
        results,
        budget_chars=config.RAG_CONTEXT_BUDGET_CHARS,
    )
    if not context:
        return GroundingContextResult(
            status="no_match",
            message="No RAG snippets returned",
        )
    return GroundingContextResult(
        status="success",
        context=context,
        snippet_count=len(results),
    )


def result_section(result: RetrievalResult) -> str:
    """Return one normalized provenance section for a retrieval result."""

    metadata = result.metadata or {}
    return _first_text(metadata, _SECTION_FIELDS) or "root"


__all__ = [
    "AzureSearchAuthenticationError",
    "AzureSearchConfigurationError",
    "AzureSearchRequestError",
    "AzureSearchResponseError",
    "AzureSearchRetrievalError",
    "AzureSearchUnavailableError",
    "GroundingContextResult",
    "MAX_RETRIEVAL_RESULTS",
    "RetrievalResult",
    "render_soc_context",
    "result_section",
    "retrieve_grounding",
    "retrieve_soc_context",
]
