"""Tests for query-result interpretation prompt and validation."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.query_result_interpretation import (
    build_query_result_interpretation_context,
    build_query_result_interpretation_prompt,
    merge_query_result_interpretation,
    validate_query_result_interpretation_payload,
)


def _analysis() -> dict[str, object]:
    return {
        "alert_reconciliation": {"confidence": 0.4, "verdict": "unknown"},
        "competing_hypotheses": [{"hypothesis": "benign"}, {"hypothesis": "adversary"}],
        "query_result_section": {
            "summary": {"attempted": 1, "executed": 1, "denied": 0, "failed": 0, "skipped": 0},
            "queries": [
                {
                    "hypothesis_index": 1,
                    "query": "index=main user=alice",
                    "status": "executed",
                    "result_count": 1,
                    "search_reference": "sid-1",
                    "sample_rows": [{"user": "alice", "host": "server1"}],
                }
            ],
        },
    }


class QueryResultInterpretationTests(unittest.TestCase):
    """Interpretation validator tests."""

    def test_prompt_sets_mutation_and_grounding_boundaries(self) -> None:
        prompt = build_query_result_interpretation_prompt(
            "alert",
            _analysis(),
            context_budget_chars=4000,
            max_sample_rows=1,
        )

        self.assertIn("Do not invent events", prompt)
        self.assertIn("zero-result query is not automatically exculpatory", prompt)
        self.assertIn("read-only investigation query results", prompt)
        self.assertIn("source_query_refs may include only", prompt)

    def test_context_prunes_to_budget(self) -> None:
        context = build_query_result_interpretation_context(
            "alert" * 1000,
            _analysis(),
            context_budget_chars=800,
            max_sample_rows=1,
        )

        self.assertLess(len(str(context)), 1800)

    def test_validator_rejects_unknown_query_refs(self) -> None:
        ok, error, normalized = validate_query_result_interpretation_payload(
            {
                "query_result_interpretation": [
                    {
                        "hypothesis_index": 1,
                        "assessment": "supports",
                        "confidence_delta": "increase",
                        "rationale": "Rows show related activity.",
                        "key_observations": [],
                        "remaining_gaps": [],
                        "source_query_refs": ["unknown"],
                    }
                ]
            },
            _analysis(),
        )

        self.assertFalse(ok)
        self.assertIn("unknown ref", str(error))
        self.assertEqual(normalized, {})

    def test_merge_preserves_existing_confidence_and_query_section(self) -> None:
        analysis = _analysis()
        payload = {
            "query_result_interpretation": [
                {
                    "hypothesis_index": 1,
                    "assessment": "supports",
                    "confidence_delta": "increase",
                    "rationale": "Rows show related activity.",
                    "key_observations": ["alice appears"],
                    "remaining_gaps": [],
                    "source_query_refs": ["sid-1"],
                }
            ]
        }
        ok, _error, normalized = validate_query_result_interpretation_payload(payload, analysis)

        merged = merge_query_result_interpretation(analysis, normalized)

        self.assertTrue(ok)
        self.assertEqual(merged["alert_reconciliation"]["confidence"], 0.4)
        self.assertEqual(merged["query_result_section"], analysis["query_result_section"])
        self.assertEqual(merged["query_result_interpretation"][0]["source_query_refs"], ["sid-1"])


if __name__ == "__main__":
    unittest.main()
