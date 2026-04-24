"""Tests for ServiceNow incident draft writeback construction."""

from __future__ import annotations

import unittest

from updated_notable_analysis.adapters import (
    ServiceNowIncidentDraftBuilder,
    ServiceNowIncidentDraftConfig,
)
from updated_notable_analysis.core.models import (
    AnalysisReport,
    EvidenceSection,
    InvestigationHypothesis,
)
from updated_notable_analysis.core.vocabulary import EvidenceType, HypothesisType


class TestServiceNowIncidentDraftBuilder(unittest.TestCase):
    """Behavior-focused tests for ServiceNow draft-only writeback."""

    def _report(self) -> AnalysisReport:
        """Return a valid report fixture."""
        return AnalysisReport(
            schema_version="1.0",
            alert_reconciliation={"status": "triaged", "severity": "high"},
            competing_hypotheses=(
                InvestigationHypothesis(
                    hypothesis_type=HypothesisType.ADVERSARY,
                    hypothesis="Credential misuse activity is likely.",
                    evidence_support=("failed authentication pattern",),
                    evidence_gaps=("endpoint process context pending",),
                    best_pivots=("user", "src_ip"),
                ),
            ),
            evidence_sections=(
                EvidenceSection(
                    evidence_type=EvidenceType.ALERT_DIRECT,
                    summary="Alert evidence indicates suspicious authentication behavior.",
                ),
                EvidenceSection(
                    evidence_type=EvidenceType.QUERY_RESULT,
                    summary="Approved SPL query returned three related events.",
                ),
            ),
            ioc_extraction={"users": ["jdoe"], "src_ips": ["10.0.0.5"]},
            ttp_analysis=({"technique_id": "T1110", "confidence": "medium"},),
            query_result_section={
                "status": "query_results_applied",
                "query_result_count": 1,
            },
            advisory_context_refs=("kb://soc/sop/auth-42",),
            metadata={"query_result_enriched": True},
        )

    def _builder(self, **overrides) -> ServiceNowIncidentDraftBuilder:  # noqa: ANN003
        """Return a ServiceNow draft builder fixture."""
        config_values = {
            "assignment_group": "Security Operations",
            "category": "security",
            "subcategory": "notable_analysis",
            "impact": "2",
            "urgency": "2",
        }
        config_values.update(overrides)
        return ServiceNowIncidentDraftBuilder(
            config=ServiceNowIncidentDraftConfig(**config_values)
        )

    def test_builder_creates_draft_only_servicenow_writeback_draft(self) -> None:
        """Builder should create a ServiceNow draft without downstream side effects."""
        draft = self._builder().build(
            self._report(),
            source_record_ref="notable-123",
            source_system="splunk",
            routing_key="secops-high",
        )

        self.assertEqual(draft.target_system, "servicenow")
        self.assertEqual(draft.target_operation, "incident_draft")
        self.assertEqual(draft.routing_key, "secops-high")
        self.assertEqual(draft.external_ref, "notable-123")
        self.assertEqual(draft.summary, "Security notable notable-123: triaged")
        self.assertIn("Updated Notable Analysis Report", draft.body)
        self.assertIn("Credential misuse activity is likely.", draft.body)
        self.assertIn("Approved SPL query returned three related events.", draft.body)
        self.assertEqual(draft.fields["short_description"], draft.summary)
        self.assertEqual(draft.fields["description"], draft.body)
        self.assertEqual(draft.fields["assignment_group"], "Security Operations")
        self.assertEqual(draft.fields["category"], "security")
        self.assertEqual(draft.fields["subcategory"], "notable_analysis")
        self.assertEqual(draft.fields["impact"], "2")
        self.assertEqual(draft.fields["urgency"], "2")
        self.assertEqual(draft.fields["source_system"], "splunk")
        self.assertEqual(draft.fields["source_record_ref"], "notable-123")
        self.assertIs(draft.fields["draft_only"], True)

    def test_builder_uses_assignment_group_as_default_routing_key(self) -> None:
        """Draft routing should default to the configured assignment group."""
        draft = self._builder().build(self._report(), source_record_ref="notable-123")

        self.assertEqual(draft.routing_key, "Security Operations")

    def test_builder_falls_back_to_hypothesis_when_status_missing(self) -> None:
        """Short description should remain useful without reconciliation status."""
        report = self._report()
        report.alert_reconciliation = {"severity": "high"}

        draft = self._builder().build(report, source_record_ref="notable-123")

        self.assertEqual(
            draft.summary,
            "Security notable notable-123: Credential misuse activity is likely.",
        )

    def test_builder_applies_summary_and_body_bounds(self) -> None:
        """Draft summary and body should be bounded deterministically."""
        draft = self._builder(max_summary_chars=24, max_body_chars=80).build(
            self._report(),
            source_record_ref="notable-123",
        )

        self.assertLessEqual(len(draft.summary), 24)
        self.assertLessEqual(len(draft.body), 80)
        self.assertTrue(draft.summary.endswith(" [truncated]"))
        self.assertTrue(draft.body.endswith(" [truncated]"))
        self.assertEqual(draft.fields["short_description"], draft.summary)
        self.assertEqual(draft.fields["description"], draft.body)

    def test_builder_rejects_malformed_config(self) -> None:
        """Malformed ServiceNow draft config should fail closed."""
        with self.assertRaises(ValueError):
            ServiceNowIncidentDraftConfig(assignment_group="")

        with self.assertRaises(ValueError):
            ServiceNowIncidentDraftConfig(
                assignment_group="Security Operations",
                max_summary_chars=0,
            )

    def test_builder_rejects_malformed_inputs(self) -> None:
        """Builder should reject malformed report and source references."""
        builder = self._builder()

        with self.assertRaises(ValueError):
            builder.build(object(), source_record_ref="notable-123")  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            builder.build(self._report(), source_record_ref="")

        with self.assertRaises(ValueError):
            builder.build(self._report(), source_record_ref="notable-123", source_system="")

    def test_builder_requires_config_contract(self) -> None:
        """Builder construction should require a ServiceNow config object."""
        with self.assertRaises(ValueError):
            ServiceNowIncidentDraftBuilder(config=object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
