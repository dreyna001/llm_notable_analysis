"""Tests for deterministic query-result enrichment."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.query_result_enrichment import enrich_analysis_with_query_results


class QueryResultEnrichmentTests(unittest.TestCase):
    """Query result enrichment behavior tests."""

    def test_enrichment_adds_summary_and_hypothesis_annotations(self) -> None:
        analysis = {
            "competing_hypotheses": [
                {"hypothesis": "benign"},
                {"hypothesis": "adversary"},
            ],
            "evidence_vs_inference": {"evidence": ["field=value"], "inferences": []},
        }
        query_results = [
            {
                "hypothesis_index": 1,
                "query_strategy": "resolve_unknown",
                "query": "index=main user=alice",
                "status": "success",
                "result_count": 2,
                "sample_columns": ["user"],
                "sample_rows": [{"user": "alice"}],
                "search_id": "sid-1",
            },
            {
                "hypothesis_index": 0,
                "query": "index=blocked",
                "status": "denied",
                "message": "index denied",
            },
        ]

        enriched = enrich_analysis_with_query_results(analysis, query_results)

        self.assertEqual(
            enriched["query_result_section"]["summary"],
            {"attempted": 2, "executed": 1, "denied": 1, "failed": 0, "skipped": 0},
        )
        self.assertEqual(enriched["query_result_section"]["queries"][0]["status"], "executed")
        self.assertEqual(enriched["competing_hypotheses"][1]["query_result_reference"], "sid-1")
        self.assertEqual(
            enriched["evidence_vs_inference"],
            {"evidence": ["field=value"], "inferences": []},
        )

    def test_empty_query_results_are_noop_copy(self) -> None:
        analysis = {"competing_hypotheses": [{"hypothesis": "benign"}]}

        enriched = enrich_analysis_with_query_results(analysis, [])

        self.assertEqual(enriched, analysis)
        self.assertIsNot(enriched, analysis)


if __name__ == "__main__":
    unittest.main()
