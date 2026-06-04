"""Read-only Postgres case archive index queries for the analyst portal."""

# Optional database dependency is imported lazily so non-portal deployments can
# import the analyzer without opening the Postgres path.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .case_store import CaseArchiveRecord, quote_identifier
from .config import Config

ConnectionFactory = Callable[[str], Any]
_MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class CaseListFilters:
    """Filters and pagination for case list queries."""

    processed_from: datetime | None = None
    processed_to: datetime | None = None
    verdict: str | None = None
    search_name_prefix: str | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True)
class CaseSummary:
    """Portal list-view case metadata."""

    case_id: str
    finding_id: str | None
    source_filename: str
    processed_at: datetime
    expires_at: datetime
    verdict: str | None
    confidence: float | None
    search_name: str | None
    risk_score: float | None
    retrieval_status: str
    source_completeness: str
    report_md_path: str | None
    report_html_path: str | None


def _default_connect(dsn: str) -> Any:
    """Open a psycopg connection for case index reads."""
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is unavailable in the runtime.") from exc
    return psycopg.connect(dsn, connect_timeout=5)


def _set_statement_timeout(conn: Any, timeout_ms: int) -> None:
    """Set a transaction-local Postgres statement timeout."""
    if int(timeout_ms) > 0:
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{int(timeout_ms)}ms",),
        )


def _fetchall(result: Any) -> list[Any]:
    """Read all rows from a cursor-like result."""
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        return list(fetchall())
    return []


def _fetchone(result: Any) -> Any:
    """Read one row from a cursor-like result."""
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    return None


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


def _bounded_limit(config: Config, limit: int | None) -> int:
    """Return a bounded case list page size."""
    default = max(1, min(_MAX_PAGE_SIZE, int(config.PORTAL_PAGE_SIZE)))
    if limit is None:
        return default
    return max(1, min(_MAX_PAGE_SIZE, int(limit)))


def _escape_like_prefix(value: str) -> str:
    """Escape user-controlled LIKE wildcards for prefix matching."""
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        + "%"
    )


def build_list_cases_query(
    schema: str,
    filters: CaseListFilters,
    *,
    page_size: int,
) -> tuple[str, tuple[Any, ...]]:
    """Build a parameterized case list query."""
    table = f"{quote_identifier(schema, 'schema')}.cases"
    clauses: list[str] = []
    params: list[Any] = []

    if filters.processed_from is not None:
        clauses.append("processed_at >= %s")
        params.append(filters.processed_from)
    if filters.processed_to is not None:
        clauses.append("processed_at <= %s")
        params.append(filters.processed_to)
    if filters.verdict:
        clauses.append("verdict = %s")
        params.append(filters.verdict)
    if filters.search_name_prefix:
        clauses.append("search_name ILIKE %s ESCAPE '\\'")
        params.append(_escape_like_prefix(filters.search_name_prefix))

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend((page_size, max(0, int(filters.offset))))
    return (
        f"""
SELECT
    case_id,
    finding_id,
    source_filename,
    processed_at,
    expires_at,
    verdict,
    confidence,
    search_name,
    risk_score,
    retrieval_status,
    source_completeness,
    report_md_path,
    report_html_path
FROM {table}
{where_clause}
ORDER BY processed_at DESC, case_id ASC
LIMIT %s OFFSET %s
""".strip(),
        tuple(params),
    )


def build_get_case_query(schema: str) -> str:
    """Build a parameterized case detail query."""
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
WHERE case_id = %s
""".strip()


def _summary_from_row(row: Any) -> CaseSummary:
    """Build a CaseSummary from a selected row."""
    return CaseSummary(
        case_id=_row_get(row, 0, "case_id"),
        finding_id=_row_get(row, 1, "finding_id"),
        source_filename=_row_get(row, 2, "source_filename"),
        processed_at=_row_get(row, 3, "processed_at"),
        expires_at=_row_get(row, 4, "expires_at"),
        verdict=_row_get(row, 5, "verdict"),
        confidence=_row_get(row, 6, "confidence"),
        search_name=_row_get(row, 7, "search_name"),
        risk_score=_row_get(row, 8, "risk_score"),
        retrieval_status=_row_get(row, 9, "retrieval_status"),
        source_completeness=_row_get(row, 10, "source_completeness"),
        report_md_path=_row_get(row, 11, "report_md_path"),
        report_html_path=_row_get(row, 12, "report_html_path"),
    )


def _detail_from_row(row: Any) -> CaseArchiveRecord:
    """Build a CaseArchiveRecord from a selected detail row."""
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


def list_cases(
    *,
    config: Config,
    filters: CaseListFilters | None = None,
    connect: ConnectionFactory | None = None,
) -> list[CaseSummary]:
    """List cases ordered by processed_at descending."""
    filters = filters or CaseListFilters()
    page_size = _bounded_limit(config, filters.limit)
    sql, params = build_list_cases_query(
        config.CASE_POSTGRES_SCHEMA,
        filters,
        page_size=page_size,
    )
    connect_fn = connect or _default_connect
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        result = conn.execute(sql, params)
        return [_summary_from_row(row) for row in _fetchall(result)]


def get_case(
    *,
    config: Config,
    case_id: str,
    connect: ConnectionFactory | None = None,
) -> CaseArchiveRecord | None:
    """Fetch one case detail by case_id."""
    normalized = str(case_id or "").strip()
    if not normalized:
        return None
    connect_fn = connect or _default_connect
    sql = build_get_case_query(config.CASE_POSTGRES_SCHEMA)
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        row = _fetchone(conn.execute(sql, (normalized,)))
        if row is None:
            return None
        return _detail_from_row(row)
