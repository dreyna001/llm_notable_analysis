"""Manifest-driven, application-managed Azure AI Search ingestion."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .azure_openai_gateway import embed_texts
from .azure_search_adapter import AzureSearchAdapter, build_filter
from .azure_clients import blob_service_client
from .blob_store import read_blob_result

MANIFEST_SCHEMA_VERSION = 1
_SAFE_CORPUS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SUPPORTED_SUFFIXES = {"", "csv", "json", "log", "md", "markdown", "txt"}


@dataclass(frozen=True)
class ManifestDocument:
    """One versioned Azure Blob source referenced by a manifest."""

    container: str
    blob_name: str
    version_id: str = ""
    etag: str = ""
    source_file: str = ""
    deleted: bool = False

    @property
    def key(self) -> str:
        return self.blob_name


@dataclass(frozen=True)
class RagManifest:
    manifest_schema_version: int
    manifest_id: str
    manifest_version: str
    tenant_id: str
    corpus_id: str
    documents: tuple[ManifestDocument, ...]


@dataclass(frozen=True)
class IngestionResult:
    manifest_id: str
    manifest_version: str
    corpus_id: str
    indexed_count: int
    source_count: int
    tombstoned_count: int = 0


def config_value(config: Any, name: str, default: Any = "") -> Any:
    value = getattr(config, name, None)
    return value if value not in (None, "") else os.getenv(name, default)


def validate_manifest(payload: Mapping[str, Any]) -> RagManifest:
    """Validate the manifest before reading source Blobs or mutating Search."""

    if not isinstance(payload, Mapping):
        raise ValueError("RAG manifest must be a JSON object")
    schema_version = payload.get("manifest_schema_version", payload.get("schema_version"))
    if isinstance(schema_version, bool) or int(schema_version or 0) != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported RAG manifest schema version: {schema_version}")
    manifest_id = _required(payload, "manifest_id")
    manifest_version = _required(payload, "manifest_version")
    tenant_id = _required(payload, "tenant_id")
    corpus_id = _required(payload, "corpus_id")
    if not _SAFE_CORPUS_RE.fullmatch(corpus_id):
        raise ValueError("corpus_id contains unsupported characters")
    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValueError("RAG manifest documents must be a non-empty list")

    documents: list[ManifestDocument] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_documents:
        if not isinstance(item, Mapping):
            raise ValueError("RAG manifest document entries must be objects")
        container = str(item.get("container", item.get("container_name", "")) or "").strip()
        blob_name = str(item.get("blob_name", item.get("key", "")) or "").strip().lstrip("/")
        if not container or not blob_name:
            raise ValueError("RAG manifest document requires container and blob_name")
        version_id = str(item.get("version_id", "") or "").strip()
        etag = str(item.get("etag", "") or "").strip().strip('"')
        if not version_id and not etag:
            raise ValueError(f"RAG manifest source requires version_id or etag: {container}/{blob_name}")
        identity = (container, blob_name, version_id or etag)
        if identity in seen:
            raise ValueError(f"duplicate RAG manifest document: {container}/{blob_name}")
        seen.add(identity)
        documents.append(
            ManifestDocument(
                container=container,
                blob_name=blob_name,
                version_id=version_id,
                etag=etag,
                source_file=str(item.get("source_file", "") or blob_name).strip(),
                deleted=bool(item.get("deleted", False)),
            )
        )
    return RagManifest(
        manifest_schema_version=MANIFEST_SCHEMA_VERSION,
        manifest_id=manifest_id,
        manifest_version=manifest_version,
        tenant_id=tenant_id,
        corpus_id=corpus_id,
        documents=tuple(documents),
    )


def load_manifest(
    *,
    container: str,
    blob_name: str,
    blob_store: Any | None = None,
    account_url: str | None = None,
    version_id: str = "",
    etag: str = "",
    max_bytes: int = 1_048_576,
) -> RagManifest:
    raw = _read_blob(
        container=container,
        blob_name=blob_name,
        blob_store=blob_store,
        version_id=version_id,
        etag=etag,
        max_bytes=max_bytes,
        account_url=account_url,
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("RAG manifest must be valid UTF-8 JSON") from exc
    return validate_manifest(payload)


def parse_blob_document(
    *,
    source: ManifestDocument,
    blob_store: Any | None = None,
    account_url: str | None = None,
    max_bytes: int = 5_242_880,
) -> str:
    """Read one exact version and normalize supported text document formats."""

    raw = _read_blob(
        container=source.container,
        blob_name=source.blob_name,
        blob_store=blob_store,
        version_id=source.version_id,
        etag=source.etag,
        max_bytes=max_bytes,
        account_url=account_url,
    )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"RAG document must be UTF-8 text: {source.blob_name}") from exc
    suffix = source.blob_name.rsplit("/", 1)[-1].lower().rsplit(".", 1)[-1] if "." in source.blob_name else ""
    if suffix not in _SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported RAG document type: {suffix}")
    if suffix == "json":
        try:
            return json.dumps(json.loads(text), ensure_ascii=True, sort_keys=True, indent=2)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON document: {source.blob_name}") from exc
    return text


def chunk_text(text: str, *, max_chars: int = 2500) -> list[str]:
    """Split paragraphs and enforce a hard deterministic character bound."""

    limit = max(1, int(max_chars))
    chunks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        normalized = paragraph.strip()
        if normalized:
            chunks.extend(normalized[start : start + limit] for start in range(0, len(normalized), limit))
    return chunks


def stable_document_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def build_rag_documents(
    *,
    manifest: RagManifest,
    source: ManifestDocument,
    text: str,
    config: Any,
    embedding_gateway: Any | None = None,
    embedding_client: Any | None = None,
    manifest_container: str,
    manifest_blob_name: str,
) -> list[dict[str, Any]]:
    """Build embedded Search documents with complete immutable provenance."""

    gateway = embedding_gateway if embedding_gateway is not None else embedding_client
    chunks = chunk_text(text, max_chars=int(config_value(config, "RAG_CHUNK_MAX_CHARS", 2500)))
    vectors = embed_texts(
        chunks,
        gateway=gateway,
        deployment=str(config_value(config, "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "")) or None,
    )
    expected_dimensions = int(config_value(config, "CASE_QA_VECTOR_DIMENSIONS", 1024))
    if any(len(vector) != expected_dimensions for vector in vectors):
        raise ValueError("Azure OpenAI embedding dimensions did not match configured dimensions")
    identity = source.version_id or source.etag
    return [
        {
            "id": stable_document_id(manifest.tenant_id, manifest.corpus_id, source.container, source.blob_name, identity, str(ordinal)),
            "document_id": stable_document_id(manifest.tenant_id, manifest.corpus_id, source.container, source.blob_name, identity, str(ordinal)),
            "text": chunk,
            "search_text": chunk,
            "embedding": vector,
            "tenant_id": manifest.tenant_id,
            "corpus_id": manifest.corpus_id,
            "active": True,
            "source_container": source.container,
            "source_blob_name": source.blob_name,
            "source_key": source.blob_name,
            "source_version_id": source.version_id,
            "source_etag": source.etag,
            "source_file": source.source_file,
            "manifest_id": manifest.manifest_id,
            "manifest_version": manifest.manifest_version,
            "manifest_container": manifest_container,
            "manifest_blob_name": manifest_blob_name,
            "chunk_ordinal": ordinal,
            "embedding_model": str(config_value(config, "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "")),
            "created_at": _utc_now(),
        }
        for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
    ]


def ingest_manifest(
    *,
    manifest_container: str,
    manifest_blob_name: str,
    manifest_version_id: str = "",
    manifest_etag: str = "",
    config: Any,
    blob_store: Any | None = None,
    source_account_url: str | None = None,
    embedding_gateway: Any | None = None,
    adapter: Any | None = None,
) -> IngestionResult:
    """Read one exact manifest, push new chunks, and tombstone stale chunks."""

    configured_container = str(config_value(config, "RAG_SOURCE_CONTAINER", "") or "").strip()
    configured_tenant = str(config_value(config, "RAG_TENANT_ID", "") or "").strip()
    source_prefix = str(config_value(config, "RAG_SOURCE_PREFIX", "rag-sources") or "").strip().strip("/")
    if configured_container and manifest_container != configured_container:
        raise ValueError("manifest container is outside RAG_SOURCE_CONTAINER")
    if source_prefix and not _in_prefix(manifest_blob_name, source_prefix):
        raise ValueError("manifest Blob is outside RAG_SOURCE_PREFIX")
    if not manifest_version_id and not manifest_etag:
        raise ValueError("manifest_version_id or manifest_etag is required")
    manifest = load_manifest(
        container=manifest_container,
        blob_name=manifest_blob_name,
        blob_store=blob_store,
        version_id=manifest_version_id,
        etag=manifest_etag,
        max_bytes=int(config_value(config, "RAG_INGEST_MAX_MANIFEST_BYTES", 1_048_576)),
        account_url=source_account_url or str(config_value(config, "RAG_SOURCE_STORAGE_ACCOUNT_URL", "") or "") or None,
    )
    if configured_tenant and manifest.tenant_id != configured_tenant:
        raise ValueError("RAG manifest tenant does not match configured tenant")
    index = str(config_value(config, "RAG_AZURE_SEARCH_INDEX", "") or "").strip()
    if not index:
        raise ValueError("RAG_AZURE_SEARCH_INDEX is required for RAG ingestion")
    search = adapter or AzureSearchAdapter.from_config(config, index_name=index)
    indexed_count = 0
    tombstoned_count = 0
    max_bytes = int(config_value(config, "RAG_INGEST_MAX_DOCUMENT_BYTES", 5_242_880))
    for source in manifest.documents:
        if configured_container and source.container != configured_container:
            raise ValueError(f"RAG source container is outside configured container: {source.blob_name}")
        if source_prefix and not _in_prefix(source.blob_name, source_prefix):
            raise ValueError(f"RAG source Blob is outside configured prefix: {source.blob_name}")
        old_ids = _adapter_ids(search, index=index, manifest=manifest, source=source)
        if source.deleted:
            tombstoned_count += tombstone_documents(index=index, document_ids=old_ids, adapter=search)
            continue
        text = parse_blob_document(
            source=source,
            blob_store=blob_store,
            max_bytes=max_bytes,
            account_url=source_account_url or str(config_value(config, "RAG_SOURCE_STORAGE_ACCOUNT_URL", "") or "") or None,
        )
        documents = build_rag_documents(
            manifest=manifest,
            source=source,
            text=text,
            config=config,
            embedding_gateway=embedding_gateway,
            manifest_container=manifest_container,
            manifest_blob_name=manifest_blob_name,
        )
        indexed_count += index_documents(index=index, documents=documents, adapter=search)
        current_ids = {str(document["id"]) for document in documents}
        tombstoned_count += tombstone_documents(
            index=index,
            document_ids=(document_id for document_id in old_ids if document_id not in current_ids),
            adapter=search,
        )
    return IngestionResult(
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        corpus_id=manifest.corpus_id,
        indexed_count=indexed_count,
        source_count=len(manifest.documents),
        tombstoned_count=tombstoned_count,
    )


def index_documents(*, index: str, documents: Iterable[dict[str, Any]], adapter: Any, batch_size: int = 100) -> int:
    pending = list(documents)
    total = 0
    for start in range(0, len(pending), max(1, int(batch_size))):
        batch = pending[start : start + max(1, int(batch_size))]
        if hasattr(adapter, "upload_documents"):
            adapter.upload_documents(index=index, documents=batch)
        else:
            adapter.index_documents(index=index, documents=batch)
        total += len(batch)
    return total


def tombstone_documents(*, index: str, document_ids: Iterable[str], adapter: Any) -> int:
    ids = [str(value).strip() for value in document_ids if str(value).strip()]
    if not ids:
        return 0
    body = [{"id": value, "active": False, "tombstoned_at": _utc_now()} for value in ids]
    if hasattr(adapter, "merge_documents"):
        adapter.merge_documents(index=index, documents=body)
    else:
        adapter.update_documents(index=index, documents=body)
    return len(ids)


def delete_documents(*, index: str, document_ids: Iterable[str], adapter: Any) -> int:
    ids = [str(value).strip() for value in document_ids if str(value).strip()]
    if not ids:
        return 0
    if hasattr(adapter, "delete_documents"):
        return int(adapter.delete_documents(index=index, document_ids=ids))
    return int(adapter.delete(index=index, document_ids=ids))


def reconcile_document_ids(expected_ids: Iterable[str], actual_ids: Iterable[str]) -> dict[str, list[str]]:
    expected = {str(value) for value in expected_ids}
    actual = {str(value) for value in actual_ids}
    return {
        "missing": sorted(expected - actual),
        "orphaned": sorted(actual - expected),
        "matched": sorted(expected & actual),
    }


def _adapter_ids(adapter: Any, *, index: str, manifest: RagManifest, source: ManifestDocument) -> list[str]:
    if hasattr(adapter, "list_ids"):
        return adapter.list_ids(
            index=index,
            tenant_id=manifest.tenant_id,
            corpus_id=manifest.corpus_id,
            source_key=source.blob_name,
            active_only=True,
        )
    response = adapter.search(
        index=index,
        filter=build_filter(
            tenant_id=manifest.tenant_id,
            corpus_id=manifest.corpus_id,
            source_key=source.blob_name,
            active_only=True,
        ),
        select=["id"],
        top=10_000,
    )
    return [str(item.get("id", "")) for item in response if str(item.get("id", "")).strip()]


def _read_blob(*, container: str, blob_name: str, blob_store: Any | None, version_id: str, etag: str, max_bytes: int, account_url: str | None = None) -> bytes:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    service = blob_store
    if service is None and version_id:
        selected_url = account_url or os.getenv("RAG_SOURCE_STORAGE_ACCOUNT_URL", "")
        if not selected_url:
            raise ValueError("RAG_SOURCE_STORAGE_ACCOUNT_URL is required for versioned Blob reads")
        service = blob_service_client(selected_url)
    if service is not None and hasattr(service, "get_blob_client"):
        client = service.get_blob_client(container=container, blob=blob_name, version_id=version_id or None)
        properties = client.get_blob_properties()
        size = int(getattr(properties, "size", 0) or 0)
        if size > max_bytes:
            raise ValueError(f"RAG document exceeds configured size limit: {blob_name}")
        observed_etag = str(getattr(properties, "etag", "") or "").strip('"')
        if etag and observed_etag and observed_etag != etag:
            raise ValueError(f"RAG Blob ETag changed while reading: {blob_name}")
        body = client.download_blob().readall()
    else:
        result = read_blob_result(
            container,
            blob_name,
            max_bytes=max_bytes,
            store=blob_store,
        )
        observed_etag = result.info.etag.strip('"')
        if etag and observed_etag and observed_etag != etag:
            raise ValueError(f"RAG Blob ETag changed while reading: {blob_name}")
        body = result.body
    if not isinstance(body, bytes):
        body = bytes(body)
    if len(body) > max_bytes:
        raise ValueError(f"RAG document exceeds configured size limit: {blob_name}")
    return body


def _required(payload: Mapping[str, Any], name: str) -> str:
    value = str(payload.get(name, "") or "").strip()
    if not value:
        raise ValueError(f"RAG manifest field {name} is required")
    return value


def _in_prefix(value: str, prefix: str) -> bool:
    return value == prefix or value.startswith(f"{prefix}/")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "IngestionResult",
    "ManifestDocument",
    "RagManifest",
    "build_rag_documents",
    "chunk_text",
    "config_value",
    "delete_documents",
    "index_documents",
    "ingest_manifest",
    "load_manifest",
    "parse_blob_document",
    "reconcile_document_ids",
    "stable_document_id",
    "tombstone_documents",
    "validate_manifest",
]
