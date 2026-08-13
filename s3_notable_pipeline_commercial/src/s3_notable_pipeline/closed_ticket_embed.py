"""Post-sync closed ticket render, embed, and OpenSearch indexing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .case_embed import embed_text
from .closed_ticket_attachment_extract import load_closed_ticket_attachments
from .closed_ticket_render import (
    CLOSED_TICKET_CORPUS_ID,
    ClosedTicketChunkRecord,
    ClosedTicketRecord,
    build_closed_ticket_chunks,
)
from .config import Config
from .servicenow_closed_ticket_sync import (
    _format_servicenow_timestamp,
    _from_ddb_item,
    _parse_servicenow_datetime,
    _to_ddb_item,
    ticket_manifest_key,
)

logger = logging.getLogger(__name__)

_INDEX_STATUS_PENDING = "pending"
_INDEX_STATUS_READY = "ready"
_INDEX_STATUS_FAILED = "failed"
_INDEX_STATUS_NOT_INDEXED = "not_indexed"


@dataclass(frozen=True)
class ClosedTicketEmbedResult:
    """Result of indexing one closed ticket."""

    ticket_id: str
    chunk_count: int
    status: str
    skipped: bool = False
    message: str = ""


@dataclass
class ClosedTicketPendingEmbedSummary:
    """Summary of a bounded pending-ticket indexing batch."""

    selected: int = 0
    ready: int = 0
    failed: int = 0
    skipped: int = 0
    tombstoned: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "error" if self.errors and self.ready == 0 else "success",
            "selected": self.selected,
            "ready": self.ready,
            "failed": self.failed,
            "skipped": self.skipped,
            "tombstoned": self.tombstoned,
            "errors": self.errors,
        }


def embed_closed_ticket(
    *,
    ticket_id: str,
    config: Config,
    s3_client: Any,
    bedrock_client: Any,
    dynamodb_client: Any,
    adapter: Any | None = None,
) -> ClosedTicketEmbedResult:
    """Render, embed, and index one closed ticket from its S3 manifest."""

    if not config.CLOSED_TICKET_EMBED_ENABLED:
        return ClosedTicketEmbedResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="skipped",
            skipped=True,
            message="closed ticket embed disabled",
        )

    registry = _get_registry_ticket(dynamodb_client, config, ticket_id)
    if registry is None:
        return ClosedTicketEmbedResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="failed",
            message="ticket not found in registry",
        )

    bucket = _archive_bucket(config)
    raw_prefix = config.CLOSED_TICKET_RAW_PREFIX
    manifest_key = str(registry.get("manifest_key") or ticket_manifest_key(raw_prefix, ticket_id))
    is_active = registry.get("is_active") is not False

    try:
        manifest = _load_json_object(s3_client, bucket=bucket, key=manifest_key)
    except Exception as exc:
        _update_index_status(
            dynamodb_client=dynamodb_client,
            config=config,
            s3_client=s3_client,
            bucket=bucket,
            raw_prefix=raw_prefix,
            ticket_id=ticket_id,
            manifest_key=manifest_key,
            index_status=_INDEX_STATUS_FAILED,
            index_error=str(exc),
        )
        return ClosedTicketEmbedResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="failed",
            message=str(exc),
        )

    if not is_active or manifest.get("is_active") is False:
        tombstoned = _tombstone_ticket_index(
            ticket_id=ticket_id,
            config=config,
            adapter=adapter,
        )
        _update_index_status(
            dynamodb_client=dynamodb_client,
            config=config,
            s3_client=s3_client,
            bucket=bucket,
            raw_prefix=raw_prefix,
            ticket_id=ticket_id,
            manifest_key=manifest_key,
            index_status=_INDEX_STATUS_NOT_INDEXED,
            index_error=None,
        )
        return ClosedTicketEmbedResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="not_indexed",
            skipped=True,
            message=f"tombstoned {tombstoned} chunk(s)",
        )

    record = _record_from_manifest(manifest)
    if not _ticket_is_indexable(record):
        _tombstone_ticket_index(ticket_id=ticket_id, config=config, adapter=adapter)
        _update_index_status(
            dynamodb_client=dynamodb_client,
            config=config,
            s3_client=s3_client,
            bucket=bucket,
            raw_prefix=raw_prefix,
            ticket_id=ticket_id,
            manifest_key=manifest_key,
            index_status=_INDEX_STATUS_NOT_INDEXED,
            index_error=None,
        )
        return ClosedTicketEmbedResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="not_indexed",
            skipped=True,
            message="ticket expired or inactive",
        )

    version_key = str(manifest.get("version_key") or registry.get("version_key") or "").strip()
    if not version_key:
        message = "manifest missing version_key"
        _update_index_status(
            dynamodb_client=dynamodb_client,
            config=config,
            s3_client=s3_client,
            bucket=bucket,
            raw_prefix=raw_prefix,
            ticket_id=ticket_id,
            manifest_key=manifest_key,
            index_status=_INDEX_STATUS_FAILED,
            index_error=message,
        )
        return ClosedTicketEmbedResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="failed",
            message=message,
        )

    try:
        payload = _load_json_object(s3_client, bucket=bucket, key=version_key)
        record = _record_from_version_payload(payload, manifest=manifest)
        attachments = load_closed_ticket_attachments(
            ticket_id=ticket_id,
            config=config,
            s3_client=s3_client,
            dynamodb_client=dynamodb_client,
            bucket=bucket,
            textract_client=_textract_client_for_attachments(config),
        )
        chunks = build_closed_ticket_chunks(record, config, attachments=attachments)
        count = _index_ticket_chunks(
            record=record,
            chunks=chunks,
            config=config,
            bedrock_client=bedrock_client,
            bucket=bucket,
            version_key=version_key,
            adapter=adapter,
        )
        _update_index_status(
            dynamodb_client=dynamodb_client,
            config=config,
            s3_client=s3_client,
            bucket=bucket,
            raw_prefix=raw_prefix,
            ticket_id=ticket_id,
            manifest_key=manifest_key,
            index_status=_INDEX_STATUS_READY,
            index_error=None,
            chunk_count=count,
            content_hash=record.content_hash,
        )
        return ClosedTicketEmbedResult(
            ticket_id=ticket_id,
            chunk_count=count,
            status="ready",
        )
    except Exception as exc:
        logger.exception("closed ticket embed failed for %s", ticket_id)
        _update_index_status(
            dynamodb_client=dynamodb_client,
            config=config,
            s3_client=s3_client,
            bucket=bucket,
            raw_prefix=raw_prefix,
            ticket_id=ticket_id,
            manifest_key=manifest_key,
            index_status=_INDEX_STATUS_FAILED,
            index_error=str(exc),
        )
        return ClosedTicketEmbedResult(
            ticket_id=ticket_id,
            chunk_count=0,
            status="failed",
            message=str(exc),
        )


def index_pending_closed_tickets(
    *,
    config: Config,
    s3_client: Any,
    bedrock_client: Any,
    dynamodb_client: Any,
    adapter: Any | None = None,
    batch_size: int | None = None,
    max_tickets: int | None = None,
) -> dict[str, Any]:
    """Index a bounded batch of pending/failed active closed tickets."""

    summary = ClosedTicketPendingEmbedSummary()
    if not config.CLOSED_TICKET_EMBED_ENABLED:
        summary.skipped = 1
        return summary.as_dict()

    page_size = max(1, int(batch_size or config.CLOSED_TICKET_EMBED_BATCH_SIZE))
    cap = max(1, int(max_tickets or page_size))
    after_ticket_id: str | None = None
    processed = 0

    while processed < cap:
        limit = min(page_size, cap - processed)
        ticket_ids = _list_pending_ticket_ids(
            dynamodb_client,
            config,
            after_ticket_id=after_ticket_id,
            limit=limit,
        )
        if not ticket_ids:
            break
        for ticket_id in ticket_ids:
            summary.selected += 1
            processed += 1
            result = embed_closed_ticket(
                ticket_id=ticket_id,
                config=config,
                s3_client=s3_client,
                bedrock_client=bedrock_client,
                dynamodb_client=dynamodb_client,
                adapter=adapter,
            )
            if result.skipped and result.status in {"skipped", "not_indexed"}:
                summary.skipped += 1
                if "tombstoned" in result.message:
                    summary.tombstoned += 1
            elif result.status == "ready":
                summary.ready += 1
            else:
                summary.failed += 1
                summary.errors.append(f"{ticket_id}: {result.message}")
            if processed >= cap:
                break
        after_ticket_id = ticket_ids[-1]
        if len(ticket_ids) < limit:
            break
    return summary.as_dict()


def _index_ticket_chunks(
    *,
    record: ClosedTicketRecord,
    chunks: list[ClosedTicketChunkRecord],
    config: Config,
    bedrock_client: Any,
    bucket: str,
    version_key: str,
    adapter: Any | None,
) -> int:
    from .opensearch_retrieval import adapter_for, config_value, opensearch_enabled, tenant_id_for
    from .rag_ingestion import closed_ticket_chunk_document, index_closed_ticket_chunks

    if not opensearch_enabled(config):
        raise ValueError("OpenSearch retrieval backend is required for closed ticket embed")

    tenant_id = tenant_id_for(config, required=True)
    index = str(config_value(config, "OPENSEARCH_CLOSED_TICKET_INDEX", "closed_tickets")).strip()
    opensearch_adapter = adapter_for(config, adapter)
    documents: list[dict[str, Any]] = []
    for chunk in chunks:
        embedding = embed_text(chunk.search_text, config, bedrock_client)
        documents.append(
            closed_ticket_chunk_document(
                chunk=chunk,
                embedding=embedding,
                bucket=bucket,
                version_key=version_key,
                tenant_id=tenant_id,
                content_hash=record.content_hash,
            )
        )
    if not documents:
        _tombstone_ticket_index(
            ticket_id=record.ticket_id,
            config=config,
            adapter=opensearch_adapter,
        )
        return 0
    return index_closed_ticket_chunks(
        index=index,
        ticket_id=record.ticket_id,
        tenant_id=tenant_id,
        documents=documents,
        adapter=opensearch_adapter,
        batch_size=int(config_value(config, "OPENSEARCH_BULK_BATCH_SIZE", 100)),
    )


def _tombstone_ticket_index(
    *,
    ticket_id: str,
    config: Config,
    adapter: Any | None,
) -> int:
    from .opensearch_retrieval import adapter_for, config_value, tenant_id_for
    from .rag_ingestion import tombstone_closed_ticket_chunks

    tenant_id = tenant_id_for(config, required=True)
    index = str(config_value(config, "OPENSEARCH_CLOSED_TICKET_INDEX", "closed_tickets")).strip()
    return tombstone_closed_ticket_chunks(
        index=index,
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        adapter=adapter_for(config, adapter),
    )


def _ticket_is_indexable(record: ClosedTicketRecord) -> bool:
    if not record.is_active:
        return False
    if record.expires_at is not None:
        now = datetime.now(record.expires_at.tzinfo or UTC)
        if record.expires_at <= now:
            return False
    return True


def _record_from_manifest(manifest: dict[str, Any]) -> ClosedTicketRecord:
    return ClosedTicketRecord(
        ticket_id=str(manifest.get("ticket_id") or "").strip(),
        ticket_number=_optional_str(manifest.get("ticket_number")),
        source_table=_optional_str(manifest.get("source_table")),
        source_url=_optional_str(manifest.get("source_url")),
        state=_optional_str(manifest.get("state")),
        is_active=manifest.get("is_active") is not False,
        closed_at=_parse_servicenow_datetime(manifest.get("closed_at")),
        source_updated_at=_parse_servicenow_datetime(manifest.get("source_updated_at")),
        raw_payload={},
        journals_payload=[],
        expires_at=_parse_servicenow_datetime(manifest.get("expires_at")),
        content_hash=_optional_str(manifest.get("content_hash")),
    )


def _record_from_version_payload(
    payload: dict[str, Any],
    *,
    manifest: dict[str, Any],
) -> ClosedTicketRecord:
    return ClosedTicketRecord(
        ticket_id=str(payload.get("ticket_id") or manifest.get("ticket_id") or "").strip(),
        ticket_number=_optional_str(payload.get("ticket_number") or manifest.get("ticket_number")),
        source_table=_optional_str(payload.get("source_table") or manifest.get("source_table")),
        source_url=_optional_str(payload.get("source_url") or manifest.get("source_url")),
        state=_optional_str(payload.get("state") or manifest.get("state")),
        is_active=manifest.get("is_active") is not False,
        closed_at=_parse_servicenow_datetime(payload.get("closed_at") or manifest.get("closed_at")),
        source_updated_at=_parse_servicenow_datetime(
            payload.get("source_updated_at") or manifest.get("source_updated_at")
        ),
        raw_payload=payload.get("raw_payload") or {},
        journals_payload=payload.get("journals_payload") or [],
        expires_at=_parse_servicenow_datetime(payload.get("expires_at") or manifest.get("expires_at")),
        content_hash=_optional_str(payload.get("content_hash") or manifest.get("content_hash")),
    )


def _archive_bucket(config: Config) -> str:
    bucket = (
        str(config.CLOSED_TICKET_ARCHIVE_BUCKET or "").strip()
        or str(config.OUTPUT_BUCKET_NAME or "").strip()
    )
    if not bucket:
        raise ValueError("CLOSED_TICKET_ARCHIVE_BUCKET or OUTPUT_BUCKET_NAME is required")
    return bucket


def _get_registry_ticket(
    dynamodb_client: Any,
    config: Config,
    ticket_id: str,
) -> dict[str, Any] | None:
    response = dynamodb_client.get_item(
        TableName=config.CLOSED_TICKET_REGISTRY_TABLE,
        Key={"ticket_id": {"S": ticket_id}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None
    row = _from_ddb_item(item)
    if str(row.get("record_type") or "ticket") != "ticket":
        return None
    return row


def _list_pending_ticket_ids(
    dynamodb_client: Any,
    config: Config,
    *,
    after_ticket_id: str | None,
    limit: int,
) -> list[str]:
    pending: list[str] = []
    request: dict[str, Any] = {
        "TableName": config.CLOSED_TICKET_REGISTRY_TABLE,
        "FilterExpression": (
            "record_type = :ticket AND is_active = :active AND "
            "index_status IN (:pending, :failed)"
        ),
        "ExpressionAttributeValues": {
            ":ticket": {"S": "ticket"},
            ":active": {"BOOL": True},
            ":pending": {"S": _INDEX_STATUS_PENDING},
            ":failed": {"S": _INDEX_STATUS_FAILED},
        },
    }
    while len(pending) < limit:
        response = dynamodb_client.scan(**request)
        for item in response.get("Items", []):
            row = _from_ddb_item(item)
            ticket_id = str(row.get("ticket_id") or "").strip()
            if not ticket_id or ticket_id.startswith("attachment#"):
                continue
            if after_ticket_id is not None and ticket_id <= after_ticket_id:
                continue
            pending.append(ticket_id)
            if len(pending) >= limit:
                break
        last_key = response.get("LastEvaluatedKey")
        if not last_key or len(pending) >= limit:
            break
        request["ExclusiveStartKey"] = last_key
    pending.sort()
    return pending[:limit]


def _update_index_status(
    *,
    dynamodb_client: Any,
    config: Config,
    s3_client: Any,
    bucket: str,
    raw_prefix: str,
    ticket_id: str,
    manifest_key: str,
    index_status: str,
    index_error: str | None,
    chunk_count: int | None = None,
    content_hash: str | None = None,
) -> None:
    run_at = datetime.now(UTC)
    existing = _get_registry_ticket(dynamodb_client, config, ticket_id)
    if existing:
        existing["index_status"] = index_status
        existing["synced_at"] = _format_servicenow_timestamp(run_at)
        if index_error is not None:
            existing["index_error"] = index_error[:500]
        elif "index_error" in existing:
            existing.pop("index_error", None)
        if chunk_count is not None:
            existing["indexed_chunk_count"] = int(chunk_count)
        if content_hash:
            existing["content_hash"] = content_hash
        dynamodb_client.put_item(
            TableName=config.CLOSED_TICKET_REGISTRY_TABLE,
            Item=_to_ddb_item(existing),
        )
    try:
        manifest = _load_json_object(s3_client, bucket=bucket, key=manifest_key)
        manifest["index_status"] = index_status
        manifest["synced_at"] = _format_servicenow_timestamp(run_at)
        if index_error is not None:
            manifest["index_error"] = index_error[:500]
        elif "index_error" in manifest:
            manifest.pop("index_error", None)
        if chunk_count is not None:
            manifest["indexed_chunk_count"] = int(chunk_count)
        s3_client.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as exc:
        logger.warning("failed to update manifest index_status for %s: %s", ticket_id, exc)


def _load_json_object(s3_client: Any, *, bucket: str, key: str) -> dict[str, Any]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    parsed = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(parsed, dict):
        raise ValueError(f"S3 object must be a JSON object: {key}")
    return parsed


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _textract_client_for_attachments(config: Config) -> Any | None:
    if not config.CLOSED_TICKET_VISION_ENABLED:
        return None
    from .aws_clients import textract_client

    return textract_client()
