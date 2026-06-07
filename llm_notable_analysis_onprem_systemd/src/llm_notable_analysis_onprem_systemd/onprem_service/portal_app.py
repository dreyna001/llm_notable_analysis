"""Read-only FastAPI analyst portal for the Postgres case archive."""

# Optional FastAPI/psycopg imports are lazy or guarded for non-portal installs.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import logging
import secrets
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .case_chat import (
    CaseNotFoundError,
    GeneralSynthesizeFn,
    SynthesizeFn,
    answer_case_chat,
    check_case_chat_ready,
)
from .case_index import (
    CaseListFilters,
    CaseSummary,
    ConnectionFactory,
    get_case,
    list_cases,
)
from .case_chat_history import (
    delete_chat_session,
    delete_last_chat_turn,
    get_chat_session_messages,
    list_chat_sessions,
)
from .case_store import CaseArchiveRecord, quote_identifier
from .case_db import (
    default_connect as _default_connect,
    fetchone as _fetchone,
    postgres_operation_errors,
    set_statement_timeout as _set_statement_timeout,
)
from .config import Config, load_config

logger = logging.getLogger(__name__)

_MAX_PAGE_SIZE = 100
_MAX_LIST_OFFSET = 10_000
_MAX_CASE_ID_LENGTH = 128
_MAX_TRUSTED_USER_LENGTH = 256
_PUBLIC_PATHS = frozenset({"/health", "/ready"})
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_TRUSTED_USER_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "portal_trusted_user",
    default=None,
)


def _lazy_import_fastapi():
    try:
        from fastapi import FastAPI, HTTPException, Request  # type: ignore
        from fastapi.responses import JSONResponse  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("fastapi is unavailable in the runtime.") from exc
    return FastAPI, HTTPException, Request, JSONResponse


def _is_loopback_bind_host(host: str) -> bool:
    text = str(host or "").strip().lower()
    if text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _portal_header_name(value: str, setting_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{setting_name} must be non-empty when PORTAL_ENABLED=true.")
    return text


def _validate_portal_security_config(config: Config) -> None:
    """Fail closed for portal deployments that could trust spoofed proxy headers."""
    _portal_header_name(config.PORTAL_TRUSTED_USER_HEADER, "PORTAL_TRUSTED_USER_HEADER")
    _portal_header_name(config.PORTAL_PROXY_SECRET_HEADER, "PORTAL_PROXY_SECRET_HEADER")
    if not str(config.PORTAL_PROXY_SECRET or "").strip():
        raise ValueError("PORTAL_PROXY_SECRET is required when PORTAL_ENABLED=true.")
    bind_host = str(config.PORTAL_BIND_HOST or "").strip()
    if _is_loopback_bind_host(bind_host):
        return
    if not bool(config.PORTAL_ALLOW_NON_LOOPBACK_BIND):
        raise ValueError(
            "PORTAL_BIND_HOST must be loopback unless "
            "PORTAL_ALLOW_NON_LOOPBACK_BIND=true is explicitly configured."
        )


def _trusted_user_from_request(request: Any, config: Config) -> str | None:
    header = _portal_header_name(
        config.PORTAL_TRUSTED_USER_HEADER,
        "PORTAL_TRUSTED_USER_HEADER",
    )
    value = request.headers.get(header)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > _MAX_TRUSTED_USER_LENGTH:
        return None
    return text


def _proxy_secret_matches(request: Any, config: Config) -> bool:
    expected = str(config.PORTAL_PROXY_SECRET or "").strip()
    if not expected:
        return False
    header = _portal_header_name(
        config.PORTAL_PROXY_SECRET_HEADER,
        "PORTAL_PROXY_SECRET_HEADER",
    )
    supplied = request.headers.get(header)
    if supplied is None:
        return False
    return secrets.compare_digest(str(supplied).strip(), expected)


def _same_origin_request(request: Any) -> bool:
    """Reject browser cross-site writes while allowing non-browser clients."""
    fetch_site = str(request.headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site and fetch_site not in {"same-origin", "none"}:
        return False

    origin = str(request.headers.get("origin") or "").strip()
    if not origin:
        return True
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = str(request.headers.get("host") or "").strip().lower()
    if parsed.netloc.lower() != host:
        return False
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip().lower()
    if forwarded_proto and parsed.scheme != forwarded_proto:
        return False
    return True


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
    """Return True when required case archive tables are readable by portal traffic."""
    schema = str(config.CASE_POSTGRES_SCHEMA or "").strip()
    if not schema:
        return False
    connect_fn = connect or _default_connect
    try:
        list_cases(
            config=config,
            filters=CaseListFilters(limit=1),
            connect=connect_fn,
        )
        chunks_table = f"{quote_identifier(schema, 'schema')}.case_chunks"
        sql = f"""
SELECT 1
FROM {chunks_table}
LIMIT 1
""".strip()
        with connect_fn(config.CASE_POSTGRES_DSN) as conn:
            _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
            _fetchone(conn.execute(sql))
        return True
    except postgres_operation_errors():
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
        if parsed_offset > _MAX_LIST_OFFSET:
            raise ValueError(f"offset must be at most {_MAX_LIST_OFFSET}.")

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
    chat_general_synthesizer: GeneralSynthesizeFn | None = None,
    chat_embedding_model: Any = None,
    chat_knowledge_base_provider: Any = None,
) -> Any:
    """Build the read-only analyst portal FastAPI application."""
    FastAPI, HTTPException, Request, JSONResponse = _lazy_import_fastapi()
    _validate_portal_security_config(config)
    connect_fn = connect or _default_connect
    trusted_header = _portal_header_name(
        config.PORTAL_TRUSTED_USER_HEADER,
        "PORTAL_TRUSTED_USER_HEADER",
    )
    proxy_secret_header = _portal_header_name(
        config.PORTAL_PROXY_SECRET_HEADER,
        "PORTAL_PROXY_SECRET_HEADER",
    )

    app = FastAPI(
        title="Notable Analyst Portal",
        description="Read-only case archive portal",
        version="1.0.0",
    )
    app.state.config = config
    app.state.connect = connect_fn
    chat_semaphore = threading.BoundedSemaphore(
        max(1, int(config.PORTAL_CHAT_MAX_CONCURRENCY))
    )

    def fetch_case_detail(case_id: str) -> tuple[str, CaseArchiveRecord]:
        normalized = str(case_id or "").strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="case_id must be non-empty.")
        if len(normalized) > _MAX_CASE_ID_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"case_id must be at most {_MAX_CASE_ID_LENGTH} characters.",
            )
        try:
            record = get_case(
                config=config,
                case_id=normalized,
                connect=connect_fn,
            )
        except Exception as exc:
            logger.exception("Failed to fetch case %s", normalized)
            raise HTTPException(
                status_code=503,
                detail="Case archive unavailable.",
            ) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="Case not found.")
        return normalized, record

    @app.middleware("http")
    async def trusted_user_middleware(request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC_PATHS:
            return await call_next(request)
        if request.method.upper() in _MUTATING_METHODS and not _same_origin_request(
            request
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-site portal write requests are not allowed."},
            )
        if not _proxy_secret_matches(request, config):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        f"Missing or invalid proxy secret header {proxy_secret_header!r}. "
                        "Requests must come through the trusted reverse proxy."
                    )
                },
            )
        trusted_user = _trusted_user_from_request(request, config)
        if trusted_user is None:
            raw_user = request.headers.get(trusted_header)
            if raw_user is not None and str(raw_user).strip():
                detail = (
                    f"Trusted user header {trusted_header!r} exceeds "
                    f"{_MAX_TRUSTED_USER_LENGTH} characters."
                )
            else:
                detail = (
                    f"Missing trusted user header {trusted_header!r}. "
                    "Requests must come through nginx with proxy auth."
                )
            return JSONResponse(
                status_code=401,
                content={"detail": detail},
            )
        token = _TRUSTED_USER_CTX.set(trusted_user)
        try:
            return await call_next(request)
        finally:
            _TRUSTED_USER_CTX.reset(token)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness probe for load balancers; intentionally minimal and unauthenticated."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> Any:
        """Archive readiness for load balancers; does not probe chat LLM dependencies."""
        archive_ready = check_case_archive_ready(config=config, connect=connect_fn)
        if archive_ready:
            return {"status": "ready"}
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.get("/api/capabilities")
    def api_capabilities() -> dict[str, Any]:
        return {
            "case_qa_enabled": bool(config.CASE_QA_ENABLED),
            "global_retrieval_enabled": bool(config.CASE_QA_GLOBAL_RETRIEVAL_ENABLED),
            "chat_history_enabled": bool(config.CASE_QA_CHAT_HISTORY_ENABLED),
            "general_knowledge_enabled": bool(config.CASE_QA_GENERAL_KNOWLEDGE_ENABLED),
            "max_question_chars": int(config.CASE_QA_MAX_QUESTION_CHARS),
            "max_answer_tokens": int(config.CASE_QA_MAX_ANSWER_TOKENS),
            "max_chat_sessions_per_user": int(config.CASE_QA_MAX_SESSIONS_PER_USER),
            "case_retention_days": int(config.CASE_RETENTION_DAYS),
        }

    @app.get("/api/diagnostics/chat-readiness")
    def api_chat_readiness() -> Any:
        chat_ready = check_case_chat_ready(
            config=config,
            connect=connect_fn,
            embedding_model=chat_embedding_model,
        )
        if chat_ready:
            return {"status": "ready"}
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.get("/api/cases")
    def api_list_cases(
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
            items = list_cases(
                config=config,
                filters=filters,
                connect=connect_fn,
                fetch_extra=True,
            )
        except Exception as exc:
            logger.exception("Failed to list cases")
            raise HTTPException(status_code=503, detail="Case archive unavailable.") from exc
        response_items = items[:page_size]

        return {
            "items": [_summary_item(item) for item in response_items],
            "limit": page_size,
            "offset": filters.offset,
            "has_more": len(items) > page_size,
        }

    @app.get("/api/cases/{case_id}")
    def api_get_case(case_id: str) -> dict[str, Any]:
        _normalized, record = fetch_case_detail(case_id)
        return _detail_payload(record)

    @app.get("/api/chat/sessions")
    def api_list_chat_sessions(limit: str | None = None) -> dict[str, Any]:
        page_size = 50
        if limit is not None:
            try:
                page_size = max(1, min(int(limit), _MAX_PAGE_SIZE))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="limit must be an integer.") from exc
        if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
            return {"history_enabled": False, "items": []}
        try:
            items = list_chat_sessions(
                config=config,
                user_id=_TRUSTED_USER_CTX.get(),
                connect=connect_fn,
                limit=page_size,
            )
        except Exception as exc:
            logger.exception("Failed to list portal chat sessions")
            raise HTTPException(status_code=503, detail="Chat history unavailable.") from exc
        return {"history_enabled": True, "items": items}

    @app.get("/api/chat/sessions/{session_id}/messages")
    def api_get_chat_session_messages(session_id: str) -> dict[str, Any]:
        if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
            raise HTTPException(status_code=404, detail="Chat history is disabled.")
        try:
            return get_chat_session_messages(
                config=config,
                session_id=session_id,
                user_id=_TRUSTED_USER_CTX.get(),
                connect=connect_fn,
            )
        except ValueError as exc:
            message = str(exc)
            if "not found" in message or "expired" in message or "does not belong" in message:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to load portal chat session messages")
            raise HTTPException(status_code=503, detail="Chat history unavailable.") from exc

    @app.delete("/api/chat/sessions/{session_id}")
    def api_delete_chat_session(session_id: str) -> dict[str, Any]:
        if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
            raise HTTPException(status_code=404, detail="Chat history is disabled.")
        try:
            deleted = delete_chat_session(
                config=config,
                session_id=session_id,
                user_id=_TRUSTED_USER_CTX.get(),
                connect=connect_fn,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to delete portal chat session")
            raise HTTPException(status_code=503, detail="Chat history unavailable.") from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="session_id was not found.")
        return {"deleted": True, "session_id": session_id}

    @app.delete("/api/chat/sessions/{session_id}/turns/last")
    def api_delete_last_chat_turn(
        session_id: str,
        expected_message_count: int | None = None,
    ) -> dict[str, Any]:
        if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
            raise HTTPException(status_code=404, detail="Chat history is disabled.")
        try:
            deleted_count = delete_last_chat_turn(
                config=config,
                session_id=session_id,
                user_id=_TRUSTED_USER_CTX.get(),
                expected_message_count=expected_message_count,
                connect=connect_fn,
            )
        except ValueError as exc:
            detail = str(exc)
            if "does not match the expected orphan cleanup snapshot" in detail:
                raise HTTPException(status_code=409, detail=detail) from exc
            raise HTTPException(status_code=400, detail=detail) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to delete last portal chat turn")
            raise HTTPException(status_code=503, detail="Chat history unavailable.") from exc
        if deleted_count <= 0:
            raise HTTPException(status_code=404, detail="No chat turn was found to delete.")
        return {
            "deleted": True,
            "session_id": session_id,
            "deleted_messages": deleted_count,
        }

    def _answer_portal_chat(payload: dict[str, Any]) -> dict[str, Any]:
        return answer_case_chat(
            payload=payload,
            config=config,
            connect=connect_fn,
            embedding_model=chat_embedding_model,
            synthesize=chat_synthesizer,
            general_synthesize=chat_general_synthesizer,
            knowledge_base_provider=chat_knowledge_base_provider,
            user_id=_TRUSTED_USER_CTX.get(),
        )

    @app.post("/api/chat")
    async def api_chat(payload: dict[str, Any]) -> dict[str, Any]:
        if not chat_semaphore.acquire(blocking=False):
            raise HTTPException(
                status_code=429,
                detail="Too many chat requests are already running. Try again shortly.",
            )
        try:
            return await asyncio.to_thread(_answer_portal_chat, payload)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to answer portal chat request")
            raise HTTPException(status_code=503, detail="Case chat unavailable.") from exc
        finally:
            chat_semaphore.release()

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
