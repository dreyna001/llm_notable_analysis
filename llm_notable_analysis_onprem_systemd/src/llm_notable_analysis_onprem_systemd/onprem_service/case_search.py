"""Case archive chunk building and Postgres persistence for portal retrieval."""

# Optional database and embedding dependencies are imported lazily so default
# non-portal deployments can import the analyzer without loading retrieval code.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import json
import hashlib
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Sequence

from .case_store import CaseArchiveRecord, quote_identifier
from .config import Config

ConnectionFactory = Callable[[str], Any]
SleepFn = Callable[[float], None]

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_CHUNK_TEXT_CHARS = 2500
_MAX_ALERT_FIELDS = 40
_MAX_JSON_DEPTH = 40
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

_ALERT_SUMMARY_KEYS = (
    "summary",
    "description",
    "title",
    "search_name",
    "searchName",
    "rule_name",
    "rule",
    "signature",
    "notable_id",
    "event_id",
    "correlation_id",
    "text",
)
_ALERT_HIGH_VALUE_KEYS = {
    "action",
    "command",
    "command_line",
    "commandLine",
    "correlation_id",
    "dest",
    "dest_ip",
    "destination",
    "destination_ip",
    "description",
    "domain",
    "event_id",
    "file_hash",
    "file_name",
    "file_path",
    "finding_id",
    "host",
    "hostname",
    "ip",
    "notable_id",
    "parent_process",
    "process",
    "process_name",
    "process_path",
    "riskScore",
    "risk_score",
    "rule",
    "rule_name",
    "searchName",
    "search_name",
    "signature",
    "src",
    "src_ip",
    "source",
    "source_ip",
    "summary",
    "text",
    "title",
    "url",
    "user",
    "username",
}
_ANALYSIS_SECTIONS: tuple[tuple[str, str], ...] = (
    ("analysis.alert_reconciliation", "alert_reconciliation"),
    ("analysis.competing_hypotheses", "competing_hypotheses"),
    ("analysis.evidence_vs_inference", "evidence_vs_inference"),
    ("analysis.ioc_extraction", "ioc_extraction"),
    ("analysis.ttp_analysis", "ttp_analysis"),
    ("analysis.query_result_section", "query_result_section"),
    ("analysis.servicenow_section", "servicenow_section"),
)


@dataclass(frozen=True)
class CaseChunkRecord:
    """A deterministic retrieval chunk derived from a stored case record."""

    chunk_id: str
    case_id: str
    source_lane: str
    section: str
    field_path: str
    text: str
    metadata: dict[str, Any]
    chunk_schema_version: int
    embedding_model: str


class CaseChunkWriteError(RuntimeError):
    """Case chunk persistence failed."""


def _default_connect(dsn: str) -> Any:
    """Open a psycopg connection for case chunk writes."""
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is unavailable in the runtime.") from exc
    return psycopg.connect(dsn, connect_timeout=5)


def _lazy_import_sentence_transformer() -> Any:
    """Import SentenceTransformer lazily for optional case chunk embedding."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "sentence-transformers is unavailable in the runtime."
        ) from exc
    return SentenceTransformer


def _get_embedding_model(model_name: str) -> Any:
    """Return a lazily initialized, process-local embedding model."""
    normalized = (model_name or "").strip()
    if not normalized:
        raise ValueError("CASE_QA_EMBEDDING_MODEL is required for case chunks")
    with _EMBEDDING_MODEL_LOCK:
        model = _EMBEDDING_MODEL_CACHE.get(normalized)
        if model is None:
            SentenceTransformer = _lazy_import_sentence_transformer()
            model = SentenceTransformer(normalized)
            _EMBEDDING_MODEL_CACHE[normalized] = model
        return model


def _json(value: Any) -> str:
    """Serialize a JSONB value deterministically."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_text(value: Any) -> str:
    """Serialize a value into stable readable chunk text."""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2)


def _string_or_none(value: Any) -> str | None:
    """Return a stripped scalar string or None."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _safe_component(value: str) -> str:
    """Sanitize one chunk-id component with the notable-id character set."""
    raw = str(value)
    sanitized = _SAFE_COMPONENT_RE.sub("_", raw).strip("_")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    if not sanitized:
        return f"unknown_{digest}"
    if sanitized != raw or len(sanitized) > 100:
        return f"{sanitized[:87]}_{digest}"
    return sanitized


def build_chunk_id(
    *, case_id: str, source_lane: str, section: str, ordinal: int
) -> str:
    """Build a stable chunk id for one section ordinal."""
    return ":".join(
        (
            _safe_component(case_id),
            _safe_component(source_lane),
            _safe_component(section),
            str(int(ordinal)),
        )
    )


def _field_path_join(base_path: str, key: str) -> str:
    """Append a JSON object key to a simple JSON path."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{base_path}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{base_path}['{escaped}']"


def _iter_leaf_values(
    value: Any, path: str = "$", *, depth: int = 0
) -> Iterable[tuple[str, Any]]:
    """Yield deterministic leaf values from nested JSON-like data."""
    if depth >= _MAX_JSON_DEPTH:
        yield path, "[max JSON depth reached]"
        return
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _iter_leaf_values(
                value[key],
                _field_path_join(path, str(key)),
                depth=depth + 1,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_leaf_values(item, f"{path}[{index}]", depth=depth + 1)
    else:
        yield path, value


def _iter_alert_key_fields(alert_payload: Any) -> Iterable[tuple[str, str]]:
    """Yield selected high-value alert fields for retrieval chunks."""
    if not isinstance(alert_payload, dict):
        return
    yielded = 0
    for path, value in _iter_leaf_values(alert_payload):
        key = path.rsplit(".", 1)[-1].split("[", 1)[0].strip("'")
        if key not in _ALERT_HIGH_VALUE_KEYS:
            continue
        text = _string_or_none(value)
        if text is None:
            continue
        yield path, f"{path}: {text}"
        yielded += 1
        if yielded >= _MAX_ALERT_FIELDS:
            return


def _build_alert_summary_text(alert_payload: Any) -> str | None:
    """Build a compact alert summary from high-value top-level fields."""
    if isinstance(alert_payload, str):
        return alert_payload.strip()[:_MAX_CHUNK_TEXT_CHARS] or None
    if not isinstance(alert_payload, dict):
        return None
    lines = []
    for key in _ALERT_SUMMARY_KEYS:
        value = _string_or_none(alert_payload.get(key))
        if value is not None:
            lines.append(f"{key}: {value}")
    if not lines:
        return None
    return "\n".join(lines)


def _split_text(text: str) -> list[str]:
    """Split large scalar text into deterministic embedding-sized chunks."""
    normalized = text.strip()
    if not normalized:
        return []
    return [
        normalized[start : start + _MAX_CHUNK_TEXT_CHARS]
        for start in range(0, len(normalized), _MAX_CHUNK_TEXT_CHARS)
    ]


def _iter_section_parts(
    value: Any, root_path: str, *, depth: int = 0
) -> Iterable[tuple[str, str]]:
    """Yield deterministic chunk-sized parts for one stored JSON section."""
    if depth >= _MAX_JSON_DEPTH:
        yield root_path, "[max JSON depth reached]"
        return
    text = _json_text(value)
    if not isinstance(value, (dict, list)):
        for part in _split_text(text):
            yield root_path, part
        return
    if len(text) <= _MAX_CHUNK_TEXT_CHARS:
        yield root_path, text
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_section_parts(
                item,
                f"{root_path}[{index}]",
                depth=depth + 1,
            )
        return

    for key in sorted(value):
        yield from _iter_section_parts(
            value[key],
            _field_path_join(root_path, str(key)),
            depth=depth + 1,
        )


def _make_chunk(
    *,
    case_id: str,
    source_lane: str,
    section: str,
    field_path: str,
    text: str,
    ordinal: int,
    record: CaseArchiveRecord,
    config: Config,
) -> CaseChunkRecord:
    """Create one chunk with citation metadata."""
    chunk_id = build_chunk_id(
        case_id=case_id,
        source_lane=source_lane,
        section=section,
        ordinal=ordinal,
    )
    metadata = {
        "case_id": case_id,
        "chunk_id": chunk_id,
        "stored_source_lane": source_lane,
        "section": section,
        "field_path": field_path,
        "source_filename": record.source_filename,
        "finding_id": record.finding_id,
        "report_md_path": record.report_md_path,
        "report_html_path": record.report_html_path,
    }
    return CaseChunkRecord(
        chunk_id=chunk_id,
        case_id=case_id,
        source_lane=source_lane,
        section=section,
        field_path=field_path,
        text=f"{section}\n{field_path}\n{text}".strip(),
        metadata=metadata,
        chunk_schema_version=config.CASE_QA_CHUNK_SCHEMA_VERSION,
        embedding_model=config.CASE_QA_EMBEDDING_MODEL,
    )


def _index_chunk_budget(config: Config) -> int:
    """Return the per-case chunk build budget for indexing."""
    return max(1, int(config.CASE_QA_MAX_INDEX_CHUNKS_PER_CASE))


def build_case_chunks(record: CaseArchiveRecord, config: Config) -> list[CaseChunkRecord]:
    """Build deterministic case chunks from JSON fields, never rendered reports."""
    chunks: list[CaseChunkRecord] = []
    chunk_budget = _index_chunk_budget(config)

    alert_summary = _build_alert_summary_text(record.alert_payload)
    if alert_summary:
        for ordinal, text in enumerate(_split_text(alert_summary)):
            chunks.append(
                _make_chunk(
                    case_id=record.case_id,
                    source_lane="alert_payload",
                    section="alert.summary",
                    field_path="$",
                    text=text,
                    ordinal=ordinal,
                    record=record,
                    config=config,
                )
            )
            if len(chunks) >= chunk_budget:
                return chunks

    ordinal = 0
    for field_path, text in _iter_alert_key_fields(record.alert_payload):
        for part in _split_text(text):
            chunks.append(
                _make_chunk(
                    case_id=record.case_id,
                    source_lane="alert_payload",
                    section="alert.key_fields",
                    field_path=field_path,
                    text=part,
                    ordinal=ordinal,
                    record=record,
                    config=config,
                )
            )
            ordinal += 1
            if len(chunks) >= chunk_budget:
                return chunks

    if record.analysis is None:
        return chunks

    for section, key in _ANALYSIS_SECTIONS:
        if key not in record.analysis:
            continue
        value = record.analysis[key]
        root_path = f"$.{key}"
        for ordinal, (field_path, text) in enumerate(_iter_section_parts(value, root_path)):
            chunks.append(
                _make_chunk(
                    case_id=record.case_id,
                    source_lane="case_analysis",
                    section=section,
                    field_path=field_path,
                    text=text,
                    ordinal=ordinal,
                    record=record,
                    config=config,
                )
            )
            if len(chunks) >= chunk_budget:
                return chunks
    return chunks


def build_delete_case_chunks_sql(schema: str) -> str:
    """Build SQL that deletes chunks for one case."""
    return f"DELETE FROM {quote_identifier(schema, 'schema')}.case_chunks WHERE case_id = %s"


def build_insert_case_chunks_sql(schema: str) -> str:
    """Build parameterized upsert SQL for case chunk rows."""
    table = f"{quote_identifier(schema, 'schema')}.case_chunks"
    return f"""
INSERT INTO {table} (
    chunk_id,
    case_id,
    source_lane,
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
    case_id = EXCLUDED.case_id,
    source_lane = EXCLUDED.source_lane,
    section = EXCLUDED.section,
    field_path = EXCLUDED.field_path,
    text = EXCLUDED.text,
    embedding = EXCLUDED.embedding,
    metadata = EXCLUDED.metadata,
    chunk_schema_version = EXCLUDED.chunk_schema_version,
    embedding_model = EXCLUDED.embedding_model
""".strip()


def build_update_case_retrieval_status_sql(schema: str) -> str:
    """Build SQL that updates retrieval status for one case."""
    return (
        f"UPDATE {quote_identifier(schema, 'schema')}.cases "
        "SET retrieval_status = %s WHERE case_id = %s"
    )


def build_select_case_records_sql(
    schema: str,
    *,
    case_id: str | None = None,
    after_processed_at: datetime | None = None,
) -> str:
    """Build SQL that selects case rows needed for chunk rebuild."""
    if case_id is not None:
        where_clause = "WHERE case_id = %s"
    elif after_processed_at is not None:
        where_clause = (
            "WHERE (processed_at < %s OR (processed_at = %s AND case_id > %s))"
        )
    else:
        where_clause = ""
    return f"""
SELECT
    case_id,
    finding_id,
    source_filename,
    processed_at,
    expires_at,
    correlation_id,
    capability_snapshot,
    archive_metadata,
    alert_payload,
    analysis,
    case_schema_version,
    analysis_schema_version,
    verdict,
    confidence,
    search_name,
    risk_score,
    report_md_path,
    report_html_path,
    retrieval_status,
    backfill_status,
    source_completeness
FROM {quote_identifier(schema, 'schema')}.cases
{where_clause}
ORDER BY processed_at DESC, case_id ASC
LIMIT %s
""".strip()


def _vectors_to_lists(values: Any) -> list[list[float]]:
    """Normalize common embedding outputs into list-of-float vectors."""
    data = values.tolist() if hasattr(values, "tolist") else values
    return [[float(v) for v in row] for row in data]


def _l2_normalize_vector(values: Sequence[float]) -> list[float]:
    """Apply L2 normalization to one vector."""
    norm = math.sqrt(sum(float(v) * float(v) for v in values)) + 1e-12
    return [float(v) / norm for v in values]


def _vector_literal(values: Sequence[float]) -> str:
    """Format a pgvector literal from normalized embedding values."""
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def _execute_many(conn: Any, sql: str, rows: Sequence[tuple[Any, ...]]) -> None:
    """Execute many rows through either a test fake or a psycopg cursor."""
    executemany = getattr(conn, "executemany", None)
    if callable(executemany):
        executemany(sql, rows)
        return
    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)


def _set_statement_timeout(conn: Any, timeout_ms: int) -> None:
    """Set a transaction-local Postgres statement timeout."""
    if int(timeout_ms) > 0:
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{int(timeout_ms)}ms",),
        )


def _chunk_rows(
    *,
    chunks: Sequence[CaseChunkRecord],
    vectors: Sequence[Sequence[float]],
    vector_dimensions: int,
) -> list[tuple[Any, ...]]:
    """Build insert rows from chunks plus normalized vectors."""
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
                chunk.case_id,
                chunk.source_lane,
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


def _is_retryable(exc: BaseException) -> bool:
    """Return whether a database exception should be retried."""
    return isinstance(exc, (ConnectionError, TimeoutError, OSError)) or (
        exc.__class__.__name__ in _RETRYABLE_EXCEPTION_NAMES
    )


def _encode_chunk_vectors(
    *,
    chunks: Sequence[CaseChunkRecord],
    config: Config,
    embedding_model: Any = None,
) -> list[list[float]]:
    """Embed chunk text outside the database transaction."""
    if not chunks:
        return []
    model = embedding_model or _get_embedding_model(config.CASE_QA_EMBEDDING_MODEL)
    encode_args = {
        "show_progress_bar": False,
        "convert_to_numpy": True,
    }
    if embedding_model is None:
        with _EMBEDDING_ENCODE_LOCK:
            encoded = model.encode([chunk.text for chunk in chunks], **encode_args)
    else:
        encoded = model.encode([chunk.text for chunk in chunks], **encode_args)
    return _vectors_to_lists(encoded)


def mark_case_retrieval_status_once(
    *,
    config: Config,
    case_id: str,
    status: str,
    connect: ConnectionFactory | None = None,
) -> None:
    """Mark one case retrieval status without retry handling."""
    connect_fn = connect or _default_connect
    sql = build_update_case_retrieval_status_sql(config.CASE_POSTGRES_SCHEMA)
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        conn.execute(sql, (status, case_id))


def mark_case_retrieval_status(
    *,
    config: Config,
    case_id: str,
    status: str,
    connect: ConnectionFactory | None = None,
    sleep: SleepFn = time.sleep,
) -> None:
    """Mark one case retrieval status with bounded retries."""
    if status not in {"pending", "ready", "failed", "not_indexed"}:
        raise ValueError("status must be pending, ready, failed, or not_indexed")
    attempts = max(1, int(config.CASE_ARCHIVE_WRITE_MAX_ATTEMPTS))
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            mark_case_retrieval_status_once(
                config=config,
                case_id=case_id,
                status=status,
                connect=connect,
            )
            return
        except Exception as exc:
            if not _is_retryable(exc):
                raise CaseChunkWriteError("case retrieval status update failed") from exc
            last_exc = exc
            if attempt >= attempts:
                break
            sleep(float(config.CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS))
    raise CaseChunkWriteError("case retrieval status update failed after retries") from last_exc


def store_case_chunks_once(
    *,
    record: CaseArchiveRecord,
    config: Config,
    rows: Sequence[tuple[Any, ...]],
    connect: ConnectionFactory | None = None,
) -> int:
    """Replace stored chunks for one case without retry handling."""
    connect_fn = connect or _default_connect
    delete_sql = build_delete_case_chunks_sql(config.CASE_POSTGRES_SCHEMA)
    insert_sql = build_insert_case_chunks_sql(config.CASE_POSTGRES_SCHEMA)
    status_sql = build_update_case_retrieval_status_sql(config.CASE_POSTGRES_SCHEMA)

    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        conn.execute(delete_sql, (record.case_id,))
        if not rows:
            conn.execute(status_sql, ("not_indexed", record.case_id))
            return 0
        _execute_many(conn, insert_sql, rows)
        conn.execute(status_sql, ("ready", record.case_id))
    return len(rows)


def store_case_chunks(
    *,
    record: CaseArchiveRecord,
    config: Config,
    connect: ConnectionFactory | None = None,
    embedding_model: Any = None,
    sleep: SleepFn = time.sleep,
) -> int:
    """Replace stored chunks for one case and mark retrieval readiness."""
    chunks = build_case_chunks(record, config)
    vectors = _encode_chunk_vectors(
        chunks=chunks,
        config=config,
        embedding_model=embedding_model,
    )
    rows = _chunk_rows(
        chunks=chunks,
        vectors=vectors,
        vector_dimensions=config.CASE_QA_VECTOR_DIMENSIONS,
    )
    attempts = max(1, int(config.CASE_ARCHIVE_WRITE_MAX_ATTEMPTS))
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return store_case_chunks_once(
                record=record,
                config=config,
                rows=rows,
                connect=connect,
            )
        except Exception as exc:
            if not _is_retryable(exc):
                raise CaseChunkWriteError("case chunk write failed") from exc
            last_exc = exc
            if attempt >= attempts:
                break
            sleep(float(config.CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS))
    raise CaseChunkWriteError("case chunk write failed after retries") from last_exc


def _json_from_db(value: Any) -> Any:
    """Normalize JSONB values returned by psycopg or test fakes."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_get(row: Any, index: int, key: str) -> Any:
    """Read a row value from a tuple or mapping."""
    if isinstance(row, dict):
        return row[key]
    return row[index]


def _record_from_row(row: Any) -> CaseArchiveRecord:
    """Build a CaseArchiveRecord from a selected database row."""
    return CaseArchiveRecord(
        case_id=_row_get(row, 0, "case_id"),
        finding_id=_row_get(row, 1, "finding_id") or "",
        source_filename=_row_get(row, 2, "source_filename"),
        processed_at=_row_get(row, 3, "processed_at"),
        expires_at=_row_get(row, 4, "expires_at"),
        correlation_id=_row_get(row, 5, "correlation_id"),
        capability_snapshot=_json_from_db(_row_get(row, 6, "capability_snapshot")) or {},
        archive_metadata=_json_from_db(_row_get(row, 7, "archive_metadata")) or {},
        alert_payload=_json_from_db(_row_get(row, 8, "alert_payload")),
        analysis=_json_from_db(_row_get(row, 9, "analysis")),
        case_schema_version=int(_row_get(row, 10, "case_schema_version")),
        analysis_schema_version=int(_row_get(row, 11, "analysis_schema_version")),
        verdict=_row_get(row, 12, "verdict"),
        confidence=_row_get(row, 13, "confidence"),
        search_name=_row_get(row, 14, "search_name"),
        risk_score=_row_get(row, 15, "risk_score"),
        report_md_path=_row_get(row, 16, "report_md_path"),
        report_html_path=_row_get(row, 17, "report_html_path"),
        retrieval_status=_row_get(row, 18, "retrieval_status"),
        backfill_status=_row_get(row, 19, "backfill_status"),
        source_completeness=_row_get(row, 20, "source_completeness"),
    )


def _fetchall(result: Any) -> list[Any]:
    """Read rows from a cursor-like result."""
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        return list(fetchall())
    return []


def fetch_case_records(
    *,
    config: Config,
    case_id: str | None = None,
    after_processed_at: datetime | None = None,
    after_case_id: str | None = None,
    limit: int = 100,
    connect: ConnectionFactory | None = None,
) -> list[CaseArchiveRecord]:
    """Fetch stored case rows needed for a manual chunk rebuild."""
    connect_fn = connect or _default_connect
    page_size = max(1, int(limit))
    sql = build_select_case_records_sql(
        config.CASE_POSTGRES_SCHEMA,
        case_id=case_id,
        after_processed_at=after_processed_at,
    )
    if case_id is not None:
        params = (case_id, page_size)
    elif after_processed_at is not None:
        params = (after_processed_at, after_processed_at, after_case_id or "", page_size)
    else:
        params = (page_size,)
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        result = conn.execute(sql, params)
        return [_record_from_row(row) for row in _fetchall(result)]


def _record_is_rebuildable(record: CaseArchiveRecord) -> bool:
    """Return whether a stored case should be indexed for archive chat."""
    if record.retrieval_status == "not_indexed":
        return False
    if record.backfill_status == "legacy_summary":
        return False
    return record.source_completeness == "complete"


def rebuild_case_chunks(
    *,
    config: Config,
    case_id: str | None = None,
    batch_size: int = 100,
    connect: ConnectionFactory | None = None,
    embedding_model: Any = None,
) -> dict[str, int]:
    """Rebuild chunks for one case or all retained cases."""
    rebuilt = 0
    chunks = 0
    skipped = 0
    cursor_processed_at: datetime | None = None
    cursor_case_id: str | None = None
    page_size = 1 if case_id is not None else max(1, int(batch_size))
    while True:
        records = fetch_case_records(
            config=config,
            case_id=case_id,
            after_processed_at=cursor_processed_at,
            after_case_id=cursor_case_id,
            limit=page_size,
            connect=connect,
        )
        if not records:
            break
        for record in records:
            if not _record_is_rebuildable(record):
                skipped += 1
                continue
            chunks += store_case_chunks(
                record=record,
                config=config,
                connect=connect,
                embedding_model=embedding_model,
            )
            rebuilt += 1
        if case_id is not None or len(records) < page_size:
            break
        cursor_processed_at = records[-1].processed_at
        cursor_case_id = records[-1].case_id
    return {"cases": rebuilt, "chunks": chunks, "skipped": skipped}


def dry_run_case_chunk_rebuild(
    *,
    config: Config,
    case_id: str | None = None,
    batch_size: int = 100,
    connect: ConnectionFactory | None = None,
) -> dict[str, int]:
    """Count rebuildable cases and deterministic chunks without writing."""
    rebuilt = 0
    chunks = 0
    skipped = 0
    cursor_processed_at: datetime | None = None
    cursor_case_id: str | None = None
    page_size = 1 if case_id is not None else max(1, int(batch_size))
    while True:
        records = fetch_case_records(
            config=config,
            case_id=case_id,
            after_processed_at=cursor_processed_at,
            after_case_id=cursor_case_id,
            limit=page_size,
            connect=connect,
        )
        if not records:
            break
        for record in records:
            if not _record_is_rebuildable(record):
                skipped += 1
                continue
            rebuilt += 1
            chunks += len(build_case_chunks(record, config))
        if case_id is not None or len(records) < page_size:
            break
        cursor_processed_at = records[-1].processed_at
        cursor_case_id = records[-1].case_id
    return {"cases": rebuilt, "chunks": chunks, "skipped": skipped}
