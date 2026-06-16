"""Read-only analyst portal API Lambda handler."""

from __future__ import annotations

import json
import threading
from typing import Any

from .aws_clients import bedrock_runtime_client, dynamodb_client, s3_client
from .case_index import get_case_detail, get_case_raw_section, list_cases
from .config import Config, load_config
from .portal_api_models import (
    CaseDetailResponse,
    CaseListResponse,
    CaseRawSectionResponse,
    HealthResponse,
    PortalCapabilitiesResponse,
    portal_response,
)

CHAT_LIMIT_MESSAGE = (
    "Too many chat requests are already running. Try again shortly."
)
_chat_semaphore: threading.BoundedSemaphore | None = None
_chat_semaphore_limit: int | None = None


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Route API Gateway HTTP events to the read-only portal API."""

    config = load_config()
    method = _method(event)
    path = _path(event)
    if method not in {"GET", "POST"}:
        return _json_response(405, {"error": "Method not allowed"})
    if method == "POST" and path != "/api/chat":
        return _json_response(405, {"error": "Method not allowed"})
    if path not in {"/health", "/ready"} and not _is_authenticated(event, config):
        return _json_response(401, {"error": "Unauthorized"})

    if method == "POST" and path == "/api/chat":
        return _handle_chat_gate(config)
    if path == "/health":
        return _model_response(HealthResponse, {"status": "ok"})
    if path == "/ready":
        ready = config.PORTAL_ENABLED and bool(config.CASE_INDEX_TABLE)
        return _json_response(200 if ready else 503, {"status": "ready" if ready else "not_ready"})
    if path == "/api/capabilities":
        return _model_response(PortalCapabilitiesResponse, _capabilities(config))
    if path == "/api/cases":
        query = event.get("queryStringParameters") or {}
        payload = list_cases(
            config=config,
            dynamodb_client=dynamodb_client(),
            limit=_int_query(query.get("limit")),
            cursor=query.get("cursor"),
        )
        return _model_response(CaseListResponse, payload)

    case_id, raw_section = _case_route(path)
    if case_id and raw_section:
        query = event.get("queryStringParameters") or {}
        payload = get_case_raw_section(
            config=config,
            dynamodb_client=dynamodb_client(),
            s3_client=s3_client(),
            case_id=case_id,
            section=raw_section,
            offset=_int_query(query.get("offset"), default=0),
            limit=_int_query(query.get("limit")),
        )
        if payload is None:
            return _json_response(404, {"error": "Case not found"})
        return _model_response(CaseRawSectionResponse, payload)
    if case_id:
        payload = get_case_detail(
            config=config,
            dynamodb_client=dynamodb_client(),
            s3_client=s3_client(),
            case_id=case_id,
        )
        if payload is None:
            return _json_response(404, {"error": "Case not found"})
        return _model_response(CaseDetailResponse, payload)
    return _json_response(404, {"error": "Not found"})


def _handle_chat_gate(config: Config) -> dict[str, Any]:
    semaphore = _get_chat_semaphore(config.PORTAL_CHAT_MAX_CONCURRENCY)
    if not semaphore.acquire(blocking=False):
        return _json_response(429, {"error": CHAT_LIMIT_MESSAGE})
    try:
        return _json_response(501, {"error": "Case Q&A is implemented in Wave 2 Diff 4"})
    finally:
        semaphore.release()


def _get_chat_semaphore(limit: int) -> threading.BoundedSemaphore:
    global _chat_semaphore, _chat_semaphore_limit  # pylint: disable=global-statement
    if _chat_semaphore is None or _chat_semaphore_limit != limit:
        _chat_semaphore = threading.BoundedSemaphore(limit)
        _chat_semaphore_limit = limit
    return _chat_semaphore


def _capabilities(config: Config) -> dict[str, Any]:
    dependency_status = None
    degraded_reason = None
    chat_ready = False
    if config.CASE_QA_ENABLED:
        dependency_status = _probe_chat_dependencies(config)
        chat_ready = all(value == "ready" for value in dependency_status.values())
        if not chat_ready:
            degraded_reason = "One or more chat dependencies are unavailable."
    return {
        "case_qa_enabled": config.CASE_QA_ENABLED,
        "chat_history_enabled": config.CASE_QA_CHAT_HISTORY_ENABLED,
        "general_knowledge_enabled": config.CASE_QA_GENERAL_KNOWLEDGE_ENABLED,
        "max_question_chars": config.CASE_QA_MAX_QUESTION_CHARS,
        "max_answer_tokens": config.CASE_QA_MAX_ANSWER_TOKENS,
        "max_chat_sessions_per_user": config.CASE_QA_MAX_SESSIONS_PER_USER,
        "case_retention_days": config.CASE_RETENTION_DAYS,
        "chat_ready": chat_ready,
        "chat_dependency_status": dependency_status,
        "chat_degraded_reason": degraded_reason,
    }


def _probe_chat_dependencies(config: Config) -> dict[str, str]:
    status = {
        "embeddings": "ready" if config.CASE_EMBED_LAMBDA_NAME else "unavailable",
        "archive_retrieval": "unavailable",
        "llm_gateway": "unavailable",
    }
    try:
        dynamodb_client().describe_table(TableName=config.CASE_INDEX_TABLE)
        status["archive_retrieval"] = "ready"
    except Exception:
        status["archive_retrieval"] = "unavailable"
    if (config.PORTAL_CHAT_BEDROCK_MODEL_ID or config.BEDROCK_MODEL_ID).strip():
        try:
            bedrock_runtime_client()
            status["llm_gateway"] = "ready"
        except Exception:
            status["llm_gateway"] = "unavailable"
    return status


def _is_authenticated(event: dict[str, Any], config: Config) -> bool:
    authorizer = ((event.get("requestContext") or {}).get("authorizer") or {})
    if config.PORTAL_AUTH_MODE == "jwt":
        claims = (authorizer.get("jwt") or {}).get("claims")
        if not isinstance(claims, dict):
            return False
        audience = claims.get("aud")
        if isinstance(audience, list):
            audience_valid = config.PORTAL_JWT_AUDIENCE in audience
        else:
            audience_valid = str(audience or "") == config.PORTAL_JWT_AUDIENCE
        return str(claims.get("iss") or "") == config.PORTAL_JWT_ISSUER and audience_valid
    if config.PORTAL_AUTH_MODE == "iam":
        return bool(authorizer.get("iam"))
    return False


def _case_route(path: str) -> tuple[str | None, str | None]:
    prefix = "/api/cases/"
    if not path.startswith(prefix):
        return None, None
    remainder = path[len(prefix) :].strip("/")
    parts = remainder.split("/")
    if len(parts) == 1 and parts[0]:
        return parts[0], None
    if len(parts) == 3 and parts[1] == "raw" and parts[2] in {"alert_payload", "analysis"}:
        return parts[0], parts[2]
    return None, None


def _method(event: dict[str, Any]) -> str:
    return str(
        ((event.get("requestContext") or {}).get("http") or {}).get("method")
        or event.get("httpMethod")
        or "GET"
    ).upper()


def _path(event: dict[str, Any]) -> str:
    return str(event.get("rawPath") or event.get("path") or "/").rstrip("/") or "/"


def _int_query(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _model_response(model: Any, payload: Any) -> dict[str, Any]:
    return _json_response(200, portal_response(model, payload).model_dump(mode="json"))


def _json_response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, default=str),
    }
