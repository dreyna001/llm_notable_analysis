"""Tests for SPL query generation helpers."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.spl_query_generation import (
    build_spl_query_generation_prompt,
    merge_spl_query_fields_by_position,
    validate_spl_query_contract,
)


def _hypotheses() -> list[dict[str, object]]:
    return [
        {
            "hypothesis_type": "benign" if i < 3 else "adversary",
            "hypothesis": f"hypothesis {i}",
            "evidence_support": [],
            "evidence_gaps": [],
            "best_pivots": [],
        }
        for i in range(6)
    ]


def _generated_query(index: str = "main") -> dict[str, object]:
    return {
        "competing_hypotheses": [
            {
                "query_strategy": "resolve_unknown",
                "primary_spl_query": f"index={index} user=alice | stats count",
                "why_this_query": "Counts related events.",
                "supports_if": "Related events exist.",
                "weakens_if": "No events exist.",
            }
            for i in range(6)
        ]
    }


class SplQueryGenerationTests(unittest.TestCase):
    """SPL generation contract tests."""

    def test_prompt_contains_hypotheses_and_grounding(self) -> None:
        prompt = build_spl_query_generation_prompt(
            alert_text="user=alice index=main",
            hypotheses=_hypotheses(),
            spl_query_grounding_context="SPL_QUERY_GROUNDING_CONTEXT\n[1] [spl.md :: indexes] main",
        )

        self.assertIn("INPUT_COMPETING_HYPOTHESES", prompt)
        self.assertIn("SPL_QUERY_GROUNDING_CONTEXT", prompt)
        self.assertIn("Return ONLY a single JSON object", prompt)
        self.assertIn("unvalidated draft investigation guidance", prompt)
        self.assertIn("ALERT_TIME is provided", prompt)

    def test_contract_requires_grounded_environment_tokens(self) -> None:
        ok, error = validate_spl_query_contract(
            _generated_query("unknown"),
            alert_text="user=alice",
            spl_query_grounding_context="SPL_QUERY_GROUNDING_CONTEXT\n[1] [spl.md :: indexes] main",
            require_spl_grounding=True,
        )

        self.assertFalse(ok)
        self.assertIn("ungrounded index", str(error))

    def test_contract_accepts_schema_without_hypothesis_type(self) -> None:
        ok, error = validate_spl_query_contract(
            _generated_query("main"),
            alert_text="user=alice",
            allowed_indexes="main",
        )

        self.assertTrue(ok, error)

    def test_merge_adds_queries_and_grounding_refs_by_position(self) -> None:
        merged = merge_spl_query_fields_by_position(
            base_hypotheses=_hypotheses(),
            generated_payload=_generated_query("main"),
            spl_query_grounding_context="SPL_QUERY_GROUNDING_CONTEXT\n[1] [spl.md :: indexes] main index",
        )

        self.assertEqual(len(merged), 6)
        self.assertEqual(merged[0]["primary_spl_query"], "index=main user=alice | stats count")
        self.assertEqual(
            merged[0]["primary_spl_query_grounding_refs"],
            [{"source_file": "spl.md", "section_path": "indexes"}],
        )


if __name__ == "__main__":
    unittest.main()
