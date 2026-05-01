import unittest
from unittest.mock import MagicMock, patch

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.splunk_investigation import (
    execute_hypothesis_queries,
    execute_splunk_mcp_query,
    execute_splunk_rest_query,
    validate_splunk_query_policy,
)


class _FakeMcpClient:
    def __init__(self, response):
        self.response = response
        self.last_payload = None

    def run_search(self, payload):
        self.last_payload = payload
        return self.response


def _base_config() -> Config:
    config = Config(
        SPLUNK_BASE_URL="https://splunk.internal:8089",
        SPLUNK_API_TOKEN="token",
    )
    config.SPLUNK_SEARCH_ALLOWED_INDEXES = "main,notable,risk"
    config.SPLUNK_SEARCH_ALLOWED_COMMANDS = "search,stats,table,fields,where,head"
    config.SPLUNK_SEARCH_DENIED_COMMANDS = (
        "delete,collect,outputlookup,sendemail,map,rest,script,dbxquery"
    )
    config.SPLUNK_SEARCH_MAX_TIME_RANGE = "24h"
    config.SPLUNK_SEARCH_MAX_ROWS = 100
    config.SPLUNK_SEARCH_TIMEOUT_SECONDS = 20
    config.SPLUNK_SEARCH_ENDPOINT_PATH = "/services/search/jobs/oneshot"
    config.SPLUNK_MCP_TOOL_NAME = "splunk_search"
    config.INVESTIGATION_QUERY_EXECUTION_ENABLED = True
    config.INVESTIGATION_QUERY_EXECUTOR = "rest"
    config.INVESTIGATION_MAX_QUERIES_PER_ALERT = 6
    config.INVESTIGATION_MAX_CONCURRENT_QUERIES = 3
    return config


class TestSplunkInvestigation(unittest.TestCase):
    def test_validate_policy_rejects_disallowed_index_and_denied_command(self) -> None:
        config = _base_config()
        ok, reason = validate_splunk_query_policy(
            "search index=secret | stats count",
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )
        self.assertFalse(ok)
        self.assertIn("allowed index policy", reason or "")

        ok2, reason2 = validate_splunk_query_policy(
            "search index=main | delete",
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )
        self.assertFalse(ok2)
        self.assertIn("denied command", reason2 or "")

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.splunk_investigation.requests.post"
    )
    def test_execute_splunk_rest_query_builds_expected_request_and_normalizes(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [{"user": "admin", "src": "10.0.0.5"}],
            "sid": "sid-123",
        }
        mock_post.return_value = response
        config = _base_config()

        result = execute_splunk_rest_query(
            "search index=main user=admin | stats count by src",
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["executor"], "rest")
        self.assertEqual(result["result_count"], 1)
        self.assertIn("sid-123", str(result))
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["earliest_time"], "-1h")
        self.assertEqual(kwargs["data"]["count"], "50")
        self.assertEqual(kwargs["timeout"], 10)

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.splunk_investigation.requests.post"
    )
    def test_execute_splunk_rest_query_denied_does_not_call_transport(
        self, mock_post: MagicMock
    ) -> None:
        config = _base_config()
        result = execute_splunk_rest_query(
            "search index=secret user=admin | stats count",
            config=config,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )
        self.assertEqual(result["status"], "denied")
        self.assertEqual(mock_post.call_count, 0)

    def test_execute_splunk_mcp_query_builds_payload_and_normalizes(self) -> None:
        config = _base_config()
        client = _FakeMcpClient(
            {
                "raw_result_ref": "ref-1",
                "rows": [{"host": "srv1", "user": "admin"}],
                "result_count": 1,
            }
        )
        result = execute_splunk_mcp_query(
            "search index=main user=admin | head 50",
            config=config,
            mcp_client=client,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["executor"], "mcp")
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(client.last_payload["tool_name"], "splunk_search")
        self.assertEqual(client.last_payload["time_range"], "1h")
        self.assertEqual(client.last_payload["max_rows"], 50)

    def test_execute_splunk_mcp_query_returns_error_for_malformed_response(self) -> None:
        config = _base_config()
        client = _FakeMcpClient({"rows": [{"host": "srv1"}]})
        result = execute_splunk_mcp_query(
            "search index=main user=admin | head 50",
            config=config,
            mcp_client=client,
            time_range="1h",
            max_rows=50,
            timeout_seconds=10,
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("reference", result["message"])

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.splunk_investigation.requests.post"
    )
    def test_execute_hypothesis_queries_respects_max_queries_per_alert(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"results": []}
        mock_post.return_value = response
        config = _base_config()
        config.INVESTIGATION_MAX_QUERIES_PER_ALERT = 2
        analysis_result = {
            "competing_hypotheses": [
                {"primary_spl_query": "search index=main user=a | head 10"},
                {"primary_spl_query": "search index=main user=b | head 10"},
                {"primary_spl_query": "search index=main user=c | head 10"},
            ]
        }

        results = execute_hypothesis_queries(analysis_result, config=config)
        self.assertEqual(len(results), 2)
        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
