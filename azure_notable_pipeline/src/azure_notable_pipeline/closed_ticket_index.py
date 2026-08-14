"""Azure AI Search indexing for closed-ticket hybrid retrieval chunks."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .azure_openai_gateway import embed_texts
from .azure_search_adapter import AzureSearchAdapter, build_filter
from .azure_search_retrieval import tenant_id_for
from .blob_store import read_blob
from .closed_ticket_attachment_extract import (
    ClosedTicketAttachmentInput,
    build_attachment_semantic_metadata,
)
from .closed_ticket_render import (
    ClosedTicketAttachmentRecord,
    ClosedTicketChunkRecord,
    ClosedTicketRecord,
    build_closed_ticket_chunks,
)
from .config import Config
from .cosmos_store import CosmosStore

logger = logging.getLogger(__name__)

_CORPUS_ID = "closed_tickets"


def _ticket_scope_filter(*, tenant_id: str, ticket_id: str) -> str:
    escaped_ticket = str(ticket_id or "").strip().replace("'", "''")
    return (
        f"{build_filter(tenant_id=tenant_id, corpus_id=_CORPUS_ID, active_only=True)} "
        f"and ticket_id eq '{escaped_ticket}'"
    )


@dataclass(frozen=True)
class ClosedTicketIndexResult:
    ticket_id: str
    chunk_count: int
    status: str
    skipped: bool = False
    error: str | None = None


@dataclass
class ClosedTicketPendingIndexResult:
    selected: int = 0
    ready: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _ticket_is_indexable(record: ClosedTicketRecord) -> bool:
    if not record.is_active:
        return False
    if record.expires_at is not None:
        now = datetime.now(record.expires_at.tzinfo or UTC)
        if record.expires_at <= now:
            return False
    return True


def _load_envelope(
    *,
    config: Config,
    blob_service: Any | None,
    envelope_blob_name: str,
) -> dict[str, Any]:
    body = read_blob(
        config.CLOSED_TICKET_ARCHIVE_CONTAINER,
        envelope_blob_name,
        store=blob_service,
    )
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("closed ticket envelope must be a JSON object")
    return parsed


def _record_from_envelope(
    envelope: dict[str, Any],
    *,
    cosmos_row: dict[str, Any],
) -> ClosedTicketRecord:
    return ClosedTicketRecord(
        ticket_id=str(envelope.get("ticket_id") or cosmos_row.get("ticket_id", "")),
        ticket_number=envelope.get("ticket_number") or cosmos_row.get("ticket_number"),
        source_table=envelope.get("source_table") or cosmos_row.get("source_table"),
        source_url=envelope.get("source_url") or cosmos_row.get("source_url"),
        state=envelope.get("state") or cosmos_row.get("state"),
        is_active=bool(cosmos_row.get("is_active", True)),
        closed_at=_parse_timestamp(envelope.get("closed_at") or cosmos_row.get("closed_at")),
        source_updated_at=_parse_timestamp(
            envelope.get("source_updated_at") or cosmos_row.get("source_updated_at")
        ),
        raw_payload=envelope.get("raw_payload") or {},
        journals_payload=envelope.get("journals_payload") or [],
        expires_at=_parse_timestamp(cosmos_row.get("expires_at")),
        content_hash=str(envelope.get("content_hash") or cosmos_row.get("content_hash") or ""),
    )


def _attachment_storage_key(row: dict[str, Any]) -> str:
    return str(
        row.get("storage_blob_name")
        or row.get("storage_s3_key")
        or ""
    ).strip()


def _attachment_records_from_envelope(
    *,
    envelope: dict[str, Any],
    config: Config,
    blob_service: Any | None,
    document_intelligence_client: Any | None = None,
) -> list[ClosedTicketAttachmentRecord]:
    attachments = envelope.get("attachments")
    if not isinstance(attachments, list):
        return []
    output: list[ClosedTicketAttachmentRecord] = []
    for row in attachments:
        if not isinstance(row, dict):
            continue
        attachment_id = str(row.get("attachment_id", "")).strip()
        ticket_id = str(row.get("ticket_id", "")).strip()
        if not attachment_id or not ticket_id:
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        raw_content: bytes | None = None
        storage_key = _attachment_storage_key(row)
        if str(row.get("download_status", "")).strip() == "downloaded" and storage_key:
            try:
                raw_content = read_blob(
                    config.CLOSED_TICKET_ARCHIVE_CONTAINER,
                    storage_key,
                    store=blob_service,
                )
            except Exception as exc:
                logger.warning("failed to read attachment %s: %s", storage_key, exc)
        enriched = build_attachment_semantic_metadata(
            ClosedTicketAttachmentInput(
                attachment_id=attachment_id,
                ticket_id=ticket_id,
                filename=row.get("file_name"),
                content_type=row.get("content_type"),
                metadata=dict(metadata),
                raw_content=raw_content,
            ),
            config=config,
            document_intelligence_client=document_intelligence_client,
        )
        output.append(
            ClosedTicketAttachmentRecord(
                attachment_id=enriched.attachment_id,
                ticket_id=enriched.ticket_id,
                filename=enriched.filename,
                content_type=enriched.content_type,
                metadata=enriched.metadata,
                semantic_text=enriched.semantic_text,
                extraction_status=enriched.extraction_status,
            )
        )
    return output


def closed_ticket_chunk_document(
    *,
    chunk: ClosedTicketChunkRecord,
    embedding: list[float],
    tenant_id: str,
    container: str,
    envelope_blob_name: str,
) -> dict[str, Any]:
    """Convert one closed-ticket chunk into the Azure AI Search document shape."""
    return {
        "id": chunk.chunk_id,
        "document_id": chunk.chunk_id,
        "chunk_id": chunk.chunk_id,
        "ticket_id": chunk.ticket_id,
        "tenant_id": tenant_id,
        "corpus_id": _CORPUS_ID,
        "active": True,
        "text": chunk.text,
        "search_text": chunk.text,
        "embedding": embedding,
        "embedding_model": chunk.embedding_model,
        "source_container": container,
        "source_blob_name": envelope_blob_name,
        "section": chunk.section,
        "field_path": chunk.field_path,
        "metadata": dict(chunk.metadata),
        "chunk_schema_version": chunk.chunk_schema_version,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _update_index_status(
    *,
    cosmos_store: CosmosStore,
    config: Config,
    ticket_id: str,
    index_status: str,
    index_error: str | None = None,
) -> None:
    existing = cosmos_store.get_closed_ticket(config.CLOSED_TICKET_CONTAINER, ticket_id)
    if existing is None:
        return
    replacement = dict(existing)
    replacement["index_status"] = index_status
    replacement["last_indexed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if index_error is not None:
        replacement["index_error"] = str(index_error)[:1000]
    cosmos_store.upsert_closed_ticket(config.CLOSED_TICKET_CONTAINER, replacement)


def index_closed_ticket(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any | None,
    adapter: AzureSearchAdapter,
    ticket_id: str,
    document_intelligence_client: Any | None = None,
    embedding_gateway: Any | None = None,
) -> ClosedTicketIndexResult:
    """Index one closed ticket into Azure AI Search."""
    row = cosmos_store.get_closed_ticket(config.CLOSED_TICKET_CONTAINER, ticket_id)
    if not row:
        return ClosedTicketIndexResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="failed",
            error="ticket not found",
        )
    envelope_blob_name = str(
        row.get("envelope_blob_name") or row.get("envelope_s3_key") or ""
    ).strip()
    if not envelope_blob_name:
        _update_index_status(
            cosmos_store=cosmos_store,
            config=config,
            ticket_id=ticket_id,
            index_status="failed",
            index_error="missing envelope_blob_name",
        )
        return ClosedTicketIndexResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="failed",
            error="missing envelope_blob_name",
        )

    envelope = _load_envelope(
        config=config,
        blob_service=blob_service,
        envelope_blob_name=envelope_blob_name,
    )
    record = _record_from_envelope(envelope, cosmos_row=row)
    if not _ticket_is_indexable(record):
        _update_index_status(
            cosmos_store=cosmos_store,
            config=config,
            ticket_id=ticket_id,
            index_status="not_indexed",
        )
        return ClosedTicketIndexResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="not_indexed",
            skipped=True,
        )

    attachments = _attachment_records_from_envelope(
        envelope=envelope,
        config=config,
        blob_service=blob_service,
        document_intelligence_client=document_intelligence_client,
    )
    chunks = build_closed_ticket_chunks(record, config, attachments=attachments)
    tenant_id = tenant_id_for(config, required=True)
    index = str(config.CLOSED_TICKET_AZURE_SEARCH_INDEX).strip()

    if not chunks:
        _update_index_status(
            cosmos_store=cosmos_store,
            config=config,
            ticket_id=ticket_id,
            index_status="not_indexed",
        )
        return ClosedTicketIndexResult(ticket_id=ticket_id, chunk_count=0, status="not_indexed")

    vectors = embed_texts(
        [chunk.text for chunk in chunks],
        gateway=embedding_gateway,
        deployment=getattr(config, "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "") or None,
    )
    if len(vectors) != len(chunks):
        raise ValueError("embedding response count did not match closed-ticket chunks")

    documents: list[dict[str, Any]] = []
    for chunk, embedding in zip(chunks, vectors, strict=True):
        documents.append(
            closed_ticket_chunk_document(
                chunk=chunk,
                embedding=embedding,
                tenant_id=tenant_id,
                container=config.CLOSED_TICKET_ARCHIVE_CONTAINER,
                envelope_blob_name=envelope_blob_name,
            )
        )

    old_documents = adapter.search(
        index=index,
        filter=_ticket_scope_filter(tenant_id=tenant_id, ticket_id=ticket_id),
        select=["id"],
        top=10_000,
    )
    old_ids = [
        str(document.get("id", "")).strip()
        for document in old_documents
        if str(document.get("id", "")).strip()
    ]
    if old_ids:
        adapter.delete_documents(index=index, document_ids=old_ids)

    count = adapter.upload_documents(index=index, documents=documents)
    _update_index_status(
        cosmos_store=cosmos_store,
        config=config,
        ticket_id=ticket_id,
        index_status="ready",
    )
    return ClosedTicketIndexResult(ticket_id=ticket_id, chunk_count=count, status="ready")


def fetch_pending_ticket_ids(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    limit: int,
    status: str,
) -> list[str]:
    rows = cosmos_store.list_closed_tickets_by_index_status(
        config.CLOSED_TICKET_CONTAINER,
        index_status=status,
        limit=max(1, int(limit)),
    )
    return [
        str(row.get("ticket_id", "")).strip()
        for row in rows
        if str(row.get("ticket_id", "")).strip()
    ]


def index_pending_closed_tickets(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any | None = None,
    adapter: AzureSearchAdapter | None = None,
    document_intelligence_client: Any | None = None,
    embedding_gateway: Any | None = None,
    max_tickets: int = 500,
) -> ClosedTicketPendingIndexResult:
    """Index a bounded batch of pending/failed closed tickets."""
    result = ClosedTicketPendingIndexResult()
    search_adapter = adapter or AzureSearchAdapter.from_config(
        config,
        index_name=str(config.CLOSED_TICKET_AZURE_SEARCH_INDEX).strip(),
    )
    remaining = max(1, int(max_tickets))
    for status in ("pending", "failed"):
        if remaining <= 0:
            break
        ticket_ids = fetch_pending_ticket_ids(
            config=config,
            cosmos_store=cosmos_store,
            limit=remaining,
            status=status,
        )
        for ticket_id in ticket_ids:
            result.selected += 1
            remaining -= 1
            try:
                index_result = index_closed_ticket(
                    config=config,
                    cosmos_store=cosmos_store,
                    blob_service=blob_service,
                    adapter=search_adapter,
                    ticket_id=ticket_id,
                    document_intelligence_client=document_intelligence_client,
                    embedding_gateway=embedding_gateway,
                )
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"{ticket_id}: {exc}")
                try:
                    _update_index_status(
                        cosmos_store=cosmos_store,
                        config=config,
                        ticket_id=ticket_id,
                        index_status="failed",
                        index_error=str(exc),
                    )
                except Exception:
                    pass
                continue
            if index_result.skipped:
                result.skipped += 1
            elif index_result.status == "ready":
                result.ready += 1
            else:
                result.skipped += 1
            if remaining <= 0:
                break
    return result
