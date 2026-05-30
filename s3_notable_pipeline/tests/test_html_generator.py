"""Tests for deterministic HTML report generation."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.html_generator import generate_html_report


class HtmlGeneratorTests(unittest.TestCase):
    """HTML report behavior tests."""

    def test_html_report_escapes_untrusted_values(self) -> None:
        """Generated HTML should escape alert and model-controlled text."""
        html = generate_html_report(
            "<script>alert(1)</script>",
            {
                "alert_reconciliation": {
                    "verdict": "<bad>",
                    "confidence": 0.7,
                    "one_sentence_summary": "summary",
                    "decision_drivers": ["<driver>"],
                }
            },
            [{"ttp_id": "T1059", "ttp_name": "<PowerShell>", "score": 0.9}],
            "# Report\n<script>",
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;bad&gt;", html)
        self.assertIn("&lt;PowerShell&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_query_results_and_interpretation_are_rendered_and_escaped(self) -> None:
        """Query result sections should render without trusting model text."""
        html = generate_html_report(
            "alert",
            {
                "alert_reconciliation": {"verdict": "unknown", "confidence": 0.5},
                "query_result_section": {
                    "queries": [
                        {
                            "hypothesis_index": 0,
                            "status": "executed",
                            "result_count": 1,
                            "search_reference": "sid-1",
                            "query": "index=main <bad>",
                        }
                    ]
                },
                "query_result_interpretation": [
                    {
                        "hypothesis_index": 0,
                        "assessment": "supports",
                        "confidence_delta": "increase",
                        "rationale": "<script>bad()</script>",
                        "key_observations": ["<row>"],
                    }
                ],
            },
            [],
            "markdown",
        )

        self.assertIn("Query Results", html)
        self.assertIn("Query Result Interpretation", html)
        self.assertIn("index=main &lt;bad&gt;", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>bad()</script>", html)


if __name__ == "__main__":
    unittest.main()
