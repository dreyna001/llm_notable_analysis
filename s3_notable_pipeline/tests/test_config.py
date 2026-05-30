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
