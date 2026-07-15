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
from .azure_openai_gateway import embed_texts
from .azure_search_adapter import AzureSearchAdapter, AzureSearchAdapterError

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


@dataclass(frozen=True)
class RetrievedDocument:
    """Tenant/corpus-scoped document with durable source provenance."""

    document_id: str
    text: str
    score: float
    tenant_id: str
    corpus_id: str
    case_id: str = ""
    run_id: str = ""
    source_container: str = ""
    source_blob_name: str = ""
    source_version_id: str = ""
    source_etag: str = ""
    source_file: str = ""
    section: str = ""
    metadata: dict[str, Any] | None = None


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
    if application_managed_search_enabled(config):
        return _retrieve_application_managed_soc_context(alert_text, config, client=client)
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


def config_value(config: Any, name: str, default: Any = "") -> Any:
    value = getattr(config, name, None)
    if value not in (None, ""):
        return value
    return os.getenv(name, default)


def retrieval_backend(config: Any, *, case: bool = False) -> str:
    names = ("CASE_QA_RETRIEVAL_BACKEND", "CASE_QA_SEARCH_BACKEND") if case else (
        "RAG_RETRIEVAL_BACKEND", "RAG_SEARCH_BACKEND"
    )
    for name in names:
        value = str(config_value(config, name, "") or "").strip().lower()
        if value:
            if value not in {"legacy", "azure_search", "azure-ai-search", "search"}:
                raise ValueError(f"{name} must be legacy or azure_search")
            return "azure_search" if value in {"azure_search", "azure-ai-search", "search"} else "legacy"
    return "legacy"


def application_managed_search_enabled(config: Any, *, case: bool = False) -> bool:
    index_name = config_value(
        config,
        "CASE_QA_AZURE_SEARCH_INDEX" if case else "RAG_AZURE_SEARCH_INDEX",
        "",
    )
    return (
        retrieval_backend(config, case=case) == "azure_search"
        and bool(str(index_name or "").strip())
    )


def tenant_id_for(config: Any, *, required: bool = False) -> str:
    value = str(config_value(config, "RAG_TENANT_ID", "") or "").strip()
    if required and not value:
        raise ValueError("RAG_TENANT_ID is required for Azure Search retrieval")
    return value


def retrieve_hybrid_documents(
    *,
    query_text: str,
    index: str,
    tenant_id: str,
    corpus_id: str,
    top_k: int,
    adapter: Any,
    query_embedding: list[float] | None = None,
    case_id: str = "",
    run_id: str = "",
) -> list[RetrievedDocument]:
    """Execute a hybrid query and preserve source and generation provenance."""

    normalized_query = _required_text(query_text, name="query_text") if not query_embedding else str(query_text or "").strip()
    embedding = query_embedding or embed_texts([normalized_query])[0]
    if hasattr(adapter, "hybrid_search"):
        raw_documents = adapter.hybrid_search(
            index=index,
            query_text=normalized_query,
            query_embedding=embedding,
            tenant_id=tenant_id,
            corpus_id=corpus_id,
            case_id=case_id,
            run_id=run_id,
            top_k=_max_results(top_k),
        )
    else:
        raw_documents = adapter.search(
            index=index,
            query_text=normalized_query,
            query_embedding=embedding,
            tenant_id=tenant_id,
            corpus_id=corpus_id,
            case_id=case_id,
            run_id=run_id,
            top_k=_max_results(top_k),
        )
    documents: list[RetrievedDocument] = []
    for raw in raw_documents:
        document = _mapping(raw)
        metadata = _metadata(document.get("metadata"))
        provenance = {
            key: str(document.get(key, ""))
            for key in (
                "tenant_id", "corpus_id", "case_id", "run_id", "chunk_id",
                "source_container", "source_blob_name", "source_version_id",
                "source_etag", "source_file", "manifest_id", "manifest_version",
                "embedding_model",
            )
        }
        metadata.setdefault("provenance", provenance)
        documents.append(
            RetrievedDocument(
                document_id=str(document.get("id") or document.get("document_id") or document.get("chunk_id") or ""),
                text=str(document.get("text") or document.get("search_text") or "").strip(),
                score=float(document.get("@search.score", document.get("score", 0.0)) or 0.0),
                tenant_id=str(document.get("tenant_id", tenant_id)),
                corpus_id=str(document.get("corpus_id", corpus_id)),
                case_id=str(document.get("case_id", case_id)),
                run_id=str(document.get("run_id", run_id)),
                source_container=str(document.get("source_container", "")),
                source_blob_name=str(document.get("source_blob_name", document.get("source_key", ""))),
                source_version_id=str(document.get("source_version_id", "")),
                source_etag=str(document.get("source_etag", "")),
                source_file=str(document.get("source_file", "")),
                section=str(document.get("section", "")),
                metadata=metadata,
            )
        )
    return documents


def render_hybrid_documents(
    documents: list[RetrievedDocument],
    *,
    budget_chars: int,
) -> str:
    rendered: list[str] = []
    remaining = max(0, int(budget_chars))
    for index, document in enumerate(documents, 1):
        if not document.text or remaining <= 0:
            continue
        source = document.source_file or document.source_blob_name or "azure_ai_search"
        prefix = f"[{index}] Source: {source}"
        if document.section:
            prefix += f" :: {document.section}"
        prefix += "\n"
        text = document.text[: max(0, remaining - len(prefix))].strip()
        if not text:
            continue
        block = prefix + text
        rendered.append(block)
        remaining -= len(block) + 2
    return "\n\n".join(rendered)


def _retrieve_application_managed_soc_context(
    alert_text: str,
    config: Any,
    *,
    client: Any | None,
) -> GroundingContextResult:
    index = str(config_value(config, "RAG_AZURE_SEARCH_INDEX", "") or "").strip()
    corpus = str(config_value(config, "RAG_CORPUS_ID", "soc") or "").strip()
    try:
        tenant = tenant_id_for(config, required=True)
        adapter = client or AzureSearchAdapter.from_config(config, index_name=index)
        documents = retrieve_hybrid_documents(
            query_text=alert_text,
            index=index,
            tenant_id=tenant,
            corpus_id=corpus,
            top_k=int(config_value(config, "RAG_MAX_SNIPPETS", 4)),
            adapter=adapter,
        )
    except Exception as exc:
        message = f"Azure AI Search RAG retrieval failed: {exc}"
        if str(config_value(config, "RAG_FAILURE_MODE", "suppress")) == "fail_closed":
            raise RuntimeError(message) from exc
        return GroundingContextResult(status="failed", message=message)
    context = render_hybrid_documents(
        documents,
        budget_chars=int(config_value(config, "RAG_CONTEXT_BUDGET_CHARS", 1600)),
    )
    if not context:
        return GroundingContextResult(status="no_match", message="No RAG snippets returned")
    return GroundingContextResult(status="success", context=context, snippet_count=len(documents))


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
    "RetrievedDocument",
    "application_managed_search_enabled",
    "config_value",
    "render_soc_context",
    "render_hybrid_documents",
    "result_section",
    "retrieve_hybrid_documents",
    "retrieve_grounding",
    "retrieve_soc_context",
    "retrieval_backend",
    "tenant_id_for",
]
