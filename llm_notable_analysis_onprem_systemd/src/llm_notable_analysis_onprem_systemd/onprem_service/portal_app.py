"""Read-only FastAPI analyst portal for the Postgres case archive."""

# Optional FastAPI/psycopg imports are lazy or guarded for non-portal installs.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

from .case_chat import SynthesizeFn, answer_case_chat
from .case_index import (
    CaseListFilters,
    CaseSummary,
    ConnectionFactory,
    get_case,
    list_cases,
)
from .case_store import CaseArchiveRecord
from .config import Config, load_config

logger = logging.getLogger(__name__)

_MAX_PAGE_SIZE = 100
_PUBLIC_PATHS = frozenset({"/health", "/ready"})


def _lazy_import_fastapi():
    try:
        from fastapi import FastAPI, HTTPException, Request  # type: ignore
        from fastapi.responses import HTMLResponse, JSONResponse  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("fastapi is unavailable in the runtime.") from exc
    return FastAPI, HTTPException, Request, HTMLResponse, JSONResponse


def _default_connect(dsn: str) -> Any:
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is unavailable in the runtime.") from exc
    return psycopg.connect(dsn, connect_timeout=5)


def _set_statement_timeout(conn: Any, timeout_ms: int) -> None:
    if int(timeout_ms) > 0:
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{int(timeout_ms)}ms",),
        )


def _fetchone(result: Any) -> Any:
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    return None


def _requires_trusted_user_header(config: Config) -> bool:
    return str(config.PORTAL_BIND_HOST or "").strip() != "127.0.0.1"


def _trusted_user_from_request(request: Any, config: Config) -> str | None:
    header = str(config.PORTAL_TRUSTED_USER_HEADER or "X-Forwarded-User").strip()
    if not header:
        return None
    value = request.headers.get(header)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_iso8601_timestamp(value: str, field_name: str) -> datetime:
    """Parse an ISO-8601 timestamp query parameter."""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty ISO-8601 timestamp.")
    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_case_archive_ready(
    *,
    config: Config,
    connect: ConnectionFactory | None = None,
) -> bool:
    """Return True when required case archive tables exist and are reachable."""
    schema = str(config.CASE_POSTGRES_SCHEMA or "").strip()
    if not schema:
        return False
    cases_table = f"{schema}.cases"
    chunks_table = f"{schema}.case_chunks"
    sql = "SELECT to_regclass(%s) IS NOT NULL, to_regclass(%s) IS NOT NULL"
    connect_fn = connect or _default_connect
    try:
        with connect_fn(config.CASE_POSTGRES_DSN) as conn:
            _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
            row = _fetchone(conn.execute(sql, (cases_table, chunks_table)))
            if row is None:
                return False
            return bool(row[0]) and bool(row[1])
    except Exception:
        logger.exception("Case archive readiness check failed")
        return False


def _summary_item(summary: CaseSummary) -> dict[str, Any]:
    return {
        "case_id": summary.case_id,
        "processed_at": _format_utc_timestamp(summary.processed_at),
        "expires_at": _format_utc_timestamp(summary.expires_at),
        "verdict": summary.verdict,
        "confidence": summary.confidence,
        "search_name": summary.search_name,
        "retrieval_status": summary.retrieval_status,
        "source_completeness": summary.source_completeness,
    }


def _detail_payload(record: CaseArchiveRecord) -> dict[str, Any]:
    return {
        "case_id": record.case_id,
        "metadata": {
            "processed_at": _format_utc_timestamp(record.processed_at),
            "expires_at": _format_utc_timestamp(record.expires_at),
            "retrieval_status": record.retrieval_status,
            "source_completeness": record.source_completeness,
        },
        "alert_payload": record.alert_payload,
        "analysis": record.analysis,
        "report_md_path": record.report_md_path,
        "report_html_path": record.report_html_path,
    }


def _parse_list_filters(
    *,
    limit: str | None,
    offset: str | None,
    start: str | None,
    end: str | None,
    verdict: str | None,
    search_name: str | None,
) -> CaseListFilters:
    parsed_limit: int | None = None
    if limit is not None:
        if not str(limit).strip().isdigit():
            raise ValueError("limit must be a positive integer.")
        parsed_limit = int(limit)
        if parsed_limit < 1 or parsed_limit > _MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {_MAX_PAGE_SIZE}.")

    parsed_offset = 0
    if offset is not None:
        if not str(offset).strip().isdigit():
            raise ValueError("offset must be a non-negative integer.")
        parsed_offset = int(offset)
        if parsed_offset < 0:
            raise ValueError("offset must be a non-negative integer.")

    processed_from = (
        parse_iso8601_timestamp(start, "start") if start is not None else None
    )
    processed_to = parse_iso8601_timestamp(end, "end") if end is not None else None
    if (
        processed_from is not None
        and processed_to is not None
        and processed_from > processed_to
    ):
        raise ValueError("start must be earlier than or equal to end.")

    normalized_verdict = str(verdict).strip() if verdict is not None else None
    if verdict is not None and not normalized_verdict:
        raise ValueError("verdict must be a non-empty string.")

    normalized_search_name = (
        str(search_name).strip() if search_name is not None else None
    )
    if search_name is not None and not normalized_search_name:
        raise ValueError("search_name must be a non-empty string.")

    return CaseListFilters(
        processed_from=processed_from,
        processed_to=processed_to,
        verdict=normalized_verdict,
        search_name=normalized_search_name,
        limit=parsed_limit,
        offset=parsed_offset,
    )


def _bounded_page_size(config: Config, limit: int | None) -> int:
    default = max(1, min(_MAX_PAGE_SIZE, int(config.PORTAL_PAGE_SIZE)))
    if limit is None:
        return default
    return max(1, min(_MAX_PAGE_SIZE, int(limit)))


def build_portal_app(
    config: Config,
    *,
    connect: ConnectionFactory | None = None,
    chat_synthesizer: SynthesizeFn | None = None,
    chat_embedding_model: Any = None,
    chat_soc_context_provider: Any = None,
) -> Any:
    """Build the read-only analyst portal FastAPI application."""
    FastAPI, HTTPException, Request, HTMLResponse, JSONResponse = _lazy_import_fastapi()
    connect_fn = connect or _default_connect
    require_header = _requires_trusted_user_header(config)
    trusted_header = str(config.PORTAL_TRUSTED_USER_HEADER or "X-Forwarded-User").strip()

    app = FastAPI(
        title="Notable Analyst Portal",
        description="Read-only case archive portal",
        version="1.0.0",
    )
    app.state.config = config
    app.state.connect = connect_fn

    @app.middleware("http")
    async def trusted_user_middleware(request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC_PATHS:
            return await call_next(request)
        if require_header and not _trusted_user_from_request(request, config):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        f"Missing trusted user header {trusted_header!r}. "
                        "Requests must come through nginx with proxy auth."
                    )
                },
            )
        request.state.trusted_user = _trusted_user_from_request(request, config)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> Any:
        if check_case_archive_ready(config=config, connect=connect_fn):
            return {"status": "ready"}
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.get("/api/cases")
    async def api_list_cases(
        limit: str | None = None,
        offset: str | None = None,
        start: str | None = None,
        end: str | None = None,
        verdict: str | None = None,
        search_name: str | None = None,
    ) -> dict[str, Any]:
        try:
            filters = _parse_list_filters(
                limit=limit,
                offset=offset,
                start=start,
                end=end,
                verdict=verdict,
                search_name=search_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        page_size = _bounded_page_size(config, filters.limit)
        try:
            items = list_cases(config=config, filters=filters, connect=connect_fn)
        except Exception as exc:
            logger.exception("Failed to list cases")
            raise HTTPException(status_code=503, detail="Case archive unavailable.") from exc

        return {
            "items": [_summary_item(item) for item in items],
            "limit": page_size,
            "offset": filters.offset,
            "has_more": len(items) == page_size,
        }

    @app.get("/api/cases/{case_id}")
    async def api_get_case(case_id: str) -> dict[str, Any]:
        normalized = str(case_id or "").strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="case_id must be non-empty.")
        try:
            record = get_case(
                config=config,
                case_id=normalized,
                connect=connect_fn,
            )
        except Exception as exc:
            logger.exception("Failed to fetch case %s", normalized)
            raise HTTPException(status_code=503, detail="Case archive unavailable.") from exc
        if record is None:
            raise HTTPException(status_code=404, detail="Case not found.")
        return _detail_payload(record)

    @app.post("/api/chat")
    async def api_chat(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return answer_case_chat(
                payload=payload,
                config=config,
                connect=connect_fn,
                embedding_model=chat_embedding_model,
                synthesize=chat_synthesizer,
                soc_context_provider=chat_soc_context_provider,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to answer portal chat request")
            raise HTTPException(status_code=503, detail="Case chat unavailable.") from exc

    @app.get("/", response_class=HTMLResponse)
    async def portal_home(request: Request) -> str:
        user = getattr(request.state, "trusted_user", None)
        user_line = (
            f"<p>Signed in as: {html.escape(user)}</p>" if user else "<p>Local portal view</p>"
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Notable Analyst Portal</title>
</head>
<body>
  <h1>Notable Analyst Portal</h1>
  {user_line}
  <p>Read-only access to archived cases.</p>
  <ul>
    <li><a href="/cases">Browse cases</a></li>
    <li><a href="/api/cases">Cases API</a></li>
    <li><a href="/health">Health</a></li>
    <li><a href="/ready">Ready</a></li>
  </ul>
</body>
</html>"""

    @app.get("/cases", response_class=HTMLResponse)
    async def portal_cases(
        limit: str | None = None,
        offset: str | None = None,
        start: str | None = None,
        end: str | None = None,
        verdict: str | None = None,
        search_name: str | None = None,
    ) -> str:
        try:
            filters = _parse_list_filters(
                limit=limit,
                offset=offset,
                start=start,
                end=end,
                verdict=verdict,
                search_name=search_name,
            )
            items = list_cases(config=config, filters=filters, connect=connect_fn)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to render case list")
            raise HTTPException(status_code=503, detail="Case archive unavailable.") from exc

        rows = []
        for item in items:
            rows.append(
                "<tr>"
                f"<td><a href=\"/cases/{html.escape(item.case_id)}\">"
                f"{html.escape(item.case_id)}</a></td>"
                f"<td>{html.escape(_format_utc_timestamp(item.processed_at))}</td>"
                f"<td>{html.escape(item.verdict or '')}</td>"
                f"<td>{html.escape(item.search_name or '')}</td>"
                f"<td>{html.escape(item.retrieval_status)}</td>"
                "</tr>"
            )
        body_rows = "\n".join(rows) if rows else "<tr><td colspan=\"5\">No cases found.</td></tr>"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Archived Cases</title>
</head>
<body>
  <h1>Archived Cases</h1>
  <p><a href="/">Home</a></p>
  <table border="1" cellpadding="4" cellspacing="0">
    <thead>
      <tr>
        <th>Case ID</th>
        <th>Processed</th>
        <th>Verdict</th>
        <th>Search Name</th>
        <th>Retrieval</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
</body>
</html>"""

    @app.get("/cases/{case_id}", response_class=HTMLResponse)
    async def portal_case_detail(case_id: str) -> str:
        normalized = str(case_id or "").strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="case_id must be non-empty.")
        record = get_case(config=config, case_id=normalized, connect=connect_fn)
        if record is None:
            raise HTTPException(status_code=404, detail="Case not found.")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Case {html.escape(normalized)}</title>
</head>
<body>
  <h1>Case {html.escape(normalized)}</h1>
  <p><a href="/cases">Back to cases</a></p>
  <p>Processed: {html.escape(_format_utc_timestamp(record.processed_at))}</p>
  <p>Verdict: {html.escape(record.verdict or '')}</p>
  <p>Search name: {html.escape(record.search_name or '')}</p>
  <p>Retrieval status: {html.escape(record.retrieval_status)}</p>
  <p>Source completeness: {html.escape(record.source_completeness)}</p>
</body>
</html>"""

    return app


def create_app() -> Any:
    """Factory entrypoint for uvicorn --factory."""
    config = load_config()
    if not config.PORTAL_ENABLED:
        raise RuntimeError("PORTAL_ENABLED must be true to run the portal service.")
    if not config.CASE_ARCHIVE_ENABLED:
        raise RuntimeError("CASE_ARCHIVE_ENABLED must be true to run the portal service.")
    return build_portal_app(config)


def main() -> None:
    """Run the portal with uvicorn using loaded config."""
    config = load_config()
    if not config.PORTAL_ENABLED:
        raise RuntimeError("PORTAL_ENABLED must be true to run the portal service.")
    if not config.CASE_ARCHIVE_ENABLED:
        raise RuntimeError("CASE_ARCHIVE_ENABLED must be true to run the portal service.")

    try:
        import uvicorn  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("uvicorn is unavailable in the runtime.") from exc

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "llm_notable_analysis_onprem_systemd.onprem_service.portal_app:create_app",
        factory=True,
        host=config.PORTAL_BIND_HOST,
        port=int(config.PORTAL_PORT),
        log_level="info",
    )


if __name__ == "__main__":
    main()
