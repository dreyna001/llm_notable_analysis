"""Focused tests for notable sink routing behavior."""

from __future__ import annotations

import gzip
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def load_lambda_handler_module() -> types.ModuleType:
    """Load Lambda handler package with stubbed external dependencies."""
    module_name = "s3_notable_pipeline.lambda_handler"

    fake_boto3 = types.ModuleType("boto3")

    def fake_client(service_name: str):
        if service_name == "secretsmanager":
            return types.SimpleNamespace(get_secret_value=lambda **_kwargs: {"SecretString": ""})
        return types.SimpleNamespace(put_object=lambda **_kwargs: None)

    fake_boto3.client = fake_client

    fake_ttp_analyzer = types.ModuleType("s3_notable_pipeline.ttp_analyzer")

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

    fake_markdown_generator = types.ModuleType("s3_notable_pipeline.markdown_generator")
    fake_markdown_generator.generate_markdown_report = lambda *_args, **_kwargs: "markdown"

    sys.modules.pop(module_name, None)
    with patch.dict(
        sys.modules,
        {
            "boto3": fake_boto3,
            "s3_notable_pipeline.ttp_analyzer": fake_ttp_analyzer,
            "s3_notable_pipeline.markdown_generator": fake_markdown_generator,
        },
        clear=False,
    ):
        return importlib.import_module(module_name)


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


class CompressedInputTests(unittest.TestCase):
    """Tests for gzip-aware S3 input decoding."""

    def setUp(self) -> None:
        self.lambda_handler = load_lambda_handler_module()

    def test_uncompressed_json_still_decodes_as_json(self) -> None:
        """Plain `.json` input should keep the existing JSON content hint."""
        decoded = self.lambda_handler.decode_s3_notable_object(
            "incoming/example.json",
            b'{"finding_id":"abc-123"}',
        )

        self.assertEqual(decoded.content, '{"finding_id":"abc-123"}')
        self.assertEqual(decoded.content_type, "json")
        self.assertFalse(decoded.was_compressed)

    def test_gzip_json_by_extension_decodes_inner_json_payload(self) -> None:
        """`.json.gz` input should decompress and keep the JSON content hint."""
        decoded = self.lambda_handler.decode_s3_notable_object(
            "incoming/example.json.gz",
            gzip.compress(b'{"finding_id":"abc-123"}'),
        )

        self.assertEqual(decoded.content, '{"finding_id":"abc-123"}')
        self.assertEqual(decoded.content_type, "json")
        self.assertTrue(decoded.was_compressed)

    def test_gzip_text_by_content_encoding_decodes_payload(self) -> None:
        """S3 `ContentEncoding: gzip` should trigger decompression without `.gz`."""
        decoded = self.lambda_handler.decode_s3_notable_object(
            "incoming/example.txt",
            gzip.compress(b"plain notable text"),
            "gzip",
        )

        self.assertEqual(decoded.content, "plain notable text")
        self.assertEqual(decoded.content_type, "text")
        self.assertTrue(decoded.was_compressed)

    def test_malformed_gzip_returns_actionable_error(self) -> None:
        """Malformed gzip input should fail before analysis."""
        with self.assertRaisesRegex(ValueError, "Invalid gzip content"):
            self.lambda_handler.decode_s3_notable_object(
                "incoming/example.json.gz",
                b"not gzip bytes",
            )

    def test_oversized_gzip_is_rejected_before_analysis(self) -> None:
        """Decompressed payloads larger than the configured limit should be rejected."""
        with (
            patch.dict("os.environ", {"MAX_DECOMPRESSED_INPUT_BYTES": "10"}, clear=True),
            self.assertRaisesRegex(ValueError, "Decompressed input exceeds"),
        ):
            self.lambda_handler.decode_s3_notable_object(
                "incoming/example.txt.gz",
                gzip.compress(b"this is too long"),
            )

    def test_report_key_strips_data_and_gzip_extensions(self) -> None:
        """S3 report names should strip `.gz` and the inner data extension."""
        with (
            patch.dict("os.environ", {"OUTPUT_BUCKET_NAME": "out"}, clear=True),
            patch.object(self.lambda_handler.s3_client, "put_object", create=True) as mock_put,
        ):
            result = self.lambda_handler.write_to_s3_sink(
                "incoming/example.json.gz",
                "# Report",
                {"markdown": "# Report"},
            )

        self.assertEqual(result["markdown_key"], "reports/example.md")
        mock_put.assert_called_once()
        self.assertEqual(mock_put.call_args.kwargs["Key"], "reports/example.md")

    def test_finding_id_strips_data_and_gzip_extensions(self) -> None:
        """Compressed source keys should derive the same finding ID as raw inputs."""
        self.assertEqual(
            self.lambda_handler.extract_finding_id_from_s3_key("incoming/abc-123.json.gz"),
            "abc-123",
        )


if __name__ == "__main__":
    unittest.main()
