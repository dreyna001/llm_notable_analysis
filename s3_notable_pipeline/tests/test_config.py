"""Tests for AWS pipeline runtime configuration."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import load_config


class ConfigTests(unittest.TestCase):
    """Profile and runtime-contract tests."""

    def test_default_config_preserves_core_behavior(self) -> None:
        """Default config should keep optional parity features disabled."""
        with patch.dict("os.environ", {}, clear=True):
            config = load_config()

        self.assertEqual(config.CAPABILITY_PROFILES, "core")
        self.assertEqual(config.SPLUNK_SINK_MODE, "s3")
        self.assertFalse(config.RAG_ENABLED)
        self.assertFalse(config.SPL_QUERY_GENERATION_ENABLED)
        self.assertFalse(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)
        self.assertFalse(config.SPLUNK_SINK_ENABLED)
        self.assertFalse(config.CASE_ARCHIVE_ENABLED)
        self.assertFalse(config.PORTAL_ENABLED)
        self.assertFalse(config.CASE_QA_ENABLED)
        self.assertEqual(config.PORTAL_CHAT_MAX_CONCURRENCY, 18)

    def test_action_gated_profile_enables_writeback_and_idempotency(self) -> None:
        """`action_gated` should mirror the on-prem external-action posture."""
        with patch.dict(
            "os.environ",
            {
                "CAPABILITY_PROFILES": "core,action_gated",
                "SERVICENOW_APPROVAL_HMAC_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:snow-approval",
            },
            clear=True,
        ):
            config = load_config()

        self.assertTrue(config.SPLUNK_SINK_ENABLED)
        self.assertTrue(config.SERVICENOW_DRAFT_ENABLED)
        self.assertTrue(config.SERVICENOW_CREATE_ENABLED)
        self.assertTrue(config.SERVICENOW_CREATE_REQUIRES_APPROVAL)
        self.assertTrue(config.SIDE_EFFECT_IDEMPOTENCY_ENABLED)

    def test_analyst_portal_profile_enables_archive_portal_and_qa(self) -> None:
        """`analyst_portal` should enable only the read-only portal bundle."""
        with patch.dict(
            "os.environ",
            {
                "CAPABILITY_PROFILES": "core,analyst_portal",
                "OUTPUT_BUCKET_NAME": "notable-output",
                "CASE_INDEX_TABLE": "notable-case-index",
                "CASE_EMBED_LAMBDA_NAME": "notable-case-embed",
                "PORTAL_JWT_ISSUER": "https://issuer.example.test",
                "PORTAL_JWT_AUDIENCE": "notable-portal",
            },
            clear=True,
        ):
            config = load_config()

        self.assertTrue(config.CASE_ARCHIVE_ENABLED)
        self.assertTrue(config.PORTAL_ENABLED)
        self.assertTrue(config.CASE_QA_ENABLED)
        self.assertEqual(config.CASE_ARCHIVE_BUCKET, "notable-output")
        self.assertEqual(config.CASE_INDEX_TABLE, "notable-case-index")
        self.assertEqual(config.CASE_RETENTION_DAYS, 30)
        self.assertEqual(config.PORTAL_AUTH_MODE, "jwt")
        self.assertEqual(config.PORTAL_CHAT_MAX_CONCURRENCY, 18)
        self.assertFalse(config.HTML_REPORT_ENABLED)
        self.assertFalse(config.SPLUNK_SINK_ENABLED)
        self.assertFalse(config.SERVICENOW_CREATE_ENABLED)

    def test_spl_and_elastic_readonly_profiles_are_mutually_exclusive(self) -> None:
        """Only one read-only investigation backend can be active."""
        with (
            patch.dict(
                "os.environ",
                {"CAPABILITY_PROFILES": "core,spl_readonly,elastic_readonly"},
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "cannot include both"),
        ):
            load_config()

    def test_unknown_profile_fails_fast(self) -> None:
        """Unsupported profile names should not silently degrade."""
        with (
            patch.dict("os.environ", {"CAPABILITY_PROFILES": "core,unknown"}, clear=True),
            self.assertRaisesRegex(ValueError, "unsupported profile"),
        ):
            load_config()

    def test_invalid_sink_mode_fails_fast(self) -> None:
        """Sink mode remains restricted to the current supported values."""
        with (
            patch.dict("os.environ", {"SPLUNK_SINK_MODE": "side_effects"}, clear=True),
            self.assertRaisesRegex(ValueError, "SPLUNK_SINK_MODE"),
        ):
            load_config()

    def test_analyst_portal_requires_case_index_table(self) -> None:
        """Archive or portal enablement needs a DynamoDB CaseIndex table."""
        with (
            patch.dict(
                "os.environ",
                {
                    "CAPABILITY_PROFILES": "core,analyst_portal",
                    "OUTPUT_BUCKET_NAME": "notable-output",
                    "PORTAL_JWT_ISSUER": "https://issuer.example.test",
                    "PORTAL_JWT_AUDIENCE": "notable-portal",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "CASE_INDEX_TABLE"),
        ):
            load_config()

    def test_case_qa_requires_embed_lambda_name(self) -> None:
        """Case Q&A should not start without the async embed Lambda target."""
        with (
            patch.dict(
                "os.environ",
                {
                    "CAPABILITY_PROFILES": "core,analyst_portal",
                    "OUTPUT_BUCKET_NAME": "notable-output",
                    "CASE_INDEX_TABLE": "notable-case-index",
                    "PORTAL_JWT_ISSUER": "https://issuer.example.test",
                    "PORTAL_JWT_AUDIENCE": "notable-portal",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "CASE_EMBED_LAMBDA_NAME"),
        ):
            load_config()

    def test_portal_jwt_auth_requires_issuer_and_audience(self) -> None:
        """JWT portal auth should fail closed when identity settings are missing."""
        with (
            patch.dict(
                "os.environ",
                {
                    "PORTAL_ENABLED": "true",
                    "CASE_INDEX_TABLE": "notable-case-index",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "PORTAL_JWT_ISSUER"),
        ):
            load_config()

    def test_invalid_portal_auth_mode_fails_fast(self) -> None:
        """Portal auth mode remains restricted to the approved v1 modes."""
        with (
            patch.dict("os.environ", {"PORTAL_AUTH_MODE": "none"}, clear=True),
            self.assertRaisesRegex(ValueError, "PORTAL_AUTH_MODE"),
        ):
            load_config()

    def test_case_qa_requires_portal(self) -> None:
        """Case Q&A is only exposed through the portal API."""
        with (
            patch.dict("os.environ", {"CASE_QA_ENABLED": "true"}, clear=True),
            self.assertRaisesRegex(ValueError, "CASE_QA_ENABLED"),
        ):
            load_config()

    def test_portal_chat_concurrency_is_bounded(self) -> None:
        """The per-environment chat semaphore limit should be capped."""
        with (
            patch.dict(
                "os.environ",
                {"PORTAL_CHAT_MAX_CONCURRENCY": "65"},
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "PORTAL_CHAT_MAX_CONCURRENCY"),
        ):
            load_config()

    def test_case_qa_vector_dimensions_are_locked_to_titan_v2(self) -> None:
        """Titan V2 embeddings use the locked 1024-dimensional vector contract."""
        with (
            patch.dict("os.environ", {"CASE_QA_VECTOR_DIMENSIONS": "1536"}, clear=True),
            self.assertRaisesRegex(ValueError, "CASE_QA_VECTOR_DIMENSIONS"),
        ):
            load_config()

    def test_chat_history_requires_dynamodb_tables(self) -> None:
        """Persisted chat history should not start without both table names."""
        with (
            patch.dict(
                "os.environ",
                {"CASE_QA_CHAT_HISTORY_ENABLED": "true"},
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "CHAT_SESSIONS_TABLE"),
        ):
            load_config()

    def test_spl_readonly_profile_sets_splunk_backend(self) -> None:
        """SPL read-only profile should enable Splunk investigation flags."""
        with patch.dict("os.environ", {"CAPABILITY_PROFILES": "core,spl_readonly"}, clear=True):
            config = load_config()

        self.assertTrue(config.SPL_QUERY_GENERATION_ENABLED)
        self.assertTrue(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)
        self.assertEqual(config.INVESTIGATION_QUERY_BACKEND, "splunk")

    def test_elastic_readonly_profile_sets_elasticsearch_backend(self) -> None:
        """Elastic read-only profile should enable Elastic investigation flags."""
        with patch.dict(
            "os.environ",
            {
                "CAPABILITY_PROFILES": "core,elastic_readonly",
                "ELASTICSEARCH_BASE_URL": "https://elastic.example.test",
                "ELASTICSEARCH_INDEX_ALLOWLIST": "logs-*",
                "ELASTICSEARCH_ALLOWED_FIELDS": "@timestamp,user,host",
            },
            clear=True,
        ):
            config = load_config()

        self.assertTrue(config.ELASTIC_QUERY_GENERATION_ENABLED)
        self.assertTrue(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)
        self.assertEqual(config.INVESTIGATION_QUERY_BACKEND, "elasticsearch")

    def test_elasticsearch_execution_requires_https_base_url(self) -> None:
        """Elastic execution should fail fast for non-HTTPS endpoints."""
        with (
            patch.dict(
                "os.environ",
                {
                    "CAPABILITY_PROFILES": "core,elastic_readonly",
                    "ELASTICSEARCH_BASE_URL": "http://elastic.example.test",
                    "ELASTICSEARCH_INDEX_ALLOWLIST": "logs-*",
                    "ELASTICSEARCH_ALLOWED_FIELDS": "@timestamp,user,host",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "must be an HTTPS URL"),
        ):
            load_config()

    def test_outbound_private_ip_requires_explicit_allowance(self) -> None:
        """Outbound integration URLs should not silently target private IPs."""
        with (
            patch.dict(
                "os.environ",
                {
                    "SPLUNK_SINK_MODE": "notable_rest",
                    "SPLUNK_BASE_URL": "https://127.0.0.1:8089",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "private or local IP"),
        ):
            load_config()


if __name__ == "__main__":
    unittest.main()
