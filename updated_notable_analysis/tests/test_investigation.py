"""Tests for policy-gated read-only query investigation orchestration."""

from __future__ import annotations

import unittest

from updated_notable_analysis.core.config_models import QueryPolicyBundle
from updated_notable_analysis.core.investigation import (
    QueryInvestigationResult,
    execute_query_plan_with_policy,
)
from updated_notable_analysis.core.models import (
    QueryExecutionRequest,
    QueryPlan,
    QueryResultEvidence,
)
from updated_notable_analysis.core.policy import PolicyDecision
from updated_notable_analysis.core.vocabulary import EvidenceType, QueryDialect, QueryStrategy


class _FakeReadOnlyQueryExecutor:
    """Simple read-only query executor test double."""

    def __init__(self, result: QueryResultEvidence | object | None = None) -> None:
        self.result = result
        self.calls: list[QueryExecutionRequest] = []

    def execute(self, request: QueryExecutionRequest):  # noqa: ANN201
        self.calls.append(request)
        if self.result is not None:
            return self.result
        return QueryResultEvidence(
            evidence_type=EvidenceType.QUERY_RESULT,
            query_dialect=request.query_plan.query_dialect,
            query_text=request.query_plan.query_text,
            result_summary="The approved query returned one matching row.",
            raw_result_ref="memory://query-results/one",
            rows_returned=1,
            execution_time_ms=25,
            metadata={"adapter": "fake"},
        )


class TestReadOnlyInvestigation(unittest.TestCase):
    """Behavior-focused tests for read-only investigation orchestration."""

    def _policy_bundle(self) -> QueryPolicyBundle:
        """Return a policy bundle fixture."""
        return QueryPolicyBundle(
            allowed_indexes=("main",),
            allowed_commands=("search", "stats", "where"),
            denied_commands=("delete",),
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=30,
        )

    def _query_plan(self, query_text: str = "search index=main | stats count") -> QueryPlan:
        """Return a query plan fixture."""
        return QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text=query_text,
            purpose="Resolve whether the notable has matching events.",
            time_range="1h",
            max_rows=50,
            execution_timeout_seconds=20,
        )

    def _request(self, query_text: str = "search index=main | stats count") -> QueryExecutionRequest:
        """Return a query execution request fixture."""
        return QueryExecutionRequest(
            query_plan=self._query_plan(query_text),
            policy_bundle_name="spl_readonly_default",
            source_system="splunk",
        )

    def test_denied_query_does_not_execute_adapter(self) -> None:
        """Policy-denied queries must not call the executor."""
        executor = _FakeReadOnlyQueryExecutor()

        result = execute_query_plan_with_policy(
            request=self._request("search index=secret | stats count"),
            policy_bundle=self._policy_bundle(),
            executor=executor,
        )

        self.assertFalse(result.executed)
        self.assertEqual(result.policy_decision.reason_code, "policy_disallowed_index")
        self.assertIsNone(result.query_result_evidence)
        self.assertEqual(executor.calls, [])

    def test_allowed_query_executes_once_and_returns_query_result_evidence(self) -> None:
        """Policy-allowed queries should execute exactly once and return normalized evidence."""
        request = self._request()
        executor = _FakeReadOnlyQueryExecutor()

        result = execute_query_plan_with_policy(
            request=request,
            policy_bundle=self._policy_bundle(),
            executor=executor,
        )

        self.assertTrue(result.executed)
        self.assertEqual(result.policy_decision.reason_code, "allow")
        self.assertEqual(executor.calls, [request])
        assert result.query_result_evidence is not None
        self.assertEqual(result.query_result_evidence.evidence_type, EvidenceType.QUERY_RESULT)
        self.assertEqual(result.query_result_evidence.query_text, request.query_plan.query_text)

    def test_executor_must_return_query_result_evidence(self) -> None:
        """Executor output must satisfy the normalized query-result contract."""
        with self.assertRaises(ValueError):
            execute_query_plan_with_policy(
                request=self._request(),
                policy_bundle=self._policy_bundle(),
                executor=_FakeReadOnlyQueryExecutor(result={"not": "evidence"}),
            )

    def test_executor_result_must_match_approved_query_text(self) -> None:
        """Executor evidence must preserve the approved query identity."""
        bad_evidence = QueryResultEvidence(
            evidence_type=EvidenceType.QUERY_RESULT,
            query_dialect=QueryDialect.SPL,
            query_text="search index=main | stats count by host",
            result_summary="Mismatched query evidence.",
            raw_result_ref="memory://query-results/bad",
        )

        with self.assertRaises(ValueError):
            execute_query_plan_with_policy(
                request=self._request(),
                policy_bundle=self._policy_bundle(),
                executor=_FakeReadOnlyQueryExecutor(result=bad_evidence),
            )

    def test_executor_result_must_stay_within_approved_row_bound(self) -> None:
        """Executor evidence should not exceed approved row limits."""
        bad_evidence = QueryResultEvidence(
            evidence_type=EvidenceType.QUERY_RESULT,
            query_dialect=QueryDialect.SPL,
            query_text="search index=main | stats count",
            result_summary="Too many rows.",
            raw_result_ref="memory://query-results/too-many-rows",
            rows_returned=51,
        )

        with self.assertRaises(ValueError):
            execute_query_plan_with_policy(
                request=self._request(),
                policy_bundle=self._policy_bundle(),
                executor=_FakeReadOnlyQueryExecutor(result=bad_evidence),
            )

    def test_executor_result_must_stay_within_approved_timeout_bound(self) -> None:
        """Executor evidence should not exceed approved execution timeout."""
        bad_evidence = QueryResultEvidence(
            evidence_type=EvidenceType.QUERY_RESULT,
            query_dialect=QueryDialect.SPL,
            query_text="search index=main | stats count",
            result_summary="Too slow.",
            raw_result_ref="memory://query-results/too-slow",
            execution_time_ms=20_001,
        )

        with self.assertRaises(ValueError):
            execute_query_plan_with_policy(
                request=self._request(),
                policy_bundle=self._policy_bundle(),
                executor=_FakeReadOnlyQueryExecutor(result=bad_evidence),
            )

    def test_query_investigation_result_rejects_inconsistent_state(self) -> None:
        """Result model should reject impossible execution/evidence combinations."""
        with self.assertRaises(ValueError):
            QueryInvestigationResult(
                executed=True,
                policy_decision=PolicyDecision(allowed=False, reason_code="deny"),
                query_result_evidence=QueryResultEvidence(
                    evidence_type=EvidenceType.QUERY_RESULT,
                    query_dialect=QueryDialect.SPL,
                    query_text="search index=main",
                    result_summary="Should not exist.",
                    raw_result_ref="memory://bad",
                ),
            )

        with self.assertRaises(ValueError):
            QueryInvestigationResult(
                executed=True,
                policy_decision=PolicyDecision(allowed=True, reason_code="allow"),
                query_result_evidence=None,
            )

        with self.assertRaises(ValueError):
            QueryInvestigationResult(
                executed=False,
                policy_decision=PolicyDecision(allowed=False, reason_code="deny"),
                query_result_evidence=QueryResultEvidence(
                    evidence_type=EvidenceType.QUERY_RESULT,
                    query_dialect=QueryDialect.SPL,
                    query_text="search index=main",
                    result_summary="Should not exist.",
                    raw_result_ref="memory://bad",
                ),
            )


if __name__ == "__main__":
    unittest.main()
