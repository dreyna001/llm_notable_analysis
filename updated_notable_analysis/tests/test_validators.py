"""Deterministic tests for shared core validator functions."""

from __future__ import annotations

import unittest

from updated_notable_analysis.core.models import (
    AnalysisReport,
    EvidenceSection,
    InvestigationHypothesis,
    QueryPlan,
    WritebackDraft,
)
from updated_notable_analysis.core.validators import (
    validate_analysis_report_contract,
    validate_query_plan_contract,
    validate_writeback_draft_contract,
)
from updated_notable_analysis.core.vocabulary import EvidenceType, HypothesisType, QueryDialect, QueryStrategy


class TestCoreValidators(unittest.TestCase):
    """Behavior-focused tests for validator contract checks."""

    def test_validate_query_plan_contract_accepts_query_plan(self) -> None:
        """QueryPlan contract validator should accept valid plans."""
        plan = QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=QueryStrategy.RESOLVE_UNKNOWN,
            query_text="search index=main | stats count",
            purpose="close evidence gap",
        )
        validate_query_plan_contract(plan)

    def test_validate_writeback_draft_contract_rejects_wrong_type(self) -> None:
        """Writeback draft contract validator should reject non-draft input."""
        with self.assertRaises(ValueError):
            validate_writeback_draft_contract({"target_system": "servicenow"})

    def test_validate_analysis_report_contract_accepts_supported_sections(self) -> None:
        """Analysis report validation should allow supported evidence types."""
        report = AnalysisReport(
            schema_version="1.0",
            alert_reconciliation={"status": "reviewed"},
            competing_hypotheses=[
                InvestigationHypothesis(
                    hypothesis_type=HypothesisType.BENIGN,
                    hypothesis="Likely expected behavior.",
                    evidence_support=["known scanner"],
                    evidence_gaps=["owner confirmation"],
                )
            ],
            evidence_sections=[
                EvidenceSection(
                    evidence_type=EvidenceType.ALERT_DIRECT,
                    summary="direct alert facts",
                )
            ],
            ioc_extraction={"ips": []},
            ttp_analysis=[{"technique_id": "T0000", "confidence": "low"}],
        )
        validate_analysis_report_contract(report)

    def test_validate_analysis_report_contract_rejects_wrong_type(self) -> None:
        """Analysis report validation should reject non-report inputs."""
        with self.assertRaises(ValueError):
            validate_analysis_report_contract({"schema_version": "1.0"})

    def test_writeback_draft_validation_failure(self) -> None:
        """Writeback draft model should fail when required strings are empty."""
        with self.assertRaises(ValueError):
            WritebackDraft(
                target_system="servicenow",
                target_operation="create_ticket",
                summary="",
                body="ticket body",
            )


if __name__ == "__main__":
    unittest.main()

