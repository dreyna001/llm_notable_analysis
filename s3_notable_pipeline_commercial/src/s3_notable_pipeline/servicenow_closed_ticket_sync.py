"""Read-only ServiceNow closed ticket sync for AWS (Table API -> S3 + DynamoDB)."""

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

from .config import Config
from .runtime_security import resolve_secret_string, validate_https_url
from .servicenow_disposition_sync import (
    DispositionSyncAuthError,
    _format_servicenow_timestamp,
    _from_ddb_item,
    _parse_servicenow_datetime,
    _request_with_retry,
    _to_ddb_item,
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
_INDEX_STATUS_PENDING = "pending"


class ClosedTicketSyncConfigError(Exception):
    """Closed-ticket sync configuration validation failed."""


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
    retention_attachments_deleted: int = 0
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
            "retention_attachments_deleted": self.retention_attachments_deleted,
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


def ticket_manifest_key(prefix: str, ticket_id: str) -> str:
    """S3 key for the latest ticket manifest (P4 consumer entry point)."""

    return f"{_normalize_prefix(prefix)}/tickets/{ticket_id}/manifest.json"


def ticket_version_key(prefix: str, ticket_id: str, content_hash: str) -> str:
    """S3 key for an immutable versioned ticket JSON payload."""

    return (
        f"{_normalize_prefix(prefix)}/tickets/{ticket_id}/versions/{content_hash}/ticket.json"
    )


def attachment_object_key(
    prefix: str,
    *,
    ticket_id: str,
    attachment_id: str,
    file_name: str | None,
) -> str:
    """S3 key for a downloaded attachment blob."""

    safe_name = _safe_attachment_file_name(file_name, attachment_id)
    return (
        f"{_normalize_prefix(prefix)}/attachments/{ticket_id}/{attachment_id}/{safe_name}"
    )


def run_closed_ticket_sync(
    *,
    config: Config,
    s3_client: Any,
    dynamodb_client: Any,
    http_session: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one ServiceNow closed ticket sync cycle."""

    summary = SyncSummary()
    if not config.SERVICENOW_CLOSED_TICKET_SYNC_ENABLED:
        summary.enabled = False
        summary.skipped = True
        logger.info("ServiceNow closed ticket sync skipped: disabled")
        return summary.as_dict()

    run_at = _coerce_utc(now)
    try:
        base_url = validate_https_url(
            config.SERVICENOW_BASE_URL,
            setting_name="SERVICENOW_BASE_URL",
            allow_private=config.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
        )
        token = _resolve_sync_token(config)
        if not token:
            raise ClosedTicketSyncConfigError(
                "SERVICENOW_CLOSED_TICKET_TOKEN is required when closed ticket sync is enabled"
            )
        customer_query = str(config.SERVICENOW_CLOSED_TICKET_QUERY or "").strip()
        if not customer_query:
            raise ClosedTicketSyncConfigError("SERVICENOW_CLOSED_TICKET_QUERY is required")
        bucket = _resolve_archive_bucket(config)
        if not bucket:
            raise ClosedTicketSyncConfigError(
                "CLOSED_TICKET_ARCHIVE_BUCKET or OUTPUT_BUCKET_NAME is required"
            )
        if not config.CLOSED_TICKET_SYNC_STATE_TABLE.strip():
            raise ClosedTicketSyncConfigError("CLOSED_TICKET_SYNC_STATE_TABLE is required")
        if not config.CLOSED_TICKET_REGISTRY_TABLE.strip():
            raise ClosedTicketSyncConfigError("CLOSED_TICKET_REGISTRY_TABLE is required")
        source_table = _validate_table_name(config.SERVICENOW_CLOSED_TICKET_TABLE)
    except (ClosedTicketSyncConfigError, ValueError) as exc:
        summary.errors.append(str(exc))
        logger.error("ServiceNow closed ticket sync config error: %s", exc)
        return summary.as_dict()

    raw_prefix = config.CLOSED_TICKET_RAW_PREFIX
    retention_days = int(config.CLOSED_TICKET_RETENTION_DAYS)
    backfill_days = int(config.SERVICENOW_CLOSED_TICKET_BACKFILL_DAYS)
    overlap_hours = int(config.SERVICENOW_CLOSED_TICKET_CURSOR_OVERLAP_HOURS)
    reconcile_interval_days = int(config.SERVICENOW_CLOSED_TICKET_RECONCILE_INTERVAL_DAYS)
    retention_start = run_at - timedelta(days=retention_days)
    backfill_start = run_at - timedelta(days=backfill_days)

    session = http_session or requests.Session()
    try:
        summary.retention_tickets_deleted, summary.retention_attachments_deleted = (
            _purge_expired_tickets(
                config=config,
                s3_client=s3_client,
                dynamodb_client=dynamodb_client,
                bucket=bucket,
                raw_prefix=raw_prefix,
                run_at=run_at,
            )
        )

        cursor_state = _read_cursor(
            dynamodb_client,
            config.CLOSED_TICKET_SYNC_STATE_TABLE,
        )
        rows = list(
            fetch_closed_tickets(
                config,
                base_url=base_url,
                token=token,
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
                    journal_fetch = fetch_ticket_journals(
                        config,
                        base_url=base_url,
                        token=token,
                        ticket_sys_id=sys_id,
                        session=session,
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
                mapped.append(
                    _build_ticket_record(
                        row,
                        source_table=source_table,
                        base_url=base_url,
                        journals_payload=journals,
                    )
                )
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
                action = _persist_ticket(
                    config=config,
                    s3_client=s3_client,
                    dynamodb_client=dynamodb_client,
                    bucket=bucket,
                    raw_prefix=raw_prefix,
                    ticket=ticket,
                    retention_days=retention_days,
                    run_at=run_at,
                )
                if action == "skipped":
                    summary.skipped_noop += 1
                else:
                    summary.persisted += 1

                att_fetched, att_downloaded, att_truncated = _process_attachments(
                    config,
                    s3_client=s3_client,
                    dynamodb_client=dynamodb_client,
                    bucket=bucket,
                    raw_prefix=raw_prefix,
                    ticket_id=ticket.ticket_id,
                    source_table=source_table,
                    base_url=base_url,
                    token=token,
                    session=session,
                    run_at=run_at,
                )
                summary.attachments_fetched += att_fetched
                summary.attachments_downloaded += att_downloaded
                if att_truncated:
                    summary.attachment_metadata_truncated += 1

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
            >= timedelta(days=reconcile_interval_days)
        )
        last_reconciled_at = cursor_state.last_reconciled_at
        if should_reconcile:
            try:
                reconcile_result = _reconcile_active_tickets(
                    config,
                    dynamodb_client=dynamodb_client,
                    s3_client=s3_client,
                    bucket=bucket,
                    raw_prefix=raw_prefix,
                    base_url=base_url,
                    token=token,
                    customer_query=customer_query,
                    source_table=source_table,
                    retention_start=retention_start,
                    run_at=run_at,
                    session=session,
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
                dynamodb_client,
                config.CLOSED_TICKET_SYNC_STATE_TABLE,
                cursor_value=cursor_candidate[0],
                cursor_sys_id=cursor_candidate[1],
                last_reconciled_at=last_reconciled_at,
                updated_at=run_at,
            )
            summary.cursor_advanced = True
            summary.max_source_updated_at = cursor_candidate[0]
            summary.max_cursor_sys_id = cursor_candidate[1]
        elif last_reconciled_at != cursor_state.last_reconciled_at:
            if cursor_state.cursor_value is not None:
                _write_cursor(
                    dynamodb_client,
                    config.CLOSED_TICKET_SYNC_STATE_TABLE,
                    cursor_value=cursor_state.cursor_value,
                    cursor_sys_id=cursor_state.cursor_sys_id,
                    last_reconciled_at=last_reconciled_at,
                    updated_at=run_at,
                )
    except DispositionSyncAuthError as exc:
        summary.errors.append(str(exc))
        logger.error("ServiceNow closed ticket sync auth failed: %s", exc)
    except Exception as exc:
        summary.errors.append(str(exc))
        logger.exception("ServiceNow closed ticket sync failed")

    logger.info("ServiceNow closed ticket sync finished: %s", summary.as_dict())
    return summary.as_dict()


def fetch_closed_tickets(
    config: Config,
    *,
    base_url: str,
    token: str,
    customer_query: str,
    source_table: str,
    cursor: CursorState,
    backfill_start: datetime,
    overlap_hours: int,
    session: requests.Session | None = None,
) -> Iterator[dict[str, Any]]:
    cursor_clause = _cursor_clause(
        cursor,
        overlap_hours=overlap_hours,
        backfill_start=backfill_start,
    )
    encoded_query = _combine_encoded_query([customer_query, cursor_clause])
    return _fetch_table_rows(
        base_url=base_url,
        token=token,
        table=source_table,
        encoded_query=encoded_query,
        timeout_seconds=config.SERVICENOW_TIMEOUT_SECONDS,
        session=session,
    )


def fetch_ticket_journals(
    config: Config,
    *,
    base_url: str,
    token: str,
    ticket_sys_id: str,
    session: requests.Session | None = None,
) -> TicketChildFetchResult:
    query = f"element_id={ticket_sys_id}"
    rows, truncated = _fetch_table_rows_list(
        base_url=base_url,
        token=token,
        table=_JOURNAL_TABLE,
        encoded_query=query,
        timeout_seconds=config.SERVICENOW_TIMEOUT_SECONDS,
        session=session,
        max_records=MAX_CHILD_RECORDS_PER_TICKET,
    )
    enriched = [_enrich_display_values(row) for row in rows]
    if truncated:
        logger.warning(
            "journal fetch truncated for ticket %s at %s rows",
            ticket_sys_id,
            len(enriched),
        )
    return TicketChildFetchResult(rows=enriched, truncated=truncated)


def fetch_ticket_attachment_rows(
    config: Config,
    *,
    base_url: str,
    token: str,
    source_table: str,
    ticket_sys_id: str,
    session: requests.Session | None = None,
) -> TicketChildFetchResult:
    query = f"table_name={source_table}^table_sys_id={ticket_sys_id}"
    rows, truncated = _fetch_table_rows_list(
        base_url=base_url,
        token=token,
        table=_ATTACHMENT_TABLE,
        encoded_query=query,
        timeout_seconds=config.SERVICENOW_TIMEOUT_SECONDS,
        session=session,
        max_records=MAX_CHILD_RECORDS_PER_TICKET,
    )
    enriched = [_enrich_display_values(row) for row in rows]
    if truncated:
        logger.warning(
            "attachment metadata truncated for ticket %s at %s rows",
            ticket_sys_id,
            len(enriched),
        )
    return TicketChildFetchResult(rows=enriched, truncated=truncated)


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


def _persist_ticket(
    *,
    config: Config,
    s3_client: Any,
    dynamodb_client: Any,
    bucket: str,
    raw_prefix: str,
    ticket: TicketRecord,
    retention_days: int,
    run_at: datetime,
) -> str:
    existing = _get_registry_item(
        dynamodb_client,
        config.CLOSED_TICKET_REGISTRY_TABLE,
        ticket.ticket_id,
    )
    if existing and str(existing.get("content_hash", "")) == ticket.content_hash:
        return "skipped"

    expires_at = compute_ticket_retention_expires_at(
        closed_at=ticket.closed_at,
        source_updated_at=ticket.source_updated_at,
        retention_days=retention_days,
        synced_at=run_at,
    )
    version_key = ticket_version_key(raw_prefix, ticket.ticket_id, ticket.content_hash)
    manifest_key = ticket_manifest_key(raw_prefix, ticket.ticket_id)
    payload = {
        "schema_version": 1,
        "ticket_id": ticket.ticket_id,
        "ticket_number": ticket.ticket_number,
        "source_table": ticket.source_table,
        "source_url": ticket.source_url,
        "state": ticket.state,
        "closed_at": _format_servicenow_timestamp(ticket.closed_at),
        "source_updated_at": _format_servicenow_timestamp(ticket.source_updated_at),
        "content_hash": ticket.content_hash,
        "raw_payload": ticket.raw_payload,
        "journals_payload": ticket.journals_payload,
        "synced_at": _format_servicenow_timestamp(run_at),
    }
    s3_client.put_object(
        Bucket=bucket,
        Key=version_key,
        Body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )
    index_status = (
        "not_indexed" if expires_at <= run_at else _INDEX_STATUS_PENDING
    )
    manifest = {
        "schema_version": 1,
        "ticket_id": ticket.ticket_id,
        "ticket_number": ticket.ticket_number,
        "source_table": ticket.source_table,
        "source_url": ticket.source_url,
        "state": ticket.state,
        "closed_at": _format_servicenow_timestamp(ticket.closed_at),
        "source_updated_at": _format_servicenow_timestamp(ticket.source_updated_at),
        "content_hash": ticket.content_hash,
        "version_key": version_key,
        "manifest_key": manifest_key,
        "is_active": True,
        "index_status": index_status,
        "synced_at": _format_servicenow_timestamp(run_at),
        "expires_at": _format_servicenow_timestamp(expires_at),
    }
    s3_client.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )
    _upsert_registry_item(
        dynamodb_client=dynamodb_client,
        table_name=config.CLOSED_TICKET_REGISTRY_TABLE,
        ticket_id=ticket.ticket_id,
        item={
            "ticket_id": ticket.ticket_id,
            "ticket_number": ticket.ticket_number or ticket.ticket_id,
            "content_hash": ticket.content_hash,
            "manifest_key": manifest_key,
            "version_key": version_key,
            "source_updated_at": _format_servicenow_timestamp(ticket.source_updated_at),
            "closed_at": _format_servicenow_timestamp(ticket.closed_at),
            "is_active": True,
            "index_status": index_status,
            "synced_at": _format_servicenow_timestamp(run_at),
            "expires_at": _format_servicenow_timestamp(expires_at),
            "expires_at_epoch": int(expires_at.timestamp()),
        },
    )
    return "inserted" if existing is None else "updated"


def _process_attachments(
    config: Config,
    *,
    s3_client: Any,
    dynamodb_client: Any,
    bucket: str,
    raw_prefix: str,
    ticket_id: str,
    source_table: str,
    base_url: str,
    token: str,
    session: requests.Session | None,
    run_at: datetime,
) -> tuple[int, int, bool]:
    if not bool(config.SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS):
        return 0, 0, False

    max_bytes = int(config.CLOSED_TICKET_ATTACHMENT_MAX_BYTES)
    fetched = 0
    downloaded = 0

    try:
        attachment_fetch = fetch_ticket_attachment_rows(
            config,
            base_url=base_url,
            token=token,
            source_table=source_table,
            ticket_sys_id=ticket_id,
            session=session,
        )
    except Exception as exc:
        logger.warning("attachment metadata fetch failed for %s: %s", ticket_id, exc)
        return 0, 0, False

    metadata_truncated = attachment_fetch.truncated
    for row in attachment_fetch.rows:
        if not isinstance(row, dict):
            continue
        attachment_id = str(_field_raw_value(row.get("sys_id")) or "").strip()
        if not attachment_id:
            continue
        try:
            _validate_servicenow_sys_id(attachment_id, "attachment_id")
            _validate_servicenow_sys_id(ticket_id, "ticket_id")
        except ValueError as exc:
            logger.warning("skipping attachment with invalid ids: %s", exc)
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
        existing = _get_attachment_registry(
            dynamodb_client,
            config.CLOSED_TICKET_REGISTRY_TABLE,
            attachment_id,
        )
        download_status = str(existing.get("download_status") or "pending") if existing else "pending"
        storage_key = str(existing.get("storage_key") or "").strip() if existing else ""

        if (
            existing
            and str(existing.get("metadata_hash", "")) == metadata_hash
            and download_status == "downloaded"
            and storage_key
        ):
            continue
        if size_bytes is not None and size_bytes > max_bytes:
            download_status = "skipped"
            storage_key = ""
        else:
            payload = _download_attachment_bytes(
                base_url=base_url,
                token=token,
                attachment_sys_id=attachment_id,
                max_bytes=max_bytes,
                timeout_seconds=config.SERVICENOW_TIMEOUT_SECONDS,
                session=session,
            )
            if payload is None:
                download_status = "failed" if not storage_key else download_status
            else:
                storage_key = attachment_object_key(
                    raw_prefix,
                    ticket_id=ticket_id,
                    attachment_id=attachment_id,
                    file_name=file_name,
                )
                put_kwargs: dict[str, Any] = {
                    "Bucket": bucket,
                    "Key": storage_key,
                    "Body": payload,
                }
                if content_type:
                    put_kwargs["ContentType"] = content_type
                s3_client.put_object(**put_kwargs)
                download_status = "downloaded"
                downloaded += 1

        _upsert_attachment_registry(
            dynamodb_client=dynamodb_client,
            table_name=config.CLOSED_TICKET_REGISTRY_TABLE,
            attachment_id=attachment_id,
            item={
                "record_type": "attachment",
                "attachment_id": attachment_id,
                "ticket_id": ticket_id,
                "file_name": file_name or attachment_id,
                "content_type": content_type or "",
                "size_bytes": size_bytes if size_bytes is not None else -1,
                "metadata_hash": metadata_hash,
                "download_status": download_status,
                "storage_key": storage_key,
                "synced_at": _format_servicenow_timestamp(run_at),
            },
        )
        if (
            existing is None
            or str(existing.get("metadata_hash", "")) != metadata_hash
            or str(existing.get("download_status", "")) != download_status
            or str(existing.get("storage_key", "")) != storage_key
        ):
            _mark_ticket_index_pending(
                dynamodb_client,
                config.CLOSED_TICKET_REGISTRY_TABLE,
                s3_client=s3_client,
                bucket=bucket,
                raw_prefix=raw_prefix,
                ticket_id=ticket_id,
                run_at=run_at,
            )

    return fetched, downloaded, metadata_truncated


def _reconcile_active_tickets(
    config: Config,
    *,
    dynamodb_client: Any,
    s3_client: Any,
    bucket: str,
    raw_prefix: str,
    base_url: str,
    token: str,
    customer_query: str,
    source_table: str,
    retention_start: datetime,
    run_at: datetime,
    session: requests.Session | None,
) -> ReconcileResult:
    window_clause = f"sys_updated_on>={_sn_query_timestamp(retention_start)}"
    encoded_query = _combine_encoded_query([customer_query, window_clause])
    rows, truncated = _fetch_table_rows_list(
        base_url=base_url,
        token=token,
        table=source_table,
        encoded_query=encoded_query,
        timeout_seconds=config.SERVICENOW_TIMEOUT_SECONDS,
        session=session,
        max_records=MAX_RECONCILE_IDS_PER_RUN,
    )
    seen_ids: set[str] = set()
    for row in rows:
        sys_id = str(_field_raw_value(row.get("sys_id")) or "").strip()
        if sys_id:
            seen_ids.add(sys_id)

    if truncated:
        logger.warning(
            "reconciliation incomplete: source fetch hit cap %s",
            MAX_RECONCILE_IDS_PER_RUN,
        )
        return ReconcileResult(deactivated=0, seen_ids=frozenset(seen_ids), complete=False)

    if not seen_ids:
        return ReconcileResult(deactivated=0, seen_ids=frozenset(), complete=True)

    stale_ids = _list_stale_active_ticket_ids(
        dynamodb_client,
        config.CLOSED_TICKET_REGISTRY_TABLE,
        retention_start=retention_start,
        seen_ids=seen_ids,
    )
    deactivated = 0
    for ticket_id in stale_ids:
        if _deactivate_ticket(
            dynamodb_client=dynamodb_client,
            s3_client=s3_client,
            bucket=bucket,
            raw_prefix=raw_prefix,
            table_name=config.CLOSED_TICKET_REGISTRY_TABLE,
            ticket_id=ticket_id,
            run_at=run_at,
        ):
            deactivated += 1
    return ReconcileResult(
        deactivated=deactivated,
        seen_ids=frozenset(seen_ids),
        complete=True,
    )


def _purge_expired_tickets(
    *,
    config: Config,
    s3_client: Any,
    dynamodb_client: Any,
    bucket: str,
    raw_prefix: str,
    run_at: datetime,
) -> tuple[int, int]:
    expired = _list_expired_ticket_ids(
        dynamodb_client,
        config.CLOSED_TICKET_REGISTRY_TABLE,
        run_at=run_at,
    )
    tickets_deleted = 0
    attachments_deleted = 0
    for ticket_id in expired:
        attachment_keys = _delete_ticket_storage(
            s3_client=s3_client,
            bucket=bucket,
            raw_prefix=raw_prefix,
            ticket_id=ticket_id,
        )
        attachments_deleted += len(attachment_keys)
        _delete_registry_ticket(
            dynamodb_client,
            config.CLOSED_TICKET_REGISTRY_TABLE,
            ticket_id,
        )
        tickets_deleted += 1
    return tickets_deleted, attachments_deleted


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


def _normalize_prefix(prefix: str) -> str:
    return str(prefix or "closed_tickets").strip().strip("/")


def _resolve_archive_bucket(config: Config) -> str:
    return (
        str(config.CLOSED_TICKET_ARCHIVE_BUCKET or "").strip()
        or str(config.OUTPUT_BUCKET_NAME or "").strip()
    )


def _resolve_sync_token(config: Config) -> str:
    direct = str(config.SERVICENOW_CLOSED_TICKET_TOKEN or "").strip()
    if direct:
        return direct
    secret_arn = str(config.SERVICENOW_CLOSED_TICKET_TOKEN_SECRET_ARN or "").strip()
    if not secret_arn or secret_arn == "*":
        return ""
    return resolve_secret_string(
        secret_arn=secret_arn,
        setting_name="SERVICENOW_CLOSED_TICKET_TOKEN",
        secret_field="token",
        fallback_fields=("SERVICENOW_CLOSED_TICKET_TOKEN",),
    )


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
    return TicketRecord(
        ticket_id=sys_id,
        ticket_number=_extract_ticket_number(row),
        source_table=source_table,
        source_url=(
            f"{base_url.rstrip('/')}/nav_to.do?uri="
            f"{quote(f'{source_table}.do?sys_id={sys_id}', safe='')}"
        ),
        state=_extract_state(row),
        closed_at=_extract_closed_at(row),
        source_updated_at=source_updated_at,
        raw_payload=raw_payload,
        journals_payload=journals_payload,
        content_hash=_content_hash(raw_payload, journals_payload),
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
        return f"sys_updated_on>{ts}^OR^sys_updated_on={ts}^sys_id>{sys_id}"
    return f"sys_updated_on>{ts}"


def _fetch_table_rows(
    *,
    base_url: str,
    token: str,
    table: str,
    encoded_query: str,
    timeout_seconds: int,
    session: requests.Session | None = None,
    max_records: int = MAX_RECORDS_PER_RUN,
) -> Iterator[dict[str, Any]]:
    url = _table_api_url(base_url, table)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
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
            session=session or requests,
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
    *,
    base_url: str,
    token: str,
    table: str,
    encoded_query: str,
    timeout_seconds: int,
    session: requests.Session | None,
    max_records: int,
) -> tuple[list[dict[str, Any]], bool]:
    rows = list(
        _fetch_table_rows(
            base_url=base_url,
            token=token,
            table=table,
            encoded_query=encoded_query,
            timeout_seconds=timeout_seconds,
            session=session,
            max_records=max_records,
        )
    )
    return rows, len(rows) >= int(max_records)


def _download_attachment_bytes(
    *,
    base_url: str,
    token: str,
    attachment_sys_id: str,
    max_bytes: int,
    timeout_seconds: int,
    session: requests.Session | None = None,
) -> bytes | None:
    url = f"{base_url.rstrip('/')}/api/now/attachment/{attachment_sys_id}/file"
    headers = {"Authorization": f"Bearer {token}", "Accept": "*/*"}
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


def _safe_attachment_file_name(file_name: str | None, attachment_id: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name or attachment_id).strip("_")
    if not safe_name:
        safe_name = attachment_id
    return safe_name[:200]


def _read_cursor(dynamodb_client: Any, table_name: str) -> CursorState:
    response = dynamodb_client.get_item(
        TableName=table_name,
        Key={"job_name": {"S": JOB_NAME}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return CursorState(cursor_value=None, cursor_sys_id="", last_reconciled_at=None)
    row = _from_ddb_item(item)
    cursor_value = _parse_servicenow_datetime(row.get("cursor_value"))
    last_reconciled_at = _parse_servicenow_datetime(row.get("last_reconciled_at"))
    return CursorState(
        cursor_value=cursor_value,
        cursor_sys_id=str(row.get("cursor_sys_id") or ""),
        last_reconciled_at=last_reconciled_at,
    )


def _write_cursor(
    dynamodb_client: Any,
    table_name: str,
    *,
    cursor_value: datetime,
    cursor_sys_id: str,
    last_reconciled_at: datetime | None,
    updated_at: datetime,
) -> None:
    item = {
        "job_name": JOB_NAME,
        "cursor_value": _format_servicenow_timestamp(cursor_value),
        "cursor_sys_id": cursor_sys_id,
        "updated_at": _format_servicenow_timestamp(updated_at),
    }
    if last_reconciled_at is not None:
        item["last_reconciled_at"] = _format_servicenow_timestamp(last_reconciled_at)
    dynamodb_client.put_item(TableName=table_name, Item=_to_ddb_item(item))


def _get_registry_item(
    dynamodb_client: Any,
    table_name: str,
    ticket_id: str,
) -> dict[str, Any] | None:
    response = dynamodb_client.get_item(
        TableName=table_name,
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


def _upsert_registry_item(
    *,
    dynamodb_client: Any,
    table_name: str,
    ticket_id: str,
    item: dict[str, Any],
) -> None:
    payload = dict(item)
    payload["ticket_id"] = ticket_id
    payload["record_type"] = "ticket"
    dynamodb_client.put_item(TableName=table_name, Item=_to_ddb_item(payload))


def _get_attachment_registry(
    dynamodb_client: Any,
    table_name: str,
    attachment_id: str,
) -> dict[str, Any] | None:
    response = dynamodb_client.get_item(
        TableName=table_name,
        Key={"ticket_id": {"S": f"attachment#{attachment_id}"}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None
    return _from_ddb_item(item)


def _upsert_attachment_registry(
    *,
    dynamodb_client: Any,
    table_name: str,
    attachment_id: str,
    item: dict[str, Any],
) -> None:
    payload = dict(item)
    payload["ticket_id"] = f"attachment#{attachment_id}"
    dynamodb_client.put_item(TableName=table_name, Item=_to_ddb_item(payload))


def _mark_ticket_index_pending(
    dynamodb_client: Any,
    table_name: str,
    *,
    s3_client: Any,
    bucket: str,
    raw_prefix: str,
    ticket_id: str,
    run_at: datetime,
) -> None:
    existing = _get_registry_item(dynamodb_client, table_name, ticket_id)
    if not existing:
        return
    existing["index_status"] = _INDEX_STATUS_PENDING
    existing["synced_at"] = _format_servicenow_timestamp(run_at)
    _upsert_registry_item(
        dynamodb_client=dynamodb_client,
        table_name=table_name,
        ticket_id=ticket_id,
        item=existing,
    )
    manifest_key = str(existing.get("manifest_key") or ticket_manifest_key(raw_prefix, ticket_id))
    try:
        response = s3_client.get_object(Bucket=bucket, Key=manifest_key)
        manifest = json.loads(response["Body"].read().decode("utf-8"))
        if isinstance(manifest, dict):
            manifest["index_status"] = _INDEX_STATUS_PENDING
            manifest["synced_at"] = _format_servicenow_timestamp(run_at)
            s3_client.put_object(
                Bucket=bucket,
                Key=manifest_key,
                Body=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                ),
                ContentType="application/json",
            )
    except Exception as exc:
        logger.warning("failed to update manifest index_status for %s: %s", ticket_id, exc)


def _list_stale_active_ticket_ids(
    dynamodb_client: Any,
    table_name: str,
    *,
    retention_start: datetime,
    seen_ids: set[str],
) -> list[str]:
    stale: list[str] = []
    request: dict[str, Any] = {
        "TableName": table_name,
        "FilterExpression": "record_type = :ticket AND is_active = :active",
        "ExpressionAttributeValues": {
            ":ticket": {"S": "ticket"},
            ":active": {"BOOL": True},
        },
    }
    retention_text = _format_servicenow_timestamp(retention_start)
    while True:
        response = dynamodb_client.scan(**request)
        for item in response.get("Items", []):
            row = _from_ddb_item(item)
            ticket_id = str(row.get("ticket_id") or "")
            if not ticket_id or ticket_id.startswith("attachment#"):
                continue
            source_updated_at = str(row.get("source_updated_at") or "")
            if source_updated_at and source_updated_at < retention_text:
                continue
            if ticket_id not in seen_ids:
                stale.append(ticket_id)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key
    return stale


def _deactivate_ticket(
    *,
    dynamodb_client: Any,
    s3_client: Any,
    bucket: str,
    raw_prefix: str,
    table_name: str,
    ticket_id: str,
    run_at: datetime,
) -> bool:
    existing = _get_registry_item(dynamodb_client, table_name, ticket_id)
    if not existing or existing.get("is_active") is False:
        return False
    existing["is_active"] = False
    existing["synced_at"] = _format_servicenow_timestamp(run_at)
    _upsert_registry_item(
        dynamodb_client=dynamodb_client,
        table_name=table_name,
        ticket_id=ticket_id,
        item=existing,
    )
    manifest_key = str(existing.get("manifest_key") or ticket_manifest_key(raw_prefix, ticket_id))
    try:
        response = s3_client.get_object(Bucket=bucket, Key=manifest_key)
        manifest = json.loads(response["Body"].read().decode("utf-8"))
        if isinstance(manifest, dict):
            manifest["is_active"] = False
            manifest["synced_at"] = _format_servicenow_timestamp(run_at)
            s3_client.put_object(
                Bucket=bucket,
                Key=manifest_key,
                Body=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                ),
                ContentType="application/json",
            )
    except Exception as exc:
        logger.warning("failed to deactivate manifest for %s: %s", ticket_id, exc)
    return True


def _list_expired_ticket_ids(
    dynamodb_client: Any,
    table_name: str,
    *,
    run_at: datetime,
) -> list[str]:
    expired: list[str] = []
    request: dict[str, Any] = {
        "TableName": table_name,
        "FilterExpression": "record_type = :ticket AND expires_at_epoch <= :now",
        "ExpressionAttributeValues": {
            ":ticket": {"S": "ticket"},
            ":now": {"N": str(int(run_at.timestamp()))},
        },
    }
    while True:
        response = dynamodb_client.scan(**request)
        for item in response.get("Items", []):
            row = _from_ddb_item(item)
            ticket_id = str(row.get("ticket_id") or "")
            if ticket_id and not ticket_id.startswith("attachment#"):
                expired.append(ticket_id)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key
    return expired


def _delete_registry_ticket(
    dynamodb_client: Any,
    table_name: str,
    ticket_id: str,
) -> None:
    dynamodb_client.delete_item(
        TableName=table_name,
        Key={"ticket_id": {"S": ticket_id}},
    )


def _delete_ticket_storage(
    *,
    s3_client: Any,
    bucket: str,
    raw_prefix: str,
    ticket_id: str,
) -> list[str]:
    deleted_keys: list[str] = []
    prefixes = [
        f"{_normalize_prefix(raw_prefix)}/tickets/{ticket_id}/",
        f"{_normalize_prefix(raw_prefix)}/attachments/{ticket_id}/",
    ]
    for prefix in prefixes:
        continuation: str | None = None
        while True:
            request: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
            if continuation:
                request["ContinuationToken"] = continuation
            response = s3_client.list_objects_v2(**request)
            for obj in response.get("Contents", []):
                key = str(obj.get("Key") or "")
                if key:
                    s3_client.delete_object(Bucket=bucket, Key=key)
                    deleted_keys.append(key)
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
    return deleted_keys


def _sn_query_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
