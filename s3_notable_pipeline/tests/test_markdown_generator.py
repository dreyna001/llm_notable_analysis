"""Tests for markdown report rendering."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.markdown_generator import generate_markdown_report


class MarkdownGeneratorTests(unittest.TestCase):
    """Markdown rendering tests."""

    def test_elasticsearch_query_is_rendered_in_hypothesis(self) -> None:
        report = generate_markdown_report(
            alert_text="user=alice",
            llm_response={
                "competing_hypotheses": [
                    {
                        "hypothesis_type": "adversary",
                        "hypothesis": "Suspicious user activity",
                        "primary_elastic_query": {
                            "index_pattern": "logs-*",
                            "body": {
                                "size": 10,
                                "query": {
                                    "bool": {
                                        "filter": [
                                            {"term": {"user": "alice"}},
                                            {
                                                "range": {
                                                    "@timestamp": {
                                                        "gte": "now-24h",
                                                        "lte": "now",
                                                    }
                                                }
                                            },
                                        ]
                                    }
                                },
                            },
                        },
                        "primary_elastic_query_grounding_refs": [
                            {"source_file": "elastic.md", "section_path": "indexes"}
                        ],
                    }
                ]
            },
            scored_ttps=[],
        )

        self.assertIn("Primary Elasticsearch query", report)
        self.assertIn('"index_pattern": "logs-*"', report)
        self.assertIn("Elasticsearch grounding refs", report)
        self.assertIn("elastic.md :: indexes", report)


if __name__ == "__main__":
    unittest.main()
