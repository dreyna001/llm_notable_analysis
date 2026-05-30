"""Tests for read-only Elasticsearch investigation execution."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.elasticsearch_investigation import (
    execute_elasticsearch_query,
    execute_hypothesis_elasticsearch_queries,
    validate_elasticsearch_query_policy,
)


def _config(**overrides):
    base = {
        "CAPABILITY_PROFILES": "core",
        "INVESTIGATION_QUERY_EXECUTION_ENABLED": True,
        "INVESTIGATION_QUERY_BACKEND": "elasticsearch",
        "ELASTICSEARCH_BASE_URL": "https://elastic.example.test",
        "ELASTICSEARCH_INDEX_ALLOWLIST": "logs-*",
        "ELASTICSEARCH_ALLOWED_FIELDS": "@timestamp,user,host",
        "ELASTICSEARCH_ALLOW_WILDCARD_INDEXES": True,
        "ELASTICSEARCH_MAX_TIME_RANGE": "24h",
        "ELASTICSEARCH_MAX_ROWS": 100,
        "ELASTICSEARCH_TIMEOUT_SECONDS": 30,
    }
    base.update(overrides)
    return Config(**base)


def _query(index_pattern: str = "logs-*") -> dict[str, object]:
    return {
        "index_pattern": index_pattern,
        "body": {
            "size": 25,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"user": "alice"}},
                        {"range": {"@timestamp": {"gte": "now-24h", "lte": "now"}}},
                    ]
                }
            },
        },
    }


def _analysis() -> dict[str, object]:
    return {
        "competing_hypotheses": [
            {
                "query_strategy": "resolve_unknown",
                "primary_elastic_query": _query(),
                "supports_if": "count > 0",
                "weakens_if": "count = 0",
            }
        ]
    }


class ElasticsearchInvestigationTests(unittest.TestCase):
    """Read-only Elasticsearch policy and executor tests."""

    def test_policy_denies_unallowlisted_index_pattern(self) -> None:
        allowed, reason = validate_elasticsearch_query_policy(
            _query("other-*"),
            config=_config(),
            time_range="24h",
            max_rows=100,
            timeout_seconds=30,
        )

        self.assertFalse(allowed)
        self.assertIn("index_pattern", str(reason))

    def test_executor_normalizes_search_results_and_filters_fields(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "hits": {
                "total": {"value": 1},
                "hits": [{"_source": {"user": "alice", "host": "server1", "secret": "hidden"}}],
            }
        }

        with patch("s3_notable_pipeline.elasticsearch_investigation.requests.post", return_value=response):
            result = execute_elasticsearch_query(
                _query(),
                config=_config(),
                api_key="api-key",
                time_range="24h",
                max_rows=100,
                timeout_seconds=30,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["executor"], "elasticsearch")
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["sample_rows"], [{"host": "server1", "user": "alice"}])

    def test_execute_hypothesis_queries_preserves_hypothesis_index(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"hits": {"total": {"value": 0}, "hits": []}}

        with patch("s3_notable_pipeline.elasticsearch_investigation.requests.post", return_value=response):
            results = execute_hypothesis_elasticsearch_queries(
                _analysis(),
                config=_config(),
                api_key="api-key",
            )

        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[0]["hypothesis_index"], 0)
        self.assertEqual(results[0]["query_strategy"], "resolve_unknown")


if __name__ == "__main__":
    unittest.main()
