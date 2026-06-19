"""Read-only analyst portal API Lambda handler."""

from __future__ import annotations

import json
import threading
from typing import Any

from .aws_clients import bedrock_runtime_client, dynamodb_client, s3_client
from .case_chat import answer_selected_case_question
from .case_chat_history import (
    ChatSessionExpiredError,
    ChatSessionNotFoundError,
    delete_chat_session,
    delete_last_chat_turn,
    get_chat_session_messages,
    list_chat_sessions,
    persist_chat_history,
    validate_chat_history_request,
)
from .case_index import get_case_detail, get_case_raw_section, list_cases
from .config import Config, load_config
from .portal_jwt import resolve_portal_jwt_claims, resolve_portal_user_id
from .portal_api_models import (
    CaseDetailResponse,
    CaseListResponse,
    CaseRawSectionResponse,
    ChatResponseModel,
    ChatSessionMessagesResponse,
    ChatSessionsResponse,
    DeleteChatSessionResponse,
    DeleteLastChatTurnResponse,
    HealthResponse,
    PortalCapabilitiesResponse,
    portal_response,
)

CHAT_LIMIT_MESSAGE = (
    "Too many chat requests are already running. Try again shortly."
)
_chat_semaphore: threading.BoundedSemaphore | None = None
_chat_semaphore_limit: int | None = None
_SUPPORTED_CHAT_MODES = frozenset({"selected_case"})


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Route API Gateway HTTP events to the read-only portal API."""

    config = load_config()
    method = _method(event)
    path = _path(event)
    if method == "OPTIONS":
        return _cors_response(config, event)
    return _with_cors(config, event, _route(event, config, method, path))


def _route(
    event: dict[str, Any],
    config: Config,
    method: str,
    path: str,
) -> dict[str, Any]:
    if method not in {"GET", "POST", "DELETE"}:
        return _json_response(405, {"error": "Method not allowed"})
    if method == "POST" and path != "/api/chat":
        return _json_response(405, {"error": "Method not allowed"})
    if method == "DELETE" and _chat_session_route(path) is None:
        return _json_response(405, {"error": "Method not allowed"})
    if path not in {"/health", "/ready"} and not _is_authenticated(event, config):
        return _json_response(401, {"error": "Unauthorized"})

    if method == "POST" and path == "/api/chat":
        return _handle_chat_gate(config, event)
    if path == "/health":
        return _model_response(HealthResponse, {"status": "ok"})
    if path == "/ready":
        ready = config.PORTAL_ENABLED and bool(config.CASE_INDEX_TABLE)
        return _json_response(200 if ready else 503, {"status": "ready" if ready else "not_ready"})
    if path == "/api/capabilities":
        return _model_response(PortalCapabilitiesResponse, _capabilities(config))
    if path == "/api/diagnostics/chat-readiness":
        return _handle_chat_readiness(config)
    if path == "/api/cases":
        query = event.get("queryStringParameters") or {}
        payload = list_cases(
            config=config,
            dynamodb_client=dynamodb_client(),
            limit=_int_query(query.get("limit")),
            cursor=query.get("cursor"),
        )
        return _model_response(CaseListResponse, payload)

    chat_session_route = _chat_session_route(path)
    if chat_session_route is not None:
        return _handle_chat_session_route(
            config,
            event,
            method,
            chat_session_route,
        )

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


def _handle_chat_session_route(
    config: Config,
    event: dict[str, Any],
    method: str,
    route: str,
) -> dict[str, Any]:
    user_id = resolve_portal_user_id(event, config)
    session_id = _chat_session_id(event, route)
    if route == "list":
        if method != "GET":
            return _json_response(405, {"error": "Method not allowed"})
        if not config.CASE_QA_CHAT_HISTORY_ENABLED:
            return _model_response(
                ChatSessionsResponse,
                {"history_enabled": False, "items": []},
            )
        query = event.get("queryStringParameters") or {}
        try:
            limit = _int_query(query.get("limit"), default=50) or 50
            items = list_chat_sessions(
                config=config,
                dynamodb_client=dynamodb_client(),
                user_id=user_id,
                limit=limit,
            )
        except ValueError as exc:
            return _json_response(400, {"error": str(exc)})
        return _model_response(
            ChatSessionsResponse,
            {"history_enabled": True, "items": items},
        )
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        return _json_response(404, {"error": "Chat history is disabled."})
    if session_id is None:
        return _json_response(404, {"error": "Not found"})
    if route == "messages":
        if method != "GET":
            return _json_response(405, {"error": "Method not allowed"})
        try:
            payload = get_chat_session_messages(
                config=config,
                dynamodb_client=dynamodb_client(),
                session_id=session_id,
                user_id=user_id,
            )
            return _model_response(ChatSessionMessagesResponse, payload)
        except (ChatSessionNotFoundError, ChatSessionExpiredError, ValueError) as exc:
            return _chat_session_error_response(exc)
        except RuntimeError as exc:
            return _json_response(404, {"error": str(exc)})
    if route == "delete_session":
        if method != "DELETE":
            return _json_response(405, {"error": "Method not allowed"})
        try:
            deleted = delete_chat_session(
                config=config,
                dynamodb_client=dynamodb_client(),
                session_id=session_id,
                user_id=user_id,
            )
        except (ChatSessionNotFoundError, ChatSessionExpiredError, ValueError) as exc:
            return _chat_session_error_response(exc)
        except RuntimeError as exc:
            return _json_response(404, {"error": str(exc)})
        if not deleted:
            return _json_response(404, {"error": "session_id was not found."})
        return _model_response(
            DeleteChatSessionResponse,
            {"deleted": True, "session_id": session_id},
        )
    if route == "delete_last_turn":
        if method != "DELETE":
            return _json_response(405, {"error": "Method not allowed"})
        query = event.get("queryStringParameters") or {}
        expected_count = _int_query(query.get("expected_message_count"))
        try:
            deleted_count = delete_last_chat_turn(
                config=config,
                dynamodb_client=dynamodb_client(),
                session_id=session_id,
                user_id=user_id,
                expected_message_count=expected_count,
            )
        except (ChatSessionNotFoundError, ChatSessionExpiredError) as exc:
            return _chat_session_error_response(exc)
        except ValueError as exc:
            detail = str(exc)
            if "does not match the expected orphan cleanup snapshot" in detail:
                return _json_response(409, {"error": detail})
            return _json_response(400, {"error": detail})
        except RuntimeError as exc:
            return _json_response(404, {"error": str(exc)})
        if deleted_count <= 0:
            return _json_response(404, {"error": "No chat turn was found to delete."})
        return _model_response(
            DeleteLastChatTurnResponse,
            {
                "deleted": True,
                "session_id": session_id,
                "deleted_messages": deleted_count,
            },
        )
    return _json_response(404, {"error": "Not found"})


def _handle_chat_gate(config: Config, event: dict[str, Any]) -> dict[str, Any]:
    semaphore = _get_chat_semaphore(config.PORTAL_CHAT_MAX_CONCURRENCY)
    if not semaphore.acquire(blocking=False):
        return _json_response(429, {"error": CHAT_LIMIT_MESSAGE})
    try:
        request = _json_body(event)
        mode = str(request.get("mode") or "selected_case").strip()
        if mode not in _SUPPORTED_CHAT_MODES:
            raise ValueError(
                "mode must be one of: " + ", ".join(sorted(_SUPPORTED_CHAT_MODES))
            )
        selected_case_id = request.get("selected_case_id")
        selected_case_id = (
            str(selected_case_id).strip() if selected_case_id is not None else None
        )
        session_id = request.get("session_id")
        session_id = str(session_id).strip() if session_id else None
        user_id = resolve_portal_user_id(event, config)
        if config.CASE_QA_CHAT_HISTORY_ENABLED:
            validate_chat_history_request(
                config=config,
                dynamodb_client=dynamodb_client(),
                mode=mode,
                selected_case_id=selected_case_id,
                requested_session_id=session_id,
                user_id=user_id,
            )
        answer = answer_selected_case_question(
            case_id=str(selected_case_id or ""),
            question=str(request.get("question", "")),
            config=config,
            dynamodb_client=dynamodb_client(),
            s3_client=s3_client(),
            bedrock_client=bedrock_runtime_client(),
        )
        response_payload: dict[str, Any] = {
            "answer": answer.answer,
            "answer_status": answer.answer_status,
            "session_id": None,
        }
        if config.CASE_QA_CHAT_HISTORY_ENABLED:
            try:
                response_payload["session_id"] = persist_chat_history(
                    config=config,
                    dynamodb_client=dynamodb_client(),
                    mode=mode,
                    question=str(request.get("question", "")),
                    selected_case_id=selected_case_id,
                    requested_session_id=session_id,
                    user_id=user_id,
                    response=response_payload,
                )
            except (ChatSessionNotFoundError, ChatSessionExpiredError, ValueError) as exc:
                return _chat_session_error_response(exc)
            except RuntimeError as exc:
                return _json_response(503, {"error": str(exc)})
        return _model_response(ChatResponseModel, response_payload)
    except LookupError:
        return _json_response(404, {"error": "Case not found"})
    except ValueError as exc:
        return _json_response(400, {"error": str(exc)})
    finally:
        semaphore.release()


def _chat_session_error_response(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ChatSessionNotFoundError):
        return _json_response(404, {"error": str(exc)})
    if isinstance(exc, ChatSessionExpiredError):
        return _json_response(410, {"error": str(exc)})
    message = str(exc)
    if "does not belong to the authenticated user" in message:
        return _json_response(404, {"error": message})
    return _json_response(400, {"error": message})


def _get_chat_semaphore(limit: int) -> threading.BoundedSemaphore:
    global _chat_semaphore, _chat_semaphore_limit  # pylint: disable=global-statement
    if _chat_semaphore is None or _chat_semaphore_limit != limit:
        _chat_semaphore = threading.BoundedSemaphore(limit)
        _chat_semaphore_limit = limit
    return _chat_semaphore


def _handle_chat_readiness(config: Config) -> dict[str, Any]:
    if not config.CASE_QA_ENABLED:
        return _json_response(
            503,
            {
                "status": "not_ready",
                "reason": "Case Q&A is disabled in portal configuration.",
                "dependencies": {
                    "embeddings": "unavailable",
                    "archive_retrieval": "unavailable",
                    "llm_gateway": "unavailable",
                },
            },
        )
    dependencies = _probe_chat_dependencies(config)
    ready = all(value == "ready" for value in dependencies.values())
    if ready:
        return _json_response(200, {"status": "ready"})
    return _json_response(
        503,
        {
            "status": "not_ready",
            "dependencies": dependencies,
            "reason": "One or more chat dependencies are unavailable.",
        },
    )


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
    if config.PORTAL_AUTH_MODE == "jwt":
        return resolve_portal_jwt_claims(event, config) is not None
    if config.PORTAL_AUTH_MODE == "iam":
        authorizer = ((event.get("requestContext") or {}).get("authorizer") or {})
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


def _chat_session_route(path: str) -> str | None:
    if path == "/api/chat/sessions":
        return "list"
    prefix = "/api/chat/sessions/"
    if not path.startswith(prefix):
        return None
    remainder = path[len(prefix) :].strip("/")
    parts = remainder.split("/")
    if len(parts) == 1 and parts[0]:
        return "delete_session"
    if len(parts) == 2 and parts[0] and parts[1] == "messages":
        return "messages"
    if len(parts) == 3 and parts[0] and parts[1] == "turns" and parts[2] == "last":
        return "delete_last_turn"
    return None


def _chat_session_id(event: dict[str, Any], route: str) -> str | None:
    if route == "list":
        return None
    path = _path(event)
    prefix = "/api/chat/sessions/"
    remainder = path[len(prefix) :].strip("/")
    return remainder.split("/")[0] or None


def _method(event: dict[str, Any]) -> str:
    return str(
        ((event.get("requestContext") or {}).get("http") or {}).get("method")
        or event.get("httpMethod")
        or "GET"
    ).upper()


def _path(event: dict[str, Any]) -> str:
    return str(event.get("rawPath") or event.get("path") or "/").rstrip("/") or "/"


def _origin(event: dict[str, Any]) -> str:
    headers = event.get("headers") or {}
    for key, value in headers.items():
        if str(key).lower() == "origin":
            return str(value or "").strip()
    return ""


def _cors_headers(config: Config, event: dict[str, Any]) -> dict[str, str]:
    origin = _origin(event)
    allowed_origins = {
        item.strip()
        for item in config.PORTAL_CORS_ALLOWED_ORIGINS.split(",")
        if item.strip()
    }
    if not origin or origin not in allowed_origins:
        return {}
    return {
        "access-control-allow-origin": origin,
        "access-control-allow-methods": "GET,POST,DELETE,OPTIONS",
        "access-control-allow-headers": "authorization,content-type",
        "access-control-max-age": "300",
        "vary": "Origin",
    }


def _cors_response(config: Config, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": 204,
        "headers": _cors_headers(config, event),
        "body": "",
    }


def _with_cors(
    config: Config,
    event: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    headers = dict(response.get("headers") or {})
    headers.update(_cors_headers(config, event))
    response["headers"] = headers
    return response


def _int_query(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("request body must be JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _model_response(model: Any, payload: Any) -> dict[str, Any]:
    return _json_response(200, portal_response(model, payload).model_dump(mode="json"))


def _json_response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, default=str),
    }
