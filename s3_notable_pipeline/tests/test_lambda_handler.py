"""Focused tests for notable sink routing behavior."""

from __future__ import annotations

import gzip
import importlib
import json
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

    def fake_client(service_name: str | None = None, **_kwargs):
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

        def analyze_ttp(self, alert_text: str, **_kwargs) -> list[dict[str, str]]:
            return []

    fake_ttp_analyzer.BedrockAnalyzer = FakeBedrockAnalyzer

    fake_markdown_generator = types.ModuleType("s3_notable_pipeline.markdown_generator")
    fake_markdown_generator.generate_markdown_report = lambda *_args, **_kwargs: "markdown"

    sys.modules.pop(module_name, None)
    sys.modules.pop("s3_notable_pipeline.aws_clients", None)
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
                return_value={
                    "status": "success",
                    "bucket": "out",
                    "markdown_key": "reports/example.md",
                    "json_key": "reports/example.json",
                },
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

        mock_s3.assert_called_once()
        self.assertEqual(
            mock_s3.call_args.args[:3],
            ("incoming/example.json", "# Report", self.analysis_result),
        )
        mock_rest.assert_called_once()
        self.assertEqual(
            mock_rest.call_args.args[:2],
            (self.analysis_result, "incoming/example.json"),
        )
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
            ) as mock_rest,
        ):
            result = self.lambda_handler.write_to_notable_rest_sink(
                "incoming/example.json",
                self.analysis_result,
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["s3_result"]["status"], "error")
        self.assertEqual(result["rest_result"]["status"], "skipped")
        mock_rest.assert_not_called()

    def test_notable_rest_sink_treats_duplicate_writeback_as_success(self) -> None:
        """Idempotent duplicate writeback should not fail the combined sink."""
        with (
            patch.object(
                self.lambda_handler,
                "write_to_s3_sink",
                return_value={"status": "success", "bucket": "out"},
            ),
            patch.object(
                self.lambda_handler,
                "write_to_splunk_rest",
                return_value={"status": "skipped", "finding_id": "example"},
            ),
        ):
            result = self.lambda_handler.write_to_notable_rest_sink(
                "incoming/example.json",
                self.analysis_result,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["rest_result"]["status"], "skipped")

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

    def test_get_servicenow_api_token_from_json_secret(self) -> None:
        """ServiceNow token resolver should read token from Secrets Manager JSON."""
        with (
            patch.dict(
                "os.environ",
                {"SERVICENOW_API_TOKEN_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:snow"},
                clear=True,
            ),
            patch.object(
                self.lambda_handler.secretsmanager_client,
                "get_secret_value",
                return_value={"SecretString": '{"token":"snow-token"}'},
            ),
        ):
            token = self.lambda_handler.get_servicenow_api_token()

        self.assertEqual(token, "snow-token")

    def test_get_elasticsearch_api_key_from_json_secret(self) -> None:
        """Elasticsearch API key resolver should read api_key from Secrets Manager JSON."""
        with (
            patch.dict(
                "os.environ",
                {"ELASTICSEARCH_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:elastic"},
                clear=True,
            ),
            patch.object(
                self.lambda_handler.secretsmanager_client,
                "get_secret_value",
                return_value={"SecretString": '{"api_key":"elastic-token"}'},
            ),
        ):
            token = self.lambda_handler.get_elasticsearch_api_key()

        self.assertEqual(token, "elastic-token")

    def test_writeback_finding_id_requires_payload_key_match_when_present(self) -> None:
        """Writeback should not let the object key target a different payload finding."""
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.lambda_handler.resolve_finding_id_for_writeback(
                {"alert_payload": {"finding_id": "payload-1"}},
                "incoming/key-1.json",
                self.lambda_handler.Config(),
            )

    def test_writeback_can_require_payload_finding_id(self) -> None:
        """Deployments can require trusted payload finding ids for writeback."""
        with self.assertRaisesRegex(ValueError, "payload finding_id is required"):
            self.lambda_handler.resolve_finding_id_for_writeback(
                {"alert_payload": {}},
                "incoming/key-1.json",
                self.lambda_handler.Config(SPLUNK_REQUIRE_PAYLOAD_FINDING_ID=True),
            )


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

    def test_oversized_uncompressed_input_is_rejected(self) -> None:
        """Uncompressed objects should be bounded before prompt construction."""
        with self.assertRaisesRegex(ValueError, "exceeds MAX_DECOMPRESSED_INPUT_BYTES"):
            self.lambda_handler.decode_s3_notable_object(
                "incoming/example.txt",
                b"0123456789ABCDEF",
                config=self.lambda_handler.Config(MAX_DECOMPRESSED_INPUT_BYTES=10),
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
        self.assertEqual(result["json_key"], "reports/example.json")
        self.assertEqual(mock_put.call_count, 2)
        keys = [mock_put.call_args_list[i].kwargs["Key"] for i in range(2)]
        self.assertEqual(set(keys), {"reports/example.md", "reports/example.json"})
        md_call = next(c for c in mock_put.call_args_list if c.kwargs["Key"].endswith(".md"))
        json_call = next(c for c in mock_put.call_args_list if c.kwargs["Key"].endswith(".json"))
        self.assertEqual(md_call.kwargs["ContentType"], "text/markdown")
        self.assertEqual(json_call.kwargs["ContentType"], "application/json")
        self.assertEqual(json_call.kwargs["Body"], b"{}")

    def test_html_report_is_written_when_enabled(self) -> None:
        """HTML reports should be a third S3 artifact only when enabled."""
        with (
            patch.dict(
                "os.environ",
                {"OUTPUT_BUCKET_NAME": "out", "HTML_REPORT_ENABLED": "true"},
                clear=True,
            ),
            patch.object(self.lambda_handler.s3_client, "put_object", create=True) as mock_put,
        ):
            result = self.lambda_handler.write_to_s3_sink(
                "incoming/example.json",
                "# Report",
                {"markdown": "# Report", "html": "<html></html>"},
            )

        self.assertEqual(result["html_key"], "reports/example.html")
        self.assertEqual(mock_put.call_count, 3)
        html_call = next(c for c in mock_put.call_args_list if c.kwargs["Key"].endswith(".html"))
        self.assertEqual(html_call.kwargs["ContentType"], "text/html")

    def test_archive_failure_is_suppressed_after_successful_report_write(self) -> None:
        """Suppress mode should preserve report output and record archive failure."""
        with patch.object(
            self.lambda_handler,
            "archive_case",
            side_effect=RuntimeError("archive unavailable"),
        ):
            result = self.lambda_handler.write_case_archive_after_sink(
                analysis_result={"alert_payload": {}, "llm_response": {}},
                config=self.lambda_handler.Config(
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_ARCHIVE_BUCKET="case-bucket",
                    CASE_INDEX_TABLE="case-index",
                    CASE_ARCHIVE_FAILURE_MODE="suppress",
                ),
                source_bucket="input-bucket",
                source_key="incoming/example.json",
                decoded_notable=self.lambda_handler.DecodedNotable(
                    content="{}",
                    content_type="json",
                    was_compressed=False,
                ),
                sink_result={"status": "success", "markdown_key": "reports/example.md"},
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("archive unavailable", result["message"])

    def test_archive_failure_fail_closed_raises(self) -> None:
        """Fail-closed mode should fail the Lambda record after report write."""
        with (
            patch.object(
                self.lambda_handler,
                "archive_case",
                side_effect=RuntimeError("archive unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "archive unavailable"),
        ):
            self.lambda_handler.write_case_archive_after_sink(
                analysis_result={"alert_payload": {}, "llm_response": {}},
                config=self.lambda_handler.Config(
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_ARCHIVE_BUCKET="case-bucket",
                    CASE_INDEX_TABLE="case-index",
                    CASE_ARCHIVE_FAILURE_MODE="fail_closed",
                ),
                source_bucket="input-bucket",
                source_key="incoming/example.json",
                decoded_notable=self.lambda_handler.DecodedNotable(
                    content="{}",
                    content_type="json",
                    was_compressed=False,
                ),
                sink_result={"status": "success", "markdown_key": "reports/example.md"},
            )

    def test_finding_id_strips_data_and_gzip_extensions(self) -> None:
        """Compressed source keys should derive the same finding ID as raw inputs."""
        self.assertEqual(
            self.lambda_handler.extract_finding_id_from_s3_key("incoming/abc-123.json.gz"),
            "abc-123",
        )

    def test_sqs_s3_notification_is_unwrapped_with_message_id(self) -> None:
        nested = {"Records": [{"s3": {"bucket": {"name": "input"}, "object": {"key": "team%2Fone.json"}}}]}
        records, message_id = self.lambda_handler._s3_event_records(
            {"eventSource": "aws:sqs", "messageId": "msg-1", "body": __import__("json").dumps(nested)}
        )

        self.assertEqual(message_id, "msg-1")
        self.assertEqual(records[0]["s3"]["object"]["key"], "team%2Fone.json")

    def test_processing_identity_distinguishes_replays_and_preserves_prefix(self) -> None:
        identity = self.lambda_handler.S3ProcessingIdentity(
            bucket="input",
            key="team/one.json",
            version_id="v1",
            etag="etag-1",
            sequencer="001",
        )
        other = self.lambda_handler.S3ProcessingIdentity(
            bucket="input",
            key="team/one.json",
            version_id="v2",
            etag="etag-2",
            sequencer="002",
        )

        self.assertNotEqual(identity.processing_id, other.processing_id)
        key = self.lambda_handler._report_key("reports", identity.key, "md", identity)
        self.assertTrue(key.startswith("reports/team/one--"))

    def test_sqs_partial_batch_returns_only_failed_message_ids(self) -> None:
        class Body:
            def __init__(self, value: bytes) -> None:
                self.value = value

            def read(self) -> bytes:
                return self.value

        def get_object(**kwargs):
            calls.append(kwargs)
            if kwargs["Key"] == "bad.json":
                raise RuntimeError("temporary S3 failure")
            return {"Body": Body(b'{"finding_id":"good"}'), "ETag": '"etag-good"'}

        calls: list[dict[str, str]] = []
        event = {
            "Records": [
                {
                    "eventSource": "aws:sqs",
                    "messageId": "good-message",
                    "body": json.dumps({"Records": [{"s3": {"bucket": {"name": "input"}, "object": {"key": "good.json", "size": 25, "versionId": "v2"}}}]}),
                },
                {
                    "eventSource": "aws:sqs",
                    "messageId": "bad-message",
                    "body": json.dumps({"Records": [{"s3": {"bucket": {"name": "input"}, "object": {"key": "bad.json", "size": 25, "versionId": "v1"}}}]}),
                },
            ]
        }
        with (
            patch.object(self.lambda_handler, "load_config", return_value=self.lambda_handler.Config(BEDROCK_MODEL_ID="test")),
            patch.object(self.lambda_handler.s3_client, "get_object", side_effect=get_object, create=True),
            patch.object(self.lambda_handler, "write_to_s3_sink", return_value={"status": "success"}),
        ):
            result = self.lambda_handler.handler(event, None)

        self.assertEqual(result["batchItemFailures"], [{"itemIdentifier": "bad-message"}])
        self.assertEqual([call["VersionId"] for call in calls], ["v2", "v1"])

    def test_terminal_sqs_envelope_is_sent_to_dlq_via_partial_failure(self) -> None:
        event = {
            "Records": [
                {
                    "eventSource": "aws:sqs",
                    "messageId": "malformed-message",
                    "body": "not-json",
                }
            ]
        }
        with patch.object(
            self.lambda_handler,
            "load_config",
            return_value=self.lambda_handler.Config(BEDROCK_MODEL_ID="test"),
        ):
            result = self.lambda_handler.handler(event, None)

        self.assertEqual(
            result["batchItemFailures"],
            [{"itemIdentifier": "malformed-message"}],
        )


if __name__ == "__main__":
    unittest.main()
