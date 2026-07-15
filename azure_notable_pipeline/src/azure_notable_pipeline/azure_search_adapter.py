"""Managed-identity Azure AI Search transport and document operations."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.search.documents.models import VectorizedQuery

from .azure_clients import AzureClientConfigurationError, azure_search_client


class AzureSearchAdapterError(RuntimeError):
    """A normalized Azure AI Search adapter failure."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AzureSearchAdapter:
    """Keep SDK calls and Search response handling behind one application seam."""

    def __init__(
        self,
        *,
        endpoint: str,
        index_name: str = "",
        client: Any | None = None,
        client_factory: Any | None = None,
        batch_size: int = 100,
    ) -> None:
        self.endpoint = str(endpoint or "").strip()
        self.index_name = str(index_name or "").strip()
        self._client_instance = client
        self._client_factory = client_factory or azure_search_client
        self.batch_size = max(1, int(batch_size))

    @classmethod
    def from_config(cls, config: Any, *, index_name: str = "") -> "AzureSearchAdapter":
        endpoint = _config_value(config, "AZURE_SEARCH_ENDPOINT", "")
        selected_index = index_name or _config_value(config, "RAG_AZURE_SEARCH_INDEX", "")
        if not endpoint:
            raise AzureSearchAdapterError("AZURE_SEARCH_ENDPOINT is required")
        if not selected_index:
            raise AzureSearchAdapterError("Azure AI Search index name is required")
        return cls(
            endpoint=endpoint,
            index_name=selected_index,
            batch_size=int(_config_value(config, "RAG_SEARCH_BATCH_SIZE", 100)),
        )

    def _client(self, index: str | None = None) -> Any:
        selected = str(index or self.index_name).strip()
        if not selected:
            raise AzureSearchAdapterError("Azure AI Search index name is required")
        if self._client_instance is not None:
            return self._client_instance
        try:
            return self._client_factory(self.endpoint, selected)
        except AzureClientConfigurationError as exc:
            raise AzureSearchAdapterError(str(exc)) from exc

    def hybrid_search(
        self,
        *,
        index: str | None = None,
        query_text: str,
        query_embedding: Sequence[float] | None = None,
        tenant_id: str,
        corpus_id: str,
        case_id: str = "",
        run_id: str = "",
        top_k: int = 10,
        text_fields: str = "search_text",
        vector_field: str = "embedding",
        select: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a hybrid query with mandatory tenant and corpus isolation."""

        top = _bounded_top(top_k)
        normalized_query = str(query_text or "").strip()
        if not normalized_query and not query_embedding:
            raise ValueError("query_text or query_embedding is required")
        filter_expression = build_filter(
            tenant_id=tenant_id,
            corpus_id=corpus_id,
            case_id=case_id,
            run_id=run_id,
            active_only=True,
        )
        kwargs: dict[str, Any] = {
            "search_text": normalized_query or "*",
            "filter": filter_expression,
            "top": top,
            "include_total_count": False,
        }
        if select:
            kwargs["select"] = list(select)
        if query_embedding:
            kwargs["vector_queries"] = [
                VectorizedQuery(
                    vector=[float(value) for value in query_embedding],
                    k_nearest_neighbors=top,
                    fields=text_field_name(vector_field),
                )
            ]
        try:
            pager = self._client(index).search(**kwargs)
            return [_plain_document(item) for item in pager][:top]
        except Exception as exc:
            _raise_adapter_error(exc, "Azure AI Search hybrid search")
            raise AssertionError("unreachable")

    def search(
        self,
        *,
        index: str | None = None,
        search_text: str = "*",
        filter: str | None = None,
        select: Sequence[str] | bool | None = None,
        top: int = 1000,
    ) -> list[dict[str, Any]]:
        """Run a bounded lexical query for reconciliation and diagnostics."""

        kwargs: dict[str, Any] = {
            "search_text": search_text or "*",
            "top": _bounded_top(top, maximum=10_000),
            "include_total_count": False,
        }
        if filter:
            kwargs["filter"] = filter
        if select is not False and select:
            kwargs["select"] = list(select)
        try:
            return [_plain_document(item) for item in self._client(index).search(**kwargs)]
        except Exception as exc:
            _raise_adapter_error(exc, "Azure AI Search query")
            raise AssertionError("unreachable")

    def upload_documents(
        self,
        *,
        index: str | None = None,
        documents: Iterable[Mapping[str, Any]],
    ) -> int:
        """Upload complete documents in bounded batches."""

        return self._send_documents("upload_documents", index=index, documents=documents)

    def merge_documents(
        self,
        *,
        index: str | None = None,
        documents: Iterable[Mapping[str, Any]],
    ) -> int:
        """Merge partial documents, used for tombstones and generation fences."""

        return self._send_documents("merge_documents", index=index, documents=documents)

    def delete_documents(
        self,
        *,
        index: str | None = None,
        document_ids: Iterable[str],
    ) -> int:
        """Hard-delete selected documents by key after reconciliation approval."""

        ids = [str(value).strip() for value in document_ids if str(value).strip()]
        total = 0
        for start in range(0, len(ids), self.batch_size):
            batch = [{"id": value} for value in ids[start : start + self.batch_size]]
            self._send_batch("delete_documents", index=index, documents=batch)
            total += len(batch)
        return total

    def list_ids(
        self,
        *,
        index: str | None = None,
        tenant_id: str,
        corpus_id: str,
        source_key: str = "",
        case_id: str = "",
        run_id: str = "",
        active_only: bool = True,
    ) -> list[str]:
        """List document keys within a fully scoped reconciliation query."""

        documents = self.search(
            index=index,
            filter=build_filter(
                tenant_id=tenant_id,
                corpus_id=corpus_id,
                source_key=source_key,
                case_id=case_id,
                run_id=run_id,
                active_only=active_only,
            ),
            select=["id", "document_id", "chunk_id"],
            top=10_000,
        )
        return sorted(
            {
                str(document.get("id") or document.get("document_id") or document.get("chunk_id") or "")
                for document in documents
                if str(document.get("id") or document.get("document_id") or document.get("chunk_id") or "").strip()
            }
        )

    def _send_documents(
        self,
        method: str,
        *,
        index: str | None,
        documents: Iterable[Mapping[str, Any]],
    ) -> int:
        pending = [dict(document) for document in documents]
        for document in pending:
            if not str(document.get("id", "")).strip():
                raise ValueError("Azure AI Search document requires id")
        total = 0
        for start in range(0, len(pending), self.batch_size):
            batch = pending[start : start + self.batch_size]
            self._send_batch(method, index=index, documents=batch)
            total += len(batch)
        return total

    def _send_batch(self, method: str, *, index: str | None, documents: list[dict[str, Any]]) -> None:
        try:
            response = getattr(self._client(index), method)(documents)
            for item in response or ():
                if not bool(getattr(item, "succeeded", item.get("succeeded", True) if isinstance(item, Mapping) else True)):
                    raise AzureSearchAdapterError("Azure AI Search batch contained a failed item")
        except AzureSearchAdapterError:
            raise
        except Exception as exc:
            _raise_adapter_error(exc, f"Azure AI Search {method}")


def build_filter(
    *,
    tenant_id: str,
    corpus_id: str,
    source_key: str = "",
    case_id: str = "",
    run_id: str = "",
    active_only: bool = True,
) -> str:
    """Build an escaped OData filter for a single tenant/corpus scope."""

    values = {
        "tenant_id": tenant_id,
        "corpus_id": corpus_id,
        "source_key": source_key,
        "case_id": case_id,
        "run_id": run_id,
    }
    clauses = [
        f"{field} eq '{_odata(value, field)}'"
        for field, value in values.items()
        if str(value or "").strip()
    ]
    if active_only:
        clauses.append("active eq true")
    if len(clauses) < 3:
        raise ValueError("tenant_id and corpus_id are required for Azure Search scope")
    return " and ".join(clauses)


def text_field_name(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in normalized):
        raise ValueError("Azure Search vector field name is invalid")
    return normalized


def _odata(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required for Azure Search scope")
    if len(normalized) > 512:
        raise ValueError(f"{field} exceeds Azure Search filter length limit")
    return normalized.replace("'", "''")


def _bounded_top(value: int, *, maximum: int = 1000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"top must be an integer from 1 to {maximum}")
    return value


def _config_value(config: Any, name: str, default: Any) -> Any:
    value = getattr(config, name, None)
    return value if value not in (None, "") else os.getenv(name, default)


def _plain_document(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    try:
        return dict(value)
    except (TypeError, ValueError) as exc:
        raise AzureSearchAdapterError("Azure AI Search returned a non-object document") from exc


def _raise_adapter_error(exc: Exception, operation: str) -> None:
    message = f"{operation} failed"
    if isinstance(exc, AzureSearchAdapterError):
        raise exc
    if isinstance(exc, ClientAuthenticationError):
        raise AzureSearchAdapterError(message) from exc
    if isinstance(exc, (ServiceRequestError, ServiceResponseError)):
        raise AzureSearchAdapterError(message, retryable=True) from exc
    if isinstance(exc, HttpResponseError):
        if getattr(exc, "status_code", None) in {408, 429, 500, 502, 503, 504}:
            raise AzureSearchAdapterError(message, retryable=True) from exc
        raise AzureSearchAdapterError(message) from exc
    if isinstance(exc, AzureError):
        raise AzureSearchAdapterError(message) from exc
    raise exc


__all__ = [
    "AzureSearchAdapter",
    "AzureSearchAdapterError",
    "build_filter",
]
