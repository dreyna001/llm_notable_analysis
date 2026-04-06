"""Behavior tests for markdown report generation."""

import unittest
from copy import deepcopy

from onprem_service.markdown_generator import generate_markdown_report


class TestMarkdownGenerator(unittest.TestCase):
    """Validate report structure and guardrail-oriented rendering."""

    def test_section_order_and_confidence_buckets(self) -> None:
        """Renders expected section order and confidence bucket headers."""
        llm_response = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.88",
                "one_sentence_summary": "Suspicious auth activity appears adversarial.",
                "decision_drivers": ["failed logins then success"],
                "recommended_actions": ["disable account"],
            },
            "competing_hypotheses": [
                {"hypothesis_type": "adversary", "hypothesis": "Password spraying"}
            ],
            "evidence_vs_inference": {
                "evidence": ["user=admin"],
                "inferences": ["possible credential access"],
            },
            "ioc_extraction": {"ip_addresses": ["203.0.113.45"]},
        }
        scored_ttps = [
            {"ttp_id": "T1110", "ttp_name": "Brute Force", "score": 0.90},
            {"ttp_id": "T1078", "ttp_name": "Valid Accounts", "score": 0.70},
            {"ttp_id": "T1566", "ttp_name": "Phishing", "score": 0.20},
            {"ttp_id": "T0000", "ttp_name": "No score provided"},
        ]

        markdown = generate_markdown_report("alert", llm_response, scored_ttps)

        headers = [
            "### Alert Reconciliation",
            "### Competing Hypotheses & Pivots",
            "### Evidence vs Inference",
            "### Indicators of Compromise (IOCs)",
            "### Scored TTPs",
        ]
        positions = [markdown.find(header) for header in headers]
        self.assertTrue(all(pos >= 0 for pos in positions))
        self.assertEqual(positions, sorted(positions))

        self.assertIn("#### High Confidence (>=0.80)", markdown)
        self.assertIn("#### Medium Confidence (0.50-0.79)", markdown)
        self.assertIn("#### Low Confidence (<0.50)", markdown)
        self.assertIn("**T0000** - No score provided: **0.000**", markdown)

    def test_output_is_deterministic_for_same_input(self) -> None:
        """Returns identical markdown for repeated equivalent inputs."""
        llm_response = {
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
        }
        scored_ttps = [{"ttp_id": "T1110", "ttp_name": "Brute Force", "score": 0.6}]

        out1 = generate_markdown_report(
            "alert",
            deepcopy(llm_response),
            deepcopy(scored_ttps),
        )
        out2 = generate_markdown_report(
            "alert",
            deepcopy(llm_response),
            deepcopy(scored_ttps),
        )
        self.assertEqual(out1, out2)

    def test_poc_fallback_renders_raw_block_first_and_escapes_fences(self) -> None:
        """Keeps raw model text in PoC block and escapes triple-tilde fences."""
        llm_response = {
            "poc_unstructured_output": True,
            "poc_fallback_reason": "schema validation failed",
            "raw_response": "line1\n~~~line2",
            "alert_reconciliation": {"verdict": "unknown"},
            "competing_hypotheses": [],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
        }

        markdown = generate_markdown_report("alert", llm_response, [])
        pos_poc = markdown.find("## PoC: raw model output")
        pos_recon = markdown.find("### Alert Reconciliation")
        self.assertGreaterEqual(pos_poc, 0)
        self.assertGreater(pos_recon, pos_poc)
        self.assertIn("~~~text", markdown)
        self.assertIn("~\\~~\\~~line2", markdown)

    def test_spl_details_render_only_when_enabled(self) -> None:
        """Renders SPL details only when SPL generation is enabled and available."""
        response_enabled = {
            "metadata": {"spl_query_generation_enabled": True},
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "hypothesis": "expected admin activity",
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search user=admin",
                    "why_this_query": "test hypothesis",
                    "supports_if": "baseline match",
                    "weakens_if": "first seen",
                }
            ],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
        }
        response_disabled = deepcopy(response_enabled)
        response_disabled["metadata"]["spl_query_generation_enabled"] = False

        enabled = generate_markdown_report("alert", response_enabled, [])
        disabled = generate_markdown_report("alert", response_disabled, [])

        self.assertIn("**Primary SPL query:**", enabled)
        self.assertIn("```spl", enabled)
        self.assertNotIn("**Primary SPL query:**", disabled)
        self.assertNotIn("```spl", disabled)

    def test_spl_unavailable_adds_note_and_skips_query_blocks(self) -> None:
        """Shows SPL unavailable note and omits query block rendering."""
        llm_response = {
            "metadata": {
                "spl_query_generation_enabled": True,
                "spl_query_generation_unavailable": True,
                "spl_query_generation_unavailable_reason": "contract validation failed",
            },
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "hypothesis": "expected admin activity",
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search user=admin",
                }
            ],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
        }

        markdown = generate_markdown_report("alert", llm_response, [])
        self.assertIn("SPL query generation was enabled but unavailable", markdown)
        self.assertIn("contract validation failed", markdown)
        self.assertNotIn("```spl", markdown)


if __name__ == "__main__":
    unittest.main()
