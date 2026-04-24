"""Tests for the Splunk REST read-only execution adapter."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from updated_notable_analysis.adapters import SplunkRestReadOnlyExecutor
from updated_notable_analysis.core.config_models import QueryPolicyBundle
from updated_notable_analysis.core.investigation import execute_query_plan_with_policy
from updated_notable_analysis.core.models import QueryExecutionRequest, QueryPlan
from updated_notable_analysis.core.vocabulary import EvidenceType, QueryDialect, QueryStrategy


class _FakeSplunkRestTransport:
    """Fake REST transport that records requests and returns a configured response."""

    def __init__(self, response: Mapping[str, Any] | object) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        *,
        path: str,
        data: Mapping[str, Any],
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "path": path,
                "data": dict(data),
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response  # type: ignore[return-value]


class TestSplunkRestReadOnlyExecutor(unittest.TestCase):
    """Behavior-focused tests for Splunk REST query execution normalization."""

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

    def test_executor_sends_bounded_rest_payload_and_normalizes_evidence(self) -> None:
        """Adapter should pass guardrails to REST and normalize returned evidence."""
        transport = _FakeSplunkRestTransport(
            {
                "sid": "sid-123",
                "result_summary": "One host matched the investigation query.",
                "results": [{"host": "web-1", "count": "7"}],
                "execution_time_ms": 15,
                "dispatch_state": "DONE",
                "field_names": ["host", "count"],
            }
        )
        executor = SplunkRestReadOnlyExecutor(transport=transport)

        evidence = executor.execute(self._request())

        self.assertEqual(
            transport.calls,
            [
                {
                    "path": "/services/search/jobs/oneshot",
                    "data": {
                        "search": "search index=main sourcetype=access | stats count by host",
                        "output_mode": "json",
                        "exec_mode": "oneshot",
                        "earliest_time": "-1h",
                        "latest_time": "now",
                        "count": 50,
                        "timeout": 20,
                    },
                    "timeout_seconds": 20,
                }
            ],
        )
        self.assertEqual(evidence.evidence_type, EvidenceType.QUERY_RESULT)
        self.assertEqual(evidence.query_dialect, QueryDialect.SPL)
        self.assertEqual(evidence.rows_returned, 1)
        self.assertEqual(evidence.execution_time_ms, 15)
        self.assertEqual(
            evidence.raw_result_ref,
            "splunk-rest://search/spl_readonly_default/sid-123",
        )
        self.assertEqual(evidence.metadata["adapter"], "splunk_rest")
        self.assertEqual(evidence.metadata["endpoint_path"], "/services/search/jobs/oneshot")
        self.assertEqual(evidence.metadata["dispatch_state"], "DONE")
        self.assertEqual(evidence.metadata["field_names"], ("host", "count"))

    def test_policy_gated_execution_uses_splunk_rest_executor(self) -> None:
        """Splunk REST executor should plug into the shared policy gate."""
        transport = _FakeSplunkRestTransport(
            {
                "raw_result_ref": "splunk-rest://search/spl_readonly_default/sid-456",
                "row_count": 0,
                "execution_time_seconds": 0.25,
            }
        )

        result = execute_query_plan_with_policy(
            request=self._request(),
            policy_bundle=self._policy_bundle(),
            executor=SplunkRestReadOnlyExecutor(transport=transport),
        )

        self.assertTrue(result.executed)
        self.assertEqual(result.policy_decision.reason_code, "allow")
        assert result.query_result_evidence is not None
        self.assertEqual(result.query_result_evidence.rows_returned, 0)
        self.assertEqual(result.query_result_evidence.execution_time_ms, 250)

    def test_policy_denial_does_not_call_splunk_rest_transport(self) -> None:
        """The shared policy gate must prevent REST calls for denied queries."""
        transport = _FakeSplunkRestTransport({"sid": "should-not-run"})
        request = self._request()
        request.query_plan.query_text = "search index=secret | stats count"

        result = execute_query_plan_with_policy(
            request=request,
            policy_bundle=self._policy_bundle(),
            executor=SplunkRestReadOnlyExecutor(transport=transport),
        )

        self.assertFalse(result.executed)
        self.assertEqual(result.policy_decision.reason_code, "policy_disallowed_index")
        self.assertEqual(transport.calls, [])

    def test_executor_rejects_non_splunk_source_system(self) -> None:
        """Splunk REST execution should fail closed for non-Splunk requests."""
        executor = SplunkRestReadOnlyExecutor(
            transport=_FakeSplunkRestTransport({"sid": "sid-123"})
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request(source_system="elastic"))

    def test_executor_rejects_response_above_approved_row_limit(self) -> None:
        """REST responses must not exceed the approved query row limit."""
        executor = SplunkRestReadOnlyExecutor(
            transport=_FakeSplunkRestTransport(
                {
                    "sid": "sid-123",
                    "rows_returned": 51,
                }
            )
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request())

    def test_executor_rejects_response_above_approved_timeout(self) -> None:
        """REST responses must not exceed the approved query timeout."""
        executor = SplunkRestReadOnlyExecutor(
            transport=_FakeSplunkRestTransport(
                {
                    "sid": "sid-123",
                    "execution_time_ms": 20_001,
                }
            )
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request())

    def test_executor_rejects_response_without_raw_result_reference(self) -> None:
        """Evidence needs a durable raw result reference or search identifier."""
        executor = SplunkRestReadOnlyExecutor(
            transport=_FakeSplunkRestTransport(
                {
                    "rows_returned": 1,
                    "execution_time_ms": 10,
                }
            )
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request())

    def test_executor_rejects_non_mapping_transport_response(self) -> None:
        """REST transport responses must be mapping-like."""
        executor = SplunkRestReadOnlyExecutor(
            transport=_FakeSplunkRestTransport(["not", "mapping"])
        )

        with self.assertRaises(ValueError):
            executor.execute(self._request())

    def test_executor_rejects_endpoint_path_without_leading_slash(self) -> None:
        """REST endpoint paths should be absolute Splunk service paths."""
        with self.assertRaises(ValueError):
            SplunkRestReadOnlyExecutor(
                transport=_FakeSplunkRestTransport({"sid": "sid-123"}),
                search_endpoint_path="services/search/jobs/oneshot",
            )


if __name__ == "__main__":
    unittest.main()
