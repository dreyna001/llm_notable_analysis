"""Application-managed RAG ingestion for S3 corpora and case chunks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

from .case_embed import embed_text
from .kb_document_extract import (
    FAIL_SOFT_STATUSES,
    extract_kb_document,
    is_media_suffix,
)
from .opensearch_retrieval import config_value
from .runtime_security import read_bounded_bytes

MANIFEST_SCHEMA_VERSION = 1
_SAFE_CORPUS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CANONICAL_CORPUS_IDS = {
    "soc": "soc",
    "soc_knowledge": "soc",
    "soc_operational_knowledge": "soc",
    "spl": "spl",
    "splunk": "spl",
    "spl_dictionary": "spl",
    "splunk_data_dictionary": "spl",
    "elastic": "elastic",
    "elasticsearch": "elastic",
    "elastic_dictionary": "elastic",
    "elastic_data_dictionary": "elastic",
    "closed_ticket": "closed_tickets",
    "closed_tickets": "closed_tickets",
}
_DEFAULT_EXTRACT_CONFIG = SimpleNamespace(
    KB_EXTRACT_MAX_BYTES=10_485_760,
    KB_EXTRACT_MAX_PDF_PAGES=50,
    KB_EXTRACT_MAX_OUTPUT_CHARS=12_000,
)


@dataclass(frozen=True)
class ManifestDocument:
    """One versioned S3 source referenced by a RAG manifest."""

    bucket: str
    key: str
    version_id: str = ""
    etag: str = ""
    source_file: str = ""
    deleted: bool = False


@dataclass(frozen=True)
class RagManifest:
    """Validated, versioned corpus manifest."""

    manifest_schema_version: int
    manifest_id: str
    manifest_version: str
    tenant_id: str
    corpus_id: str
    documents: tuple[ManifestDocument, ...]


@dataclass(frozen=True)
class ParsedS3Document:
    """Parsed manifest source content and optional extraction metadata."""

    text: str
    extraction_status: str = "extracted"
    extraction_detail: str = ""
    source_suffix: str = ""


@dataclass(frozen=True)
class IngestionResult:
    """Summary of one manifest import."""

    manifest_id: str
    manifest_version: str
    corpus_id: str
    indexed_count: int
    source_count: int
    tombstoned_count: int = 0
    extraction_reports: tuple[dict[str, Any], ...] = ()


def validate_manifest(payload: Mapping[str, Any]) -> RagManifest:
    """Validate the versioned manifest before any S3 read or indexing."""

    if not isinstance(payload, Mapping):
        raise ValueError("RAG manifest must be a JSON object")
    schema_version = payload.get("manifest_schema_version", payload.get("schema_version"))
    if int(schema_version or 0) != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported RAG manifest schema version: {schema_version}")
    manifest_id = _required_string(payload, "manifest_id")
    manifest_version = _required_string(payload, "manifest_version")
    tenant_id = _required_string(payload, "tenant_id")
    supplied_corpus_id = _required_string(payload, "corpus_id")
    if not _SAFE_CORPUS_RE.fullmatch(supplied_corpus_id):
        raise ValueError("corpus_id contains unsupported characters")
    corpus_id = _canonical_corpus_id(supplied_corpus_id)
    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValueError("RAG manifest documents must be a non-empty list")
    documents: list[ManifestDocument] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_documents:
        if not isinstance(item, Mapping):
            raise ValueError("RAG manifest document entries must be objects")
        bucket = _required_string(item, "bucket")
        key = _required_string(item, "key")
        version_id = str(item.get("version_id", "") or "").strip()
        etag = str(item.get("etag", "") or "").strip().strip('"')
        if not version_id and not etag:
            raise ValueError(f"RAG manifest source requires version_id or etag: {bucket}/{key}")
        identity = (bucket, key, version_id or etag)
        if identity in seen:
            raise ValueError(f"duplicate RAG manifest document: {bucket}/{key}")
        seen.add(identity)
        documents.append(
            ManifestDocument(
                bucket=bucket,
                key=key,
                version_id=version_id,
                etag=etag,
                source_file=str(item.get("source_file", "") or key).strip(),
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
    bucket: str,
    key: str,
    s3_client: Any,
    version_id: str = "",
    etag: str = "",
    max_bytes: int = 262_144,
) -> RagManifest:
    """Load and validate one manifest object from S3."""

    response = _get_exact_object(
        bucket=bucket,
        key=key,
        s3_client=s3_client,
        version_id=version_id,
        etag=etag,
    )
    content_length = response.get("ContentLength")
    if content_length is not None and int(content_length) > max_bytes:
        raise ValueError("RAG manifest exceeds configured size limit")
    payload = _json_body(response.get("Body"), max_bytes=max_bytes)
    return validate_manifest(payload)


def parse_s3_document(
    *,
    bucket: str,
    key: str,
    s3_client: Any,
    version_id: str = "",
    etag: str = "",
    max_bytes: int | None = None,
    config: Any | None = None,
    textract_client: Any | None = None,
) -> ParsedS3Document:
    """Parse bounded text from text, JSON, CSV, PDF, DOCX, or image S3 content."""

    response = _get_exact_object(
        bucket=bucket,
        key=key,
        s3_client=s3_client,
        version_id=version_id,
        etag=etag,
    )
    content_length = response.get("ContentLength")
    if max_bytes is not None and content_length is not None and int(content_length) > max_bytes:
        raise ValueError(f"RAG document exceeds configured size limit: {key}")
    limit = max_bytes if max_bytes is not None else 20_971_520
    raw = read_bounded_bytes(
        response.get("Body"), max_bytes=limit, setting_name="RAG_INGEST_MAX_DOCUMENT_BYTES"
    )
    suffix = _document_suffix(key)
    if suffix == "json":
        text = raw.decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON document: {key}") from exc
        normalized = json.dumps(parsed, ensure_ascii=True, sort_keys=True, indent=2)
        return ParsedS3Document(text=normalized, source_suffix=suffix)
    if suffix in {"md", "markdown", "txt", "csv", "log"} or suffix == "":
        return ParsedS3Document(text=raw.decode("utf-8"), source_suffix=suffix)
    if is_media_suffix(suffix):
        media_limit = limit
        if config is not None:
            media_limit = min(
                media_limit,
                int(config_value(config, "KB_EXTRACT_MAX_BYTES", 10_485_760)),
            )
        if len(raw) > media_limit:
            raise ValueError(f"RAG media document exceeds configured size limit: {key}")
        extraction = extract_kb_document(
            raw,
            suffix=suffix,
            config=config or _DEFAULT_EXTRACT_CONFIG,
            textract_client=textract_client,
        )
        return ParsedS3Document(
            text=extraction.text,
            extraction_status=extraction.extraction_status,
            extraction_detail=extraction.extraction_detail,
            source_suffix=extraction.source_suffix,
        )
    raise ValueError(f"unsupported RAG document type: {suffix}")


def chunk_text(text: str, *, max_chars: int = 2500) -> list[str]:
    """Split text at paragraph boundaries, then enforce a hard size bound."""

    limit = max(1, int(max_chars))
    chunks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        normalized = paragraph.strip()
        if not normalized:
            continue
        chunks.extend(normalized[start : start + limit] for start in range(0, len(normalized), limit))
    return chunks


def build_rag_documents(
    *,
    manifest: RagManifest,
    source: ManifestDocument,
    text: str,
    config: Any,
    bedrock_client: Any,
    manifest_bucket: str,
    manifest_key: str,
    extraction_metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Chunk, embed, and attach complete source provenance to one document."""

    chunks = chunk_text(text, max_chars=int(config_value(config, "RAG_CHUNK_MAX_CHARS", 2500)))
    metadata = dict(extraction_metadata or {})
    documents: list[dict[str, Any]] = []
    for ordinal, chunk in enumerate(chunks):
        document_id = stable_document_id(
            manifest.tenant_id,
            manifest.corpus_id,
            source.bucket,
            source.key,
            source.version_id or source.etag,
            str(ordinal),
        )
        document = {
            "document_id": document_id,
            "text": chunk,
            "search_text": chunk,
            "embedding": embed_text(chunk, config, bedrock_client),
            "tenant_id": manifest.tenant_id,
            "corpus_id": manifest.corpus_id,
            "active": True,
            "source_bucket": source.bucket,
            "source_key": source.key,
            "source_version_id": source.version_id,
            "source_etag": source.etag,
            "source_file": source.source_file,
            "manifest_id": manifest.manifest_id,
            "manifest_version": manifest.manifest_version,
            "manifest_bucket": manifest_bucket,
            "manifest_key": manifest_key,
            "chunk_ordinal": ordinal,
            "embedding_model": str(getattr(config, "CASE_QA_EMBEDDING_MODEL", "")),
            "created_at": _utc_now(),
        }
        if metadata:
            document["extraction_metadata"] = metadata
        documents.append(document)
    return documents


def index_documents(
    *,
    index: str,
    documents: Iterable[dict[str, Any]],
    adapter: Any,
    batch_size: int = 100,
) -> int:
    """Bulk index documents in bounded batches and return the item count."""

    pending = list(documents)
    count = 0
    for start in range(0, len(pending), max(1, int(batch_size))):
        batch = pending[start : start + max(1, int(batch_size))]
        adapter.bulk(
            index=index,
            actions=[
                {"operation": "index", "id": str(document["document_id"]), "document": document}
                for document in batch
            ],
        )
        count += len(batch)
    return count


def tombstone_documents(*, index: str, document_ids: Iterable[str], adapter: Any) -> int:
    """Mark documents inactive so stale content cannot be retrieved."""

    ids = [str(document_id).strip() for document_id in document_ids if str(document_id).strip()]
    if not ids:
        return 0
    adapter.bulk(
        index=index,
        actions=[
            {
                "operation": "update",
                "id": document_id,
                "document": {"active": False, "tombstoned_at": _utc_now()},
            }
            for document_id in ids
        ],
    )
    return len(ids)


def delete_source_documents(
    *,
    index: str,
    tenant_id: str,
    corpus_id: str,
    source_key: str,
    adapter: Any,
) -> dict[str, Any]:
    """Delete one source version only within its tenant and corpus scope."""

    query = {
        "bool": {
            "filter": [
                {"term": {"tenant_id.keyword": tenant_id}},
                {"term": {"corpus_id.keyword": corpus_id}},
                {"term": {"source_key.keyword": source_key}},
            ]
        }
    }
    return adapter.delete_by_query(index=index, query=query)


def reconcile_document_ids(expected_ids: Iterable[str], actual_ids: Iterable[str]) -> dict[str, list[str]]:
    """Return deterministic missing, orphan, and common document IDs."""

    expected = {str(value) for value in expected_ids}
    actual = {str(value) for value in actual_ids}
    return {
        "missing": sorted(expected - actual),
        "orphaned": sorted(actual - expected),
        "matched": sorted(expected & actual),
    }


def case_chunk_document(
    *,
    chunk: Mapping[str, Any],
    embedding: list[float],
    bucket: str,
    envelope_key: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Convert an embedded case chunk into the shared OpenSearch document shape."""

    case_id = str(chunk.get("case_id", "")).strip()
    chunk_id = str(chunk.get("chunk_id", "")).strip()
    if not case_id or not chunk_id or not tenant_id.strip():
        raise ValueError("case OpenSearch documents require tenant, case, and chunk IDs")
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    return {
        "document_id": chunk_id,
        "chunk_id": chunk_id,
        "case_id": case_id,
        "tenant_id": tenant_id,
        "corpus_id": "case_chunks",
        "active": True,
        "text": str(chunk.get("text", "")),
        "search_text": str(chunk.get("search_text", "")),
        "embedding": embedding,
        "embedding_model": str(chunk.get("embedding_model", "")),
        "source_bucket": bucket,
        "source_key": envelope_key,
        "source_file": str(metadata.get("source_filename", "")),
        "section": str(chunk.get("section", "")),
        "field_path": str(chunk.get("field_path", "")),
        "metadata": dict(metadata),
        "created_at": _utc_now(),
    }


def index_case_chunks(
    *,
    index: str,
    case_id: str,
    tenant_id: str,
    documents: Iterable[dict[str, Any]],
    adapter: Any,
    batch_size: int = 100,
) -> int:
    """Replace one scoped case's active OpenSearch chunks atomically enough for replay."""

    pending_documents = list(documents)
    if hasattr(adapter, "ensure_vector_index"):
        dimensions = len(pending_documents[0].get("embedding", [])) if pending_documents else 1
        adapter.ensure_vector_index(index=index, dimensions=dimensions)
    adapter.delete_by_query(
        index=index,
        query={
            "bool": {
                "filter": [
                    {"term": {"tenant_id.keyword": tenant_id}},
                    {"term": {"corpus_id.keyword": "case_chunks"}},
                    {"term": {"case_id.keyword": case_id}},
                ]
            }
        },
    )
    return index_documents(
        index=index,
        documents=pending_documents,
        adapter=adapter,
        batch_size=batch_size,
    )


def closed_ticket_chunk_document(
    *,
    chunk: Any,
    embedding: list[float],
    bucket: str,
    version_key: str,
    tenant_id: str,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """Convert one closed-ticket chunk into the shared OpenSearch document shape."""

    ticket_id = str(getattr(chunk, "ticket_id", "") or "").strip()
    chunk_id = str(getattr(chunk, "chunk_id", "") or "").strip()
    if not ticket_id or not chunk_id or not tenant_id.strip():
        raise ValueError("closed ticket OpenSearch documents require tenant, ticket, and chunk IDs")
    metadata = getattr(chunk, "metadata", None)
    metadata_dict = dict(metadata) if isinstance(metadata, dict) else {}
    if content_hash:
        metadata_dict.setdefault("content_hash", content_hash)
    return {
        "document_id": chunk_id,
        "chunk_id": chunk_id,
        "ticket_id": ticket_id,
        "tenant_id": tenant_id,
        "corpus_id": "closed_tickets",
        "active": True,
        "text": str(getattr(chunk, "text", "")),
        "search_text": str(getattr(chunk, "search_text", "")),
        "embedding": embedding,
        "embedding_model": str(getattr(chunk, "embedding_model", "")),
        "source_bucket": bucket,
        "source_key": version_key,
        "source_file": metadata_dict.get("ticket_number") or ticket_id,
        "section": str(getattr(chunk, "section", "")),
        "field_path": str(getattr(chunk, "field_path", "")),
        "metadata": metadata_dict,
        "created_at": _utc_now(),
    }


def index_closed_ticket_chunks(
    *,
    index: str,
    ticket_id: str,
    tenant_id: str,
    documents: Iterable[dict[str, Any]],
    adapter: Any,
    batch_size: int = 100,
) -> int:
    """Replace one ticket's active OpenSearch chunks without leaving duplicate actives."""

    pending_documents = list(documents)
    if hasattr(adapter, "ensure_vector_index"):
        dimensions = len(pending_documents[0].get("embedding", [])) if pending_documents else 1
        adapter.ensure_vector_index(index=index, dimensions=dimensions)
    previous_document_ids = active_closed_ticket_document_ids(
        index=index,
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        adapter=adapter,
    )
    indexed_count = index_documents(
        index=index,
        documents=pending_documents,
        adapter=adapter,
        batch_size=batch_size,
    )
    current_document_ids = {str(document["document_id"]) for document in pending_documents}
    tombstone_documents(
        index=index,
        document_ids=(
            document_id
            for document_id in previous_document_ids
            if document_id not in current_document_ids
        ),
        adapter=adapter,
    )
    return indexed_count


def tombstone_closed_ticket_chunks(
    *,
    index: str,
    tenant_id: str,
    ticket_id: str,
    adapter: Any,
) -> int:
    """Tombstone all active chunks for one closed ticket within tenant scope."""

    return tombstone_documents(
        index=index,
        document_ids=active_closed_ticket_document_ids(
            index=index,
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            adapter=adapter,
        ),
        adapter=adapter,
    )


def active_closed_ticket_document_ids(
    *,
    index: str,
    tenant_id: str,
    ticket_id: str,
    adapter: Any,
) -> list[str]:
    """Return active chunk IDs for one closed ticket within its tenant and corpus."""

    response = adapter.search(
        index=index,
        query={
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id.keyword": tenant_id}},
                        {"term": {"corpus_id.keyword": "closed_tickets"}},
                        {"term": {"ticket_id.keyword": ticket_id}},
                        {"term": {"active": True}},
                    ]
                }
            },
            "_source": False,
        },
        size=10_000,
    )
    hits = response.get("hits", {}).get("hits", []) if isinstance(response, dict) else []
    return [str(hit.get("_id", "")) for hit in hits if isinstance(hit, dict) and hit.get("_id")]


def ingest_manifest(
    *,
    manifest_bucket: str,
    manifest_key: str,
    manifest_version_id: str,
    manifest_etag: str,
    config: Any,
    s3_client: Any,
    bedrock_client: Any,
    adapter: Any,
    textract_client: Any | None = None,
) -> IngestionResult:
    """Import one exact manifest and tombstone superseded source versions."""

    from .opensearch_retrieval import config_value

    if textract_client is None:
        from .aws_clients import textract_client as _textract_client_factory

        textract_client = _textract_client_factory()

    configured_bucket = str(config_value(config, "RAG_SOURCE_BUCKET", "")).strip()
    configured_tenant = str(config_value(config, "RAG_TENANT_ID", "")).strip()
    source_prefix = str(config_value(config, "RAG_SOURCE_PREFIX", "rag-sources")).strip().strip("/")
    if not configured_bucket:
        raise ValueError("RAG_SOURCE_BUCKET is required for RAG ingestion")
    if manifest_bucket != configured_bucket:
        raise ValueError("manifest bucket is outside RAG_SOURCE_BUCKET")
    if source_prefix and not _is_key_in_prefix(manifest_key, source_prefix):
        raise ValueError("manifest key is outside RAG_SOURCE_PREFIX")
    if not configured_tenant:
        raise ValueError("RAG_TENANT_ID is required for RAG ingestion")
    if not manifest_version_id and not manifest_etag:
        raise ValueError("manifest_version_id or manifest_etag is required")

    manifest = load_manifest(
        bucket=manifest_bucket,
        key=manifest_key,
        s3_client=s3_client,
        version_id=manifest_version_id,
        etag=manifest_etag,
        max_bytes=int(config_value(config, "RAG_INGEST_MAX_MANIFEST_BYTES", 262_144)),
    )
    max_documents = int(config_value(config, "RAG_INGEST_MAX_DOCUMENTS_PER_MANIFEST", 100))
    if len(manifest.documents) > max_documents:
        raise ValueError("RAG manifest exceeds configured document count limit")
    if manifest.tenant_id != configured_tenant:
        raise ValueError("RAG manifest tenant does not match configured tenant")
    index = _index_for_corpus(manifest.corpus_id, config)
    if hasattr(adapter, "ensure_vector_index"):
        adapter.ensure_vector_index(
            index=index,
            dimensions=int(config_value(config, "CASE_QA_VECTOR_DIMENSIONS", 1024)),
        )
    max_bytes = int(config_value(config, "RAG_INGEST_MAX_DOCUMENT_BYTES", 5_242_880))
    batch_size = int(config_value(config, "OPENSEARCH_BULK_BATCH_SIZE", 100))
    indexed_count = 0
    tombstoned_count = 0
    total_source_bytes = 0
    total_embeddings = 0
    extraction_reports: list[dict[str, Any]] = []
    max_total_source_bytes = int(
        config_value(config, "RAG_INGEST_MAX_TOTAL_SOURCE_BYTES", 52_428_800)
    )
    max_embeddings = int(
        config_value(config, "RAG_INGEST_MAX_EMBEDDINGS_PER_MANIFEST", 2_000)
    )
    for source in manifest.documents:
        if source.bucket != configured_bucket:
            raise ValueError(f"RAG source bucket is outside configured bucket: {source.key}")
        if source_prefix and not _is_key_in_prefix(source.key, source_prefix):
            raise ValueError(f"RAG source key is outside configured prefix: {source.key}")
        if source.deleted:
            tombstoned_count += tombstone_source_documents(
                index=index,
                tenant_id=manifest.tenant_id,
                corpus_id=manifest.corpus_id,
                source_key=source.key,
                adapter=adapter,
            )
            continue
        parsed = parse_s3_document(
            bucket=source.bucket,
            key=source.key,
            s3_client=s3_client,
            version_id=source.version_id,
            etag=source.etag,
            max_bytes=max_bytes,
            config=config,
            textract_client=textract_client,
        )
        report_entry = {
            "source_key": source.key,
            "source_file": source.source_file,
            "source_suffix": parsed.source_suffix,
            "extraction_status": parsed.extraction_status,
            "extraction_detail": parsed.extraction_detail,
            "indexed": False,
        }
        if not parsed.text.strip():
            if parsed.extraction_status in FAIL_SOFT_STATUSES:
                extraction_reports.append(report_entry)
                continue
            detail = parsed.extraction_detail or parsed.extraction_status
            raise ValueError(f"RAG document produced no indexable text: {source.key} ({detail})")
        report_entry["indexed"] = True
        extraction_reports.append(report_entry)
        text = parsed.text
        extraction_metadata = {
            "extraction_status": parsed.extraction_status,
            "extraction_detail": parsed.extraction_detail,
            "source_suffix": parsed.source_suffix,
        }
        total_source_bytes += len(text.encode("utf-8"))
        if total_source_bytes > max_total_source_bytes:
            raise ValueError("RAG manifest exceeds configured total source byte limit")
        chunk_count = len(
            chunk_text(text, max_chars=int(config_value(config, "RAG_CHUNK_MAX_CHARS", 2500)))
        )
        total_embeddings += chunk_count
        if total_embeddings > max_embeddings:
            raise ValueError("RAG manifest exceeds configured embedding count limit")
        documents = build_rag_documents(
            manifest=manifest,
            source=source,
            text=text,
            config=config,
            bedrock_client=bedrock_client,
            manifest_bucket=manifest_bucket,
            manifest_key=manifest_key,
            extraction_metadata=extraction_metadata,
        )
        previous_document_ids = active_source_document_ids(
            index=index,
            tenant_id=manifest.tenant_id,
            corpus_id=manifest.corpus_id,
            source_key=source.key,
            adapter=adapter,
        )
        indexed_count += index_documents(
            index=index,
            documents=documents,
            adapter=adapter,
            batch_size=batch_size,
        )
        current_document_ids = {str(document["document_id"]) for document in documents}
        tombstoned_count += tombstone_documents(
            index=index,
            document_ids=(document_id for document_id in previous_document_ids if document_id not in current_document_ids),
            adapter=adapter,
        )
    return IngestionResult(
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        corpus_id=manifest.corpus_id,
        indexed_count=indexed_count,
        source_count=len(manifest.documents),
        tombstoned_count=tombstoned_count,
        extraction_reports=tuple(extraction_reports),
    )


def tombstone_source_documents(
    *,
    index: str,
    tenant_id: str,
    corpus_id: str,
    source_key: str,
    adapter: Any,
) -> int:
    """Find and tombstone all active chunks for one scoped source key."""

    return tombstone_documents(
        index=index,
        document_ids=active_source_document_ids(
            index=index,
            tenant_id=tenant_id,
            corpus_id=corpus_id,
            source_key=source_key,
            adapter=adapter,
        ),
        adapter=adapter,
    )


def active_source_document_ids(
    *,
    index: str,
    tenant_id: str,
    corpus_id: str,
    source_key: str,
    adapter: Any,
) -> list[str]:
    """Return active chunk IDs for one source within its tenant and corpus."""

    response = adapter.search(
        index=index,
        query={
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id.keyword": tenant_id}},
                        {"term": {"corpus_id.keyword": corpus_id}},
                        {"term": {"source_key.keyword": source_key}},
                        {"term": {"active": True}},
                    ]
                }
            },
            "_source": False,
        },
        size=10_000,
    )
    hits = response.get("hits", {}).get("hits", []) if isinstance(response, dict) else []
    return [str(hit.get("_id", "")) for hit in hits if isinstance(hit, dict) and hit.get("_id")]


def stable_document_id(*parts: str) -> str:
    """Build a replay-safe ID from immutable source identity."""

    return hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, "") or "").strip()
    if not value:
        raise ValueError(f"RAG manifest field {key} is required")
    return value


def _get_exact_object(
    *,
    bucket: str,
    key: str,
    s3_client: Any,
    version_id: str,
    etag: str,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
    if version_id:
        kwargs["VersionId"] = version_id
    elif etag:
        kwargs["IfMatch"] = etag
    response = s3_client.get_object(**kwargs)
    response_etag = str(response.get("ETag", "")).strip().strip('"')
    if etag and response_etag and response_etag != etag.strip().strip('"'):
        raise ValueError(f"S3 object ETag changed while reading: {key}")
    if version_id and response.get("VersionId") and str(response["VersionId"]) != version_id:
        raise ValueError(f"S3 object version changed while reading: {key}")
    return response


def _document_suffix(key: str) -> str:
    filename = key.rsplit("/", 1)[-1].lower()
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1]


def _index_for_corpus(corpus_id: str, config: Any) -> str:
    from .opensearch_retrieval import config_value

    normalized = _canonical_corpus_id(corpus_id)
    if normalized == "soc":
        name = "OPENSEARCH_SOC_INDEX"
        default = "notable-soc-knowledge"
    elif normalized == "spl":
        name = "OPENSEARCH_SPLUNK_INDEX"
        default = "notable-splunk-dictionary"
    elif normalized == "elastic":
        name = "OPENSEARCH_ELASTIC_INDEX"
        default = "notable-elastic-dictionary"
    elif normalized == "closed_tickets":
        name = "OPENSEARCH_CLOSED_TICKET_INDEX"
        default = "closed_tickets"
    else:
        raise ValueError(f"unsupported RAG corpus_id: {corpus_id}")
    return str(config_value(config, name, default)).strip()


def _canonical_corpus_id(corpus_id: str) -> str:
    """Return the stable corpus filter value for a supported manifest alias."""

    normalized = corpus_id.strip().lower()
    try:
        return _CANONICAL_CORPUS_IDS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported RAG corpus_id: {corpus_id}") from exc


def _is_key_in_prefix(key: str, prefix: str) -> bool:
    return key == prefix or key.startswith(prefix + "/")


def _json_body(body: Any, *, max_bytes: int) -> dict[str, Any]:
    raw = read_bounded_bytes(
        body, max_bytes=max_bytes, setting_name="RAG_INGEST_MAX_MANIFEST_BYTES"
    )
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("RAG manifest must be a JSON object")
    return parsed


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
