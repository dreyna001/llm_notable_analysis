"""Native Azure HTTP runtime for the analyst portal API."""

from __future__ import annotations

import base64
import binascii
import json
import threading
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import azure.functions as func

from .case_chat_history import (
    ChatSessionExpiredError,
    ChatSessionNotFoundError,
    delete_chat_session,
    delete_last_chat_turn,
    get_chat_session_messages,
    list_chat_sessions,
    load_session_transcript,
    persist_chat_history,
    validate_chat_history_request,
)
from .case_index import get_case_detail, get_case_raw_section, list_cases
from .config import Config, load_config
from .cosmos_store import CosmosStore
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
from .portal_jwt import bearer_token_from_headers, validate_portal_jwt

CHAT_LIMIT_MESSAGE = "Too many chat requests are already running. Try again shortly."
_SUPPORTED_CHAT_MODES = frozenset({"selected_case"})
_MAX_PATH_COMPONENT_CHARS = 256
_MAX_CURSOR_COMPONENT_CHARS = 128
_MAX_REQUEST_BODY_BYTES = 65_536

ChatService = Callable[..., Any]
_configured_chat_service: ChatService | None = None
_chat_semaphore: threading.BoundedSemaphore | None = None
_chat_semaphore_limit: int | None = None


def configure_chat_service(service: ChatService | None) -> None:
    """Set an explicit chat callable for tests or alternate application composition."""

    global _configured_chat_service  # pylint: disable=global-statement
    _configured_chat_service = service


def handle_request(
    request: func.HttpRequest,
    *,
    chat_service: ChatService | None = None,
) -> func.HttpResponse:
    """Route one native Azure Functions request to the published portal API."""

    try:
        config = load_config()
        method = str(request.method or "GET").upper()
        path = _request_path(request)
        claims = _authenticated_claims(request, config)
        if claims is None:
            return _json_response(401, {"error": "Unauthorized"})
        user_id = str(claims.get("sub") or "").strip()
        if not user_id:
            return _json_response(401, {"error": "Unauthorized"})
        return _route(
            request,
            config,
            method,
            path,
            user_id=user_id,
            chat_service=chat_service,
        )
    except ValueError as exc:
        return _json_response(400, {"error": str(exc)})


def _route(
    request: func.HttpRequest,
    config: Config,
    method: str,
    path: str,
    *,
    user_id: str,
    chat_service: ChatService | None,
) -> func.HttpResponse:
    # Preserve the copied route table and its read-only/mutating method boundary.
    if method not in {"GET", "POST", "DELETE"}:
        return _json_response(405, {"error": "Method not allowed"})
    if method == "POST" and path != "/api/chat":
        return _json_response(405, {"error": "Method not allowed"})
    if method == "DELETE" and _chat_session_route(path) is None:
        return _json_response(405, {"error": "Method not allowed"})

    if method == "POST" and path == "/api/chat":
        return _handle_chat_gate(
            config,
            request,
            user_id=user_id,
            chat_service=chat_service,
        )
    if path == "/health":
        return _model_response(HealthResponse, {"status": "ok"})
    if path == "/ready":
        ready = config.PORTAL_ENABLED and bool(config.CASE_INDEX_CONTAINER)
        return _json_response(
            200 if ready else 503,
            {"status": "ready" if ready else "not_ready"},
        )
    if path == "/api/capabilities":
        return _model_response(PortalCapabilitiesResponse, _capabilities(config))
    if path == "/api/diagnostics/chat-readiness":
        return _handle_chat_readiness(config)
    if path == "/api/cases":
        query = request.params or {}
        payload = list_cases(
            config=config,
            cosmos_store=_cosmos_store(config),
            limit=_int_query(query.get("limit")),
            cursor=_case_cursor(query),
        )
        return _model_response(CaseListResponse, payload)

    chat_session_route = _chat_session_route(path)
    if chat_session_route is not None:
        return _handle_chat_session_route(
            config,
            request,
            method,
            chat_session_route,
            user_id=user_id,
        )

    case_id, raw_section = _case_route(path)
    if case_id and raw_section:
        query = request.params or {}
        payload = get_case_raw_section(
            config=config,
            cosmos_store=_cosmos_store(config),
            blob_service=_blob_service(config),
            case_id=case_id,
            section=raw_section,
            offset=_int_query(query.get("offset"), default=0) or 0,
            limit=_int_query(query.get("limit")),
        )
        if payload is None:
            return _json_response(404, {"error": "Case not found"})
        return _model_response(CaseRawSectionResponse, payload)
    if case_id:
        payload = get_case_detail(
            config=config,
            cosmos_store=_cosmos_store(config),
            blob_service=_blob_service(config),
            case_id=case_id,
        )
        if payload is None:
            return _json_response(404, {"error": "Case not found"})
        return _model_response(CaseDetailResponse, payload)
    return _json_response(404, {"error": "Not found"})


def _handle_chat_session_route(
    config: Config,
    request: func.HttpRequest,
    method: str,
    route: str,
    *,
    user_id: str,
) -> func.HttpResponse:
    store = _cosmos_store(config)
    session_id = _chat_session_id(_request_path(request), route)
    if route == "list":
        if method != "GET":
            return _json_response(405, {"error": "Method not allowed"})
        if not config.CASE_QA_CHAT_HISTORY_ENABLED:
            return _model_response(
                ChatSessionsResponse,
                {"history_enabled": False, "items": []},
            )
        try:
            limit = _int_query((request.params or {}).get("limit"), default=50) or 50
            items = list_chat_sessions(
                config=config,
                cosmos_store=store,
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
    try:
        if route == "messages":
            if method != "GET":
                return _json_response(405, {"error": "Method not allowed"})
            payload = get_chat_session_messages(
                config=config,
                cosmos_store=store,
                session_id=session_id,
                user_id=user_id,
            )
            return _model_response(ChatSessionMessagesResponse, payload)
        if route == "delete_session":
            if method != "DELETE":
                return _json_response(405, {"error": "Method not allowed"})
            deleted = delete_chat_session(
                config=config,
                cosmos_store=store,
                session_id=session_id,
                user_id=user_id,
            )
            if not deleted:
                return _json_response(404, {"error": "session_id was not found."})
            return _model_response(
                DeleteChatSessionResponse,
                {"deleted": True, "session_id": session_id},
            )
        if route == "delete_last_turn":
            if method != "DELETE":
                return _json_response(405, {"error": "Method not allowed"})
            expected_count = _int_query(
                (request.params or {}).get("expected_message_count")
            )
            deleted_count = delete_last_chat_turn(
                config=config,
                cosmos_store=store,
                session_id=session_id,
                user_id=user_id,
                expected_message_count=expected_count,
            )
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
    except (ChatSessionNotFoundError, ChatSessionExpiredError, ValueError) as exc:
        return _chat_session_error_response(exc)
    except RuntimeError as exc:
        return _json_response(404, {"error": str(exc)})
    return _json_response(404, {"error": "Not found"})


def _handle_chat_gate(
    config: Config,
    request: func.HttpRequest,
    *,
    user_id: str,
    chat_service: ChatService | None,
) -> func.HttpResponse:
    semaphore = _get_chat_semaphore(config.PORTAL_CHAT_MAX_CONCURRENCY)
    if not semaphore.acquire(blocking=False):
        return _json_response(429, {"error": CHAT_LIMIT_MESSAGE})
    try:
        payload = _json_body(request)
        mode = str(payload.get("mode") or "selected_case").strip()
        if mode not in _SUPPORTED_CHAT_MODES:
            raise ValueError(
                "mode must be one of: " + ", ".join(sorted(_SUPPORTED_CHAT_MODES))
            )
        selected_case_id = _bounded_optional_text(
            payload.get("selected_case_id"),
            "selected_case_id",
            required=True,
        )
        question = str(payload.get("question") or "")
        if not question.strip():
            raise ValueError("question is required")
        if len(question) > config.CASE_QA_MAX_QUESTION_CHARS:
            raise ValueError(
                f"question exceeds {config.CASE_QA_MAX_QUESTION_CHARS} characters"
            )
        session_id = _bounded_optional_text(payload.get("session_id"), "session_id")
        store = _cosmos_store(config)
        if config.CASE_QA_CHAT_HISTORY_ENABLED:
            validate_chat_history_request(
                config=config,
                cosmos_store=store,
                mode=mode,
                selected_case_id=selected_case_id,
                requested_session_id=session_id,
                user_id=user_id,
            )
        prior_transcript = None
        if config.CASE_QA_CHAT_HISTORY_ENABLED and session_id:
            prior_transcript = load_session_transcript(
                config=config,
                cosmos_store=store,
                session_id=session_id,
            )
        service = chat_service or _configured_chat_service or _default_chat_service()
        answer = service(
            selected_case_id=selected_case_id,
            question=question,
            config=config,
            cosmos_store=store,
            blob_store=_blob_service(config),
            user_id=user_id,
            prior_transcript=prior_transcript,
        )
        response_payload = _chat_response_payload(answer)
        if config.CASE_QA_CHAT_HISTORY_ENABLED:
            response_payload["session_id"] = persist_chat_history(
                config=config,
                cosmos_store=store,
                mode=mode,
                question=question,
                selected_case_id=selected_case_id,
                requested_session_id=session_id,
                user_id=user_id,
                response=response_payload,
            )
        return _model_response(ChatResponseModel, response_payload)
    except (ChatSessionNotFoundError, ChatSessionExpiredError) as exc:
        return _chat_session_error_response(exc)
    except ValueError as exc:
        return _chat_session_error_response(exc)
    except LookupError:
        return _json_response(404, {"error": "Case not found"})
    except RuntimeError as exc:
        return _json_response(503, {"error": str(exc)})
    finally:
        semaphore.release()


def _default_chat_service() -> ChatService:
    # The chat implementation is a separately owned module and is loaded only on this route.
    try:
        from .case_chat import answer_portal_chat
    except ImportError as exc:
        raise RuntimeError("Case Q&A service is unavailable.") from exc
    return answer_portal_chat


def _chat_response_payload(answer: Any) -> dict[str, Any]:
    if isinstance(answer, Mapping):
        value = dict(answer)
    else:
        value = {
            "answer": getattr(answer, "answer", ""),
            "answer_status": getattr(answer, "answer_status", ""),
        }
        context_usage = getattr(answer, "context_usage", None)
        if context_usage is not None:
            value["context_usage"] = context_usage
    value["session_id"] = None
    return value


def _chat_session_error_response(exc: BaseException) -> func.HttpResponse:
    if isinstance(exc, ChatSessionNotFoundError):
        return _json_response(404, {"error": str(exc)})
    if isinstance(exc, ChatSessionExpiredError):
        return _json_response(410, {"error": str(exc)})
    message = str(exc)
    if "does not belong to the authenticated user" in message:
        return _json_response(404, {"error": message})
    if "does not match the expected orphan cleanup snapshot" in message:
        return _json_response(409, {"error": message})
    return _json_response(400, {"error": message})


def _get_chat_semaphore(limit: int) -> threading.BoundedSemaphore:
    global _chat_semaphore, _chat_semaphore_limit  # pylint: disable=global-statement
    if _chat_semaphore is None or _chat_semaphore_limit != limit:
        _chat_semaphore = threading.BoundedSemaphore(limit)
        _chat_semaphore_limit = limit
    return _chat_semaphore


def _handle_chat_readiness(config: Config) -> func.HttpResponse:
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
    if all(value == "ready" for value in dependencies.values()):
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
        "model_context_tokens": config.CASE_QA_MODEL_CONTEXT_TOKENS,
        "max_chat_sessions_per_user": config.CASE_QA_MAX_SESSIONS_PER_USER,
        "case_retention_days": config.CASE_RETENTION_DAYS,
        "chat_ready": chat_ready,
        "chat_dependency_status": dependency_status,
        "chat_degraded_reason": degraded_reason,
    }


def _probe_chat_dependencies(config: Config) -> dict[str, str]:
    status = {
        "embeddings": "ready" if config.CASE_EMBED_QUEUE_NAME else "unavailable",
        "archive_retrieval": "unavailable",
        "llm_gateway": "unavailable",
    }
    try:
        _cosmos_store(config).get_case(config.CASE_INDEX_CONTAINER, "__readiness__")
        status["archive_retrieval"] = "ready"
    except Exception:  # Dependency probe must degrade without leaking provider failures.
        pass
    if config.AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT.strip():
        try:
            from .azure_clients import azure_openai_client

            azure_openai_client(config.AZURE_OPENAI_ENDPOINT, config.AZURE_OPENAI_API_VERSION)
            status["llm_gateway"] = "ready"
        except Exception:  # Dependency probe must degrade without leaking provider failures.
            pass
    return status


def _authenticated_claims(
    request: func.HttpRequest,
    config: Config,
) -> dict[str, Any] | None:
    if config.PORTAL_AUTH_MODE == "jwt":
        token = bearer_token_from_headers(dict(request.headers or {}))
        claims = validate_portal_jwt(
            token,
            issuer=config.PORTAL_JWT_ISSUER,
            audience=config.PORTAL_JWT_AUDIENCE,
        )
        if not isinstance(claims, dict) or not str(claims.get("sub") or "").strip():
            return None
        return claims
    if config.PORTAL_AUTH_MODE == "iam":
        claims = _entra_principal_claims(request.headers or {})
        required_role = config.PORTAL_ENTRA_REQUIRED_APP_ROLE.strip()
        roles = claims.get("roles") if claims else None
        if isinstance(roles, str):
            roles = [roles]
        if (
            not claims
            or not str(claims.get("sub") or "").strip()
            or not isinstance(roles, list)
            or required_role not in roles
        ):
            return None
        return claims
    return None


def _entra_principal_claims(headers: Mapping[str, Any]) -> dict[str, Any] | None:
    encoded = _header(headers, "x-ms-client-principal")
    if not encoded:
        return None
    try:
        padding = "=" * (-len(encoded) % 4)
        principal = json.loads(base64.b64decode(encoded + padding).decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeError, ValueError):
        return None
    claim_rows = principal.get("claims") if isinstance(principal, dict) else None
    if not isinstance(claim_rows, list):
        return None
    claims: dict[str, Any] = {}
    roles: list[str] = []
    for row in claim_rows:
        if not isinstance(row, dict):
            continue
        claim_type = str(row.get("typ") or "")
        value = str(row.get("val") or "").strip()
        if claim_type == "sub" and value:
            claims["sub"] = value
        elif claim_type in {"roles", "role"} or claim_type.endswith("/claims/role"):
            if value:
                roles.append(value)
    claims["roles"] = roles
    return claims


def _request_path(request: func.HttpRequest) -> str:
    path = urlsplit(str(request.url or "")).path
    if not path:
        path = "/" + str((request.route_params or {}).get("path") or "")
    return path.rstrip("/") or "/"


def _case_route(path: str) -> tuple[str | None, str | None]:
    prefix = "/api/cases/"
    if not path.startswith(prefix):
        return None, None
    parts = path[len(prefix) :].strip("/").split("/")
    if len(parts) == 1 and _valid_path_component(parts[0]):
        return parts[0], None
    if (
        len(parts) == 3
        and _valid_path_component(parts[0])
        and parts[1] == "raw"
        and parts[2] in {"alert_payload", "analysis"}
    ):
        return parts[0], parts[2]
    return None, None


def _chat_session_route(path: str) -> str | None:
    if path == "/api/chat/sessions":
        return "list"
    prefix = "/api/chat/sessions/"
    if not path.startswith(prefix):
        return None
    parts = path[len(prefix) :].strip("/").split("/")
    if len(parts) == 1 and _valid_path_component(parts[0]):
        return "delete_session"
    if len(parts) == 2 and _valid_path_component(parts[0]) and parts[1] == "messages":
        return "messages"
    if (
        len(parts) == 3
        and _valid_path_component(parts[0])
        and parts[1:] == ["turns", "last"]
    ):
        return "delete_last_turn"
    return None


def _chat_session_id(path: str, route: str) -> str | None:
    if route == "list":
        return None
    return path[len("/api/chat/sessions/") :].strip("/").split("/")[0] or None


def _valid_path_component(value: str) -> bool:
    return bool(value) and len(value) <= _MAX_PATH_COMPONENT_CHARS


def _case_cursor(query: Mapping[str, Any]) -> str | None:
    opaque = str(query.get("cursor") or "").strip()
    processed_at = str(query.get("cursor_processed_at") or "").strip()
    case_id = str(query.get("cursor_case_id") or "").strip()
    if opaque and (processed_at or case_id):
        raise ValueError("Use either cursor or cursor_processed_at/cursor_case_id, not both.")
    if bool(processed_at) != bool(case_id):
        raise ValueError("cursor_processed_at and cursor_case_id must be provided together.")
    if processed_at or case_id:
        if (
            len(processed_at) > _MAX_CURSOR_COMPONENT_CHARS
            or len(case_id) > _MAX_CURSOR_COMPONENT_CHARS
        ):
            raise ValueError("case cursor is invalid")
        return base64.urlsafe_b64encode(
            json.dumps({"processed_at": processed_at, "case_id": case_id}).encode("utf-8")
        ).decode("ascii")
    if len(opaque) > 1_024:
        raise ValueError("case cursor is invalid")
    return opaque or None


def _int_query(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("query parameter must be an integer") from exc
    if parsed < 0:
        raise ValueError("query parameter must be non-negative")
    return parsed


def _json_body(request: func.HttpRequest) -> dict[str, Any]:
    content_length = _header(request.headers or {}, "content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if declared_length < 0:
            raise ValueError("Content-Length must be non-negative")
        if declared_length > _MAX_REQUEST_BODY_BYTES:
            raise ValueError("request body is too large")
    raw = request.get_body() or b"{}"
    if len(raw) > _MAX_REQUEST_BODY_BYTES:
        raise ValueError("request body is too large")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("request body must be JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _bounded_optional_text(
    value: Any,
    name: str,
    *,
    required: bool = False,
) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        if required:
            raise ValueError(f"{name} is required")
        return None
    if len(normalized) > _MAX_PATH_COMPONENT_CHARS:
        raise ValueError(f"{name} is too long")
    return normalized


def _header(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name:
            return str(value or "").strip()
    return ""


def _cosmos_store(config: Config) -> CosmosStore:
    return CosmosStore.from_config(config)


def _blob_service(config: Config) -> Any:
    from .azure_clients import blob_service_client

    return blob_service_client(config.OUTPUT_STORAGE_ACCOUNT_URL)


def _model_response(model: Any, payload: Any) -> func.HttpResponse:
    validated = portal_response(model, payload).model_dump(mode="json")
    return _json_response(200, validated)


def _json_response(status_code: int, payload: dict[str, Any]) -> func.HttpResponse:
    # Same-origin production contract: intentionally no Access-Control-* headers.
    return func.HttpResponse(
        body=json.dumps(payload, default=str),
        status_code=status_code,
        headers={"content-type": "application/json"},
        mimetype="application/json",
        charset="utf-8",
    )
