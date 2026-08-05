"""Read-only analyst portal API Lambda handler."""

from __future__ import annotations

import copy
import base64
import json
import os
import re
import threading
from typing import Any

from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from .aws_clients import aws_client, bedrock_runtime_client, dynamodb_client, s3_client
from .case_chat import answer_selected_case_question
from .case_chat_history import (
    ChatSessionExpiredError,
    ChatSessionNotFoundError,
    delete_chat_session,
    delete_last_chat_turn,
    get_chat_session_messages,
    list_chat_sessions,
    load_session_transcript,
    get_idempotent_chat_response,
    persist_chat_history,
    validate_chat_history_request,
)
from .case_index import get_case_detail, get_case_raw_section, list_cases
from .config import Config, load_config
from .opensearch_retrieval import adapter_for
from .portal_chat import conversation_history_from_config
from .portal_jwt import (
    portal_claims_authorized,
    resolve_portal_jwt_claims,
    resolve_portal_user_id,
)
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
_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_STATIC_ASSET_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}$")


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
    if path.startswith("/api/") and not bool(getattr(config, "PORTAL_ENABLED", False)):
        return _json_response(404, {"error": "Not found"})
    if method == "GET" and path not in {"/health", "/ready"} and not path.startswith("/api"):
        return _handle_static_asset(config, path)
    if path not in {"/health", "/ready"} and not _is_authenticated(event, config):
        return _json_response(
            403 if _has_authenticated_identity(event, config) else 401,
            {"error": "Forbidden" if _has_authenticated_identity(event, config) else "Unauthorized"},
        )

    if method == "POST" and path == "/api/chat":
        return _handle_chat_gate(config, event)
    if path == "/health":
        return _model_response(HealthResponse, {"status": "ok"})
    if path == "/ready":
        return _handle_readiness(config)
    if path == "/api/capabilities":
        return _model_response(PortalCapabilitiesResponse, _capabilities(config))
    if path == "/api/diagnostics/chat-readiness":
        return _handle_chat_readiness(config)
    if path == "/api/cases":
        query = event.get("queryStringParameters") or {}
        try:
            payload = list_cases(
                config=config,
                dynamodb_client=dynamodb_client(),
                limit=_int_query(query.get("limit"), strict=True),
                cursor=query.get("cursor"),
                cursor_processed_at=query.get("cursor_processed_at"),
                cursor_case_id=query.get("cursor_case_id"),
                start=query.get("start"),
                end=query.get("end"),
                start_date=query.get("start_date"),
                end_date=query.get("end_date"),
                verdict=query.get("verdict"),
                search_name=query.get("search_name"),
            )
        except ValueError as exc:
            return _json_response(400, {"error": str(exc)})
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


def _handle_static_asset(config: Config, path: str) -> dict[str, Any]:
    """Serve bounded SPA assets from the private portal bucket."""

    bucket = _optional_setting(config, "PORTAL_UI_BUCKET")
    if not bucket:
        return _json_response(404, {"error": "Not found"})
    requested = path.lstrip("/")
    key = "index.html" if not requested or "." not in requested.rsplit("/", 1)[-1] else requested
    if not _STATIC_ASSET_KEY_RE.fullmatch(key) or ".." in key.split("/"):
        return _json_response(404, {"error": "Not found"})
    try:
        response = s3_client().get_object(Bucket=bucket, Key=key)
        body = response.get("Body")
        payload = body.read() if hasattr(body, "read") else body
        if not isinstance(payload, bytes):
            raise ValueError("portal asset body is not bytes")
        max_bytes = int(_optional_setting(config, "PORTAL_UI_MAX_ASSET_BYTES") or 5_242_880)
        if len(payload) > max_bytes:
            return _json_response(413, {"error": "Portal asset is too large"})
    except Exception:  # noqa: BLE001 - do not expose S3 details on the public asset route.
        return _json_response(404, {"error": "Not found"})
    content_type = str(response.get("ContentType") or "application/octet-stream")
    cache_control = "no-cache" if key == "index.html" else "public,max-age=31536000,immutable"
    return {
        "statusCode": 200,
        "headers": {
            "content-type": content_type,
            "cache-control": cache_control,
            # style-src/font-src allow the "Federal SOC Dark" Google Fonts import
            # (Public Sans / Roboto Mono) in frontend/analyst-portal/src/index.css.
            "content-security-policy": "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self'",
            "x-content-type-options": "nosniff",
        },
        "isBase64Encoded": True,
        "body": base64.b64encode(payload).decode("ascii"),
    }


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
        if not selected_case_id:
            raise ValueError("selected_case_id is required")
        session_id = request.get("session_id")
        session_id = str(session_id).strip() if session_id else None
        question = str(request.get("question") or "")
        if not question.strip():
            raise ValueError("question is required")
        if len(question) > config.CASE_QA_MAX_QUESTION_CHARS:
            raise ValueError(
                f"question exceeds {config.CASE_QA_MAX_QUESTION_CHARS} characters"
            )
        client_request_id = request.get("client_request_id")
        client_request_id = (
            str(client_request_id).strip() if client_request_id is not None else None
        )
        if client_request_id and not _CLIENT_REQUEST_ID_RE.fullmatch(client_request_id):
            raise ValueError("client_request_id must be 8-128 URL-safe characters")
        if client_request_id and not config.CASE_QA_CHAT_HISTORY_ENABLED:
            raise ValueError("client_request_id requires chat history to be enabled")
        user_id = resolve_portal_user_id(event, config)
        if config.CASE_QA_CHAT_HISTORY_ENABLED:
            if client_request_id:
                replay = get_idempotent_chat_response(
                    config=config,
                    dynamodb_client=dynamodb_client(),
                    mode=mode,
                    selected_case_id=selected_case_id,
                    question=question,
                    requested_session_id=session_id,
                    user_id=user_id,
                    client_request_id=client_request_id,
                )
                if replay is not None:
                    return _model_response(ChatResponseModel, replay)
            validate_chat_history_request(
                config=config,
                dynamodb_client=dynamodb_client(),
                mode=mode,
                selected_case_id=selected_case_id,
                requested_session_id=session_id,
                user_id=user_id,
            )
        conversation_history = None
        if config.CASE_QA_CHAT_HISTORY_ENABLED and session_id:
            conversation_history = conversation_history_from_config(
                config,
                load_session_transcript(
                    config=config,
                    dynamodb_client=dynamodb_client(),
                    session_id=session_id,
                ),
            )
        answer = answer_selected_case_question(
            case_id=str(selected_case_id or ""),
            question=question,
            config=config,
            dynamodb_client=dynamodb_client(),
            s3_client=s3_client(),
            bedrock_client=bedrock_runtime_client(),
            conversation_history=conversation_history,
        )
        response_payload: dict[str, Any] = {
            "answer": answer.answer,
            "answer_status": answer.answer_status,
            "session_id": None,
        }
        if answer.context_usage is not None:
            response_payload["context_usage"] = answer.context_usage
        if config.CASE_QA_CHAT_HISTORY_ENABLED:
            try:
                response_payload["session_id"] = persist_chat_history(
                    config=config,
                    dynamodb_client=dynamodb_client(),
                    mode=mode,
                    question=question,
                    selected_case_id=selected_case_id,
                    requested_session_id=session_id,
                    user_id=user_id,
                    response=response_payload,
                    client_request_id=client_request_id,
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


def _handle_readiness(config: Config) -> dict[str, Any]:
    """Probe required portal dependencies without mutating them."""

    if not bool(getattr(config, "PORTAL_ENABLED", False)):
        return _json_response(
            503,
            {"status": "not_ready", "reason": "Portal is disabled."},
        )
    dependencies = _probe_portal_dependencies(config)
    ready = all(value == "ready" for value in dependencies.values())
    payload: dict[str, Any] = {
        "status": "ready" if ready else "not_ready",
        "dependencies": dependencies,
    }
    if not ready:
        payload["reason"] = "One or more portal dependencies are unavailable."
    return _json_response(200 if ready else 503, payload)


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
        "embeddings": (
            "ready"
            if config.CASE_EMBED_QUEUE_URL or config.CASE_EMBED_LAMBDA_NAME
            else "unavailable"
        ),
        "archive_retrieval": "unavailable",
        "llm_gateway": "unavailable",
    }
    try:
        _bounded_aws_client(config, "dynamodb").describe_table(TableName=config.CASE_INDEX_TABLE)
        status["archive_retrieval"] = "ready"
    except Exception:
        status["archive_retrieval"] = "unavailable"
    model_id = (config.PORTAL_CHAT_BEDROCK_MODEL_ID or config.BEDROCK_MODEL_ID).strip()
    if model_id:
        try:
            client = _bounded_aws_client(config, "bedrock-runtime")
            try:
                client.count_tokens(
                    modelId=model_id,
                    input={
                        "converse": {
                            "messages": [
                                {"role": "user", "content": [{"text": "readiness"}]}
                            ]
                        }
                    },
                )
            except ClientError as exc:
                error = exc.response.get("Error", {})
                message = str(error.get("Message", "")).lower()
                if error.get("Code") != "ValidationException" or not any(
                    marker in message
                    for marker in ("not supported", "does not support", "unsupported")
                ):
                    raise
                client.converse(
                    modelId=model_id,
                    messages=[{"role": "user", "content": [{"text": "readiness"}]}],
                    inferenceConfig={"maxTokens": 1, "temperature": 0},
                )
            status["llm_gateway"] = "ready"
        except Exception:
            status["llm_gateway"] = "unavailable"
    return status


def _probe_portal_dependencies(config: Config) -> dict[str, str]:
    """Run bounded, read-only probes for the portal's durable dependencies."""

    status = {
        "case_index": "unavailable",
        "archive": "unavailable",
    }
    if config.CASE_QA_ENABLED:
        status["opensearch"] = "unavailable"
    if config.CASE_QA_CHAT_HISTORY_ENABLED:
        status["chat_sessions"] = "unavailable"
        status["chat_messages"] = "unavailable"
    try:
        if not str(getattr(config, "CASE_INDEX_TABLE", "")).strip():
            raise ValueError("CASE_INDEX_TABLE is not configured")
        ddb = _bounded_aws_client(config, "dynamodb")
        ddb.describe_table(TableName=config.CASE_INDEX_TABLE)
        status["case_index"] = "ready"
    except Exception:  # noqa: BLE001 - readiness must fail closed on probe errors.
        status["case_index"] = "unavailable"

    try:
        bucket = str(getattr(config, "CASE_ARCHIVE_BUCKET", "")).strip()
        if not bucket:
            raise ValueError("CASE_ARCHIVE_BUCKET is not configured")
        prefix = str(getattr(config, "CASE_ARCHIVE_PREFIX", "cases")).strip("/")
        _bounded_aws_client(config, "s3").list_objects_v2(
            Bucket=bucket,
            Prefix=f"{prefix}/" if prefix else "",
            MaxKeys=1,
        )
        status["archive"] = "ready"
    except Exception:  # noqa: BLE001 - readiness must fail closed on probe errors.
        status["archive"] = "unavailable"

    if config.CASE_QA_ENABLED and str(getattr(config, "OPENSEARCH_ENDPOINT", "")).strip():
        try:
            probe_config = copy.copy(config)
            probe_config.OPENSEARCH_TIMEOUT_SECONDS = _readiness_timeout(config)
            adapter_for(probe_config).request("GET", "/_cluster/health")
            status["opensearch"] = "ready"
        except Exception:  # noqa: BLE001 - readiness must fail closed on probe errors.
            status["opensearch"] = "unavailable"
    if config.CASE_QA_CHAT_HISTORY_ENABLED:
        for status_key, table_name in (
            ("chat_sessions", config.CHAT_SESSIONS_TABLE),
            ("chat_messages", config.CHAT_MESSAGES_TABLE),
        ):
            try:
                if not str(table_name).strip():
                    raise ValueError(f"{status_key} table is not configured")
                _bounded_aws_client(config, "dynamodb").describe_table(TableName=table_name)
                status[status_key] = "ready"
            except Exception:  # noqa: BLE001 - readiness must fail closed on probe errors.
                status[status_key] = "unavailable"
    return status


def _bounded_aws_client(config: Config, service_name: str) -> Any:
    timeout = _readiness_timeout(config)
    return aws_client(
        service_name,
        config=BotoConfig(
            connect_timeout=timeout,
            read_timeout=timeout,
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )


def _readiness_timeout(config: Config) -> int:
    raw = _optional_setting(config, "PORTAL_READINESS_TIMEOUT_SECONDS") or "2"
    try:
        return max(1, min(int(raw), 10))
    except ValueError:
        return 2


def _is_authenticated(event: dict[str, Any], config: Config) -> bool:
    if config.PORTAL_AUTH_MODE == "jwt":
        claims = resolve_portal_jwt_claims(event, config)
        return claims is not None and portal_claims_authorized(claims, config)
    if config.PORTAL_AUTH_MODE == "iam":
        authorizer = ((event.get("requestContext") or {}).get("authorizer") or {})
        return bool(authorizer.get("iam"))
    return False


def _has_authenticated_identity(event: dict[str, Any], config: Config) -> bool:
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


def _int_query(
    value: Any,
    default: int | None = None,
    *,
    strict: bool = False,
) -> int | None:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
        if strict and parsed <= 0:
            raise ValueError("query integer must be positive")
        return parsed
    except (TypeError, ValueError):
        if strict:
            raise ValueError("query integer must be a positive integer") from None
        return default


def _optional_setting(config: Config, name: str) -> str:
    if hasattr(config, name):
        return str(getattr(config, name) or "").strip()
    return os.getenv(name, "").strip()


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
