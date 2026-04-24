"""Deterministic tests for shared core policy decision checks."""

from __future__ import annotations

import unittest

from updated_notable_analysis.core.config_models import CapabilityProfile, QueryPolicyBundle
from updated_notable_analysis.core.models import QueryPlan
from updated_notable_analysis.core.policy import validate_capability_profile, validate_query_plan_policy
from updated_notable_analysis.core.vocabulary import CapabilityName, QueryDialect, QueryStrategy


class TestCorePolicy(unittest.TestCase):
    """Behavior-focused tests for profile and query policy checks."""

    def test_profile_validation_fails_on_missing_dependency(self) -> None:
        """Enriched analysis must require readonly investigation capability."""
        profile = CapabilityProfile(
            profile_name="broken_profile",
            enabled_capabilities=[
                CapabilityName.NOTABLE_ANALYSIS,
                CapabilityName.QUERY_RESULT_ENRICHED_ANALYSIS,
            ],
        )
        decision = validate_capability_profile(profile)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unsupported_capability_combination")

    def test_profile_validation_fails_without_writeback_approval(self) -> None:
        """Writeback capabilities must have explicit approval requirements."""
        profile = CapabilityProfile(
            profile_name="writeback_missing_approval",
            enabled_capabilities=[
                CapabilityName.NOTABLE_ANALYSIS,
                CapabilityName.TICKET_DRAFT_WRITEBACK,
            ],
            approval_requirements={},
        )
        decision = validate_capability_profile(profile)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "missing_writeback_approval_requirement")

    def test_query_policy_denies_denied_command(self) -> None:
        """Denied commands in query text should produce a policy denial."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main"],
            allowed_commands=["search", "stats"],
            denied_commands=["delete"],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.CHECK_CONTRADICTION,
            query_text="search index=main | delete",
            purpose="check contradiction",
            time_range="1h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "policy_denied_command")

    def test_query_policy_allows_valid_query(self) -> None:
        """Policy should allow read-only query that passes all constraints."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main", "notable"],
            allowed_commands=["search", "stats", "where"],
            denied_commands=["delete"],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=main | where status=404 | stats count by host",
            purpose="resolve unknown",
            time_range="1h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "allow")

    def test_query_policy_denies_disallowed_index_even_with_allowed_index(self) -> None:
        """Every explicit index reference must be policy-approved."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main"],
            allowed_commands=["search", "stats"],
            denied_commands=[],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=secret OR index=main | stats count",
            purpose="resolve unknown",
            time_range="1h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "policy_disallowed_index")

    def test_query_policy_denies_bare_allowed_index_token(self) -> None:
        """Allowed index names must appear as explicit index=<name> clauses."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main"],
            allowed_commands=["search", "stats"],
            denied_commands=[],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search sourcetype=main | stats count",
            purpose="resolve unknown",
            time_range="1h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "policy_missing_allowed_index")

    def test_query_policy_denies_missing_guardrail_bounds(self) -> None:
        """Policy approval requires explicit query-side execution bounds."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main"],
            allowed_commands=["search", "stats"],
            denied_commands=[],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=main | stats count",
            purpose="resolve unknown",
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "policy_missing_time_range")

    def test_query_policy_denies_exceeded_guardrail_bounds(self) -> None:
        """Query-side bounds must stay within the policy bundle maximums."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main"],
            allowed_commands=["search", "stats"],
            denied_commands=[],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=main | stats count",
            purpose="resolve unknown",
            time_range="48h",
            max_rows=101,
            execution_timeout_seconds=21,
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "policy_time_range_exceeded")

    def test_query_policy_denies_max_rows_exceeded(self) -> None:
        """Query-side max_rows should fail independently when over policy limit."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main"],
            allowed_commands=["search", "stats"],
            denied_commands=[],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=main | stats count",
            purpose="resolve unknown",
            time_range="1h",
            max_rows=101,
            execution_timeout_seconds=20,
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "policy_max_rows_exceeded")

    def test_query_policy_denies_execution_timeout_exceeded(self) -> None:
        """Query execution timeout should fail independently when over policy limit."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main"],
            allowed_commands=["search", "stats"],
            denied_commands=[],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=main | stats count",
            purpose="resolve unknown",
            time_range="1h",
            max_rows=100,
            execution_timeout_seconds=21,
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "policy_execution_timeout_exceeded")

    def test_query_policy_denies_invalid_time_range_format(self) -> None:
        """Unsupported duration formats should produce a dedicated policy denial."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main"],
            allowed_commands=["search", "stats"],
            denied_commands=[],
            max_time_range="24h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=main | stats count",
            purpose="resolve unknown",
            time_range="yesterday",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        decision = validate_query_plan_policy(plan, bundle)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "policy_invalid_time_range")


if __name__ == "__main__":
    unittest.main()

