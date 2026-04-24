"""Tests for the Splunk MCP read-only execution adapter."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from updated_notable_analysis.adapters import SplunkMcpReadOnlyExecutor
from updated_notable_analysis.core.config_models import QueryPolicyBundle
from updated_notable_analysis.core.investigation import execute_query_plan_with_policy
from updated_notable_analysis.core.models import QueryExecutionRequest, QueryPlan
from updated_notable_analysis.core.vocabulary import EvidenceType, QueryDialect, QueryStrategy


class _FakeSplunkMcpClient:
    """Fake MCP client that records payloads and returns a configured response."""

    def __init__(self, response: Mapping[str, Any] | object) -> None:
        self.response = response
        self.calls: list[Mapping[str, Any]] = []

    def run_search(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(dict(payload))
        return self.response  # type: ignore[return-value]


class TestSplunkMcpReadOnlyExecutor(unittest.TestCase):
    """Behavior-focused tests for Splunk MCP query execution normalization."""

    def _request(self, *, source_system: str = "splunk") -> QueryExecutionRequest:
        """Return a bounded Splunk query execution request fixture."""
        return QueryExecutionRequest(
            query_plan=QueryPlan(
                query_dialect=QueryDialect.SPL,
                query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
                query_text="search index=main sourcetype=access | stats count by host",
                purpose="Resolve whether the notable has matching events.",
                time_range="1h",
                max_rows=50,
                execution_timeout_seconds=20,
            ),
            policy_bundle_name="spl_readonly_default",
            source_system=source_system,
        )

    def _policy_bundle(self) -> QueryPolicyBundle:
        """Return a read-only Splunk policy bundle fixture."""
        return QueryPolicyBundle(
            allowed_indexes=("main",),
            allowed_commands=("search", "stats", "where"),
            denied_commands=("delete",),
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=30,
        )

    def test_executor_sends_bounded_payload_and_normalizes_evidence(self) -> None:
        """Adapter should pass guardrails to MCP and normalize the returned evidence."""
        client = _FakeSplunkMcpClient(
            {
                "search_id": "sid-123",
                "result_summary": "One host matched the investigation query.",
                "rows": [{"host": "web-1", "count": "7"}],
                "execution_time_ms": 15,
                "dispatch_state": "DONE",
                "field_names": ["host", "count"],
            }
        )
        executor = SplunkMcpReadOnlyExecutor(client=client)

        evidence = executor.execute(self._request())

        self.assertEqual(
            client.calls,
            [
                {
                    "tool_name": "splunk_search",
                    "query": "search index=main sourcetype=access | stats count by host",
                    "query_dialect": "spl",
                    "time_range": "1h",
                    "max_rows": 50,
                    "timeout_seconds": 20,
                    "policy_bundle_name": "spl_readonly_default",
                    "source_system": "splunk",
                }
            ],
        )
        self.assertEqual(evidence.evidence_type, EvidenceType.QUERY_RESULT)
        self.assertEqual(evidence.query_dialect, QueryDialect.SPL)
        self.assertEqual(evidence.rows_returned, 1)
        self.assertEqual(evidence.execution_time_ms, 15)
        self.assertEqual(
            evidence.raw_result_ref,
            "splunk-mcp://search/spl_readonly_default/sid-123",
        )
        self.assertEqual(evidence.metadata["adapter"], "splunk_mcp")
        self.assertEqual(evidence.metadata["dispatch_state"], "DONE")
        self.assertEqual(evidence.metadata["field_names"], ("host", "count"))

    def test_policy_gated_execution_uses_splunk_mcp_executor(self) -> None:
        """Splunk MCP executor should plug into the shared policy gate."""
        client = _FakeSplunkMcpClient(
            {
                "raw_result_ref": "splunk-mcp://search/spl_readonly_default/sid-456",
                "row_count": 0,
                "execution_time_seconds": 0.25,
            }
        )

        result = execute_query_plan_with_policy(
            request=self._request(),
            policy_bundle=self._policy_bundle(),
            executor=SplunkMcpReadOnlyExecutor(client=client),
        )

        self.assertTrue(result.executed)
        self.assertEqual(result.policy_decision.reason_code, "allow")
        assert result.query_result_evidence is not None
        self.assertEqual(result.query_result_evidence.rows_returned, 0)
        self.assertEqual(result.query_result_evidence.execution_time_ms, 250)

    def test_policy_denial_does_not_call_splunk_mcp_client(self) -> None:
        """The shared policy gate must prevent MCP calls for denied queries."""
        client = _FakeSplunkMcpClient({"search_id": "should-not-run"})
        request = self._request()
        request.query_plan.query_text = "search index=secret | stats count"

        result = execute_query_plan_with_policy(
            request=request,
            policy_bundle=self._policy_bundle(),
            executor=SplunkMcpReadOnlyExecutor(client=client),
        )

        self.assertFalse(result.executed)
        self.assertEqual(result.policy_decision.reason_code, "policy_disallowed_index")
        self.assertEqual(client.calls, [])

    def test_executor_rejects_non_splunk_source_system(self) -> None:
        """Splunk MCP execution should fail closed for non-Splunk requests."""
        executor = SplunkMcpReadOnlyExecutor(
            client=_FakeSplunkMcpClient({"search_id": "sid-123"})
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request(source_system="elastic"))

    def test_executor_rejects_response_above_approved_row_limit(self) -> None:
        """MCP responses must not exceed the approved query row limit."""
        executor = SplunkMcpReadOnlyExecutor(
            client=_FakeSplunkMcpClient(
                {
                    "search_id": "sid-123",
                    "rows_returned": 51,
                }
            )
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request())

    def test_executor_rejects_response_above_approved_timeout(self) -> None:
        """MCP responses must not exceed the approved query timeout."""
        executor = SplunkMcpReadOnlyExecutor(
            client=_FakeSplunkMcpClient(
                {
                    "search_id": "sid-123",
                    "execution_time_ms": 20_001,
                }
            )
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request())

    def test_executor_rejects_response_without_raw_result_reference(self) -> None:
        """Evidence needs a durable raw result reference or search identifier."""
        executor = SplunkMcpReadOnlyExecutor(
            client=_FakeSplunkMcpClient(
                {
                    "rows_returned": 1,
                    "execution_time_ms": 10,
                }
            )
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request())

    def test_executor_rejects_non_mapping_client_response(self) -> None:
        """MCP client responses must be mapping-like."""
        executor = SplunkMcpReadOnlyExecutor(client=_FakeSplunkMcpClient(["not", "mapping"]))

        with self.assertRaises(ValueError):
            executor.execute(self._request())


if __name__ == "__main__":
    unittest.main()
