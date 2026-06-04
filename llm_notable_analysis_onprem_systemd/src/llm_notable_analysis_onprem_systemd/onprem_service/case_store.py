"""Postgres case archive writes for the analyst portal."""

# Optional database dependency is imported lazily so default non-archive
# deployments can import the analyzer without opening the Postgres path.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import json
import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Config

ConnectionFactory = Callable[[str], Any]
SleepFn = Callable[[float], None]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_RETRYABLE_EXCEPTION_NAMES = {
    "ConnectionTimeout",
    "InterfaceError",
    "OperationalError",
    "QueryCanceled",
    "Timeout",
}
_SEARCH_NAME_KEYS = ("search_name", "searchName", "rule_name", "rule", "signature", "title")
_CORRELATION_ID_KEYS = ("correlation_id", "notable_id", "event_id", "sid", "id")
_RISK_SCORE_KEYS = ("risk_score", "riskScore")
_CASE_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_CASE_ID_CHARS = 100


class CaseArchiveWriteError(RuntimeError):
    """Case archive write failed."""


class CaseArchiveConflictError(CaseArchiveWriteError):
    """A case_id collision targeted an unrelated source identity."""


@dataclass(frozen=True)
class CaseArchiveRecord:
    """Canonical case archive row ready for Postgres persistence."""

    case_id: str
    finding_id: str
    source_filename: str
    processed_at: datetime
    expires_at: datetime
    correlation_id: str | None
    capability_snapshot: dict[str, Any]
    archive_metadata: dict[str, Any]
    alert_payload: Any
    analysis: dict[str, Any] | None
    case_schema_version: int
    analysis_schema_version: int
    verdict: str | None
    confidence: float | None
    search_name: str | None
    risk_score: float | None
    report_md_path: str | None
    report_html_path: str | None
    retrieval_status: str
    backfill_status: str
    source_completeness: str


def _default_connect(dsn: str) -> Any:
    """Open a psycopg connection for case archive writes."""
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is unavailable in the runtime.") from exc
    return psycopg.connect(dsn, connect_timeout=5)


def quote_identifier(value: str, field_name: str) -> str:
    """Validate and quote a PostgreSQL identifier."""
    normalized = (value or "").strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a simple PostgreSQL identifier.")
    return f'"{normalized}"'


def _json(value: Any) -> str:
    """Serialize a value for a `%s::jsonb` parameter."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_or_none(value: Any) -> str | None:
    """Serialize a nullable JSONB value, preserving SQL NULL."""
    if value is None:
        return None
    return _json(value)


def _string_or_none(value: Any) -> str | None:
    """Return a stripped string or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _numeric_or_none(value: Any) -> float | None:
    """Coerce numeric model/alert fields into nullable floats."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.casefold() in {"n/a", "na", "none", "null", "unknown"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _first_alert_value(alert_payload: Any, keys: tuple[str, ...]) -> str | None:
    """Extract the first non-empty scalar value from a dict alert payload."""
    if not isinstance(alert_payload, dict):
        return None
    for key in keys:
        value = _string_or_none(alert_payload.get(key))
        if value is not None:
            return value
    return None


def _first_alert_numeric(alert_payload: Any, keys: tuple[str, ...]) -> float | None:
    """Extract the first numeric alert value from a dict alert payload."""
    if not isinstance(alert_payload, dict):
        return None
    for key in keys:
        value = _numeric_or_none(alert_payload.get(key))
        if value is not None:
            return value
    return None


def _archive_alert_payload(alert_payload: Any) -> Any:
    """Preserve JSON payloads and wrap plain text inputs."""
    if isinstance(alert_payload, str):
        return {"input_type": "text", "text": alert_payload}
    return alert_payload


def _sanitize_case_id(raw_value: Any, *, fallback: str = "unknown") -> str:
    """Normalize a source identifier into a bounded portal-safe case id."""
    raw_text = str(raw_value or "").strip()
    sanitized = _CASE_ID_SAFE_RE.sub("_", raw_text).strip("_")
    if not sanitized:
        return fallback
    if sanitized != raw_text or len(sanitized) > _MAX_CASE_ID_CHARS:
        digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:12]
        prefix = sanitized[: (_MAX_CASE_ID_CHARS - 13)].strip("_") or "case"
        return f"{prefix}_{digest}"
    return sanitized


def build_native_case_id(alert_payload: Any, source_filename: str | Path) -> str:
    """Build the stable native archive id for an analyzed source alert.

    The report path keeps using the input filename stem, but archive replay must
    prefer upstream alert identity when available so transport filename changes
    do not duplicate retained cases.
    """
    source_identity = _first_alert_value(alert_payload, _CORRELATION_ID_KEYS)
    if source_identity is not None:
        return _sanitize_case_id(source_identity)
    return _sanitize_case_id(Path(source_filename).stem)


def _capability_snapshot(config: Config) -> dict[str, Any]:
    """Capture non-secret capability and runtime values for later audit."""
    return {
        "capability_profiles": config.CAPABILITY_PROFILES,
        "html_report_enabled": config.HTML_REPORT_ENABLED,
        "rag_enabled": config.RAG_ENABLED,
        "rag_backend": config.RAG_BACKEND,
        "spl_query_generation_enabled": config.SPL_QUERY_GENERATION_ENABLED,
        "elastic_query_generation_enabled": config.ELASTIC_QUERY_GENERATION_ENABLED,
        "investigation_query_execution_enabled": config.INVESTIGATION_QUERY_EXECUTION_ENABLED,
        "investigation_query_backend": config.INVESTIGATION_QUERY_BACKEND,
        "query_result_interpretation_enabled": config.QUERY_RESULT_INTERPRETATION_ENABLED,
        "servicenow_draft_enabled": config.SERVICENOW_DRAFT_ENABLED,
        "servicenow_create_enabled": config.SERVICENOW_CREATE_ENABLED,
        "llm_model_name": config.LLM_MODEL_NAME,
        "llm_structured_output_mode": config.LLM_STRUCTURED_OUTPUT_MODE,
        "rag_embedding_model": config.RAG_EMBEDDING_MODEL,
        "rag_vector_dimensions": config.RAG_VECTOR_DIMENSIONS,
        "case_qa_embedding_model": config.CASE_QA_EMBEDDING_MODEL,
        "case_qa_vector_dimensions": config.CASE_QA_VECTOR_DIMENSIONS,
    }


def build_case_archive_record(
    *,
    config: Config,
    case_id: str,
    finding_id: str,
    source_filename: str,
    alert_payload: Any,
    analysis: dict[str, Any],
    report_md_path: Path | str | None,
    report_html_path: Path | str | None,
    processed_at: datetime | None = None,
) -> CaseArchiveRecord:
    """Build a native case archive row from the final analyzer output."""
    processed = processed_at or datetime.now(timezone.utc)
    if processed.tzinfo is None:
        processed = processed.replace(tzinfo=timezone.utc)

    is_poc_fallback = bool(analysis.get("poc_unstructured_output"))
    alert_reconciliation = analysis.get("alert_reconciliation", {})
    if not isinstance(alert_reconciliation, dict):
        alert_reconciliation = {}

    archive_metadata: dict[str, Any] = {}
    stored_analysis: dict[str, Any] | None = dict(analysis)
    retrieval_status = "pending"
    source_completeness = "complete"
    if is_poc_fallback:
        archive_metadata["poc_unstructured_output"] = True
        fallback_reason = _string_or_none(analysis.get("poc_fallback_reason"))
        if fallback_reason is not None:
            archive_metadata["poc_fallback_reason"] = fallback_reason
        stored_analysis = None
        retrieval_status = "not_indexed"
        source_completeness = "missing_analysis"

    return CaseArchiveRecord(
        case_id=case_id,
        finding_id=finding_id,
        source_filename=source_filename,
        processed_at=processed,
        expires_at=processed + timedelta(days=config.CASE_RETENTION_DAYS),
        correlation_id=_first_alert_value(alert_payload, _CORRELATION_ID_KEYS),
        capability_snapshot=_capability_snapshot(config),
        archive_metadata=archive_metadata,
        alert_payload=_archive_alert_payload(alert_payload),
        analysis=stored_analysis,
        case_schema_version=config.CASE_SCHEMA_VERSION,
        analysis_schema_version=config.CASE_ANALYSIS_SCHEMA_VERSION,
        verdict=_string_or_none(alert_reconciliation.get("verdict")),
        confidence=_numeric_or_none(alert_reconciliation.get("confidence")),
        search_name=_first_alert_value(alert_payload, _SEARCH_NAME_KEYS),
        risk_score=_first_alert_numeric(alert_payload, _RISK_SCORE_KEYS),
        report_md_path=str(report_md_path) if report_md_path else None,
        report_html_path=str(report_html_path) if report_html_path else None,
        retrieval_status=retrieval_status,
        backfill_status="native",
        source_completeness=source_completeness,
    )


def build_upsert_case_sql(schema: str) -> str:
    """Build the idempotent native case upsert SQL."""
    cases = f"{quote_identifier(schema, 'schema')}.cases"
    return f"""
INSERT INTO {cases} (
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
)
VALUES (
    %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (case_id) DO UPDATE SET
    finding_id = EXCLUDED.finding_id,
    source_filename = EXCLUDED.source_filename,
    processed_at = EXCLUDED.processed_at,
    expires_at = EXCLUDED.expires_at,
    correlation_id = EXCLUDED.correlation_id,
    capability_snapshot = EXCLUDED.capability_snapshot,
    archive_metadata = EXCLUDED.archive_metadata,
    alert_payload = EXCLUDED.alert_payload,
    analysis = EXCLUDED.analysis,
    case_schema_version = EXCLUDED.case_schema_version,
    analysis_schema_version = EXCLUDED.analysis_schema_version,
    verdict = EXCLUDED.verdict,
    confidence = EXCLUDED.confidence,
    search_name = EXCLUDED.search_name,
    risk_score = EXCLUDED.risk_score,
    report_md_path = EXCLUDED.report_md_path,
    report_html_path = EXCLUDED.report_html_path,
    retrieval_status = EXCLUDED.retrieval_status,
    backfill_status = EXCLUDED.backfill_status,
    source_completeness = EXCLUDED.source_completeness
WHERE
    {cases}.source_filename = EXCLUDED.source_filename
    OR (
        {cases}.correlation_id IS NOT NULL
        AND {cases}.correlation_id <> ''
        AND {cases}.correlation_id = EXCLUDED.correlation_id
    )
    OR (
        {cases}.finding_id IS NOT NULL
        AND {cases}.finding_id <> ''
        AND {cases}.finding_id = EXCLUDED.finding_id
    )
RETURNING case_id
""".strip()


def build_delete_case_chunks_sql(schema: str) -> str:
    """Build SQL that clears derived chunks for a replayed case."""
    return f"DELETE FROM {quote_identifier(schema, 'schema')}.case_chunks WHERE case_id = %s"


def _record_params(record: CaseArchiveRecord) -> tuple[Any, ...]:
    """Return psycopg parameters for a case upsert."""
    return (
        record.case_id,
        record.finding_id,
        record.source_filename,
        record.processed_at,
        record.expires_at,
        record.correlation_id,
        _json(record.capability_snapshot),
        _json(record.archive_metadata),
        _json(record.alert_payload),
        _json_or_none(record.analysis),
        record.case_schema_version,
        record.analysis_schema_version,
        record.verdict,
        record.confidence,
        record.search_name,
        record.risk_score,
        record.report_md_path,
        record.report_html_path,
        record.retrieval_status,
        record.backfill_status,
        record.source_completeness,
    )


def _set_statement_timeout(conn: Any, timeout_ms: int) -> None:
    """Set a transaction-local Postgres statement timeout."""
    if int(timeout_ms) > 0:
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{int(timeout_ms)}ms",),
        )


def _fetchone(result: Any) -> Any:
    """Read one row from a psycopg cursor-like result."""
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    return None


def _is_retryable(exc: BaseException) -> bool:
    """Return whether a database exception should be retried."""
    return isinstance(exc, (ConnectionError, TimeoutError, OSError)) or (
        exc.__class__.__name__ in _RETRYABLE_EXCEPTION_NAMES
    )


def write_case_record_once(
    *,
    record: CaseArchiveRecord,
    config: Config,
    connect: ConnectionFactory | None = None,
) -> None:
    """Write one case archive record without retry handling."""
    connect_fn = connect or _default_connect
    upsert_sql = build_upsert_case_sql(config.CASE_POSTGRES_SCHEMA)
    delete_chunks_sql = build_delete_case_chunks_sql(config.CASE_POSTGRES_SCHEMA)

    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        result = conn.execute(upsert_sql, _record_params(record))
        if _fetchone(result) is None:
            raise CaseArchiveConflictError(
                f"case_id collision for unrelated source identity: {record.case_id}"
            )
        conn.execute(delete_chunks_sql, (record.case_id,))


def write_case_record_with_retries(
    *,
    record: CaseArchiveRecord,
    config: Config,
    connect: ConnectionFactory | None = None,
    sleep: SleepFn = time.sleep,
) -> None:
    """Write a case archive record with bounded retries for transient failures."""
    attempts = max(1, int(config.CASE_ARCHIVE_WRITE_MAX_ATTEMPTS))
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            write_case_record_once(record=record, config=config, connect=connect)
            return
        except CaseArchiveConflictError:
            raise
        except Exception as exc:
            if not _is_retryable(exc):
                raise CaseArchiveWriteError("case archive write failed") from exc
            last_exc = exc
            if attempt >= attempts:
                break
            sleep(float(config.CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS))
    raise CaseArchiveWriteError("case archive write failed after retries") from last_exc


def write_case_archive_record(
    *,
    config: Config,
    case_id: str,
    finding_id: str,
    source_filename: str,
    alert_payload: Any,
    analysis: dict[str, Any],
    report_md_path: Path | str | None,
    report_html_path: Path | str | None,
    connect: ConnectionFactory | None = None,
    sleep: SleepFn = time.sleep,
) -> CaseArchiveRecord:
    """Build and persist a native case archive record."""
    record = build_case_archive_record(
        config=config,
        case_id=case_id,
        finding_id=finding_id,
        source_filename=source_filename,
        alert_payload=alert_payload,
        analysis=analysis,
        report_md_path=report_md_path,
        report_html_path=report_html_path,
    )
    write_case_record_with_retries(
        record=record,
        config=config,
        connect=connect,
        sleep=sleep,
    )
    return record
