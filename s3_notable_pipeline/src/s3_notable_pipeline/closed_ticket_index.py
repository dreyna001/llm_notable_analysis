"""OpenSearch indexing for closed-ticket hybrid retrieval chunks."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .case_embed import embed_text
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
from .opensearch_client import OpenSearchClient
from .opensearch_retrieval import tenant_id_for
from .rag_ingestion import index_documents
from .servicenow_disposition_sync import _from_ddb_item

logger = logging.getLogger(__name__)

_INDEX_STATUS_INDEX = "IndexStatusIndex"
_CORPUS_ID = "closed_tickets"


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
    s3_client: Any,
    envelope_key: str,
) -> dict[str, Any]:
    response = s3_client.get_object(
        Bucket=config.CLOSED_TICKET_ARCHIVE_BUCKET,
        Key=envelope_key,
    )
    body = response["Body"].read()
    parsed = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(parsed, dict):
        raise ValueError("closed ticket envelope must be a JSON object")
    return parsed


def _record_from_envelope(
    envelope: dict[str, Any],
    *,
    dynamo_row: dict[str, Any],
) -> ClosedTicketRecord:
    return ClosedTicketRecord(
        ticket_id=str(envelope.get("ticket_id") or dynamo_row.get("ticket_id", "")),
        ticket_number=envelope.get("ticket_number") or dynamo_row.get("ticket_number"),
        source_table=envelope.get("source_table") or dynamo_row.get("source_table"),
        source_url=envelope.get("source_url") or dynamo_row.get("source_url"),
        state=envelope.get("state") or dynamo_row.get("state"),
        is_active=bool(dynamo_row.get("is_active", True)),
        closed_at=_parse_timestamp(envelope.get("closed_at") or dynamo_row.get("closed_at")),
        source_updated_at=_parse_timestamp(
            envelope.get("source_updated_at") or dynamo_row.get("source_updated_at")
        ),
        raw_payload=envelope.get("raw_payload") or {},
        journals_payload=envelope.get("journals_payload") or [],
        expires_at=_parse_timestamp(dynamo_row.get("expires_at")),
        content_hash=str(envelope.get("content_hash") or dynamo_row.get("content_hash") or ""),
    )


def _attachment_records_from_envelope(
    *,
    envelope: dict[str, Any],
    config: Config,
    s3_client: Any,
    textract_client: Any | None = None,
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
        storage_key = str(row.get("storage_s3_key") or "").strip()
        if str(row.get("download_status", "")).strip() == "downloaded" and storage_key:
            try:
                response = s3_client.get_object(
                    Bucket=config.CLOSED_TICKET_ARCHIVE_BUCKET,
                    Key=storage_key,
                )
                body = response["Body"].read()
                raw_content = bytes(body) if body is not None else None
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
            textract_client=textract_client,
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
    bucket: str,
    envelope_key: str,
) -> dict[str, Any]:
    """Convert one closed-ticket chunk into the shared OpenSearch document shape."""
    return {
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
        "source_bucket": bucket,
        "source_key": envelope_key,
        "section": chunk.section,
        "field_path": chunk.field_path,
        "metadata": dict(chunk.metadata),
        "chunk_schema_version": chunk.chunk_schema_version,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _update_index_status(
    *,
    dynamodb_client: Any,
    config: Config,
    ticket_id: str,
    index_status: str,
    index_error: str | None = None,
) -> None:
    expression = "SET index_status = :status, last_indexed_at = :indexed_at"
    values: dict[str, Any] = {
        ":status": {"S": index_status},
        ":indexed_at": {"S": datetime.now(UTC).isoformat().replace("+00:00", "Z")},
    }
    if index_error is not None:
        expression += ", index_error = :error"
        values[":error"] = {"S": str(index_error)[:1000]}
    dynamodb_client.update_item(
        TableName=config.CLOSED_TICKET_TABLE,
        Key={"ticket_id": {"S": ticket_id}},
        UpdateExpression=expression,
        ExpressionAttributeValues=values,
    )


def index_closed_ticket(
    *,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any,
    bedrock_client: Any,
    adapter: Any,
    ticket_id: str,
    textract_client: Any | None = None,
) -> ClosedTicketIndexResult:
    """Index one closed ticket into OpenSearch."""
    row = dynamodb_client.get_item(
        TableName=config.CLOSED_TICKET_TABLE,
        Key={"ticket_id": {"S": ticket_id}},
        ConsistentRead=True,
    ).get("Item")
    if not row:
        return ClosedTicketIndexResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="failed",
            error="ticket not found",
        )
    dynamo_row = _from_ddb_item(row)
    envelope_key = str(dynamo_row.get("envelope_s3_key", "")).strip()
    if not envelope_key:
        _update_index_status(
            dynamodb_client=dynamodb_client,
            config=config,
            ticket_id=ticket_id,
            index_status="failed",
            index_error="missing envelope_s3_key",
        )
        return ClosedTicketIndexResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="failed",
            error="missing envelope_s3_key",
        )

    envelope = _load_envelope(config=config, s3_client=s3_client, envelope_key=envelope_key)
    record = _record_from_envelope(envelope, dynamo_row=dynamo_row)
    if not _ticket_is_indexable(record):
        _update_index_status(
            dynamodb_client=dynamodb_client,
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
        s3_client=s3_client,
        textract_client=textract_client,
    )
    chunks = build_closed_ticket_chunks(record, config, attachments=attachments)
    tenant_id = tenant_id_for(config, required=True)
    index = str(config.OPENSEARCH_CLOSED_TICKET_INDEX).strip()

    if not chunks:
        _update_index_status(
            dynamodb_client=dynamodb_client,
            config=config,
            ticket_id=ticket_id,
            index_status="not_indexed",
        )
        return ClosedTicketIndexResult(ticket_id=ticket_id, chunk_count=0, status="not_indexed")

    documents: list[dict[str, Any]] = []
    for chunk in chunks:
        embedding = embed_text(chunk.text, config, bedrock_client)
        documents.append(
            closed_ticket_chunk_document(
                chunk=chunk,
                embedding=embedding,
                tenant_id=tenant_id,
                bucket=config.CLOSED_TICKET_ARCHIVE_BUCKET,
                envelope_key=envelope_key,
            )
        )

    if hasattr(adapter, "ensure_vector_index"):
        adapter.ensure_vector_index(
            index=index,
            dimensions=len(documents[0]["embedding"]),
        )
    adapter.delete_by_query(
        index=index,
        query={
            "bool": {
                "filter": [
                    {"term": {"tenant_id.keyword": tenant_id}},
                    {"term": {"corpus_id.keyword": _CORPUS_ID}},
                    {"term": {"ticket_id.keyword": ticket_id}},
                ]
            }
        },
    )
    count = index_documents(index=index, documents=documents, adapter=adapter)
    _update_index_status(
        dynamodb_client=dynamodb_client,
        config=config,
        ticket_id=ticket_id,
        index_status="ready",
    )
    return ClosedTicketIndexResult(ticket_id=ticket_id, chunk_count=count, status="ready")


def fetch_pending_ticket_ids(
    *,
    config: Config,
    dynamodb_client: Any,
    limit: int,
    status: str,
) -> list[str]:
    response = dynamodb_client.query(
        TableName=config.CLOSED_TICKET_TABLE,
        IndexName=_INDEX_STATUS_INDEX,
        KeyConditionExpression="index_status = :status",
        ExpressionAttributeValues={":status": {"S": status}},
        Limit=max(1, int(limit)),
    )
    return [
        str(_from_ddb_item(item).get("ticket_id", "")).strip()
        for item in response.get("Items", [])
        if str(_from_ddb_item(item).get("ticket_id", "")).strip()
    ]


def index_pending_closed_tickets(
    *,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any,
    bedrock_client: Any,
    adapter: Any | None = None,
    textract_client: Any | None = None,
    max_tickets: int = 500,
) -> ClosedTicketPendingIndexResult:
    """Index a bounded batch of pending/failed closed tickets."""
    result = ClosedTicketPendingIndexResult()
    if adapter is None:
        adapter = OpenSearchClient.from_config(config)
    remaining = max(1, int(max_tickets))
    for status in ("pending", "failed"):
        if remaining <= 0:
            break
        ticket_ids = fetch_pending_ticket_ids(
            config=config,
            dynamodb_client=dynamodb_client,
            limit=remaining,
            status=status,
        )
        for ticket_id in ticket_ids:
            result.selected += 1
            remaining -= 1
            try:
                index_result = index_closed_ticket(
                    config=config,
                    dynamodb_client=dynamodb_client,
                    s3_client=s3_client,
                    bedrock_client=bedrock_client,
                    adapter=adapter,
                    ticket_id=ticket_id,
                    textract_client=textract_client,
                )
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"{ticket_id}: {exc}")
                try:
                    _update_index_status(
                        dynamodb_client=dynamodb_client,
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
