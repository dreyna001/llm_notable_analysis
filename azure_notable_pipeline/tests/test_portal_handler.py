"""Native Azure HTTP tests for the analyst portal route boundary."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any

import azure.functions as func
import pytest

from azure_notable_pipeline import portal_handler
from azure_notable_pipeline.config import Config


class FakeCosmosStore:
    def list_cases(self, _container: str, *, limit: int, before=None):
        rows = [
            {
                "case_id": "case-1",
                "processed_at": "2026-07-13T12:00:00Z",
                "expires_at": "2026-08-13T12:00:00Z",
                "verdict": "likely_true_positive",
                "confidence": 0.8,
                "search_name": "Suspicious Login",
                "retrieval_status": "ready",
                "source_completeness": "complete",
            }
        ]
        return rows[:limit]

    def get_case(self, _container: str, _case_id: str):
        return None


def portal_config(**overrides: Any) -> Config:
    values: dict[str, Any] = {
        "PORTAL_ENABLED": True,
        "PORTAL_AUTH_MODE": "jwt",
        "PORTAL_JWT_ISSUER": "https://issuer.example.test",
        "PORTAL_JWT_AUDIENCE": "portal",
        "CASE_INDEX_CONTAINER": "case-index",
        "CASE_ARCHIVE_CONTAINER": "output",
        "OUTPUT_STORAGE_ACCOUNT_URL": "https://output.blob.core.windows.net",
        "COSMOS_ENDPOINT": "https://cosmos.example.test",
        "COSMOS_DATABASE_NAME": "notable",
    }
    values.update(overrides)
    return Config(**values)


def request(
    path: str,
    method: str = "GET",
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    body: bytes | None = None,
) -> func.HttpRequest:
    merged_headers = {"Authorization": "Bearer test-token", **(headers or {})}
    return func.HttpRequest(
        method=method,
        url=f"https://portal.example.test{path}",
        headers=merged_headers,
        params=params or {},
        route_params={"path": path.lstrip("/")},
        body=body,
    )


def response_json(response: func.HttpResponse) -> dict[str, Any]:
    return json.loads(response.get_body())


@pytest.fixture(autouse=True)
def reset_handler(monkeypatch):
    portal_handler.configure_chat_service(None)
    portal_handler._chat_semaphore = None
    portal_handler._chat_semaphore_limit = None
    monkeypatch.setattr(portal_handler, "load_config", lambda: portal_config())
    monkeypatch.setattr(portal_handler, "_cosmos_store", lambda _config: FakeCosmosStore())
    monkeypatch.setattr(portal_handler, "_blob_service", lambda _config: object())
    monkeypatch.setattr(
        portal_handler,
        "validate_portal_jwt",
        lambda *_args, **_kwargs: {
            "iss": "https://issuer.example.test",
            "aud": "portal",
            "sub": "user-1",
        },
    )


def test_native_request_returns_native_response_and_case_contract() -> None:
    response = portal_handler.handle_request(request("/api/cases"))

    assert isinstance(response, func.HttpResponse)
    assert response.status_code == 200
    assert response_json(response)["items"][0]["case_id"] == "case-1"


@pytest.mark.parametrize("path", ["/health", "/ready", "/api/cases"])
def test_every_route_requires_authentication(monkeypatch, path: str) -> None:
    monkeypatch.setattr(portal_handler, "validate_portal_jwt", lambda *_a, **_k: None)

    response = portal_handler.handle_request(request(path, headers={"Authorization": ""}))

    assert response.status_code == 401


def test_missing_subject_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        portal_handler,
        "validate_portal_jwt",
        lambda *_a, **_k: {"iss": "https://issuer.example.test", "aud": "portal"},
    )

    assert portal_handler.handle_request(request("/health")).status_code == 401


def test_entra_mode_requires_role_and_subject(monkeypatch) -> None:
    config = portal_config(
        PORTAL_AUTH_MODE="iam",
        PORTAL_JWT_ISSUER="",
        PORTAL_JWT_AUDIENCE="",
        PORTAL_ENTRA_REQUIRED_APP_ROLE="Case.Reader",
    )
    monkeypatch.setattr(portal_handler, "load_config", lambda: config)

    def principal(claims: list[dict[str, str]]) -> str:
        return base64.b64encode(json.dumps({"claims": claims}).encode()).decode()

    denied = request(
        "/health",
        headers={
            "x-ms-client-principal": principal(
                [{"typ": "sub", "val": "user-1"}]
            )
        },
    )
    allowed = request(
        "/health",
        headers={
            "x-ms-client-principal": principal(
                [
                    {"typ": "sub", "val": "user-1"},
                    {"typ": "roles", "val": "Case.Reader"},
                ]
            )
        },
    )

    assert portal_handler.handle_request(denied).status_code == 401
    assert portal_handler.handle_request(allowed).status_code == 200


def test_same_origin_responses_emit_no_cors_headers() -> None:
    response = portal_handler.handle_request(
        request("/api/cases", headers={"Origin": "https://evil.example.test"})
    )

    assert response.status_code == 200
    assert not any(
        key.lower().startswith("access-control-")
        for key, _value in response.headers
    )


def test_options_is_authenticated_then_rejected() -> None:
    response = portal_handler.handle_request(request("/health", "OPTIONS"))
    assert response.status_code == 405


def test_case_pagination_query_is_bounded_and_uses_public_keyset(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_list_cases(**kwargs):
        captured.update(kwargs)
        return {"items": [], "limit": 50, "has_more": False, "next_cursor": None}

    monkeypatch.setattr(portal_handler, "list_cases", fake_list_cases)
    response = portal_handler.handle_request(
        request(
            "/api/cases",
            params={
                "limit": "999999",
                "cursor_processed_at": "2026-07-13T12:00:00Z",
                "cursor_case_id": "case-1",
            },
        )
    )

    assert response.status_code == 200
    assert captured["limit"] == 999999
    decoded = json.loads(base64.urlsafe_b64decode(captured["cursor"]))
    assert decoded == {
        "processed_at": "2026-07-13T12:00:00Z",
        "case_id": "case-1",
    }


def test_partial_cursor_and_invalid_integer_are_rejected() -> None:
    partial = portal_handler.handle_request(
        request("/api/cases", params={"cursor_processed_at": "2026-07-13T12:00:00Z"})
    )
    invalid = portal_handler.handle_request(
        request("/api/cases", params={"limit": "many"})
    )

    assert partial.status_code == 400
    assert invalid.status_code == 400


def test_chat_body_size_limit_is_enforced() -> None:
    response = portal_handler.handle_request(
        request("/api/chat", "POST", body=b"{" + b"x" * 65_536 + b"}")
    )

    assert response.status_code == 400
    assert "too large" in response_json(response)["error"]


def test_chat_service_seam_receives_native_dependencies_and_user(monkeypatch) -> None:
    config = portal_config(CASE_QA_ENABLED=True, CASE_EMBED_QUEUE_NAME="case-embed")
    monkeypatch.setattr(portal_handler, "load_config", lambda: config)
    captured: dict[str, Any] = {}

    def chat_service(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            answer="The archived case indicates suspicious activity.",
            answer_status="answered",
            context_usage=None,
        )

    response = portal_handler.handle_request(
        request(
            "/api/chat",
            "POST",
            body=json.dumps(
                {
                    "mode": "selected_case",
                    "selected_case_id": "case-1",
                    "question": "What happened?",
                }
            ).encode(),
        ),
        chat_service=chat_service,
    )

    assert response.status_code == 200
    assert captured["user_id"] == "user-1"
    assert captured["selected_case_id"] == "case-1"
    assert captured["cosmos_store"].__class__ is FakeCosmosStore
    assert response_json(response)["answer_status"] == "answered"


def test_chat_history_ownership_failure_is_hidden_as_not_found(monkeypatch) -> None:
    config = portal_config(
        CASE_QA_CHAT_HISTORY_ENABLED=True,
        CHAT_SESSIONS_CONTAINER="chat-sessions",
        CHAT_MESSAGES_CONTAINER="chat-messages",
    )
    monkeypatch.setattr(portal_handler, "load_config", lambda: config)
    monkeypatch.setattr(
        portal_handler,
        "delete_chat_session",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("session_id does not belong to the authenticated user.")
        ),
    )

    response = portal_handler.handle_request(
        request("/api/chat/sessions/00000000-0000-0000-0000-000000000001", "DELETE")
    )

    assert response.status_code == 404


def test_case_routes_pass_native_cosmos_and_blob_boundaries(monkeypatch) -> None:
    store = FakeCosmosStore()
    blob = object()
    captured: dict[str, Any] = {}
    monkeypatch.setattr(portal_handler, "_cosmos_store", lambda _config: store)
    monkeypatch.setattr(portal_handler, "_blob_service", lambda _config: blob)

    def fake_detail(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(portal_handler, "get_case_detail", fake_detail)

    response = portal_handler.handle_request(request("/api/cases/case-1"))

    assert response.status_code == 404
    assert captured["cosmos_store"] is store
    assert captured["blob_service"] is blob
    assert "dynamodb_client" not in captured
    assert "s3_client" not in captured
