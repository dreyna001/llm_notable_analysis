import unittest
from unittest.mock import MagicMock, patch

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.elasticsearch_investigation import (
    execute_elasticsearch_query,
    execute_hypothesis_elasticsearch_queries,
    validate_elasticsearch_query_policy,
)


def _base_config() -> Config:
    config = Config(
        INVESTIGATION_QUERY_BACKEND="elasticsearch",
        ELASTIC_QUERY_GENERATION_ENABLED=True,
        ELASTICSEARCH_BASE_URL="https://elastic.internal:9200",
        ELASTICSEARCH_API_KEY="api-key",
        ELASTICSEARCH_INDEX_ALLOWLIST="logs-auth,security-*",
        ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=True,
        ELASTICSEARCH_ALLOWED_FIELDS="@timestamp,user.name,host.name,event.action",
        ELASTICSEARCH_MAX_TIME_RANGE="24h",
        ELASTICSEARCH_MAX_ROWS=100,
        ELASTICSEARCH_TIMEOUT_SECONDS=20,
        INVESTIGATION_QUERY_EXECUTION_ENABLED=True,
        INVESTIGATION_MAX_QUERIES_PER_ALERT=6,
        INVESTIGATION_MAX_CONCURRENT_QUERIES=3,
    )
    return config


def _primary_query(index_pattern: str = "logs-auth") -> dict:
    return {
        "index_pattern": index_pattern,
        "body": {
            "size": 25,
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"@timestamp": {"gte": "now-24h", "lte": "now"}}},
                        {"term": {"user.name": "admin"}},
                    ]
                }
            },
        },
    }


class TestElasticsearchInvestigation(unittest.TestCase):
    def test_validate_policy_rejects_disallowed_index_and_oversized_query(self) -> None:
        config = _base_config()
        ok, reason = validate_elasticsearch_query_policy(
            _primary_query("secret-index"),
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )
        self.assertFalse(ok)
        self.assertIn("allowed index policy", reason or "")

        oversized = _primary_query()
        oversized["body"]["size"] = 500
        ok2, reason2 = validate_elasticsearch_query_policy(
            oversized,
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )
        self.assertFalse(ok2)
        self.assertIn("size", reason2 or "")

    def test_validate_policy_rejects_script_clause(self) -> None:
        config = _base_config()
        primary = _primary_query()
        primary["body"]["script_fields"] = {"x": {"script": "doc['user.name'].value"}}

        ok, reason = validate_elasticsearch_query_policy(
            primary,
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )

        self.assertFalse(ok)
        self.assertIn("denied DSL key", reason or "")

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.elasticsearch_investigation.requests.post"
    )
    def test_execute_elasticsearch_query_builds_expected_request_and_normalizes(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "hits": {
                "total": {"value": 1},
                "hits": [{"_source": {"user.name": "admin", "host.name": "srv1"}}],
            }
        }
        mock_post.return_value = response
        config = _base_config()

        result = execute_elasticsearch_query(
            _primary_query(),
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["executor"], "elasticsearch")
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(
            result["sample_rows"],
            [{"host.name": "srv1", "user.name": "admin"}],
        )
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://elastic.internal:9200/logs-auth/_search")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(kwargs["headers"]["Authorization"], "ApiKey api-key")
        self.assertEqual(kwargs["json"]["size"], 25)

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.elasticsearch_investigation.requests.post"
    )
    def test_execute_elasticsearch_query_denied_does_not_call_transport(
        self, mock_post: MagicMock
    ) -> None:
        config = _base_config()
        result = execute_elasticsearch_query(
            _primary_query("secret-index"),
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )

        self.assertEqual(result["status"], "denied")
        self.assertEqual(mock_post.call_count, 0)

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.elasticsearch_investigation.requests.post"
    )
    def test_execute_hypothesis_elasticsearch_queries_respects_max_queries_per_alert(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"hits": {"total": {"value": 0}, "hits": []}}
        mock_post.return_value = response
        config = _base_config()
        config.INVESTIGATION_MAX_QUERIES_PER_ALERT = 2
        analysis_result = {
            "competing_hypotheses": [
                {"primary_elastic_query": _primary_query(), "query_strategy": "resolve_unknown"},
                {"primary_elastic_query": _primary_query(), "query_strategy": "resolve_unknown"},
                {"primary_elastic_query": _primary_query(), "query_strategy": "resolve_unknown"},
            ]
        }

        results = execute_hypothesis_elasticsearch_queries(analysis_result, config=config)

        self.assertEqual(len(results), 2)
        self.assertEqual(mock_post.call_count, 2)

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.elasticsearch_investigation.requests.post"
    )
    def test_execute_elasticsearch_query_handles_malformed_response(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = []
        mock_post.return_value = response
        config = _base_config()

        result = execute_elasticsearch_query(
            _primary_query(),
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("object", result["message"])


if __name__ == "__main__":
    unittest.main()
