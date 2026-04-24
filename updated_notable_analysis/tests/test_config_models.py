"""Deterministic tests for shared core config and bundle contracts."""

from __future__ import annotations

import unittest

from updated_notable_analysis.core.config_models import (
    CapabilityProfile,
    CustomerBundle,
    QueryPolicyBundle,
    RuntimeConfig,
)


class TestCoreConfigModels(unittest.TestCase):
    """Behavior-focused tests for runtime, profile, and bundle config models."""

    def test_runtime_config_valid_defaults(self) -> None:
        """Runtime config should apply defaults and validate timeout."""
        config = RuntimeConfig()
        self.assertEqual(config.llm_timeout_seconds, 60)

    def test_customer_bundle_missing_required_name_fails(self) -> None:
        """Customer bundle should fail when required names are empty."""
        with self.assertRaises(ValueError):
            CustomerBundle(
                prompt_pack_name="prompt-pack",
                context_bundle_name="",
                query_policy_bundle_name="policy",
                sink_bundle_name="sink",
                input_mapping_bundle_name="mapping",
            )

    def test_profile_unknown_capability_fails(self) -> None:
        """Capability profile should reject unknown capabilities."""
        with self.assertRaises(ValueError):
            CapabilityProfile(
                profile_name="analysis_only",
                enabled_capabilities=["not-a-capability"],
            )

    def test_query_policy_bundle_validation_failure(self) -> None:
        """Policy bundle should fail when allowed and denied commands overlap."""
        with self.assertRaises(ValueError):
            QueryPolicyBundle(
                allowed_indexes=["main"],
                allowed_commands=["search", "stats"],
                denied_commands=["stats"],
                max_time_range="24h",
                max_rows=1000,
                execution_timeout_seconds=30,
            )

    def test_query_policy_bundle_valid(self) -> None:
        """Policy bundle with deterministic constraints should validate."""
        bundle = QueryPolicyBundle(
            allowed_indexes=["main", "notable"],
            allowed_commands=["search", "stats", "where"],
            denied_commands=["delete"],
            max_time_range="24h",
            max_rows=500,
            execution_timeout_seconds=30,
        )
        self.assertEqual(bundle.max_rows, 500)
        self.assertIn("search", bundle.allowed_commands)


if __name__ == "__main__":
    unittest.main()

