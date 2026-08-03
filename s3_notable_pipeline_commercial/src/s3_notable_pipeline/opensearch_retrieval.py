"""Tenant-scoped hybrid retrieval and provenance for application-owned RAG."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

from .config import Config
from .opensearch_client import OpenSearchClient

SUPPORTED_BACKENDS = {"opensearch", "bedrock_kb", "legacy"}


@dataclass(frozen=True)
class RetrievedDocument:
    """Normalized OpenSearch result with durable source provenance."""

    document_id: str
    text: str
    score: float
    tenant_id: str
    corpus_id: str
    case_id: str = ""
    chunk_id: str = ""
    source_bucket: str = ""
    source_key: str = ""
    source_version_id: str = ""
    source_etag: str = ""
    source_file: str = ""
    section: str = ""
    metadata: dict[str, Any] | None = None


def config_value(config: Any, name: str, default: Any = "") -> Any:
    """Read an optional Config attribute before its environment contract."""

    value = getattr(config, name, None)
    if value not in (None, ""):
        return value
    return os.getenv(name, default)


def retrieval_backend(config: Any, *, case: bool = False) -> str:
    """Select OpenSearch when configured and retain current paths otherwise."""

    explicit = str(config_value(config, "RAG_RETRIEVAL_BACKEND", "")).strip().lower()
    if explicit:
        if explicit not in SUPPORTED_BACKENDS:
            raise ValueError("RAG_RETRIEVAL_BACKEND must be opensearch, bedrock_kb, or legacy")
        return explicit
    if str(config_value(config, "OPENSEARCH_ENDPOINT", "")).strip():
        return "opensearch"
    return "legacy" if case else "bedrock_kb"


def opensearch_enabled(config: Any, *, case: bool = False) -> bool:
    """Return whether the selected backend is application-managed OpenSearch."""

    return (
        retrieval_backend(config, case=case) == "opensearch"
        and bool(str(config_value(config, "OPENSEARCH_ENDPOINT", "")).strip())
    )


def tenant_id_for(config: Any, *, required: bool = False) -> str:
    value = str(config_value(config, "RAG_TENANT_ID", "")).strip()
    if required and not value:
        raise ValueError("RAG_TENANT_ID is required for OpenSearch retrieval")
    return value


def build_scoped_hybrid_query(
    *,
    query_text: str,
    query_embedding: list[float] | None,
    tenant_id: str,
    corpus_id: str,
    case_id: str = "",
    lexical_field: str = "search_text",
    vector_field: str = "embedding",
    top_k: int = 10,
) -> dict[str, Any]:
    """Build a lexical/vector query with mandatory tenant and corpus scope."""

    if not tenant_id.strip() or not corpus_id.strip():
        raise ValueError("tenant_id and corpus_id are required for OpenSearch queries")
    filters: list[dict[str, Any]] = [
        {"term": {"tenant_id.keyword": tenant_id}},
        {"term": {"corpus_id.keyword": corpus_id}},
        {"term": {"active": True}},
    ]
    if case_id.strip():
        filters.append({"term": {"case_id.keyword": case_id}})
    should: list[dict[str, Any]] = []
    if query_text.strip():
        should.append({"match": {lexical_field: {"query": query_text, "operator": "or"}}})
    if query_embedding:
        should.append({"knn": {vector_field: {"vector": query_embedding, "k": max(1, int(top_k))}}})
    if not should:
        raise ValueError("query_text or query_embedding is required")
    return {
        "query": {
            "bool": {
                "filter": filters,
                "should": should,
                "minimum_should_match": 1,
            }
        },
        "_source": {"excludes": [vector_field]},
    }


def retrieve_documents(
    *,
    query_text: str,
    index: str,
    tenant_id: str,
    corpus_id: str,
    top_k: int,
    adapter: Any,
    query_embedding: list[float] | None = None,
    case_id: str = "",
) -> list[RetrievedDocument]:
    """Execute one scoped hybrid query and normalize hits with provenance."""

    query = build_scoped_hybrid_query(
        query_text=query_text,
        query_embedding=query_embedding,
        tenant_id=tenant_id,
        corpus_id=corpus_id,
        case_id=case_id,
        top_k=top_k,
    )
    response = adapter.search(index=index, query=query, size=top_k)
    hits = response.get("hits", {}).get("hits", []) if isinstance(response, dict) else []
    documents: list[RetrievedDocument] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        provenance = _provenance(source)
        if isinstance(metadata.get("provenance"), dict):
            provenance.update(
                {str(key): str(value) for key, value in metadata["provenance"].items()}
            )
        documents.append(
            RetrievedDocument(
                document_id=str(hit.get("_id", source.get("chunk_id", ""))),
                text=str(source.get("text") or source.get("search_text") or "").strip(),
                score=float(hit.get("_score", 0.0) or 0.0),
                tenant_id=str(source.get("tenant_id", tenant_id)),
                corpus_id=str(source.get("corpus_id", corpus_id)),
                case_id=str(source.get("case_id", "")),
                chunk_id=str(source.get("chunk_id", "")),
                source_bucket=str(source.get("source_bucket", "")),
                source_key=str(source.get("source_key", "")),
                source_version_id=str(source.get("source_version_id", "")),
                source_etag=str(source.get("source_etag", "")),
                source_file=str(source.get("source_file", "")),
                section=str(source.get("section", "")),
                metadata={**metadata, "provenance": provenance},
            )
        )
    return documents


def render_documents(documents: Iterable[RetrievedDocument], *, budget_chars: int, header: str = "") -> str:
    """Render advisory snippets with source, scope, and document provenance."""

    rendered = [header] if header else []
    remaining = max(0, int(budget_chars) - (len(header) + 1 if header else 0))
    for index, document in enumerate(documents, 1):
        if not document.text or remaining <= 0:
            continue
        source = document.source_file or document.source_key or "opensearch"
        provenance = f"{source} :: {document.section or 'root'}"
        prefix = f"[{index}] [{provenance}] "
        snippet = document.text[: max(0, remaining - len(prefix))].strip()
        if not snippet:
            continue
        line = prefix + snippet
        rendered.append(line)
        remaining -= len(line) + 1
    if not rendered or (header and len(rendered) == 1):
        return ""
    return "\n".join(rendered)


def _provenance(source: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(source.get(key, ""))
        for key in (
            "tenant_id",
            "corpus_id",
            "case_id",
            "chunk_id",
            "source_bucket",
            "source_key",
            "source_version_id",
            "source_etag",
            "source_file",
            "manifest_id",
            "manifest_version",
            "embedding_model",
        )
    }


def adapter_for(config: Any, adapter: Any | None = None) -> Any:
    """Return an injected adapter or construct the configured signed client."""

    return adapter or OpenSearchClient.from_config(config)
