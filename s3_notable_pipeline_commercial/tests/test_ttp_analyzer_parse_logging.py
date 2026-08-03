"""Tests for safe TTP analyzer parse-error logging."""

from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.ttp_analyzer import (  # noqa: E402
    BedrockAnalyzer,
    _log_json_parse_failure,
    _response_content_digest,
)


class TTPAnalyzerParseLoggingTests(unittest.TestCase):
    def test_response_content_digest_is_short_and_stable(self) -> None:
        secret = "super-secret-model-output"
        first = _response_content_digest(secret)
        second = _response_content_digest(secret)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertNotIn(secret, first)

    def test_log_json_parse_failure_omits_raw_model_text(self) -> None:
        raw = '{"verdict":"likely_malicious","secret_host":"10.0.0.99"}'
        candidate = '{"verdict":"likely_malicious"'
        error = json.JSONDecodeError("Expecting value", raw, 10)
        with self.assertLogs("s3_notable_pipeline.ttp_analyzer", level="ERROR") as captured:
            _log_json_parse_failure(error=error, raw_text=raw, candidate_text=candidate)
        combined = "\n".join(captured.output)
        self.assertIn("digest=", combined)
        self.assertIn(f"length={len(raw)}", combined)
        self.assertNotIn("10.0.0.99", combined)
        self.assertNotIn(raw, combined)
        self.assertNotIn(candidate, combined)

    def test_parse_bedrock_response_logs_metadata_only_on_json_failure(self) -> None:
        with patch("s3_notable_pipeline.ttp_analyzer.boto3.client"):
            analyzer = BedrockAnalyzer(model_id="test-model")
        response = {
            "output": {
                "message": {
                    "content": [{"text": "not-json-at-all sensitive-token"}],
                }
            }
        }
        with self.assertLogs("s3_notable_pipeline.ttp_analyzer", level="ERROR") as captured:
            parsed, error_msg, raw_content = analyzer._parse_bedrock_response(
                response,
                allow_text_fallback=True,
            )
        self.assertIsNone(parsed)
        self.assertIn("JSON parse error", error_msg or "")
        self.assertEqual(raw_content, "not-json-at-all sensitive-token")
        combined = "\n".join(captured.output)
        self.assertIn("digest=", combined)
        self.assertNotIn("sensitive-token", combined)


if __name__ == "__main__":
    unittest.main()
