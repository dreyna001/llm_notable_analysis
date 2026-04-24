"""Policy-gated read-only query investigation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config_models import QueryPolicyBundle
from .models import QueryExecutionRequest, QueryResultEvidence
from .policy import PolicyDecision, validate_query_plan_policy
from .validators import require_bool


class ReadOnlyQueryExecutor(Protocol):
    """Adapter seam for executing already-approved read-only queries."""

    def execute(self, request: QueryExecutionRequest) -> QueryResultEvidence:
        """Execute one read-only query request and return normalized evidence."""


@dataclass(slots=True)
class QueryInvestigationResult:
    """Normalized outcome for one policy-gated query investigation attempt."""

    executed: bool
    policy_decision: PolicyDecision
    query_result_evidence: QueryResultEvidence | None = None

    def __post_init__(self) -> None:
        """Validate query investigation result fields."""
        self.executed = require_bool(self.executed, "executed")
        if not isinstance(self.policy_decision, PolicyDecision):
            raise ValueError("Field 'policy_decision' must be PolicyDecision.")
        if self.query_result_evidence is not None and not isinstance(
            self.query_result_evidence, QueryResultEvidence
        ):
            raise ValueError(
                "Field 'query_result_evidence' must be QueryResultEvidence when present."
            )
        if self.executed != self.policy_decision.allowed:
            raise ValueError("Execution state must match the policy decision.")
        if self.executed and self.query_result_evidence is None:
            raise ValueError("Executed query investigation results must include evidence.")
        if not self.executed and self.query_result_evidence is not None:
            raise ValueError("Denied query investigation results must not include evidence.")


def execute_query_plan_with_policy(
    *,
    request: QueryExecutionRequest,
    policy_bundle: QueryPolicyBundle,
    executor: ReadOnlyQueryExecutor,
) -> QueryInvestigationResult:
    """Validate policy, then execute one query request only when allowed."""
    if not isinstance(request, QueryExecutionRequest):
        raise ValueError("Field 'request' must be QueryExecutionRequest.")
    if not isinstance(policy_bundle, QueryPolicyBundle):
        raise ValueError("Field 'policy_bundle' must be QueryPolicyBundle.")

    decision = validate_query_plan_policy(request.query_plan, policy_bundle)
    if not decision.allowed:
        return QueryInvestigationResult(executed=False, policy_decision=decision)

    evidence = executor.execute(request)
    if not isinstance(evidence, QueryResultEvidence):
        raise ValueError("Read-only query executor must return QueryResultEvidence.")
    _validate_evidence_matches_request(evidence, request)
    return QueryInvestigationResult(
        executed=True,
        policy_decision=decision,
        query_result_evidence=evidence,
    )


def _validate_evidence_matches_request(
    evidence: QueryResultEvidence, request: QueryExecutionRequest
) -> None:
    """Ensure executor evidence preserves the approved query identity."""
    if evidence.query_dialect is not request.query_plan.query_dialect:
        raise ValueError("Query result evidence dialect must match the approved query plan.")
    if evidence.query_text != request.query_plan.query_text:
        raise ValueError("Query result evidence text must match the approved query plan.")
    if (
        evidence.rows_returned is not None
        and request.query_plan.max_rows is not None
        and evidence.rows_returned > request.query_plan.max_rows
    ):
        raise ValueError("Query result evidence rows_returned exceeds the approved max_rows.")
    if (
        evidence.execution_time_ms is not None
        and request.query_plan.execution_timeout_seconds is not None
        and evidence.execution_time_ms > request.query_plan.execution_timeout_seconds * 1000
    ):
        raise ValueError(
            "Query result evidence execution_time_ms exceeds the approved execution timeout."
        )
