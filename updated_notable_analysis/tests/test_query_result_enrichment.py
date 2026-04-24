"""Tests for deterministic query-result report enrichment."""

from __future__ import annotations

import unittest

from updated_notable_analysis.core.enrichment import (
    QueryResultEnrichmentInput,
    enrich_report_with_query_result,
)
from updated_notable_analysis.core.models import (
    AnalysisReport,
    EvidenceSection,
    InvestigationHypothesis,
    QueryPlan,
    QueryResultEvidence,
)
from updated_notable_analysis.core.vocabulary import (
    EvidenceType,
    HypothesisType,
    QueryDialect,
    QueryStrategy,
)


class TestQueryResultEnrichment(unittest.TestCase):
    """Behavior-focused tests for query-result-enriched analysis."""

    def _baseline_report(self) -> AnalysisReport:
        """Return a baseline report fixture."""
        return AnalysisReport(
            schema_version="1.0",
            alert_reconciliation={"status": "triaged"},
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
            ),
            ioc_extraction={"users": ["jdoe"]},
            ttp_analysis=({"technique_id": "T1110", "confidence": "medium"},),
            advisory_context_refs=("kb://soc/sop/auth-42",),
            metadata={"baseline": True},
        )

    def _query_plan(
        self,
        *,
        strategy: QueryStrategy = QueryStrategy.RESOLVE_UNKNOWN,
    ) -> QueryPlan:
        """Return a query-plan fixture."""
        return QueryPlan(
            query_dialect=QueryDialect.SPL,
            query_strategy=strategy,
            query_text="search index=main user=jdoe | stats count by src_ip",
            purpose="Check whether the user has related failed authentications.",
            time_range="1h",
            max_rows=50,
            execution_timeout_seconds=20,
            expected_signal="related failed authentication activity",
            grounding_refs=("hypothesis:credential-misuse",),
        )

    def _query_result(self, *, rows_returned: int | None = 3) -> QueryResultEvidence:
        """Return a query-result evidence fixture."""
        return QueryResultEvidence(
            evidence_type=EvidenceType.QUERY_RESULT,
            query_dialect=QueryDialect.SPL,
            query_text="search index=main user=jdoe | stats count by src_ip",
            result_summary="Three source IPs matched the follow-up query.",
            raw_result_ref="splunk-rest://search/spl_readonly_default/sid-123",
            rows_returned=rows_returned,
            execution_time_ms=42,
            metadata={"adapter": "splunk_rest"},
        )

    def test_enrich_report_adds_query_result_section_and_evidence(self) -> None:
        """Query-result enrichment should add explicit query evidence without mutation."""
        baseline = self._baseline_report()

        enriched = enrich_report_with_query_result(
            QueryResultEnrichmentInput(
                baseline_report=baseline,
                query_plan=self._query_plan(),
                query_result_evidence=self._query_result(),
            )
        )

        self.assertIsNot(enriched, baseline)
        self.assertEqual(baseline.query_result_section, {})
        self.assertEqual(len(baseline.evidence_sections), 1)
        self.assertEqual(enriched.query_result_section["status"], "query_results_applied")
        self.assertEqual(enriched.query_result_section["query_result_count"], 1)
        query_entry = enriched.query_result_section["query_results"][0]
        self.assertEqual(query_entry["query_strategy"], "resolve_unknown")
        self.assertEqual(query_entry["rows_returned"], 3)
        self.assertEqual(query_entry["hypothesis_effect"], "supports_expected_signal")
        self.assertEqual(enriched.evidence_sections[-1].evidence_type, EvidenceType.QUERY_RESULT)
        self.assertIn("Source: splunk-rest://search", enriched.evidence_sections[-1].summary)
        self.assertTrue(enriched.metadata["query_result_enriched"])
        self.assertEqual(enriched.metadata["query_result_count"], 1)

    def test_resolve_unknown_with_rows_adds_hypothesis_support(self) -> None:
        """Rows from resolve_unknown queries should support the hypothesis."""
        enriched = enrich_report_with_query_result(
            QueryResultEnrichmentInput(
                baseline_report=self._baseline_report(),
                query_plan=self._query_plan(),
                query_result_evidence=self._query_result(rows_returned=1),
            )
        )

        hypothesis = enriched.competing_hypotheses[0]
        self.assertEqual(len(hypothesis.evidence_support), 2)
        self.assertIn("supports_expected_signal", hypothesis.evidence_support[-1])
        self.assertEqual(len(hypothesis.evidence_gaps), 1)

    def test_resolve_unknown_without_rows_adds_hypothesis_gap(self) -> None:
        """Zero rows from resolve_unknown queries should remain an evidence gap."""
        enriched = enrich_report_with_query_result(
            QueryResultEnrichmentInput(
                baseline_report=self._baseline_report(),
                query_plan=self._query_plan(),
                query_result_evidence=self._query_result(rows_returned=0),
            )
        )

        hypothesis = enriched.competing_hypotheses[0]
        self.assertEqual(len(hypothesis.evidence_support), 1)
        self.assertIn("expected_signal_not_observed", hypothesis.evidence_gaps[-1])

    def test_contradiction_query_with_rows_adds_hypothesis_gap(self) -> None:
        """Rows from contradiction checks should be called out as contradiction evidence."""
        enriched = enrich_report_with_query_result(
            QueryResultEnrichmentInput(
                baseline_report=self._baseline_report(),
                query_plan=self._query_plan(strategy=QueryStrategy.CHECK_CONTRADICTION),
                query_result_evidence=self._query_result(rows_returned=2),
            )
        )

        hypothesis = enriched.competing_hypotheses[0]
        self.assertIn("contradiction_observed", hypothesis.evidence_gaps[-1])
        query_entry = enriched.query_result_section["query_results"][0]
        self.assertEqual(query_entry["hypothesis_effect"], "contradiction_observed")

    def test_contradiction_query_without_rows_adds_hypothesis_support(self) -> None:
        """Zero rows from contradiction checks should support the current hypothesis."""
        enriched = enrich_report_with_query_result(
            QueryResultEnrichmentInput(
                baseline_report=self._baseline_report(),
                query_plan=self._query_plan(strategy=QueryStrategy.CHECK_CONTRADICTION),
                query_result_evidence=self._query_result(rows_returned=0),
            )
        )

        hypothesis = enriched.competing_hypotheses[0]
        self.assertIn("contradiction_not_observed", hypothesis.evidence_support[-1])

    def test_enrichment_preserves_existing_query_result_entries(self) -> None:
        """Enrichment should append to prior query-result section entries."""
        baseline = self._baseline_report()
        baseline.query_result_section = {
            "status": "query_results_applied",
            "query_result_count": 1,
            "query_results": (
                {
                    "query_text": "search index=main old=true",
                    "raw_result_ref": "splunk-rest://old/sid-001",
                },
            ),
        }

        enriched = enrich_report_with_query_result(
            QueryResultEnrichmentInput(
                baseline_report=baseline,
                query_plan=self._query_plan(),
                query_result_evidence=self._query_result(),
            )
        )

        self.assertEqual(enriched.query_result_section["query_result_count"], 2)
        self.assertEqual(
            enriched.query_result_section["query_results"][0]["raw_result_ref"],
            "splunk-rest://old/sid-001",
        )

    def test_enrichment_rejects_mismatched_query_result_identity(self) -> None:
        """Query-result evidence must match the approved query plan identity."""
        bad_evidence = QueryResultEvidence(
            evidence_type=EvidenceType.QUERY_RESULT,
            query_dialect=QueryDialect.SPL,
            query_text="search index=main different=true",
            result_summary="Mismatched query.",
            raw_result_ref="splunk-rest://search/spl_readonly_default/sid-bad",
        )

        with self.assertRaises(ValueError):
            QueryResultEnrichmentInput(
                baseline_report=self._baseline_report(),
                query_plan=self._query_plan(),
                query_result_evidence=bad_evidence,
            )

    def test_enrichment_rejects_malformed_existing_query_result_entries(self) -> None:
        """Existing query-result section entries should fail closed if malformed."""
        baseline = self._baseline_report()
        baseline.query_result_section = {"query_results": ("not-a-mapping",)}

        with self.assertRaises(ValueError):
            enrich_report_with_query_result(
                QueryResultEnrichmentInput(
                    baseline_report=baseline,
                    query_plan=self._query_plan(),
                    query_result_evidence=self._query_result(),
                )
            )


if __name__ == "__main__":
    unittest.main()
