"""Focused tests for notable sink routing behavior."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def load_lambda_handler_module() -> types.ModuleType:
    """Load `lambda_handler.py` with stubbed external dependencies."""
    module_name = "s3_notable_pipeline_lambda_handler_test"
    module_path = Path(__file__).with_name("lambda_handler.py")

    fake_boto3 = types.ModuleType("boto3")

    def fake_client(service_name: str):
        if service_name == "secretsmanager":
            return types.SimpleNamespace(get_secret_value=lambda **_kwargs: {"SecretString": ""})
        return object()

    fake_boto3.client = fake_client

    fake_ttp_analyzer = types.ModuleType("ttp_analyzer")

    class FakeBedrockAnalyzer:
        """Minimal analyzer stub for module import."""

        last_llm_response = {}

        def __init__(self, model_id: str) -> None:
            self.model_id = model_id

        def format_alert_input(self, alert_payload, raw_content: str, content_type: str) -> str:
            return raw_content

        def analyze_ttp(self, alert_text: str) -> list[dict[str, str]]:
            return []

    fake_ttp_analyzer.BedrockAnalyzer = FakeBedrockAnalyzer

    fake_markdown_generator = types.ModuleType("markdown_generator")
    fake_markdown_generator.generate_markdown_report = lambda *_args, **_kwargs: "markdown"

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load lambda_handler.py for tests")

    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "boto3": fake_boto3,
            "ttp_analyzer": fake_ttp_analyzer,
            "markdown_generator": fake_markdown_generator,
        },
        clear=False,
    ):
        spec.loader.exec_module(module)
    return module


class NotableRestSinkTests(unittest.TestCase):
    """Tests for the combined S3 + notable REST sink behavior."""

    def setUp(self) -> None:
        self.lambda_handler = load_lambda_handler_module()
        self.analysis_result = {
            "markdown": "# Report",
            "meta": {"source_key": "incoming/example.json"},
            "scored_ttps": [],
            "llm_response": {},
        }

    def test_notable_rest_sink_writes_s3_and_rest(self) -> None:
        """`notable_rest` should preserve S3 output and then call Splunk REST."""
        with (
            patch.object(
                self.lambda_handler,
                "write_to_s3_sink",
                return_value={"status": "success", "bucket": "out", "markdown_key": "reports/example.md"},
            ) as mock_s3,
            patch.object(
                self.lambda_handler,
                "write_to_splunk_rest",
                return_value={"status": "success", "finding_id": "example"},
            ) as mock_rest,
        ):
            result = self.lambda_handler.write_to_notable_rest_sink(
                "incoming/example.json",
                self.analysis_result,
            )

        mock_s3.assert_called_once_with("incoming/example.json", "# Report", self.analysis_result)
        mock_rest.assert_called_once_with(self.analysis_result, "incoming/example.json")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["s3_result"]["status"], "success")
        self.assertEqual(result["rest_result"]["status"], "success")

    def test_notable_rest_sink_reports_error_if_either_sink_fails(self) -> None:
        """Combined sink should surface an error status when one child sink fails."""
        with (
            patch.object(
                self.lambda_handler,
                "write_to_s3_sink",
                return_value={"status": "error", "message": "s3 failed"},
            ),
            patch.object(
                self.lambda_handler,
                "write_to_splunk_rest",
                return_value={"status": "success", "finding_id": "example"},
            ),
        ):
            result = self.lambda_handler.write_to_notable_rest_sink(
                "incoming/example.json",
                self.analysis_result,
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["s3_result"]["status"], "error")
        self.assertEqual(result["rest_result"]["status"], "success")

    def test_get_splunk_api_token_from_plain_secret_string(self) -> None:
        """Token resolver should support plain-text Secrets Manager values."""
        with (
            patch.dict(
                "os.environ",
                {"SPLUNK_API_TOKEN_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:token"},
                clear=True,
            ),
            patch.object(
                self.lambda_handler.secretsmanager_client,
                "get_secret_value",
                return_value={"SecretString": "plain-secret-token"},
            ),
        ):
            token = self.lambda_handler.get_splunk_api_token()

        self.assertEqual(token, "plain-secret-token")

    def test_get_splunk_api_token_from_json_field(self) -> None:
        """Token resolver should read the configured field from a JSON secret."""
        with (
            patch.dict(
                "os.environ",
                {
                    "SPLUNK_API_TOKEN_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:token",
                    "SPLUNK_API_TOKEN_SECRET_FIELD": "api_token",
                },
                clear=True,
            ),
            patch.object(
                self.lambda_handler.secretsmanager_client,
                "get_secret_value",
                return_value={"SecretString": '{"api_token":"json-secret-token"}'},
            ),
        ):
            token = self.lambda_handler.get_splunk_api_token()

        self.assertEqual(token, "json-secret-token")


if __name__ == "__main__":
    unittest.main()
