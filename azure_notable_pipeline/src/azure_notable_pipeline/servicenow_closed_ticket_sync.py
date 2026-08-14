"""ServiceNow closed ticket raw sync for Azure (read-only Table API -> Blob + Cosmos)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator
from urllib.parse import quote

import requests

from .blob_store import delete_blobs, list_blobs, read_blob, write_blob
from .config import Config
from .cosmos_store import CosmosStore
from .runtime_security import resolve_secret_string, validate_https_url
from .servicenow_disposition_sync import (
    _format_servicenow_timestamp,
    _parse_servicenow_datetime,
    _request_with_retry,
    _servicenow_query_timestamp,
)

logger = logging.getLogger(__name__)

JOB_NAME = "servicenow_closed_tickets"
MAX_RECORDS_PER_RUN = 500
PAGE_SIZE = 100
MAX_RECONCILE_IDS_PER_RUN = 2000
MAX_CHILD_RECORDS_PER_TICKET = 500
MALFORMED_ROW_FAIL_RATIO = 0.10
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_SERVICENOW_SYS_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
_JOURNAL_TABLE = "sys_journal_field"
_ATTACHMENT_TABLE = "sys_attachment"
_TRUNCATION_MARKER_KEY = "_sync_truncation"
_CLOSED_TICKET_RETENTION_ALLOWED = frozenset({30, 60, 90})


@dataclass(frozen=True)
class CursorState:
    cursor_value: datetime | None
    cursor_sys_id: str
    last_reconciled_at: datetime | None


@dataclass(frozen=True)
class TicketRecord:
    ticket_id: str
    ticket_number: str | None
    source_table: str
    source_url: str
    state: str | None
    closed_at: datetime | None
    source_updated_at: datetime
    raw_payload: dict[str, Any]
    journals_payload: list[Any]
    content_hash: str


@dataclass
class SyncSummary:
    enabled: bool = True
    skipped: bool = False
    fetched: int = 0
    persisted: int = 0
    skipped_noop: int = 0
    deactivated: int = 0
    journals_fetched: int = 0
    attachments_fetched: int = 0
    attachments_downloaded: int = 0
    malformed: int = 0
    reconciled: int = 0
    errors: list[str] = field(default_factory=list)
    cursor_advanced: bool = False
    max_source_updated_at: datetime | None = None
    max_cursor_sys_id: str | None = None
    retention_tickets_deleted: int = 0
    retention_objects_deleted: int = 0
    reconcile_incomplete: bool = False
    journal_fetches_truncated: int = 0
    attachment_metadata_truncated: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "skipped" if self.skipped else ("error" if self.errors else "success"),
            "enabled": self.enabled,
            "skipped": self.skipped,
            "fetched": self.fetched,
            "persisted": self.persisted,
            "skipped_noop": self.skipped_noop,
            "deactivated": self.deactivated,
            "journals_fetched": self.journals_fetched,
            "attachments_fetched": self.attachments_fetched,
            "attachments_downloaded": self.attachments_downloaded,
            "malformed": self.malformed,
            "reconciled": self.reconciled,
            "errors": self.errors,
            "cursor_advanced": self.cursor_advanced,
            "retention_tickets_deleted": self.retention_tickets_deleted,
            "retention_objects_deleted": self.retention_objects_deleted,
            "reconcile_incomplete": self.reconcile_incomplete,
            "journal_fetches_truncated": self.journal_fetches_truncated,
            "attachment_metadata_truncated": self.attachment_metadata_truncated,
        }


@dataclass(frozen=True)
class TicketChildFetchResult:
    rows: list[Any]
    truncated: bool


@dataclass(frozen=True)
class ReconcileResult:
    deactivated: int
    seen_ids: frozenset[str]
    complete: bool


def _table_api_url(base_url: str, table: str) -> str:
    return f"{base_url.rstrip('/')}/api/now/table/{table}"


def _validate_table_name(table: str) -> str:
    normalized = str(table or "").strip()
    if not _TABLE_NAME_RE.fullmatch(normalized):
        raise ValueError("SERVICENOW_CLOSED_TICKET_TABLE must match [a-z0-9_]+")
    return normalized


def _validate_servicenow_sys_id(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not _SERVICENOW_SYS_ID_RE.fullmatch(normalized):
        raise ValueError(f"{name} must be a 32-character ServiceNow sys_id")
    return normalized.lower()


def _truncation_marker(kind: str, count: int) -> dict[str, Any]:
    return {_TRUNCATION_MARKER_KEY: kind, "truncated_at_count": int(count)}


def _apply_truncation_marker(rows: list[Any], kind: str, truncated: bool) -> list[Any]:
    if not truncated:
        return rows
    output = list(rows)
    output.append(_truncation_marker(kind, len(rows)))
    return output


def _combine_encoded_query(parts: list[str]) -> str:
    clauses = [part.strip() for part in parts if str(part or "").strip()]
    if not clauses:
        raise ValueError("SERVICENOW_CLOSED_TICKET_QUERY is required")
    return "^".join(clauses)


def _field_raw_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _field_display_value(value: Any) -> str | None:
    if isinstance(value, dict):
        display = str(value.get("display_value") or "").strip()
        if display:
            return display
    return None


def _extract_ticket_number(row: dict[str, Any]) -> str | None:
    for key in ("number", "ticket_number", "incident_number"):
        raw = _field_raw_value(row.get(key))
        text = str(raw or "").strip()
        if text:
            return text
    return None


def _extract_state(row: dict[str, Any]) -> str | None:
    for key in ("state", "incident_state", "ticket_state"):
        raw = _field_raw_value(row.get(key))
        text = str(raw or "").strip()
        if text:
            return text
    return None


def _extract_closed_at(row: dict[str, Any]) -> datetime | None:
    for key in ("closed_at", "close_date", "resolved_at"):
        parsed = _parse_servicenow_datetime(_field_raw_value(row.get(key)))
        if parsed is not None:
            return parsed
    return None


def _enrich_display_values(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    display_labels: dict[str, str] = {}
    for key, value in row.items():
        display = _field_display_value(value)
        if display:
            display_labels[key] = display
    if display_labels:
        enriched["_display_labels"] = display_labels
    return enriched


def _content_hash(raw_payload: dict[str, Any], journals_payload: list[Any]) -> str:
    canonical = json.dumps(
        {"raw": raw_payload, "journals": journals_payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _attachment_metadata_hash(metadata: dict[str, Any]) -> str:
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_attachment_file_name(file_name: str | None, attachment_id: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name or attachment_id).strip("_")
    if not safe_name:
        safe_name = attachment_id
    return safe_name[:200]


def _ticket_prefix(config: Config, ticket_id: str) -> str:
    return f"{config.CLOSED_TICKET_ARCHIVE_PREFIX.strip().strip('/')}/{ticket_id}"


def _envelope_key(config: Config, ticket_id: str) -> str:
    return f"{_ticket_prefix(config, ticket_id)}/envelope.json"


def _attachment_key(
    config: Config,
    *,
    ticket_id: str,
    attachment_id: str,
    file_name: str | None,
) -> str:
    safe_name = _safe_attachment_file_name(file_name, attachment_id)
    return f"{_ticket_prefix(config, ticket_id)}/attachments/{attachment_id}_{safe_name}"


def _normalize_utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def compute_ticket_retention_expires_at(
    *,
    closed_at: datetime | None,
    source_updated_at: datetime | None,
    retention_days: int,
    synced_at: datetime,
) -> datetime:
    if closed_at is not None:
        basis = _normalize_utc_timestamp(closed_at)
    elif source_updated_at is not None:
        basis = _normalize_utc_timestamp(source_updated_at)
    else:
        basis = _normalize_utc_timestamp(synced_at)
    return basis + timedelta(days=int(retention_days))


def _cursor_clause(
    cursor: CursorState,
    *,
    overlap_hours: int,
    backfill_start: datetime,
) -> str:
    if cursor.cursor_value is None:
        return f"sys_updated_on>={_servicenow_query_timestamp(backfill_start)}"
    overlap_start = cursor.cursor_value - timedelta(hours=int(overlap_hours))
    ts = _servicenow_query_timestamp(overlap_start)
    sys_id = str(cursor.cursor_sys_id or "").strip()
    if sys_id:
        return f"sys_updated_on>{ts}^OR^sys_updated_on={ts}^sys_id>{sys_id}"
    return f"sys_updated_on>{ts}"


def _resolve_sync_token(config: Config) -> str:
    direct = str(config.SERVICENOW_CLOSED_TICKET_TOKEN or "").strip()
    if direct:
        return direct
    secret_name = str(config.SERVICENOW_CLOSED_TICKET_TOKEN_SECRET_NAME or "").strip()
    if not secret_name:
        return ""
    return resolve_secret_string(
        secret_name=secret_name,
        setting_name="SERVICENOW_CLOSED_TICKET_TOKEN",
        secret_field="token",
        fallback_fields=("SERVICENOW_CLOSED_TICKET_TOKEN",),
    )


def _fetch_table_rows(
    config: Config,
    *,
    table: str,
    encoded_query: str,
    session: requests.Session | None = None,
    max_records: int = MAX_RECORDS_PER_RUN,
    token: str = "",
    base_url: str = "",
) -> Iterator[dict[str, Any]]:
    url = _table_api_url(base_url or config.SERVICENOW_BASE_URL, table)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    timeout_seconds = int(getattr(config, "SERVICENOW_TIMEOUT_SECONDS", 15))
    client = session or requests

    fetched = 0
    offset = 0
    while fetched < max_records:
        limit = min(PAGE_SIZE, max_records - fetched)
        params = {
            "sysparm_query": encoded_query,
            "sysparm_display_value": "all",
            "sysparm_exclude_reference_link": "true",
            "sysparm_limit": str(limit),
            "sysparm_offset": str(offset),
            "sysparm_order_by": "sys_updated_on,sys_id",
        }
        response = _request_with_retry(
            session=client,
            method="GET",
            url=url,
            headers=headers,
            params=params,
            timeout=timeout_seconds,
        )
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("ServiceNow response must be a JSON object")
        results = body.get("result", [])
        if not isinstance(results, list):
            raise ValueError("ServiceNow result must be an array")
        if not results:
            break
        for row in results:
            if isinstance(row, dict):
                yield row
                fetched += 1
                if fetched >= max_records:
                    return
        if len(results) < limit:
            break
        offset += limit


def _fetch_table_rows_list(
    config: Config,
    *,
    table: str,
    encoded_query: str,
    session: requests.Session | None = None,
    max_records: int,
    token: str,
    base_url: str,
) -> tuple[list[dict[str, Any]], bool]:
    rows = list(
        _fetch_table_rows(
            config,
            table=table,
            encoded_query=encoded_query,
            session=session,
            max_records=max_records,
            token=token,
            base_url=base_url,
        )
    )
    return rows, len(rows) >= int(max_records)


def fetch_closed_tickets(
    config: Config,
    *,
    customer_query: str,
    source_table: str,
    cursor: CursorState,
    backfill_start: datetime,
    overlap_hours: int,
    session: requests.Session | None = None,
    token: str = "",
    base_url: str = "",
) -> Iterator[dict[str, Any]]:
    cursor_clause = _cursor_clause(
        cursor,
        overlap_hours=overlap_hours,
        backfill_start=backfill_start,
    )
    encoded_query = _combine_encoded_query([customer_query, cursor_clause])
    return _fetch_table_rows(
        config,
        table=source_table,
        encoded_query=encoded_query,
        session=session,
        token=token,
        base_url=base_url,
    )


def fetch_ticket_journals(
    config: Config,
    *,
    ticket_sys_id: str,
    session: requests.Session | None = None,
    token: str = "",
    base_url: str = "",
) -> TicketChildFetchResult:
    query = f"element_id={ticket_sys_id}"
    rows, truncated = _fetch_table_rows_list(
        config,
        table=_JOURNAL_TABLE,
        encoded_query=query,
        session=session,
        max_records=MAX_CHILD_RECORDS_PER_TICKET,
        token=token,
        base_url=base_url,
    )
    enriched = [_enrich_display_values(row) for row in rows]
    return TicketChildFetchResult(rows=enriched, truncated=truncated)


def fetch_ticket_attachment_rows(
    config: Config,
    *,
    source_table: str,
    ticket_sys_id: str,
    session: requests.Session | None = None,
    token: str = "",
    base_url: str = "",
) -> TicketChildFetchResult:
    query = f"table_name={source_table}^table_sys_id={ticket_sys_id}"
    rows, truncated = _fetch_table_rows_list(
        config,
        table=_ATTACHMENT_TABLE,
        encoded_query=query,
        session=session,
        max_records=MAX_CHILD_RECORDS_PER_TICKET,
        token=token,
        base_url=base_url,
    )
    enriched = [_enrich_display_values(row) for row in rows]
    return TicketChildFetchResult(rows=enriched, truncated=truncated)


def _build_ticket_record(
    row: dict[str, Any],
    *,
    source_table: str,
    base_url: str,
    journals_payload: list[Any],
) -> TicketRecord:
    sys_id = str(_field_raw_value(row.get("sys_id")) or "").strip()
    if not sys_id:
        raise ValueError("missing sys_id")
    source_updated_at = _parse_servicenow_datetime(_field_raw_value(row.get("sys_updated_on")))
    if source_updated_at is None:
        raise ValueError("missing or invalid sys_updated_on")

    raw_payload = _enrich_display_values(row)
    ticket_number = _extract_ticket_number(row)
    state = _extract_state(row)
    closed_at = _extract_closed_at(row)
    source_url = (
        f"{base_url.rstrip('/')}/nav_to.do?uri="
        f"{quote(f'{source_table}.do?sys_id={sys_id}', safe='')}"
    )
    journals = journals_payload
    content_hash = _content_hash(raw_payload, journals)

    return TicketRecord(
        ticket_id=sys_id,
        ticket_number=ticket_number,
        source_table=source_table,
        source_url=source_url,
        state=state,
        closed_at=closed_at,
        source_updated_at=source_updated_at,
        raw_payload=raw_payload,
        journals_payload=journals,
        content_hash=content_hash,
    )


def _read_cursor(cosmos_store: CosmosStore, container_name: str) -> CursorState:
    row = cosmos_store.get_sync_checkpoint(container_name, JOB_NAME)
    if not row:
        return CursorState(cursor_value=None, cursor_sys_id="", last_reconciled_at=None)
    cursor_value = _parse_servicenow_datetime(row.get("cursor_value"))
    last_reconciled_at = _parse_servicenow_datetime(row.get("last_reconciled_at"))
    return CursorState(
        cursor_value=cursor_value,
        cursor_sys_id=str(row.get("cursor_sys_id") or ""),
        last_reconciled_at=last_reconciled_at,
    )


def _write_cursor(
    cosmos_store: CosmosStore,
    container_name: str,
    *,
    cursor_value: datetime,
    cursor_sys_id: str,
    last_reconciled_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> None:
    cosmos_store.upsert_sync_checkpoint(
        container_name,
        {
            "job_name": JOB_NAME,
            "cursor_value": _format_servicenow_timestamp(cursor_value),
            "cursor_sys_id": cursor_sys_id,
            "last_reconciled_at": _format_servicenow_timestamp(last_reconciled_at),
            "updated_at": _format_servicenow_timestamp(updated_at or datetime.now(UTC)),
        },
    )


def _download_attachment_bytes(
    config: Config,
    *,
    attachment_sys_id: str,
    max_bytes: int,
    session: requests.Session | None = None,
    token: str = "",
    base_url: str = "",
) -> bytes | None:
    url = f"{base_url.rstrip('/')}/api/now/attachment/{attachment_sys_id}/file"
    headers = {"Authorization": f"Bearer {token}", "Accept": "*/*"}
    timeout_seconds = int(getattr(config, "SERVICENOW_TIMEOUT_SECONDS", 15))
    client = session or requests
    response = client.get(url, headers=headers, timeout=timeout_seconds, stream=True)
    if response.status_code in {401, 403}:
        response.raise_for_status()
    if response.status_code >= 400:
        return None
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > int(max_bytes):
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _upsert_ticket(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any | None,
    ticket: TicketRecord,
    attachments: list[dict[str, Any]],
    retention_days: int,
) -> str:
    container = config.CLOSED_TICKET_CONTAINER
    existing = cosmos_store.get_closed_ticket(container, ticket.ticket_id)
    if existing and str(existing.get("content_hash", "")) == ticket.content_hash:
        return "skipped"

    synced_at = datetime.now(UTC)
    expires_at = compute_ticket_retention_expires_at(
        closed_at=ticket.closed_at,
        source_updated_at=ticket.source_updated_at,
        retention_days=retention_days,
        synced_at=synced_at,
    )
    index_status = "not_indexed" if expires_at <= synced_at else "pending"
    envelope_blob = _envelope_key(config, ticket.ticket_id)
    envelope = {
        "ticket_id": ticket.ticket_id,
        "ticket_number": ticket.ticket_number,
        "source_table": ticket.source_table,
        "source_url": ticket.source_url,
        "state": ticket.state,
        "closed_at": _format_servicenow_timestamp(ticket.closed_at),
        "source_updated_at": _format_servicenow_timestamp(ticket.source_updated_at),
        "raw_payload": ticket.raw_payload,
        "journals_payload": ticket.journals_payload,
        "attachments": attachments,
        "content_hash": ticket.content_hash,
        "synced_at": _format_servicenow_timestamp(synced_at),
    }
    write_blob(
        config.CLOSED_TICKET_ARCHIVE_CONTAINER,
        envelope_blob,
        json.dumps(envelope, ensure_ascii=True, default=str).encode("utf-8"),
        content_type="application/json",
        store=blob_service,
    )
    item: dict[str, Any] = {
        "ticket_id": ticket.ticket_id,
        "ticket_number": ticket.ticket_number or "",
        "source_table": ticket.source_table,
        "source_url": ticket.source_url,
        "state": ticket.state or "",
        "is_active": True,
        "closed_at": _format_servicenow_timestamp(ticket.closed_at),
        "source_updated_at": _format_servicenow_timestamp(ticket.source_updated_at),
        "content_hash": ticket.content_hash,
        "envelope_blob_name": envelope_blob,
        "synced_at": _format_servicenow_timestamp(synced_at),
        "expires_at": _format_servicenow_timestamp(expires_at),
        "expires_at_epoch": int(expires_at.timestamp()),
        "index_status": index_status,
    }
    if existing and str(existing.get("content_hash", "")) != ticket.content_hash:
        item["index_error"] = ""
    cosmos_store.upsert_closed_ticket(container, item)
    return "inserted" if existing is None else "updated"


def _process_attachments(
    config: Config,
    *,
    ticket_id: str,
    source_table: str,
    session: requests.Session | None,
    token: str,
    base_url: str,
    blob_service: Any | None,
) -> tuple[int, int, bool, list[dict[str, Any]]]:
    if not bool(config.SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS):
        return 0, 0, False, []

    max_bytes = int(config.CLOSED_TICKET_ATTACHMENT_MAX_BYTES)
    fetched = 0
    downloaded = 0
    attachment_rows: list[dict[str, Any]] = []

    try:
        attachment_fetch = fetch_ticket_attachment_rows(
            config,
            source_table=source_table,
            ticket_sys_id=ticket_id,
            session=session,
            token=token,
            base_url=base_url,
        )
    except Exception as exc:
        logger.warning("attachment metadata fetch failed for %s: %s", ticket_id, exc)
        return 0, 0, False, []

    for row in attachment_fetch.rows:
        if not isinstance(row, dict):
            continue
        attachment_id = str(_field_raw_value(row.get("sys_id")) or "").strip()
        if not attachment_id:
            continue
        try:
            _validate_servicenow_sys_id(attachment_id, "attachment_id")
            _validate_servicenow_sys_id(ticket_id, "ticket_id")
        except ValueError:
            continue
        fetched += 1
        file_name = str(_field_raw_value(row.get("file_name")) or "").strip() or None
        content_type = str(_field_raw_value(row.get("content_type")) or "").strip() or None
        size_raw = _field_raw_value(row.get("size_bytes"))
        size_bytes: int | None = None
        if size_raw is not None and str(size_raw).strip().isdigit():
            size_bytes = int(str(size_raw).strip())
        metadata = _enrich_display_values(row)
        metadata_hash = _attachment_metadata_hash(metadata)
        download_status = "pending"
        storage_blob_name: str | None = None

        if size_bytes is not None and size_bytes > max_bytes:
            download_status = "skipped"
        else:
            try:
                payload = _download_attachment_bytes(
                    config,
                    attachment_sys_id=attachment_id,
                    max_bytes=max_bytes,
                    session=session,
                    token=token,
                    base_url=base_url,
                )
            except Exception as exc:
                logger.warning("attachment download failed for %s: %s", attachment_id, exc)
                payload = None
            if payload is None:
                download_status = "failed"
            else:
                storage_blob_name = _attachment_key(
                    config,
                    ticket_id=ticket_id,
                    attachment_id=attachment_id,
                    file_name=file_name,
                )
                write_blob(
                    config.CLOSED_TICKET_ARCHIVE_CONTAINER,
                    storage_blob_name,
                    payload,
                    content_type=content_type or "application/octet-stream",
                    store=blob_service,
                )
                download_status = "downloaded"
                downloaded += 1

        attachment_rows.append(
            {
                "attachment_id": attachment_id,
                "ticket_id": ticket_id,
                "file_name": file_name,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "metadata": metadata,
                "metadata_hash": metadata_hash,
                "download_status": download_status,
                "storage_blob_name": storage_blob_name,
            }
        )

    return fetched, downloaded, attachment_fetch.truncated, attachment_rows


def _purge_expired_tickets(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any | None,
    now: datetime | None = None,
) -> tuple[int, int]:
    effective_now = now or datetime.now(UTC)
    deleted = 0
    objects_deleted = 0
    while True:
        expired = cosmos_store.list_expired_closed_tickets(
            config.CLOSED_TICKET_CONTAINER,
            now_epoch=int(effective_now.timestamp()),
            limit=500,
        )
        if not expired:
            break
        for row in expired:
            ticket_id = str(row.get("ticket_id", "")).strip()
            if not ticket_id:
                continue
            prefix = f"{_ticket_prefix(config, ticket_id)}/"
            blobs = list_blobs(
                config.CLOSED_TICKET_ARCHIVE_CONTAINER,
                prefix=prefix,
                limit=1000,
                store=blob_service,
            )
            if blobs:
                delete_blobs(
                    config.CLOSED_TICKET_ARCHIVE_CONTAINER,
                    [blob.blob_name for blob in blobs],
                    store=blob_service,
                )
                objects_deleted += len(blobs)
            cosmos_store.delete_closed_ticket(config.CLOSED_TICKET_CONTAINER, ticket_id)
            deleted += 1
        if len(expired) < 500:
            break
    return deleted, objects_deleted


def _reconcile_active_tickets(
    config: Config,
    cosmos_store: CosmosStore,
    *,
    customer_query: str,
    source_table: str,
    retention_start: datetime,
    session: requests.Session | None,
    token: str,
    base_url: str,
) -> ReconcileResult:
    window_clause = f"sys_updated_on>={_servicenow_query_timestamp(retention_start)}"
    encoded_query = _combine_encoded_query([customer_query, window_clause])
    rows, truncated = _fetch_table_rows_list(
        config,
        table=source_table,
        encoded_query=encoded_query,
        session=session,
        max_records=MAX_RECONCILE_IDS_PER_RUN,
        token=token,
        base_url=base_url,
    )
    seen_ids: set[str] = set()
    for row in rows:
        sys_id = str(_field_raw_value(row.get("sys_id")) or "").strip()
        if sys_id:
            seen_ids.add(sys_id)
    if truncated:
        return ReconcileResult(deactivated=0, seen_ids=frozenset(seen_ids), complete=False)
    if not seen_ids:
        return ReconcileResult(deactivated=0, seen_ids=frozenset(), complete=True)

    active_rows = cosmos_store.list_active_closed_tickets_updated_since(
        config.CLOSED_TICKET_CONTAINER,
        start_timestamp=_format_servicenow_timestamp(retention_start),
        limit=MAX_RECONCILE_IDS_PER_RUN,
    )
    stale_ids = [
        str(row.get("ticket_id", "")).strip()
        for row in active_rows
        if str(row.get("ticket_id", "")).strip() and str(row.get("ticket_id", "")).strip() not in seen_ids
    ]

    deactivated = 0
    synced_at = _format_servicenow_timestamp(datetime.now(UTC))
    for ticket_id in stale_ids:
        try:
            if cosmos_store.deactivate_closed_ticket(
                config.CLOSED_TICKET_CONTAINER,
                ticket_id=ticket_id,
                synced_at=synced_at,
            ):
                deactivated += 1
        except Exception:
            continue
    return ReconcileResult(
        deactivated=deactivated,
        seen_ids=frozenset(seen_ids),
        complete=True,
    )


def run_closed_ticket_sync(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any | None = None,
    http_session: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one ServiceNow closed ticket raw sync cycle."""
    summary = SyncSummary()
    if not bool(config.SERVICENOW_CLOSED_TICKET_SYNC_ENABLED):
        summary.enabled = False
        summary.skipped = True
        return summary.as_dict()

    run_at = now or datetime.now(UTC)
    try:
        base_url = validate_https_url(
            config.SERVICENOW_BASE_URL,
            setting_name="SERVICENOW_BASE_URL",
            allow_private=config.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
        )
        token = _resolve_sync_token(config)
        if not token:
            summary.errors.append("SERVICENOW_CLOSED_TICKET_TOKEN is required")
            return summary.as_dict()
        customer_query = str(config.SERVICENOW_CLOSED_TICKET_QUERY or "").strip()
        if not customer_query:
            summary.errors.append("SERVICENOW_CLOSED_TICKET_QUERY is required")
            return summary.as_dict()
        if not config.CLOSED_TICKET_CONTAINER.strip():
            summary.errors.append("CLOSED_TICKET_CONTAINER is required")
            return summary.as_dict()
        if not config.CLOSED_TICKET_SYNC_STATE_CONTAINER.strip():
            summary.errors.append("CLOSED_TICKET_SYNC_STATE_CONTAINER is required")
            return summary.as_dict()
        if not config.CLOSED_TICKET_ARCHIVE_CONTAINER.strip():
            summary.errors.append("CLOSED_TICKET_ARCHIVE_CONTAINER is required")
            return summary.as_dict()
        retention_days = int(config.CLOSED_TICKET_RETENTION_DAYS)
        if retention_days not in _CLOSED_TICKET_RETENTION_ALLOWED:
            summary.errors.append("CLOSED_TICKET_RETENTION_DAYS must be 30, 60, or 90")
            return summary.as_dict()
        source_table = _validate_table_name(config.SERVICENOW_CLOSED_TICKET_TABLE)
    except ValueError as exc:
        summary.errors.append(str(exc))
        return summary.as_dict()

    owns_session = http_session is None
    session = http_session or requests.Session()
    try:
        deleted, objects_deleted = _purge_expired_tickets(
            config=config,
            cosmos_store=cosmos_store,
            blob_service=blob_service,
            now=run_at,
        )
        summary.retention_tickets_deleted = deleted
        summary.retention_objects_deleted = objects_deleted

        cursor_state = _read_cursor(cosmos_store, config.CLOSED_TICKET_SYNC_STATE_CONTAINER)
        backfill_start = run_at - timedelta(days=int(config.SERVICENOW_CLOSED_TICKET_BACKFILL_DAYS))
        retention_start = run_at - timedelta(days=retention_days)

        rows = list(
            fetch_closed_tickets(
                config,
                customer_query=customer_query,
                source_table=source_table,
                cursor=cursor_state,
                backfill_start=backfill_start,
                overlap_hours=int(config.SERVICENOW_CLOSED_TICKET_CURSOR_OVERLAP_HOURS),
                session=session,
                token=token,
                base_url=base_url,
            )
        )
        summary.fetched = len(rows)

        mapped: list[TicketRecord] = []
        malformed = 0
        for row in rows:
            journals: list[Any] = []
            sys_id = str(_field_raw_value(row.get("sys_id")) or "").strip()
            if bool(config.SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS) and sys_id:
                try:
                    journal_fetch = fetch_ticket_journals(
                        config,
                        ticket_sys_id=sys_id,
                        session=session,
                        token=token,
                        base_url=base_url,
                    )
                    if journal_fetch.truncated:
                        summary.journal_fetches_truncated += 1
                    journals = _apply_truncation_marker(
                        journal_fetch.rows,
                        "journals",
                        journal_fetch.truncated,
                    )
                    summary.journals_fetched += len(journal_fetch.rows)
                except Exception as exc:
                    logger.warning("journal fetch failed for %s: %s", sys_id, exc)
            try:
                ticket = _build_ticket_record(
                    row,
                    source_table=source_table,
                    base_url=base_url,
                    journals_payload=journals,
                )
                mapped.append(ticket)
            except ValueError as exc:
                malformed += 1
                logger.warning("skipping malformed ServiceNow ticket row: %s", exc)

        summary.malformed = malformed
        if rows and malformed / len(rows) > MALFORMED_ROW_FAIL_RATIO:
            summary.errors.append(
                f"malformed row ratio exceeded {MALFORMED_ROW_FAIL_RATIO:.0%}"
            )
            return summary.as_dict()

        mapped.sort(key=lambda item: (item.source_updated_at, item.ticket_id))
        cursor_candidate: tuple[datetime, str] | None = None

        for ticket in mapped:
            try:
                att_fetched, att_downloaded, att_truncated, attachments = _process_attachments(
                    config,
                    ticket_id=ticket.ticket_id,
                    source_table=source_table,
                    session=session,
                    token=token,
                    base_url=base_url,
                    blob_service=blob_service,
                )
                summary.attachments_fetched += att_fetched
                summary.attachments_downloaded += att_downloaded
                if att_truncated:
                    summary.attachment_metadata_truncated += 1

                action = _upsert_ticket(
                    config=config,
                    cosmos_store=cosmos_store,
                    blob_service=blob_service,
                    ticket=ticket,
                    attachments=attachments,
                    retention_days=retention_days,
                )
                if action == "skipped":
                    summary.skipped_noop += 1
                else:
                    summary.persisted += 1

                if cursor_candidate is None or (
                    ticket.source_updated_at,
                    ticket.ticket_id,
                ) > cursor_candidate:
                    cursor_candidate = (ticket.source_updated_at, ticket.ticket_id)
            except Exception as exc:
                summary.errors.append(f"failed to persist ticket {ticket.ticket_id}: {exc}")
                logger.exception("ticket persistence failed for %s", ticket.ticket_id)

        should_reconcile = (
            cursor_state.last_reconciled_at is None
            or run_at - cursor_state.last_reconciled_at
            >= timedelta(days=int(config.SERVICENOW_CLOSED_TICKET_RECONCILE_INTERVAL_DAYS))
        )
        last_reconciled_at = cursor_state.last_reconciled_at
        if should_reconcile:
            try:
                reconcile_result = _reconcile_active_tickets(
                    config,
                    cosmos_store,
                    customer_query=customer_query,
                    source_table=source_table,
                    retention_start=retention_start,
                    session=session,
                    token=token,
                    base_url=base_url,
                )
                summary.deactivated += reconcile_result.deactivated
                summary.reconcile_incomplete = not reconcile_result.complete
                if reconcile_result.complete:
                    summary.reconciled = 1
                    last_reconciled_at = run_at
            except Exception as exc:
                logger.warning("reconciliation pass failed: %s", exc)

        if cursor_candidate is not None:
            _write_cursor(
                cosmos_store,
                config.CLOSED_TICKET_SYNC_STATE_CONTAINER,
                cursor_value=cursor_candidate[0],
                cursor_sys_id=cursor_candidate[1],
                last_reconciled_at=last_reconciled_at,
                updated_at=run_at,
            )
            summary.cursor_advanced = True
            summary.max_source_updated_at = cursor_candidate[0]
            summary.max_cursor_sys_id = cursor_candidate[1]
        elif last_reconciled_at != cursor_state.last_reconciled_at and cursor_state.cursor_value:
            _write_cursor(
                cosmos_store,
                config.CLOSED_TICKET_SYNC_STATE_CONTAINER,
                cursor_value=cursor_state.cursor_value,
                cursor_sys_id=cursor_state.cursor_sys_id,
                last_reconciled_at=last_reconciled_at,
                updated_at=run_at,
            )
    except Exception as exc:
        summary.errors.append(str(exc))
        logger.exception("ServiceNow closed ticket sync failed")
    finally:
        if owns_session:
            session.close()

    return summary.as_dict()
