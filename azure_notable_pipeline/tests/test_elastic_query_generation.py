"""Tests for Elasticsearch query generation helpers."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.elastic_query_generation import (
    build_elastic_query_generation_prompt,
    merge_elastic_query_fields_by_position,
    validate_elastic_query_contract,
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


def _elastic_query(index_pattern: str = "logs-*") -> dict[str, object]:
    return {
        "index_pattern": index_pattern,
        "body": {
            "size": 25,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"user": "alice"}},
                        {"range": {"@timestamp": {"gte": "now-24h", "lte": "now"}}},
                    ]
                }
            },
        },
    }


def _generated_query(index_pattern: str = "logs-*") -> dict[str, object]:
    return {
        "competing_hypotheses": [
            {
                "query_strategy": "resolve_unknown",
                "primary_elastic_query": _elastic_query(index_pattern),
                "why_this_query": "Finds user activity in allowed logs.",
                "supports_if": "Related events exist.",
                "weakens_if": "No events exist.",
            }
            for _ in range(6)
        ]
    }


class ElasticQueryGenerationTests(unittest.TestCase):
    """Elastic generation contract tests."""

    def test_prompt_contains_hypotheses_and_grounding(self) -> None:
        prompt = build_elastic_query_generation_prompt(
            alert_text="user=alice",
            hypotheses=_hypotheses(),
            elasticsearch_grounding_context=(
                "ELASTICSEARCH_GROUNDING_CONTEXT\n"
                "[1] [elastic.md :: indexes] logs-* user @timestamp"
            ),
        )

        self.assertIn("INPUT_COMPETING_HYPOTHESES", prompt)
        self.assertIn("ELASTICSEARCH_GROUNDING_CONTEXT", prompt)
        self.assertIn("Return ONLY a single JSON object", prompt)
        self.assertIn("unvalidated draft investigation guidance", prompt)
        self.assertIn("ELASTICSEARCH QUERY CONTEXT RULES", prompt)

    def test_contract_denies_unallowlisted_index(self) -> None:
        ok, error = validate_elastic_query_contract(
            _generated_query("unknown-*"),
            alert_text="user=alice",
            elasticsearch_grounding_context=(
                "ELASTICSEARCH_GROUNDING_CONTEXT\n"
                "[1] [elastic.md :: indexes] logs-* user @timestamp"
            ),
            allowed_fields="@timestamp,user",
            allowed_index_patterns="logs-*",
            allow_wildcard_indexes=True,
            require_elastic_grounding=True,
        )

        self.assertFalse(ok)
        self.assertIn("not allowlisted", str(error))

    def test_contract_denies_query_string_clause(self) -> None:
        payload = _generated_query("logs-*")
        payload["competing_hypotheses"][0]["primary_elastic_query"] = {
            "index_pattern": "logs-*",
            "body": {
                "size": 25,
                "query": {"query_string": {"query": "user:alice"}},
                "range": {"@timestamp": {"gte": "now-24h", "lte": "now"}},
            },
        }

        ok, error = validate_elastic_query_contract(
            payload,
            alert_text="user=alice",
            elasticsearch_grounding_context=(
                "ELASTICSEARCH_GROUNDING_CONTEXT\n"
                "[1] [elastic.md :: indexes] logs-* user @timestamp"
            ),
            allowed_fields="@timestamp,user",
            allowed_index_patterns="logs-*",
            allow_wildcard_indexes=True,
            require_elastic_grounding=True,
        )

        self.assertFalse(ok)
        self.assertIn("denied DSL key", str(error))

    def test_merge_adds_queries_and_grounding_refs_by_position(self) -> None:
        merged = merge_elastic_query_fields_by_position(
            base_hypotheses=_hypotheses(),
            generated_payload=_generated_query("logs-*"),
            elasticsearch_grounding_context=(
                "ELASTICSEARCH_GROUNDING_CONTEXT\n"
                "[1] [elastic.md :: indexes] logs-* user @timestamp"
            ),
        )

        self.assertEqual(len(merged), 6)
        self.assertEqual(merged[0]["primary_elastic_query"]["index_pattern"], "logs-*")
        self.assertEqual(
            merged[0]["primary_elastic_query_grounding_refs"],
            [{"source_file": "elastic.md", "section_path": "indexes"}],
        )


if __name__ == "__main__":
    unittest.main()
