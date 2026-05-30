"""Tests for read-only Splunk investigation execution."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.splunk_investigation import (
    HttpSplunkMcpClient,
    execute_hypothesis_queries,
    execute_splunk_rest_query,
    validate_splunk_query_policy,
)


def _config(**overrides):
    base = {
        "CAPABILITY_PROFILES": "core",
        "INVESTIGATION_QUERY_EXECUTION_ENABLED": True,
        "INVESTIGATION_QUERY_BACKEND": "splunk",
        "INVESTIGATION_QUERY_EXECUTOR": "rest",
        "SPLUNK_BASE_URL": "https://splunk.example.test:8089",
        "SPLUNK_SEARCH_ALLOWED_INDEXES": "main,notable",
        "SPLUNK_SEARCH_ALLOWED_COMMANDS": "search,stats,table,fields,where,head",
        "SPLUNK_SEARCH_DENIED_COMMANDS": "delete,collect,map,rest",
        "SPLUNK_SEARCH_MAX_TIME_RANGE": "24h",
        "SPLUNK_SEARCH_MAX_ROWS": 100,
        "SPLUNK_SEARCH_TIMEOUT_SECONDS": 30,
    }
    base.update(overrides)
    return Config(**base)


def _analysis() -> dict[str, object]:
    return {
        "competing_hypotheses": [
            {
                "query_strategy": "resolve_unknown",
                "primary_spl_query": "index=main user=alice | stats count",
                "supports_if": "count > 0",
                "weakens_if": "count = 0",
            }
        ]
    }


class SplunkInvestigationTests(unittest.TestCase):
    """Read-only policy and executor tests."""

    def test_policy_denies_missing_explicit_index(self) -> None:
        allowed, reason = validate_splunk_query_policy(
            "user=alice | stats count",
            config=_config(),
            time_range="24h",
            max_rows=100,
            timeout_seconds=30,
        )

        self.assertFalse(allowed)
        self.assertIn("explicit index", str(reason))

    def test_rest_executor_normalizes_results(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"sid": "sid-1", "results": [{"user": "alice"}]}

        with patch("s3_notable_pipeline.splunk_investigation.requests.post", return_value=response):
            result = execute_splunk_rest_query(
                "index=main user=alice | stats count",
                config=_config(),
                api_token="token",
                time_range="24h",
                max_rows=100,
                timeout_seconds=30,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["executor"], "rest")
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["search_id"], "sid-1")

    def test_mcp_executor_uses_same_normalized_shape(self) -> None:
        mcp_client = SimpleNamespace(
            run_search=lambda _payload: {
                "raw_result_ref": "mcp-result-1",
                "rows": [{"host": "server1"}],
            }
        )

        results = execute_hypothesis_queries(
            _analysis(),
            config=_config(INVESTIGATION_QUERY_EXECUTOR="mcp"),
            mcp_client=mcp_client,
        )

        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[0]["executor"], "mcp")
        self.assertEqual(results[0]["raw_result_ref"], "mcp-result-1")
        self.assertEqual(results[0]["hypothesis_index"], 0)

    def test_mcp_endpoint_must_be_https_without_userinfo(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS URL without userinfo"):
            HttpSplunkMcpClient(endpoint="https://user:pass@splunk.example.test/mcp")


if __name__ == "__main__":
    unittest.main()
