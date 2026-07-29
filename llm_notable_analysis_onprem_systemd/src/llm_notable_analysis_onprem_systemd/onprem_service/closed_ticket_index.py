"""Postgres indexing for closed-ticket hybrid retrieval chunks."""

# Optional database and embedding dependencies are imported lazily.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .case_db import (
    default_connect as _default_connect,
    fetchall as _fetchall,
    row_get as _row_get,
    set_statement_timeout as _set_statement_timeout,
)
from .case_store import quote_identifier
from .closed_ticket_attachment_processing import (
    ClosedTicketAttachmentInput,
    build_attachment_semantic_metadata,
)
from .closed_ticket_render import (
    ClosedTicketAttachmentRecord,
    ClosedTicketChunkRecord,
    ClosedTicketRecord,
    build_closed_ticket_chunks,
    closed_ticket_embedding_model,
)
from .config import Config

ConnectionFactory = Callable[[str], Any]
SleepFn = Callable[[float], None]

_RETRYABLE_EXCEPTION_NAMES = {
    "ConnectionTimeout",
    "InterfaceError",
    "OperationalError",
    "QueryCanceled",
    "Timeout",
}
_EMBEDDING_MODEL_CACHE: dict[str, Any] = {}
_EMBEDDING_MODEL_LOCK = threading.Lock()
_EMBEDDING_ENCODE_LOCK = threading.Lock()


class ClosedTicketChunkWriteError(RuntimeError):
    """Closed ticket chunk persistence failed."""


@dataclass(frozen=True)
class ClosedTicketIndexResult:
    """Summary of one ticket indexing attempt."""

    ticket_id: str
    chunk_count: int
    status: str
    skipped: bool = False
    error: str | None = None


@dataclass
class ClosedTicketPendingIndexResult:
    """Summary of a bounded pending/failed ticket indexing batch."""

    selected: int = 0
    ready: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _lazy_import_sentence_transformer() -> Any:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "sentence-transformers is unavailable in the runtime."
        ) from exc
    return SentenceTransformer


def _get_embedding_model(model_name: str) -> Any:
    normalized = (model_name or "").strip()
    if not normalized:
        raise ValueError("A closed-ticket embedding model name is required.")
    with _EMBEDDING_MODEL_LOCK:
        model = _EMBEDDING_MODEL_CACHE.get(normalized)
        if model is None:
            SentenceTransformer = _lazy_import_sentence_transformer()
            model = SentenceTransformer(normalized)
            _EMBEDDING_MODEL_CACHE[normalized] = model
        return model


def _config_str(config: Config, name: str, default: str) -> str:
    return str(getattr(config, name, default) or default).strip()


def _postgres_dsn(config: Config) -> str:
    dsn = _config_str(config, "CASE_POSTGRES_DSN", "")
    if not dsn:
        raise ValueError("CASE_POSTGRES_DSN is required for closed-ticket indexing.")
    return dsn


def _postgres_schema(config: Config) -> str:
    return _config_str(config, "CLOSED_TICKET_POSTGRES_SCHEMA", "notable_closed_tickets")


def _chunks_table_name(config: Config) -> str:
    return _config_str(config, "CLOSED_TICKET_POSTGRES_CHUNKS_TABLE", "ticket_chunks")


def _tickets_table(schema: str) -> str:
    return f"{quote_identifier(schema, 'schema')}.servicenow_tickets"


def _chunks_table(schema: str, table: str) -> str:
    return f"{quote_identifier(schema, 'schema')}.{quote_identifier(table, 'table')}"


def _attachments_table(schema: str) -> str:
    return f"{quote_identifier(schema, 'schema')}.attachments"


def _statement_timeout_ms(config: Config) -> int:
    return int(getattr(config, "CASE_POSTGRES_STATEMENT_TIMEOUT_MS", 5000))


def _vector_dimensions(config: Config) -> int:
    for key in ("CLOSED_TICKET_VECTOR_DIMENSIONS", "RAG_VECTOR_DIMENSIONS", "CASE_QA_VECTOR_DIMENSIONS"):
        value = getattr(config, key, None)
        if value is not None:
            return int(value)
    return 768


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_from_db(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _vectors_to_lists(values: Any) -> list[list[float]]:
    data = values.tolist() if hasattr(values, "tolist") else values
    return [[float(v) for v in row] for row in data]


def _l2_normalize_vector(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(v) * float(v) for v in values)) + 1e-12
    return [float(v) / norm for v in values]


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def _execute_many(conn: Any, sql: str, rows: Sequence[tuple[Any, ...]]) -> None:
    executemany = getattr(conn, "executemany", None)
    if callable(executemany):
        executemany(sql, rows)
        return
    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (ConnectionError, TimeoutError, OSError)) or (
        exc.__class__.__name__ in _RETRYABLE_EXCEPTION_NAMES
    )


def _attachment_max_bytes(config: Config) -> int:
    return max(1, int(getattr(config, "CLOSED_TICKET_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)))


def _attachment_root_dir(config: Config) -> Path | None:
    raw = getattr(config, "CLOSED_TICKET_ATTACHMENT_DIR", None)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return Path(text).expanduser().resolve(strict=False)


def resolve_safe_attachment_path(
    config: Config,
    storage_path: str | None,
) -> Path | None:
    """Resolve storage_path only when it lies inside CLOSED_TICKET_ATTACHMENT_DIR."""
    if storage_path is None or not str(storage_path).strip():
        return None
    root = _attachment_root_dir(config)
    if root is None:
        return None
    candidate = Path(str(storage_path).strip()).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
        resolved.relative_to(root_resolved)
    except (ValueError, OSError):
        return None
    return resolved


def read_bounded_attachment_bytes(
    path: Path,
    *,
    max_bytes: int,
) -> bytes | None:
    """Read up to max_bytes from a regular file path."""
    if max_bytes <= 0:
        return None
    try:
        if not path.is_file():
            return None
        with path.open("rb") as handle:
            return handle.read(max_bytes)
    except OSError:
        return None


def build_update_attachment_metadata_sql(schema: str) -> str:
    """Build SQL that updates attachment metadata JSON for one attachment row."""
    return (
        f"UPDATE {_attachments_table(schema)} "
        "SET metadata = %s::jsonb WHERE attachment_id = %s"
    )


def _semantic_metadata_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = ("semantic_description", "semantic_extraction_status")
    return any(before.get(key) != after.get(key) for key in keys)


def _persist_attachment_metadata_if_needed(
    conn: Any,
    *,
    schema: str,
    attachment_id: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    if not _semantic_metadata_changed(before, after):
        return
    sql = build_update_attachment_metadata_sql(schema)
    conn.execute(sql, (_json(after), attachment_id))


def _ticket_is_indexable(record: ClosedTicketRecord) -> bool:
    if not record.is_active:
        return False
    if record.expires_at is not None:
        now = datetime.now(record.expires_at.tzinfo or timezone.utc)
        if record.expires_at <= now:
            return False
    return True


def build_delete_ticket_chunks_sql(schema: str, table: str) -> str:
    """Build SQL that deletes chunks for one ticket."""
    return (
        f"DELETE FROM {_chunks_table(schema, table)} WHERE ticket_id = %s"
    )


def build_insert_ticket_chunks_sql(schema: str, table: str) -> str:
    """Build parameterized upsert SQL for closed-ticket chunk rows."""
    table_name = _chunks_table(schema, table)
    return f"""
INSERT INTO {table_name} (
    chunk_id,
    ticket_id,
    ordinal,
    section,
    field_path,
    text,
    embedding,
    metadata,
    chunk_schema_version,
    embedding_model
)
VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s::jsonb, %s, %s)
ON CONFLICT (chunk_id) DO UPDATE SET
    ticket_id = EXCLUDED.ticket_id,
    ordinal = EXCLUDED.ordinal,
    section = EXCLUDED.section,
    field_path = EXCLUDED.field_path,
    text = EXCLUDED.text,
    embedding = EXCLUDED.embedding,
    metadata = EXCLUDED.metadata,
    chunk_schema_version = EXCLUDED.chunk_schema_version,
    embedding_model = EXCLUDED.embedding_model
""".strip()


def build_update_ticket_index_status_sql(schema: str) -> str:
    """Build SQL that updates index status fields for one ticket."""
    return (
        f"UPDATE {_tickets_table(schema)} "
        "SET index_status = %s, index_error = %s, last_indexed_at = now() "
        "WHERE ticket_id = %s"
    )


def build_select_tickets_for_rebuild_sql(
    schema: str,
    *,
    ticket_id: str | None = None,
    after_ticket_id: str | None = None,
    extra_where_clauses: Sequence[str] = (),
) -> str:
    """Build SQL selecting ticket rows for chunk rebuild."""
    clauses: list[str] = list(extra_where_clauses)
    if ticket_id is not None:
        clauses.append("ticket_id = %s")
    elif after_ticket_id is not None:
        clauses.append("ticket_id > %s")
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return f"""
SELECT
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
    expires_at,
    content_hash
FROM {_tickets_table(schema)}
{where_clause}
ORDER BY ticket_id ASC
LIMIT %s
""".strip()


def build_select_pending_tickets_for_index_sql(
    schema: str,
    *,
    after_ticket_id: str | None = None,
) -> str:
    """Build SQL selecting active, unexpired pending/failed tickets for indexing."""
    return build_select_tickets_for_rebuild_sql(
        schema,
        after_ticket_id=after_ticket_id,
        extra_where_clauses=[
            "is_active = true",
            "expires_at > now()",
            "index_status IN ('pending', 'failed')",
        ],
    )


_ACTIVE_UNEXPIRED_WHERE: tuple[str, ...] = (
    "is_active = true",
    "expires_at > now()",
)


def build_select_attachments_for_ticket_sql(schema: str) -> str:
    """Build SQL selecting attachment rows for one ticket."""
    return f"""
SELECT
    attachment_id,
    ticket_id,
    file_name,
    content_type,
    storage_path,
    metadata,
    download_status
FROM {_attachments_table(schema)}
WHERE ticket_id = %s
ORDER BY attachment_id ASC
""".strip()


def _chunk_rows(
    *,
    chunks: Sequence[ClosedTicketChunkRecord],
    vectors: Sequence[Sequence[float]],
    vector_dimensions: int,
) -> list[tuple[Any, ...]]:
    if len(vectors) != len(chunks):
        raise ValueError(
            "Embedding model returned an unexpected number of vectors: "
            f"expected {len(chunks)}, got {len(vectors)}."
        )
    rows: list[tuple[Any, ...]] = []
    for chunk, vector in zip(chunks, vectors):
        if len(vector) != vector_dimensions:
            raise ValueError(
                "Embedding vector dimension mismatch: "
                f"expected {vector_dimensions}, got {len(vector)}."
            )
        rows.append(
            (
                chunk.chunk_id,
                chunk.ticket_id,
                chunk.ordinal,
                chunk.section,
                chunk.field_path,
                chunk.text,
                _vector_literal(_l2_normalize_vector(vector)),
                _json(chunk.metadata),
                chunk.chunk_schema_version,
                chunk.embedding_model,
            )
        )
    return rows


def _encode_chunk_vectors(
    *,
    chunks: Sequence[ClosedTicketChunkRecord],
    config: Config,
    embedding_model: Any = None,
) -> list[list[float]]:
    if not chunks:
        return []
    model = embedding_model or _get_embedding_model(closed_ticket_embedding_model(config))
    encode_args = {
        "show_progress_bar": False,
        "convert_to_numpy": True,
    }
    # Corpus chunks use raw passage text (no query prefix); queries use
    # format_embedding_query_text in closed_ticket_retrieval.
    texts = [chunk.text for chunk in chunks]
    if embedding_model is None:
        with _EMBEDDING_ENCODE_LOCK:
            encoded = model.encode(texts, **encode_args)
    else:
        encoded = model.encode(texts, **encode_args)
    return _vectors_to_lists(encoded)


def _record_from_row(row: Any) -> ClosedTicketRecord:
    return ClosedTicketRecord(
        ticket_id=_row_get(row, 0, "ticket_id"),
        ticket_number=_row_get(row, 1, "ticket_number"),
        source_table=_row_get(row, 2, "source_table"),
        source_url=_row_get(row, 3, "source_url"),
        state=_row_get(row, 4, "state"),
        is_active=bool(_row_get(row, 5, "is_active")),
        closed_at=_row_get(row, 6, "closed_at"),
        source_updated_at=_row_get(row, 7, "source_updated_at"),
        raw_payload=_json_from_db(_row_get(row, 8, "raw_payload")),
        journals_payload=_json_from_db(_row_get(row, 9, "journals_payload")),
        expires_at=_row_get(row, 10, "expires_at"),
        content_hash=_row_get(row, 11, "content_hash"),
    )


def _attachment_records_from_rows(
    rows: Sequence[Any],
    config: Config,
    *,
    conn: Any | None = None,
    schema: str | None = None,
) -> list[ClosedTicketAttachmentRecord]:
    output: list[ClosedTicketAttachmentRecord] = []
    for row in rows:
        metadata = _json_from_db(_row_get(row, 5, "metadata")) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        before_metadata = dict(metadata)
        storage_path = _row_get(row, 4, "storage_path")
        download_status = str(_row_get(row, 6, "download_status") or "").strip()
        raw_content: Any = None
        if download_status == "downloaded":
            safe_path = resolve_safe_attachment_path(config, storage_path)
            if safe_path is not None:
                raw_content = read_bounded_attachment_bytes(
                    safe_path,
                    max_bytes=_attachment_max_bytes(config),
                )
        attachment_id = str(_row_get(row, 0, "attachment_id"))
        enriched = build_attachment_semantic_metadata(
            ClosedTicketAttachmentInput(
                attachment_id=attachment_id,
                ticket_id=str(_row_get(row, 1, "ticket_id")),
                filename=_row_get(row, 2, "file_name"),
                content_type=_row_get(row, 3, "content_type"),
                metadata=dict(metadata),
                raw_content=raw_content,
            ),
            config=config,
        )
        if conn is not None and schema is not None:
            _persist_attachment_metadata_if_needed(
                conn,
                schema=schema,
                attachment_id=attachment_id,
                before=before_metadata,
                after=enriched.metadata,
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


def store_closed_ticket_chunks_once(
    *,
    ticket_id: str,
    config: Config,
    rows: Sequence[tuple[Any, ...]],
    index_status: str,
    index_error: str | None,
    connect: ConnectionFactory | None = None,
) -> int:
    """Replace stored chunks for one ticket within one database transaction."""
    connect_fn = connect or _default_connect
    schema = _postgres_schema(config)
    table = _chunks_table_name(config)
    delete_sql = build_delete_ticket_chunks_sql(schema, table)
    insert_sql = build_insert_ticket_chunks_sql(schema, table)
    status_sql = build_update_ticket_index_status_sql(schema)

    with connect_fn(_postgres_dsn(config)) as conn:
        _set_statement_timeout(conn, _statement_timeout_ms(config))
        conn.execute(delete_sql, (ticket_id,))
        if rows:
            _execute_many(conn, insert_sql, rows)
        conn.execute(status_sql, (index_status, index_error, ticket_id))
    return len(rows)


def index_closed_ticket_once(
    *,
    record: ClosedTicketRecord,
    config: Config,
    attachments: Sequence[ClosedTicketAttachmentRecord] = (),
    connect: ConnectionFactory | None = None,
    embedding_model: Any = None,
) -> ClosedTicketIndexResult:
    """Index one ticket without retry handling."""
    if not _ticket_is_indexable(record):
        store_closed_ticket_chunks_once(
            ticket_id=record.ticket_id,
            config=config,
            rows=[],
            index_status="not_indexed",
            index_error=None,
            connect=connect,
        )
        return ClosedTicketIndexResult(
            ticket_id=record.ticket_id,
            chunk_count=0,
            status="not_indexed",
            skipped=True,
        )

    chunks = build_closed_ticket_chunks(record, config, attachments=attachments)
    if not chunks:
        store_closed_ticket_chunks_once(
            ticket_id=record.ticket_id,
            config=config,
            rows=[],
            index_status="not_indexed",
            index_error=None,
            connect=connect,
        )
        return ClosedTicketIndexResult(
            ticket_id=record.ticket_id,
            chunk_count=0,
            status="not_indexed",
            skipped=False,
        )

    vectors = _encode_chunk_vectors(
        chunks=chunks,
        config=config,
        embedding_model=embedding_model,
    )
    rows = _chunk_rows(
        chunks=chunks,
        vectors=vectors,
        vector_dimensions=_vector_dimensions(config),
    )
    count = store_closed_ticket_chunks_once(
        ticket_id=record.ticket_id,
        config=config,
        rows=rows,
        index_status="ready",
        index_error=None,
        connect=connect,
    )
    return ClosedTicketIndexResult(
        ticket_id=record.ticket_id,
        chunk_count=count,
        status="ready",
    )


def index_closed_ticket(
    *,
    record: ClosedTicketRecord,
    config: Config,
    attachments: Sequence[ClosedTicketAttachmentRecord] = (),
    connect: ConnectionFactory | None = None,
    embedding_model: Any = None,
    sleep: SleepFn = time.sleep,
) -> ClosedTicketIndexResult:
    """Index one ticket with bounded retries and failed status on terminal errors."""
    attempts = max(1, int(getattr(config, "CASE_ARCHIVE_WRITE_MAX_ATTEMPTS", 3)))
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return index_closed_ticket_once(
                record=record,
                config=config,
                attachments=attachments,
                connect=connect,
                embedding_model=embedding_model,
            )
        except Exception as exc:
            if not _is_retryable(exc):
                try:
                    store_closed_ticket_chunks_once(
                        ticket_id=record.ticket_id,
                        config=config,
                        rows=[],
                        index_status="failed",
                        index_error=str(exc),
                        connect=connect,
                    )
                except Exception:
                    pass
                raise ClosedTicketChunkWriteError("closed ticket index failed") from exc
            last_exc = exc
            if attempt >= attempts:
                break
            sleep(float(getattr(config, "CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS", 1.0)))
    try:
        store_closed_ticket_chunks_once(
            ticket_id=record.ticket_id,
            config=config,
            rows=[],
            index_status="failed",
            index_error=str(last_exc),
            connect=connect,
        )
    except Exception:
        pass
    raise ClosedTicketChunkWriteError("closed ticket index failed after retries") from last_exc


def fetch_ticket_records(
    *,
    config: Config,
    ticket_id: str | None = None,
    after_ticket_id: str | None = None,
    limit: int,
    active_unexpired_only: bool = False,
    connect: ConnectionFactory | None = None,
) -> list[ClosedTicketRecord]:
    """Load ticket rows for rebuild operations."""
    connect_fn = connect or _default_connect
    schema = _postgres_schema(config)
    extra_where = list(_ACTIVE_UNEXPIRED_WHERE) if active_unexpired_only else []
    sql = build_select_tickets_for_rebuild_sql(
        schema,
        ticket_id=ticket_id,
        after_ticket_id=after_ticket_id if ticket_id is None else None,
        extra_where_clauses=extra_where,
    )
    if ticket_id is not None:
        params: tuple[Any, ...] = (ticket_id, limit)
    elif after_ticket_id is not None:
        params = (after_ticket_id, limit)
    else:
        params = (limit,)
    with connect_fn(_postgres_dsn(config)) as conn:
        _set_statement_timeout(conn, _statement_timeout_ms(config))
        rows = _fetchall(conn.execute(sql, params))
    return [_record_from_row(row) for row in rows]


def fetch_attachment_records_for_ticket(
    *,
    config: Config,
    ticket_id: str,
    connect: ConnectionFactory | None = None,
) -> list[ClosedTicketAttachmentRecord]:
    """Load attachment rows, extract semantic text, and persist metadata updates."""
    connect_fn = connect or _default_connect
    schema = _postgres_schema(config)
    sql = build_select_attachments_for_ticket_sql(schema)
    with connect_fn(_postgres_dsn(config)) as conn:
        _set_statement_timeout(conn, _statement_timeout_ms(config))
        rows = _fetchall(conn.execute(sql, (ticket_id,)))
        return _attachment_records_from_rows(
            rows,
            config,
            conn=conn,
            schema=schema,
        )


def fetch_pending_ticket_records(
    *,
    config: Config,
    after_ticket_id: str | None = None,
    limit: int,
    connect: ConnectionFactory | None = None,
) -> list[ClosedTicketRecord]:
    """Load pending/failed active tickets for incremental indexing."""
    connect_fn = connect or _default_connect
    schema = _postgres_schema(config)
    sql = build_select_pending_tickets_for_index_sql(
        schema,
        after_ticket_id=after_ticket_id,
    )
    params: tuple[Any, ...] = (
        (after_ticket_id, limit) if after_ticket_id is not None else (limit,)
    )
    with connect_fn(_postgres_dsn(config)) as conn:
        _set_statement_timeout(conn, _statement_timeout_ms(config))
        rows = _fetchall(conn.execute(sql, params))
    return [_record_from_row(row) for row in rows]


def index_pending_closed_tickets(
    *,
    config: Config,
    batch_size: int = 100,
    max_tickets: int | None = None,
    connect: ConnectionFactory | None = None,
    embedding_model: Any = None,
    sleep: SleepFn = time.sleep,
) -> ClosedTicketPendingIndexResult:
    """Index a bounded batch of pending/failed closed tickets."""
    page_size = max(1, int(batch_size))
    cap = max(1, int(max_tickets or page_size))
    result = ClosedTicketPendingIndexResult()
    after_ticket_id: str | None = None
    processed = 0

    while processed < cap:
        limit = min(page_size, cap - processed)
        records = fetch_pending_ticket_records(
            config=config,
            after_ticket_id=after_ticket_id,
            limit=limit,
            connect=connect,
        )
        if not records:
            break
        for record in records:
            result.selected += 1
            processed += 1
            try:
                attachments = fetch_attachment_records_for_ticket(
                    config=config,
                    ticket_id=record.ticket_id,
                    connect=connect,
                )
                index_result = index_closed_ticket(
                    record=record,
                    config=config,
                    attachments=attachments,
                    connect=connect,
                    embedding_model=embedding_model,
                    sleep=sleep,
                )
            except ClosedTicketChunkWriteError as exc:
                result.failed += 1
                result.errors.append(f"{record.ticket_id}: {exc}")
                continue
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"{record.ticket_id}: {exc}")
                continue
            if index_result.skipped:
                result.skipped += 1
            elif index_result.status == "ready":
                result.ready += 1
            else:
                result.skipped += 1
            if processed >= cap:
                break
        after_ticket_id = records[-1].ticket_id
        if len(records) < limit:
            break
    return result


def rebuild_closed_ticket_chunks(
    *,
    config: Config,
    ticket_id: str | None = None,
    batch_size: int = 100,
    connect: ConnectionFactory | None = None,
    embedding_model: Any = None,
    sleep: SleepFn = time.sleep,
) -> dict[str, int]:
    """Rebuild closed-ticket chunks for one ticket or all tickets in pages."""
    total_tickets = 0
    total_chunks = 0
    skipped = 0
    page_size = max(1, int(batch_size))
    if ticket_id:
        records = fetch_ticket_records(
            config=config,
            ticket_id=ticket_id,
            limit=1,
            connect=connect,
        )
        for record in records:
            attachments = fetch_attachment_records_for_ticket(
                config=config,
                ticket_id=record.ticket_id,
                connect=connect,
            )
            result = index_closed_ticket(
                record=record,
                config=config,
                attachments=attachments,
                connect=connect,
                embedding_model=embedding_model,
                sleep=sleep,
            )
            total_tickets += 1
            total_chunks += result.chunk_count
            if result.skipped:
                skipped += 1
        return {"tickets": total_tickets, "chunks": total_chunks, "skipped": skipped}

    after_ticket_id: str | None = None
    while True:
        records = fetch_ticket_records(
            config=config,
            ticket_id=None,
            after_ticket_id=after_ticket_id,
            limit=page_size,
            active_unexpired_only=True,
            connect=connect,
        )
        if not records:
            break
        for record in records:
            attachments = fetch_attachment_records_for_ticket(
                config=config,
                ticket_id=record.ticket_id,
                connect=connect,
            )
            result = index_closed_ticket(
                record=record,
                config=config,
                attachments=attachments,
                connect=connect,
                embedding_model=embedding_model,
                sleep=sleep,
            )
            total_tickets += 1
            total_chunks += result.chunk_count
            if result.skipped:
                skipped += 1
        after_ticket_id = records[-1].ticket_id
        if len(records) < page_size:
            break
    return {"tickets": total_tickets, "chunks": total_chunks, "skipped": skipped}


def dry_run_closed_ticket_chunk_rebuild(
    *,
    config: Config,
    ticket_id: str | None = None,
    batch_size: int = 100,
    connect: ConnectionFactory | None = None,
) -> dict[str, int]:
    """Count chunks that would be built without writing to Postgres."""
    total_tickets = 0
    total_chunks = 0
    skipped = 0
    records = fetch_ticket_records(
        config=config,
        ticket_id=ticket_id,
        limit=max(1, int(batch_size)),
        connect=connect,
    )
    for record in records:
        if not _ticket_is_indexable(record):
            skipped += 1
            continue
        attachments = fetch_attachment_records_for_ticket(
            config=config,
            ticket_id=record.ticket_id,
            connect=connect,
        )
        chunks = build_closed_ticket_chunks(record, config, attachments=attachments)
        total_tickets += 1
        total_chunks += len(chunks)
    return {"tickets": total_tickets, "chunks": total_chunks, "skipped": skipped}
