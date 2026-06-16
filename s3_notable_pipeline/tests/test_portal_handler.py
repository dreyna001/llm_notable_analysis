"""Tests for the AWS portal API Lambda handler."""

from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline import portal_handler


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

    def get_object(self, **_kwargs):
        import io

        return {"Body": io.BytesIO(json.dumps(case_envelope()).encode("utf-8"))}


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
        "CASE_ARCHIVE_BUCKET": "case-bucket",
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
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
            patch.object(portal_handler, "bedrock_runtime_client", return_value=object()),
        ):
            response = portal_handler.handler(event("/api/capabilities"), None)

        body = json.loads(response["body"])
        self.assertTrue(body["chat_ready"])
        self.assertEqual(body["chat_dependency_status"]["embeddings"], "ready")

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


if __name__ == "__main__":
    unittest.main()
