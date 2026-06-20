"""Portal API contract tests: OpenAPI snapshot and response-model alignment."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_HANDLER_TESTS = importlib.util.spec_from_file_location(
    "test_portal_handler",
    PROJECT_ROOT / "tests" / "test_portal_handler.py",
)
assert _HANDLER_TESTS and _HANDLER_TESTS.loader
_handler_module = importlib.util.module_from_spec(_HANDLER_TESTS)
sys.modules["test_portal_handler"] = _handler_module
_HANDLER_TESTS.loader.exec_module(_handler_module)

from s3_notable_pipeline import portal_handler
from s3_notable_pipeline.portal_api_models import (
    CaseDetailResponse,
    CaseListResponse,
    CaseRawSectionResponse,
    ChatResponseModel,
    PortalCapabilitiesResponse,
    portal_response,
)

FakeBedrockClient = _handler_module.FakeBedrockClient
FakeDynamoDbClient = _handler_module.FakeDynamoDbClient
FakeS3Client = _handler_module.FakeS3Client
event = _handler_module.event
portal_config = _handler_module.portal_config


class PortalApiContractTests(unittest.TestCase):
    """Validate live handler payloads against shared response models."""

    def test_capabilities_json_validates_against_response_model(self) -> None:
        config = portal_config(
            CASE_QA_ENABLED=True,
            CASE_EMBED_LAMBDA_NAME="notable-case-embed",
        )
        with (
            patch.object(portal_handler, "load_config", return_value=config),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
            patch.object(portal_handler, "bedrock_runtime_client", return_value=object()),
        ):
            response = portal_handler.handler(event("/api/capabilities"), None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        validated = portal_response(PortalCapabilitiesResponse, body)
        self.assertEqual(validated.model_dump(), body)

    def test_case_list_json_validates_against_response_model(self) -> None:
        with (
            patch.object(portal_handler, "load_config", return_value=portal_config()),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
        ):
            response = portal_handler.handler(event("/api/cases"), None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        validated = portal_response(CaseListResponse, body)
        self.assertEqual(validated.model_dump(), body)

    def test_case_detail_json_validates_against_response_model(self) -> None:
        with (
            patch.object(portal_handler, "load_config", return_value=portal_config()),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
            patch.object(portal_handler, "s3_client", return_value=FakeS3Client()),
        ):
            response = portal_handler.handler(event("/api/cases/case-1"), None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        validated = portal_response(CaseDetailResponse, body)
        self.assertEqual(validated.model_dump(), body)

    def test_case_raw_section_json_validates_against_response_model(self) -> None:
        with (
            patch.object(portal_handler, "load_config", return_value=portal_config()),
            patch.object(portal_handler, "dynamodb_client", return_value=FakeDynamoDbClient()),
            patch.object(portal_handler, "s3_client", return_value=FakeS3Client()),
        ):
            response = portal_handler.handler(
                event("/api/cases/case-1/raw/alert_payload"),
                None,
            )

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        validated = portal_response(CaseRawSectionResponse, body)
        self.assertEqual(validated.model_dump(), body)

    def test_chat_json_validates_against_response_model(self) -> None:
        config = portal_config(
            CASE_QA_ENABLED=True,
            CASE_EMBED_LAMBDA_NAME="notable-case-embed",
        )
        with (
            patch.object(portal_handler, "load_config", return_value=config),
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

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        validated = portal_response(ChatResponseModel, body)
        self.assertEqual(validated.model_dump(), body)
        self.assertNotIn("citations", body)


if __name__ == "__main__":
    unittest.main()
