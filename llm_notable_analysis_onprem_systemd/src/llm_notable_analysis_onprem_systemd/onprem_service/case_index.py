"""Read-only Postgres case archive index queries for the analyst portal."""

# Optional database dependency is imported lazily so non-portal deployments can
# import the analyzer without opening the Postgres path.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .case_db import (
    default_connect as _default_connect,
    fetchall as _fetchall,
    fetchone as _fetchone,
    row_get as _row_get,
    set_statement_timeout as _set_statement_timeout,
)
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
    search_name: str | None = None
    search_name_prefix: str | None = None
    cursor_processed_at: datetime | None = None
    cursor_case_id: str | None = None
    limit: int | None = None


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


def _json_from_db(value: Any) -> Any:
    """Normalize JSONB values returned by psycopg or test fakes."""
    if isinstance(value, str):
        return json.loads(value)
    return value


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


def _escape_like_substring(value: str) -> str:
    """Escape user-controlled LIKE wildcards for substring matching."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def build_list_cases_query(
    schema: str,
    filters: CaseListFilters,
    *,
    page_size: int,
) -> tuple[str, tuple[Any, ...]]:
    """Build a parameterized case list query."""
    table = f"{quote_identifier(schema, 'schema')}.cases"
    clauses: list[str] = ["expires_at > now()"]
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
    if filters.search_name:
        clauses.append("search_name ILIKE %s ESCAPE '\\'")
        params.append(_escape_like_substring(filters.search_name))
    elif filters.search_name_prefix:
        clauses.append("search_name ILIKE %s ESCAPE '\\'")
        params.append(_escape_like_prefix(filters.search_name_prefix))
    if filters.cursor_processed_at is not None:
        clauses.append(
            "(processed_at < %s OR (processed_at = %s AND case_id > %s))"
        )
        params.extend(
            (
                filters.cursor_processed_at,
                filters.cursor_processed_at,
                filters.cursor_case_id,
            )
        )

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(page_size)
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
LIMIT %s
""".strip(),
        tuple(params),
    )


def build_case_exists_query(schema: str) -> str:
    """Build a parameterized existence check for one non-expired case."""
    return f"""
SELECT 1
FROM {quote_identifier(schema, 'schema')}.cases
WHERE case_id = %s
  AND expires_at > now()
LIMIT 1
""".strip()


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
  AND expires_at > now()
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
    fetch_extra: bool = False,
) -> list[CaseSummary]:
    """List cases ordered by processed_at descending."""
    filters = filters or CaseListFilters()
    page_size = _bounded_limit(config, filters.limit)
    fetch_size = page_size + 1 if fetch_extra else page_size
    sql, params = build_list_cases_query(
        config.CASE_POSTGRES_SCHEMA,
        filters,
        page_size=fetch_size,
    )
    connect_fn = connect or _default_connect
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        result = conn.execute(sql, params)
        return [_summary_from_row(row) for row in _fetchall(result)]


def case_exists(
    *,
    config: Config,
    case_id: str,
    connect: ConnectionFactory | None = None,
) -> bool:
    """Return True when a non-expired case row exists for case_id."""
    normalized = str(case_id or "").strip()
    if not normalized:
        return False
    connect_fn = connect or _default_connect
    sql = build_case_exists_query(config.CASE_POSTGRES_SCHEMA)
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        row = _fetchone(conn.execute(sql, (normalized,)))
        return row is not None


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
