"""Deterministic tests for shared core canonical models."""

from __future__ import annotations

import unittest

from updated_notable_analysis.core.models import (
    AdvisoryContextSnippet,
    AlertEvidence,
    EvidenceSection,
    InvestigationHypothesis,
    NormalizedAlert,
    QueryPlan,
    QueryResultEvidence,
)
from updated_notable_analysis.core.vocabulary import EvidenceType, HypothesisType, QueryDialect, QueryStrategy


class TestCoreModels(unittest.TestCase):
    """Behavior-focused tests for canonical model construction and guardrails."""

    def test_normalized_alert_valid_construction(self) -> None:
        """Constructing a valid normalized alert should succeed."""
        model = NormalizedAlert(
            schema_version="1.0",
            source_system="splunk",
            source_type="notable",
            source_record_ref="id-123",
            received_at="2026-04-21T10:11:12Z",
            raw_content_type="json",
            raw_content='{"event": "x"}',
        )
        self.assertEqual(model.schema_version, "1.0")
        self.assertEqual(model.source_system, "splunk")

    def test_normalized_alert_missing_required_field_fails(self) -> None:
        """Missing required fields should fail fast."""
        with self.assertRaises(ValueError):
            NormalizedAlert(
                schema_version="1.0",
                source_system="splunk",
                source_type="notable",
                source_record_ref="id-123",
                received_at="",
                raw_content_type="json",
                raw_content='{"event": "x"}',
            )

    def test_invalid_enum_value_fails(self) -> None:
        """Invalid enum values should be rejected deterministically."""
        with self.assertRaises(ValueError):
            QueryPlan(
                query_dialect="not-a-dialect",
                query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
                query_text="search index=main | stats count",
                purpose="validate hypothesis",
            )

    def test_alert_evidence_enforces_alert_direct(self) -> None:
        """AlertEvidence must use alert_direct evidence type."""
        with self.assertRaises(ValueError):
            AlertEvidence(
                evidence_type=EvidenceType.ADVISORY_CONTEXT,
                label="field",
                value="value",
            )

    def test_query_result_evidence_enforces_query_result(self) -> None:
        """QueryResultEvidence must use query_result evidence type."""
        with self.assertRaises(ValueError):
            QueryResultEvidence(
                evidence_type=EvidenceType.ALERT_DIRECT,
                query_dialect=QueryDialect.SPL,
                query_text="search index=main",
                result_summary="summary",
                raw_result_ref="result-ref",
            )

    def test_hypothesis_and_evidence_section_valid(self) -> None:
        """Expected baseline hypothesis and evidence section values should validate."""
        hypothesis = InvestigationHypothesis(
            hypothesis_type=HypothesisType.ADVERSARY,
            hypothesis="This is suspicious.",
            evidence_support=["indicator one"],
            evidence_gaps=["gap one"],
        )
        section = EvidenceSection(
            evidence_type=EvidenceType.ALERT_DIRECT,
            summary="Alert evidence summary",
        )
        self.assertEqual(hypothesis.hypothesis_type, HypothesisType.ADVERSARY)
        self.assertEqual(section.evidence_type, EvidenceType.ALERT_DIRECT)

    def test_optional_numeric_fields_reject_non_integer_values(self) -> None:
        """Optional numeric fields should fail with deterministic ValueError."""
        with self.assertRaises(ValueError):
            AdvisoryContextSnippet(
                source_type="kb",
                source_id="source-1",
                title="title",
                content="content",
                provenance_ref="ref",
                rank="1",
            )

        with self.assertRaises(ValueError):
            QueryResultEvidence(
                evidence_type=EvidenceType.QUERY_RESULT,
                query_dialect=QueryDialect.SPL,
                query_text="search index=main",
                result_summary="summary",
                raw_result_ref="result-ref",
                rows_returned="1",
            )

    def test_query_plan_accepts_policy_guardrail_fields(self) -> None:
        """QueryPlan should carry query-side policy guardrail values."""
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=main | stats count",
            purpose="validate hypothesis",
            time_range="1h",
            max_rows=100,
            execution_timeout_seconds=20,
        )
        self.assertEqual(plan.max_rows, 100)
        self.assertEqual(plan.execution_timeout_seconds, 20)


if __name__ == "__main__":
    unittest.main()

