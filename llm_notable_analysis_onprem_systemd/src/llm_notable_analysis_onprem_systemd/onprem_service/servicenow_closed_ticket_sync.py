"""Read-only ServiceNow closed ticket raw sync into Postgres."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import quote

import requests

from .case_db import default_connect, fetchone, set_statement_timeout
from .config import Config
from .servicenow_disposition_sync import (
    _parse_sn_datetime,
    _request_with_retry,
    _sn_query_timestamp,
    _validate_servicenow_https,
)

logger = logging.getLogger(__name__)

JOB_NAME = "servicenow_closed_tickets"
MAX_RECORDS_PER_RUN = 500
PAGE_SIZE = 100
MAX_RECONCILE_IDS_PER_RUN = 2000
MAX_HTTP_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
MALFORMED_ROW_FAIL_RATIO = 0.10
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_JOURNAL_TABLE = "sys_journal_field"
_ATTACHMENT_TABLE = "sys_attachment"


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
    index_selected: int = 0
    index_ready: int = 0
    index_failed: int = 0
    index_skipped: int = 0
    index_errors: list[str] = field(default_factory=list)


def _table_api_url(base_url: str, table: str) -> str:
    return f"{base_url.rstrip('/')}/api/now/table/{table}"


def _validate_table_name(table: str) -> str:
    normalized = str(table or "").strip()
    if not _TABLE_NAME_RE.fullmatch(normalized):
        raise ValueError("SERVICENOW_CLOSED_TICKET_TABLE must match [a-z0-9_]+")
    return normalized


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
        parsed = _parse_sn_datetime(_field_raw_value(row.get(key)))
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


_SEMANTIC_ATTACHMENT_META_KEYS = ("semantic_description", "semantic_extraction_status")


def _merge_attachment_source_metadata(
    existing: dict[str, Any] | None,
    source_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Merge ServiceNow attachment metadata without erasing semantic extraction fields."""
    merged = dict(source_metadata)
    if existing:
        for key in _SEMANTIC_ATTACHMENT_META_KEYS:
            value = existing.get(key)
            if value is not None and str(value).strip():
                merged[key] = value
    return merged


def _fetch_attachment_row_state(
    conn: Any,
    schema: str,
    attachment_id: str,
) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
    row = fetchone(
        conn.execute(
            f"""
            SELECT content_hash, download_status, storage_path, metadata
            FROM {schema}.attachments
            WHERE attachment_id = %s
            """,
            (attachment_id,),
        )
    )
    if row is None:
        return None, None, None, {}
    if isinstance(row, dict):
        content_hash = row.get("content_hash")
        download_status = row.get("download_status")
        storage_path = row.get("storage_path")
        metadata = row.get("metadata") or {}
    else:
        content_hash = row[0]
        download_status = row[1]
        storage_path = row[2]
        metadata = row[3]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, dict):
        metadata = {}
    return (
        str(content_hash or "") or None,
        str(download_status or "").strip() or None,
        str(storage_path or "").strip() or None,
        dict(metadata),
    )


def _mark_ticket_index_pending(conn: Any, schema: str, ticket_id: str) -> None:
    conn.execute(
        f"""
        UPDATE {schema}.servicenow_tickets
        SET index_status = 'pending',
            index_error = NULL
        WHERE ticket_id = %s
          AND is_active = true
        """,
        (ticket_id,),
    )


def _attachment_row_changed(
    *,
    before_hash: str | None,
    before_status: str | None,
    after_hash: str,
    after_status: str,
    after_storage_path: str | None,
    before_storage_path: str | None = None,
) -> bool:
    if before_hash is None:
        return True
    if before_hash != after_hash:
        return True
    if before_status != after_status:
        return True
    if (before_storage_path or "") != (after_storage_path or ""):
        return True
    return False


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
    source_updated_at = _parse_sn_datetime(_field_raw_value(row.get("sys_updated_on")))
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
    content_hash = _content_hash(raw_payload, journals_payload)

    return TicketRecord(
        ticket_id=sys_id,
        ticket_number=ticket_number,
        source_table=source_table,
        source_url=source_url,
        state=state,
        closed_at=closed_at,
        source_updated_at=source_updated_at,
        raw_payload=raw_payload,
        journals_payload=journals_payload,
        content_hash=content_hash,
    )


def _cursor_clause(
    cursor: CursorState,
    *,
    overlap_hours: int,
    backfill_start: datetime,
) -> str:
    if cursor.cursor_value is None:
        return f"sys_updated_on>={_sn_query_timestamp(backfill_start)}"
    overlap_start = cursor.cursor_value - timedelta(hours=int(overlap_hours))
    ts = _sn_query_timestamp(overlap_start)
    sys_id = str(cursor.cursor_sys_id or "").strip()
    if sys_id:
        return (
            f"sys_updated_on>{ts}^OR^sys_updated_on={ts}^sys_id>{sys_id}"
        )
    return f"sys_updated_on>{ts}"


def _fetch_table_rows(
    config: Config,
    *,
    table: str,
    encoded_query: str,
    session: requests.Session | None = None,
    max_records: int = MAX_RECORDS_PER_RUN,
) -> Iterator[dict[str, Any]]:
    """Fetch Table API rows with full records (no sysparm_fields limit)."""
    _validate_servicenow_https(config.SERVICENOW_BASE_URL)
    token = str(config.SERVICENOW_CLOSED_TICKET_TOKEN or "").strip()
    if not token:
        raise ValueError("SERVICENOW_CLOSED_TICKET_TOKEN is required")

    url = _table_api_url(config.SERVICENOW_BASE_URL, table)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    timeout_seconds = int(getattr(config, "SERVICENOW_TIMEOUT_SECONDS", 15))

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
            "GET",
            url,
            headers=headers,
            params=params,
            timeout_seconds=timeout_seconds,
            session=session,
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


def fetch_closed_tickets(
    config: Config,
    *,
    customer_query: str,
    source_table: str,
    cursor: CursorState,
    backfill_start: datetime,
    overlap_hours: int,
    session: requests.Session | None = None,
) -> Iterator[dict[str, Any]]:
    """Fetch closed tickets using the customer query plus cursor/backfill clauses."""
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
    )


def fetch_ticket_journals(
    config: Config,
    *,
    ticket_sys_id: str,
    session: requests.Session | None = None,
) -> list[Any]:
    """Fetch complete journal rows for one ticket (fail-soft at caller)."""
    query = f"element_id={ticket_sys_id}"
    rows = list(
        _fetch_table_rows(
            config,
            table=_JOURNAL_TABLE,
            encoded_query=query,
            session=session,
            max_records=PAGE_SIZE,
        )
    )
    return [_enrich_display_values(row) for row in rows]


def fetch_ticket_attachment_rows(
    config: Config,
    *,
    source_table: str,
    ticket_sys_id: str,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    query = f"table_name={source_table}^table_sys_id={ticket_sys_id}"
    rows = list(
        _fetch_table_rows(
            config,
            table=_ATTACHMENT_TABLE,
            encoded_query=query,
            session=session,
            max_records=PAGE_SIZE,
        )
    )
    return [_enrich_display_values(row) for row in rows]


def _download_attachment_bytes(
    config: Config,
    *,
    attachment_sys_id: str,
    max_bytes: int,
    session: requests.Session | None = None,
) -> bytes | None:
    token = str(config.SERVICENOW_CLOSED_TICKET_TOKEN or "").strip()
    url = (
        f"{config.SERVICENOW_BASE_URL.rstrip('/')}/api/now/attachment/"
        f"{attachment_sys_id}/file"
    )
    headers = {"Authorization": f"Bearer {token}", "Accept": "*/*"}
    timeout_seconds = int(getattr(config, "SERVICENOW_TIMEOUT_SECONDS", 15))
    client = session or requests
    response = client.get(
        url,
        headers=headers,
        timeout=timeout_seconds,
        stream=True,
    )
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


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".download-", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _schema_ident(config: Config) -> str:
    return str(config.CLOSED_TICKET_POSTGRES_SCHEMA).strip()


def _read_cursor(conn: Any, schema: str) -> CursorState:
    row = fetchone(
        conn.execute(
            f"""
            SELECT cursor_value, cursor_sys_id, last_reconciled_at
            FROM {schema}.sync_state
            WHERE job_name = %s
            """,
            (JOB_NAME,),
        )
    )
    if row is None:
        return CursorState(cursor_value=None, cursor_sys_id="", last_reconciled_at=None)

    if isinstance(row, dict):
        cursor_value = row.get("cursor_value")
        cursor_sys_id = str(row.get("cursor_sys_id") or "")
        last_reconciled_at = row.get("last_reconciled_at")
    else:
        cursor_value = row[0]
        cursor_sys_id = str(row[1] or "")
        last_reconciled_at = row[2]

    parsed_cursor: datetime | None = None
    if cursor_value is not None:
        if isinstance(cursor_value, datetime):
            parsed_cursor = (
                cursor_value.replace(tzinfo=timezone.utc)
                if cursor_value.tzinfo is None
                else cursor_value.astimezone(timezone.utc)
            )
        else:
            parsed_cursor = _parse_sn_datetime(cursor_value)

    parsed_reconciled: datetime | None = None
    if last_reconciled_at is not None:
        if isinstance(last_reconciled_at, datetime):
            parsed_reconciled = (
                last_reconciled_at.replace(tzinfo=timezone.utc)
                if last_reconciled_at.tzinfo is None
                else last_reconciled_at.astimezone(timezone.utc)
            )
        else:
            parsed_reconciled = _parse_sn_datetime(last_reconciled_at)

    return CursorState(
        cursor_value=parsed_cursor,
        cursor_sys_id=cursor_sys_id,
        last_reconciled_at=parsed_reconciled,
    )


def _write_cursor(
    conn: Any,
    schema: str,
    *,
    cursor_value: datetime,
    cursor_sys_id: str,
    last_reconciled_at: datetime | None = None,
) -> None:
    conn.execute(
        f"""
        INSERT INTO {schema}.sync_state (
            job_name, cursor_value, cursor_sys_id, last_reconciled_at, updated_at
        ) VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (job_name) DO UPDATE
        SET cursor_value = EXCLUDED.cursor_value,
            cursor_sys_id = EXCLUDED.cursor_sys_id,
            last_reconciled_at = COALESCE(EXCLUDED.last_reconciled_at, {schema}.sync_state.last_reconciled_at),
            updated_at = now()
        """,
        (JOB_NAME, cursor_value, cursor_sys_id, last_reconciled_at),
    )


def _existing_content_hash(conn: Any, schema: str, ticket_id: str) -> str | None:
    row = fetchone(
        conn.execute(
            f"""
            SELECT content_hash
            FROM {schema}.servicenow_tickets
            WHERE ticket_id = %s
            """,
            (ticket_id,),
        )
    )
    if row is None:
        return None
    return str(row[0] if not isinstance(row, dict) else row.get("content_hash") or "")


def _upsert_ticket(
    conn: Any,
    schema: str,
    ticket: TicketRecord,
    *,
    retention_days: int,
) -> str:
    existing_hash = _existing_content_hash(conn, schema, ticket.ticket_id)
    if existing_hash == ticket.content_hash:
        return "skipped"

    expires_at = datetime.now(timezone.utc) + timedelta(days=int(retention_days))
    index_status = "pending"

    conn.execute(
        f"""
        INSERT INTO {schema}.servicenow_tickets (
            ticket_id,
            ticket_number,
            source_table,
            source_url,
            state,
            is_active,
            closed_at,
            source_updated_at,
            raw_payload,
            journals_payload,
            content_hash,
            synced_at,
            expires_at,
            index_status
        ) VALUES (
            %s, %s, %s, %s, %s, true, %s, %s, %s::jsonb, %s::jsonb, %s, now(), %s, %s
        )
        ON CONFLICT (ticket_id) DO UPDATE SET
            ticket_number = EXCLUDED.ticket_number,
            source_table = EXCLUDED.source_table,
            source_url = EXCLUDED.source_url,
            state = EXCLUDED.state,
            is_active = true,
            closed_at = EXCLUDED.closed_at,
            source_updated_at = EXCLUDED.source_updated_at,
            raw_payload = EXCLUDED.raw_payload,
            journals_payload = EXCLUDED.journals_payload,
            content_hash = EXCLUDED.content_hash,
            synced_at = now(),
            expires_at = EXCLUDED.expires_at,
            index_status = CASE
                WHEN {schema}.servicenow_tickets.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                THEN 'pending'
                ELSE {schema}.servicenow_tickets.index_status
            END,
            index_error = CASE
                WHEN {schema}.servicenow_tickets.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                THEN NULL
                ELSE {schema}.servicenow_tickets.index_error
            END
        """,
        (
            ticket.ticket_id,
            ticket.ticket_number,
            ticket.source_table,
            ticket.source_url,
            ticket.state,
            ticket.closed_at,
            ticket.source_updated_at,
            json.dumps(ticket.raw_payload),
            json.dumps(ticket.journals_payload),
            ticket.content_hash,
            expires_at,
            index_status,
        ),
    )
    return "inserted" if existing_hash is None else "updated"


def _upsert_attachment_metadata(
    conn: Any,
    schema: str,
    *,
    attachment_id: str,
    ticket_id: str,
    file_name: str | None,
    content_type: str | None,
    size_bytes: int | None,
    source_updated_at: datetime | None,
    metadata: dict[str, Any],
    content_hash: str,
    download_status: str,
    storage_path: str | None,
) -> None:
    conn.execute(
        f"""
        INSERT INTO {schema}.attachments (
            attachment_id,
            ticket_id,
            file_name,
            content_type,
            size_bytes,
            source_updated_at,
            storage_path,
            content_hash,
            download_status,
            metadata,
            synced_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now()
        )
        ON CONFLICT (attachment_id) DO UPDATE SET
            ticket_id = EXCLUDED.ticket_id,
            file_name = EXCLUDED.file_name,
            content_type = EXCLUDED.content_type,
            size_bytes = EXCLUDED.size_bytes,
            source_updated_at = EXCLUDED.source_updated_at,
            storage_path = EXCLUDED.storage_path,
            content_hash = EXCLUDED.content_hash,
            download_status = EXCLUDED.download_status,
            metadata = EXCLUDED.metadata,
            synced_at = now()
        """,
        (
            attachment_id,
            ticket_id,
            file_name,
            content_type,
            size_bytes,
            source_updated_at,
            storage_path,
            content_hash,
            download_status,
            json.dumps(metadata),
        ),
    )


def _deactivate_tickets(conn: Any, schema: str, ticket_ids: list[str]) -> int:
    if not ticket_ids:
        return 0
    result = conn.execute(
        f"""
        UPDATE {schema}.servicenow_tickets
        SET is_active = false,
            synced_at = now()
        WHERE ticket_id = ANY(%s)
          AND is_active = true
        """,
        (ticket_ids,),
    )
    return int(getattr(result, "rowcount", 0) or 0)


def _reconcile_active_tickets(
    config: Config,
    conn: Any,
    schema: str,
    *,
    customer_query: str,
    source_table: str,
    retention_start: datetime,
    session: requests.Session | None = None,
) -> tuple[int, set[str]]:
    """Best-effort reconciliation over the retention window; returns deactivated count."""
    window_clause = f"sys_updated_on>={_sn_query_timestamp(retention_start)}"
    encoded_query = _combine_encoded_query([customer_query, window_clause])
    seen_ids: set[str] = set()
    for row in _fetch_table_rows(
        config,
        table=source_table,
        encoded_query=encoded_query,
        session=session,
        max_records=MAX_RECONCILE_IDS_PER_RUN,
    ):
        sys_id = str(_field_raw_value(row.get("sys_id")) or "").strip()
        if sys_id:
            seen_ids.add(sys_id)

    if not seen_ids:
        return 0, seen_ids

    rows = conn.execute(
        f"""
        SELECT ticket_id
        FROM {schema}.servicenow_tickets
        WHERE is_active = true
          AND source_updated_at >= %s
        """,
        (retention_start,),
    )
    stale_ids: list[str] = []
    fetchall = getattr(rows, "fetchall", None)
    if callable(fetchall):
        for row in fetchall():
            ticket_id = (
                row[0]
                if not isinstance(row, dict)
                else str(row.get("ticket_id") or "")
            )
            if ticket_id and ticket_id not in seen_ids:
                stale_ids.append(ticket_id)

    deactivated = _deactivate_tickets(conn, schema, stale_ids)
    return deactivated, seen_ids


def _process_attachments(
    config: Config,
    conn: Any,
    schema: str,
    *,
    ticket_id: str,
    source_table: str,
    session: requests.Session | None = None,
) -> tuple[int, int]:
    if not bool(config.SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS):
        return 0, 0

    attachment_dir = Path(str(config.CLOSED_TICKET_ATTACHMENT_DIR))
    max_bytes = int(config.CLOSED_TICKET_ATTACHMENT_MAX_BYTES)
    fetched = 0
    downloaded = 0

    try:
        rows = fetch_ticket_attachment_rows(
            config,
            source_table=source_table,
            ticket_sys_id=ticket_id,
            session=session,
        )
    except Exception as exc:
        logger.warning("attachment metadata fetch failed for %s: %s", ticket_id, exc)
        return 0, 0

    for row in rows:
        attachment_id = str(_field_raw_value(row.get("sys_id")) or "").strip()
        if not attachment_id:
            continue
        fetched += 1
        file_name = str(_field_raw_value(row.get("file_name")) or "").strip() or None
        content_type = str(_field_raw_value(row.get("content_type")) or "").strip() or None
        size_raw = _field_raw_value(row.get("size_bytes"))
        size_bytes: int | None = None
        if size_raw is not None and str(size_raw).strip().isdigit():
            size_bytes = int(str(size_raw).strip())
        source_updated_at = _parse_sn_datetime(_field_raw_value(row.get("sys_updated_on")))
        metadata = _enrich_display_values(row)
        metadata_hash = _attachment_metadata_hash(metadata)
        before_hash, before_status, before_storage_path, existing_metadata = (
            _fetch_attachment_row_state(conn, schema, attachment_id)
        )
        merged_metadata = _merge_attachment_source_metadata(existing_metadata, metadata)

        download_status = "pending"
        storage_path: str | None = None
        if size_bytes is not None and size_bytes > max_bytes:
            download_status = "skipped"
        else:
            try:
                payload = _download_attachment_bytes(
                    config,
                    attachment_sys_id=attachment_id,
                    max_bytes=max_bytes,
                    session=session,
                )
            except Exception as exc:
                logger.warning(
                    "attachment download failed for %s: %s", attachment_id, exc
                )
                payload = None
            if payload is None:
                download_status = "failed"
            else:
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name or attachment_id)
                rel_path = Path(ticket_id) / f"{attachment_id}_{safe_name}"
                target = attachment_dir / rel_path
                try:
                    _atomic_write_bytes(target, payload)
                    storage_path = str(target)
                    download_status = "downloaded"
                    downloaded += 1
                except OSError as exc:
                    logger.warning("attachment write failed for %s: %s", attachment_id, exc)
                    download_status = "failed"

        _upsert_attachment_metadata(
            conn,
            schema,
            attachment_id=attachment_id,
            ticket_id=ticket_id,
            file_name=file_name,
            content_type=content_type,
            size_bytes=size_bytes,
            source_updated_at=source_updated_at,
            metadata=merged_metadata,
            content_hash=metadata_hash,
            download_status=download_status,
            storage_path=storage_path,
        )
        before_storage = existing_metadata.get("storage_path")
        if _attachment_row_changed(
            before_hash=before_hash,
            before_status=before_status,
            after_hash=metadata_hash,
            after_status=download_status,
            after_storage_path=storage_path,
            before_storage_path=before_storage_path,
        ):
            _mark_ticket_index_pending(conn, schema, ticket_id)

    return fetched, downloaded


def run_closed_ticket_sync(
    config: Config,
    connect: Callable[[str], Any] | None = None,
) -> SyncSummary:
    """Run one ServiceNow closed ticket raw sync cycle."""
    summary = SyncSummary()
    if not bool(getattr(config, "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED", False)):
        summary.enabled = False
        summary.skipped = True
        return summary

    try:
        _validate_servicenow_https(config.SERVICENOW_BASE_URL)
        token = str(getattr(config, "SERVICENOW_CLOSED_TICKET_TOKEN", "")).strip()
        if not token:
            summary.errors.append("SERVICENOW_CLOSED_TICKET_TOKEN is required")
            return summary
        customer_query = str(getattr(config, "SERVICENOW_CLOSED_TICKET_QUERY", "")).strip()
        if not customer_query:
            summary.errors.append("SERVICENOW_CLOSED_TICKET_QUERY is required")
            return summary
        dsn = str(getattr(config, "CASE_POSTGRES_DSN", "")).strip()
        if not dsn:
            summary.errors.append("CASE_POSTGRES_DSN is required")
            return summary

        source_table = _validate_table_name(config.SERVICENOW_CLOSED_TICKET_TABLE)
        schema = _schema_ident(config)
        retention_days = int(config.CLOSED_TICKET_RETENTION_DAYS)
        backfill_days = int(config.SERVICENOW_CLOSED_TICKET_BACKFILL_DAYS)
        overlap_hours = int(config.SERVICENOW_CLOSED_TICKET_CURSOR_OVERLAP_HOURS)
        reconcile_interval_days = int(
            config.SERVICENOW_CLOSED_TICKET_RECONCILE_INTERVAL_DAYS
        )
        retention_start = datetime.now(timezone.utc) - timedelta(days=retention_days)
        backfill_start = datetime.now(timezone.utc) - timedelta(days=backfill_days)
    except ValueError as exc:
        summary.errors.append(str(exc))
        return summary

    connect_fn = connect or default_connect
    conn = connect_fn(dsn)
    session = requests.Session()
    try:
        set_statement_timeout(
            conn, int(getattr(config, "CASE_POSTGRES_STATEMENT_TIMEOUT_MS", 5000))
        )
        cursor_state = _read_cursor(conn, schema)

        rows = list(
            fetch_closed_tickets(
                config,
                customer_query=customer_query,
                source_table=source_table,
                cursor=cursor_state,
                backfill_start=backfill_start,
                overlap_hours=overlap_hours,
                session=session,
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
                    journals = fetch_ticket_journals(
                        config, ticket_sys_id=sys_id, session=session
                    )
                    summary.journals_fetched += len(journals)
                except Exception as exc:
                    logger.warning("journal fetch failed for %s: %s", sys_id, exc)
            try:
                mapped.append(
                    _build_ticket_record(
                        row,
                        source_table=source_table,
                        base_url=config.SERVICENOW_BASE_URL,
                        journals_payload=journals,
                    )
                )
            except ValueError as exc:
                malformed += 1
                logger.warning("skipping malformed ServiceNow ticket row: %s", exc)

        summary.malformed = malformed
        if rows and malformed / len(rows) > MALFORMED_ROW_FAIL_RATIO:
            conn.rollback()
            summary.errors.append(
                f"malformed row ratio exceeded {MALFORMED_ROW_FAIL_RATIO:.0%}"
            )
            return summary

        mapped.sort(key=lambda item: (item.source_updated_at, item.ticket_id))
        cursor_candidate: tuple[datetime, str] | None = None

        for ticket in mapped:
            try:
                action = _upsert_ticket(
                    conn,
                    schema,
                    ticket,
                    retention_days=retention_days,
                )
                if action == "skipped":
                    summary.skipped_noop += 1
                else:
                    summary.persisted += 1

                att_fetched, att_downloaded = _process_attachments(
                    config,
                    conn,
                    schema,
                    ticket_id=ticket.ticket_id,
                    source_table=source_table,
                    session=session,
                )
                summary.attachments_fetched += att_fetched
                summary.attachments_downloaded += att_downloaded

                if cursor_candidate is None or (
                    ticket.source_updated_at,
                    ticket.ticket_id,
                ) > cursor_candidate:
                    cursor_candidate = (ticket.source_updated_at, ticket.ticket_id)
            except Exception as exc:
                summary.errors.append(
                    f"failed to persist ticket {ticket.ticket_id}: {exc}"
                )
                logger.exception("ticket persistence failed for %s", ticket.ticket_id)

        now = datetime.now(timezone.utc)
        should_reconcile = (
            cursor_state.last_reconciled_at is None
            or now - cursor_state.last_reconciled_at
            >= timedelta(days=reconcile_interval_days)
        )
        last_reconciled_at = cursor_state.last_reconciled_at
        if should_reconcile:
            try:
                deactivated, _ = _reconcile_active_tickets(
                    config,
                    conn,
                    schema,
                    customer_query=customer_query,
                    source_table=source_table,
                    retention_start=retention_start,
                    session=session,
                )
                summary.deactivated += deactivated
                summary.reconciled = 1
                last_reconciled_at = now
            except Exception as exc:
                logger.warning("reconciliation pass failed: %s", exc)

        if cursor_candidate is not None:
            _write_cursor(
                conn,
                schema,
                cursor_value=cursor_candidate[0],
                cursor_sys_id=cursor_candidate[1],
                last_reconciled_at=last_reconciled_at,
            )
            summary.cursor_advanced = True
            summary.max_source_updated_at = cursor_candidate[0]
            summary.max_cursor_sys_id = cursor_candidate[1]
        elif last_reconciled_at != cursor_state.last_reconciled_at:
            if cursor_state.cursor_value is not None:
                _write_cursor(
                    conn,
                    schema,
                    cursor_value=cursor_state.cursor_value,
                    cursor_sys_id=cursor_state.cursor_sys_id,
                    last_reconciled_at=last_reconciled_at,
                )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        summary.errors.append(str(exc))
        logger.exception("ServiceNow closed ticket sync failed")
    finally:
        session.close()
        conn.close()

    if (
        bool(getattr(config, "CLOSED_TICKET_RAG_ENABLED", False))
        and summary.enabled
        and not summary.skipped
        and not any(
            err.startswith("malformed row ratio exceeded")
            for err in summary.errors
        )
    ):
        try:
            from .closed_ticket_index import index_pending_closed_tickets

            index_summary = index_pending_closed_tickets(
                config=config,
                connect=connect_fn,
            )
            summary.index_selected = index_summary.selected
            summary.index_ready = index_summary.ready
            summary.index_failed = index_summary.failed
            summary.index_skipped = index_summary.skipped
            summary.index_errors.extend(index_summary.errors)
            if index_summary.errors:
                for err in index_summary.errors:
                    logger.warning("Closed-ticket index error: %s", err)
            logger.info(
                "Closed-ticket pending index complete selected=%s ready=%s failed=%s skipped=%s",
                index_summary.selected,
                index_summary.ready,
                index_summary.failed,
                index_summary.skipped,
            )
        except Exception as exc:
            summary.index_errors.append(str(exc))
            logger.exception("Closed-ticket pending indexing failed after sync")

    return summary
