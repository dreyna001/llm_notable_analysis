"""Tests for the AWS portal API Lambda handler."""

from __future__ import annotations

import base64
import io
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline import portal_handler
from s3_notable_pipeline.case_chat_history import ChatSessionNotFoundError


class FakeDynamoDbClient:
    """Fake DynamoDB client for portal handler tests."""

    def query(self, **_kwargs):
        return {"Items": [ddb_case_item()]}

    def get_item(self, **_kwargs):
        return {"Item": ddb_case_item()}

    def describe_table(self, **_kwargs):
        return {"Table": {"TableName": "case-index"}}


class FakeS3Client:
    """Fake S3 client for portal handler tests."""

    def list_objects_v2(self, **kwargs):
        return {
            "Contents": [{"Key": f"{kwargs['Prefix']}chunk-1.json"}],
            "IsTruncated": False,
        }

    def get_object(self, **kwargs):
        import io

        if str(kwargs.get("Key", "")).startswith("case_chunks/"):
            chunk = {
                "case_id": "case-1",
                "chunk_id": "chunk-1",
                "search_text": "alert.summary $ suspicious login",
                "embedding": [0.01] * 1024,
            }
            return {"Body": io.BytesIO(json.dumps(chunk).encode("utf-8"))}
        return {"Body": io.BytesIO(json.dumps(case_envelope()).encode("utf-8"))}


class FakeBedrockClient:
    """Fake Bedrock client for chat synthesis and Titan embeddings."""

    dimensions = 1024

    def invoke_model(self, **_kwargs):
        import io

        body = json.dumps({"embedding": [0.01] * self.dimensions}).encode("utf-8")
        return {"body": io.BytesIO(body)}

    def converse(self, **_kwargs):
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": (
                                "The login was suspicious based on the archived case chunk."
                            )
                        }
                    ]
                }
            }
        }

    def count_tokens(self, **_kwargs):
        return {"inputTokens": 1}


def ddb_case_item():
    """Return a low-level CaseIndex item."""

    return {
        "case_id": {"S": "case-1"},
        "processed_at": {"S": "2026-06-15T10:30:00Z"},
        "processed_at_case_id": {"S": "2026-06-15T10:30:00Z#case-1"},
        "expires_at": {"S": "2026-07-15T10:30:00Z"},
        "verdict": {"S": "likely_true_positive"},
        "confidence": {"S": "0.8"},
        "search_name": {"S": "Suspicious Login"},
        "retrieval_status": {"S": "ready"},
        "source_completeness": {"S": "complete"},
        "case_envelope_key": {"S": "cases/2026/06/15/case-1.json"},
    }


def case_envelope():
    """Return an archived case envelope."""

    return {
        "case_id": "case-1",
        "artifacts": {"report_markdown_key": "reports/case-1.md"},
        "alert_payload": {"finding_id": "finding-1", "user": "alice"},
        "analysis": {"alert_reconciliation": {"verdict": "likely_true_positive"}},
    }


def portal_config(**overrides):
    """Return a valid portal config."""

    values = {
        "PORTAL_ENABLED": True,
        "PORTAL_AUTH_MODE": "jwt",
        "PORTAL_JWT_ISSUER": "https://issuer.example.test",
        "PORTAL_JWT_AUDIENCE": "portal",
        "PORTAL_REQUIRED_ANALYST_ROLE": "Case.Reader",
        "CASE_ARCHIVE_BUCKET": "case-bucket",
        "CASE_ARCHIVE_CHUNKS_PREFIX": "case_chunks",
        "CASE_INDEX_TABLE": "case-index",
        "BEDROCK_MODEL_ID": "anthropic.test",
    }
    values.update(overrides)
    return Config(**values)


def event(path: str, method: str = "GET"):
    """Build an authenticated HTTP API event."""

    return {
        "rawPath": path,
        "requestContext": {
            "http": {"method": method},
            "authorizer": {
                "jwt": {
                    "claims": {
                        "iss": "https://issuer.example.test",
                        "aud": "portal",
                        "sub": "user-1",
                        "roles": ["Case.Reader"],
                    }
                }
            },
        },
        "queryStringParameters": {},
    }


class PortalHandlerTests(unittest.TestCase):
    """Portal handler behavior tests."""

    def setUp(self) -> None:
        portal_handler._chat_semaphore = None  # pylint: disable=protected-access
        portal_handler._chat_semaphore_limit = None  # pylint: disable=protected-access

    def test_unauthenticated_request_fails_closed(self) -> None:
        with patch.object(portal_handler, "load_config", return_value=portal_config()):
            response = portal_handler.handler({"rawPath": "/api/cases"}, None)

        self.assertEqual(response["statusCode"], 401)

    def test_disabled_portal_rejects_protected_routes(self) -> None:
        with patch.object(
            portal_handler,
            "load_config",
            return_value=portal_config(PORTAL_ENABLED=False),
        ):
            response = portal_handler.handler(event("/api/cases"), None)

        self.assertEqual(response["statusCode"], 404)

    def test_static_spa_asset_is_served_from_private_bucket_without_auth(self) -> None:
        class StaticS3:
            def get_object(self, **kwargs):
                self.request = kwargs
                return {
                    "Body": io.BytesIO(b"<html>portal</html>"),
                    "ContentType": "text/html",
                }

        s3 = StaticS3()
        with (
            patch.dict("os.environ", {"PORTAL_UI_BUCKET": "portal-ui"}),
            patch.object(portal_handler, "load_config", return_value=portal_config()),
            patch.object(portal_handler, "s3_client", return_value=s3),
        ):
            response = portal_handler.handler({"rawPath": "/", "requestContext": {"http": {"method": "GET"}}}, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(response["isBase64Encoded"])
        self.assertEqual(base64.b64decode(response["body"]), b"<html>portal</html>")
        self.assertEqual(s3.request, {"Bucket": "portal-ui", "Key": "index.html"})

    def test_bearer_jwt_without_analyst_grant_is_rejected(self) -> None:
        request = {
            "rawPath": "/api/cases",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {"Authorization": "Bearer test-token"},
        }
        with (
            patch.object(portal_handler, "load_config", return_value=portal_config()),
            patch.object(
                portal_handler,
                "resolve_portal_jwt_claims",
                return_value={
                    "iss": "https://issuer.example.test",
                    "aud": "portal",
                    "sub": "user-1",
                },
            ),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
        ):
            response = portal_handler.handler(request, None)

        self.assertEqual(response["statusCode"], 403)

    def test_mutating_method_is_rejected(self) -> None:
        with patch.object(portal_handler, "load_config", return_value=portal_config()):
            response = portal_handler.handler(event("/api/cases/case-1", "DELETE"), None)

        self.assertEqual(response["statusCode"], 405)

    def test_case_list_route_returns_valid_response(self) -> None:
        with (
            patch.object(portal_handler, "load_config", return_value=portal_config()),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
        ):
            response = portal_handler.handler(event("/api/cases"), None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["items"][0]["case_id"], "case-1")

    def test_allowed_cors_origin_is_returned_on_api_response(self) -> None:
        request = event("/api/cases")
        request["headers"] = {"origin": "https://portal.example.test"}
        with (
            patch.object(
                portal_handler,
                "load_config",
                return_value=portal_config(
                    PORTAL_CORS_ALLOWED_ORIGINS="https://portal.example.test"
                ),
            ),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
        ):
            response = portal_handler.handler(request, None)

        self.assertEqual(
            response["headers"]["access-control-allow-origin"],
            "https://portal.example.test",
        )

    def test_options_preflight_uses_cors_allowlist(self) -> None:
        request = event("/api/chat", "OPTIONS")
        request["headers"] = {"Origin": "https://portal.example.test"}
        with patch.object(
            portal_handler,
            "load_config",
            return_value=portal_config(
                PORTAL_CORS_ALLOWED_ORIGINS="https://portal.example.test"
            ),
        ):
            response = portal_handler.handler(request, None)

        self.assertEqual(response["statusCode"], 204)
        self.assertEqual(
            response["headers"]["access-control-allow-origin"],
            "https://portal.example.test",
        )

    def test_case_detail_and_raw_routes_return_bounded_responses(self) -> None:
        with (
            patch.object(portal_handler, "load_config", return_value=portal_config()),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
            patch.object(portal_handler, "s3_client", return_value=FakeS3Client()),
        ):
            detail = portal_handler.handler(event("/api/cases/case-1"), None)
            raw = portal_handler.handler(event("/api/cases/case-1/raw/alert_payload"), None)

        self.assertEqual(detail["statusCode"], 200)
        self.assertEqual(raw["statusCode"], 200)
        self.assertEqual(json.loads(raw["body"])["items"]["user"], "alice")

    def test_capabilities_probe_reports_chat_ready(self) -> None:
        config = portal_config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            CASE_QA_ENABLED=True,
            CASE_EMBED_LAMBDA_NAME="notable-case-embed",
        )
        with (
            patch.object(portal_handler, "load_config", return_value=config),
            patch.object(
                portal_handler,
                "_bounded_aws_client",
                side_effect=lambda _config, service: (
                    FakeBedrockClient() if service == "bedrock-runtime" else FakeDynamoDbClient()
                ),
            ),
        ):
            response = portal_handler.handler(event("/api/capabilities"), None)

        body = json.loads(response["body"])
        self.assertTrue(body["chat_ready"])
        self.assertEqual(body["chat_dependency_status"]["embeddings"], "ready")
        self.assertFalse(body["chat_images_enabled"])
        self.assertEqual(body["max_chat_images"], 1)
        self.assertEqual(body["max_chat_image_bytes"], 750_000)

    def test_chat_rejects_images_when_feature_disabled(self) -> None:
        with patch.object(
            portal_handler,
            "load_config",
            return_value=portal_config(
                CASE_QA_ENABLED=True,
                CASE_EMBED_LAMBDA_NAME="notable-case-embed",
            ),
        ):
            request = event("/api/chat", "POST")
            request["body"] = json.dumps(
                {
                    "mode": "selected_case",
                    "selected_case_id": "case-1",
                    "question": "What is in this screenshot?",
                    "images": [
                        {
                            "media_type": "image/png",
                            "data_base64": "aGVsbG8=",
                        }
                    ],
                }
            )
            response = portal_handler.handler(request, None)

        self.assertEqual(response["statusCode"], 400)
        self.assertIn("Chat images are not enabled", json.loads(response["body"])["error"])

    def test_chat_readiness_returns_ready_when_dependencies_available(self) -> None:
        config = portal_config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            CASE_QA_ENABLED=True,
            CASE_EMBED_LAMBDA_NAME="notable-case-embed",
        )
        with (
            patch.object(portal_handler, "load_config", return_value=config),
            patch.object(
                portal_handler,
                "_bounded_aws_client",
                side_effect=lambda _config, service: (
                    FakeBedrockClient() if service == "bedrock-runtime" else FakeDynamoDbClient()
                ),
            ),
        ):
            response = portal_handler.handler(
                event("/api/diagnostics/chat-readiness"),
                None,
            )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), {"status": "ready"})

    def test_chat_readiness_falls_back_when_count_tokens_is_unsupported(self) -> None:
        bedrock = FakeBedrockClient()
        unsupported = ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": "CountTokens is not supported for this inference profile",
                }
            },
            "CountTokens",
        )
        with (
            patch.object(bedrock, "count_tokens", side_effect=unsupported),
            patch.object(
                portal_handler,
                "_bounded_aws_client",
                side_effect=lambda _config, service: (
                    bedrock if service == "bedrock-runtime" else FakeDynamoDbClient()
                ),
            ),
        ):
            status = portal_handler._probe_chat_dependencies(
                portal_config(CASE_QA_ENABLED=True, CASE_EMBED_LAMBDA_NAME="embed")
            )

        self.assertEqual(status["llm_gateway"], "ready")

    def test_chat_readiness_does_not_invoke_model_after_access_denied(self) -> None:
        bedrock = FakeBedrockClient()
        denied = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
            "CountTokens",
        )
        with (
            patch.object(bedrock, "count_tokens", side_effect=denied),
            patch.object(bedrock, "converse", wraps=bedrock.converse) as converse,
            patch.object(
                portal_handler,
                "_bounded_aws_client",
                side_effect=lambda _config, service: (
                    bedrock if service == "bedrock-runtime" else FakeDynamoDbClient()
                ),
            ),
        ):
            status = portal_handler._probe_chat_dependencies(
                portal_config(CASE_QA_ENABLED=True, CASE_EMBED_LAMBDA_NAME="embed")
            )

        self.assertEqual(status["llm_gateway"], "unavailable")
        converse.assert_not_called()

    def test_chat_readiness_returns_503_when_dependencies_unavailable(self) -> None:
        config = portal_config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            CASE_QA_ENABLED=True,
            CASE_EMBED_LAMBDA_NAME="notable-case-embed",
        )
        with (
            patch.object(portal_handler, "load_config", return_value=config),
            patch.object(
                portal_handler,
                "_probe_chat_dependencies",
                return_value={
                    "embeddings": "unavailable",
                    "archive_retrieval": "ready",
                    "llm_gateway": "ready",
                },
            ),
        ):
            response = portal_handler.handler(
                event("/api/diagnostics/chat-readiness"),
                None,
            )

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(body["status"], "not_ready")

    def test_ready_uses_bounded_archive_prefix_probe(self) -> None:
        s3 = FakeS3Client()
        with (
            patch.object(portal_handler, "load_config", return_value=portal_config()),
            patch.object(
                portal_handler,
                "_bounded_aws_client",
                side_effect=lambda _config, service: (
                    FakeDynamoDbClient() if service == "dynamodb" else s3
                ),
            ),
            patch.object(s3, "list_objects_v2", wraps=s3.list_objects_v2) as list_probe,
        ):
            response = portal_handler.handler(event("/ready"), None)

        self.assertEqual(response["statusCode"], 200)
        list_probe.assert_called_once_with(Bucket="case-bucket", Prefix="cases/", MaxKeys=1)

    def test_ready_fails_closed_when_chat_client_construction_fails(self) -> None:
        config = portal_config(
            CASE_QA_ENABLED=True,
            CASE_QA_CHAT_HISTORY_ENABLED=True,
            CASE_EMBED_LAMBDA_NAME="embed",
            CHAT_SESSIONS_TABLE="chat-sessions",
            CHAT_MESSAGES_TABLE="chat-messages",
        )
        with patch.object(
            portal_handler,
            "_bounded_aws_client",
            side_effect=RuntimeError("client construction failed"),
        ):
            status = portal_handler._probe_portal_dependencies(config)

        self.assertEqual(status["chat_sessions"], "unavailable")
        self.assertEqual(status["chat_messages"], "unavailable")

    def test_chat_concurrency_limit_returns_429(self) -> None:
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        portal_handler._chat_semaphore = semaphore  # pylint: disable=protected-access
        portal_handler._chat_semaphore_limit = 1  # pylint: disable=protected-access
        with patch.object(
            portal_handler,
            "load_config",
            return_value=portal_config(PORTAL_CHAT_MAX_CONCURRENCY=1),
        ):
            response = portal_handler.handler(event("/api/chat", "POST"), None)

        self.assertEqual(response["statusCode"], 429)
        self.assertIn("Too many chat requests", json.loads(response["body"])["error"])
        semaphore.release()

    def test_chat_requires_selected_case_id(self) -> None:
        with patch.object(
            portal_handler,
            "load_config",
            return_value=portal_config(
                CASE_QA_ENABLED=True,
                CASE_EMBED_LAMBDA_NAME="notable-case-embed",
            ),
        ):
            request = event("/api/chat", "POST")
            request["body"] = json.dumps({"question": "What happened?"})
            response = portal_handler.handler(request, None)

        self.assertEqual(response["statusCode"], 400)
        self.assertIn("selected_case_id", json.loads(response["body"])["error"])

    def test_chat_returns_markdown_answer_for_selected_case(self) -> None:
        with (
            patch.object(
                portal_handler,
                "load_config",
                return_value=portal_config(
                    CASE_QA_ENABLED=True,
                    CASE_EMBED_LAMBDA_NAME="notable-case-embed",
                ),
            ),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
            patch.object(portal_handler, "s3_client", return_value=FakeS3Client()),
            patch.object(portal_handler, "bedrock_runtime_client", return_value=FakeBedrockClient()),
            patch(
                "s3_notable_pipeline.case_chat.build_chat_knowledge_sources",
                return_value=[],
            ),
        ):
            request = event("/api/chat", "POST")
            request["body"] = json.dumps(
                {
                    "mode": "selected_case",
                    "selected_case_id": "case-1",
                    "question": "What happened?",
                }
            )
            response = portal_handler.handler(request, None)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["answer_status"], "answered")
        self.assertIn("suspicious", body["answer"])
        self.assertNotIn("citations", body)

    def test_chat_replays_prior_turns_when_session_id_is_provided(self) -> None:
        captured: dict[str, object] = {}

        def _capture_answer(**kwargs):
            captured["conversation_history"] = kwargs.get("conversation_history")
            from s3_notable_pipeline.portal_chat import PortalAnswer

            return PortalAnswer(answer="Follow-up answer.", answer_status="answered")

        config = portal_config(
            CASE_QA_ENABLED=True,
            CASE_QA_CHAT_HISTORY_ENABLED=True,
            CASE_EMBED_LAMBDA_NAME="notable-case-embed",
            CHAT_SESSIONS_TABLE="chat-sessions",
            CHAT_MESSAGES_TABLE="chat-messages",
        )
        with (
            patch.object(portal_handler, "load_config", return_value=config),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
            patch.object(portal_handler, "s3_client", return_value=FakeS3Client()),
            patch.object(portal_handler, "bedrock_runtime_client", return_value=FakeBedrockClient()),
            patch.object(
                portal_handler,
                "validate_chat_history_request",
                return_value=None,
            ),
            patch.object(
                portal_handler,
                "load_session_transcript",
                return_value=[
                    {"role": "user", "content": "What is the verdict?"},
                    {"role": "assistant", "content": "Likely malicious."},
                ],
            ),
            patch.object(
                portal_handler,
                "answer_selected_case_question",
                side_effect=_capture_answer,
            ),
            patch.object(
                portal_handler,
                "persist_chat_history",
                return_value="session-existing",
            ),
        ):
            request = event("/api/chat", "POST")
            request["body"] = json.dumps(
                {
                    "mode": "selected_case",
                    "selected_case_id": "case-1",
                    "question": "Expand on that.",
                    "session_id": "session-existing",
                }
            )
            response = portal_handler.handler(request, None)

        self.assertEqual(response["statusCode"], 200)
        history = captured["conversation_history"]
        self.assertIsNotNone(history)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].content, "What is the verdict?")

    def test_chat_sessions_list_returns_disabled_payload(self) -> None:
        with patch.object(portal_handler, "load_config", return_value=portal_config()):
            response = portal_handler.handler(event("/api/chat/sessions"), None)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertFalse(body["history_enabled"])
        self.assertEqual(body["items"], [])

    def test_chat_session_delete_returns_404_when_history_disabled(self) -> None:
        session_id = "00000000-0000-0000-0000-000000000001"
        with patch.object(portal_handler, "load_config", return_value=portal_config()):
            response = portal_handler.handler(
                event(f"/api/chat/sessions/{session_id}", "DELETE"),
                None,
            )

        self.assertEqual(response["statusCode"], 404)
        self.assertIn("disabled", json.loads(response["body"])["error"])

    def test_chat_session_delete_maps_missing_session_to_404(self) -> None:
        session_id = "00000000-0000-0000-0000-000000000001"
        with (
            patch.object(
                portal_handler,
                "load_config",
                return_value=portal_config(
                    CASE_QA_CHAT_HISTORY_ENABLED=True,
                    CHAT_SESSIONS_TABLE="chat-sessions",
                    CHAT_MESSAGES_TABLE="chat-messages",
                ),
            ),
            patch.object(
                portal_handler,
                "delete_chat_session",
                side_effect=ChatSessionNotFoundError("session_id was not found."),
            ),
        ):
            response = portal_handler.handler(
                event(f"/api/chat/sessions/{session_id}", "DELETE"),
                None,
            )

        self.assertEqual(response["statusCode"], 404)
        self.assertIn("session_id was not found", json.loads(response["body"])["error"])

    def test_chat_persists_session_id_when_history_enabled(self) -> None:
        with (
            patch.object(
                portal_handler,
                "load_config",
                return_value=portal_config(
                    CASE_QA_ENABLED=True,
                    CASE_EMBED_LAMBDA_NAME="notable-case-embed",
                    CASE_QA_CHAT_HISTORY_ENABLED=True,
                    CHAT_SESSIONS_TABLE="chat-sessions",
                    CHAT_MESSAGES_TABLE="chat-messages",
                ),
            ),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
            patch.object(portal_handler, "s3_client", return_value=FakeS3Client()),
            patch.object(portal_handler, "bedrock_runtime_client", return_value=FakeBedrockClient()),
            patch(
                "s3_notable_pipeline.case_chat.build_chat_knowledge_sources",
                return_value=[],
            ),
            patch.object(
                portal_handler,
                "persist_chat_history",
                return_value="session-123",
            ) as persist_mock,
            patch.object(portal_handler, "validate_chat_history_request"),
        ):
            request = event("/api/chat", "POST")
            request["body"] = json.dumps(
                {
                    "mode": "selected_case",
                    "selected_case_id": "case-1",
                    "question": "What happened?",
                }
            )
            response = portal_handler.handler(request, None)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["session_id"], "session-123")
        persist_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
