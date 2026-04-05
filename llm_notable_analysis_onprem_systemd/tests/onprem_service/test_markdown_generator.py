import unittest
from copy import deepcopy

from llm_notable_analysis_onprem_systemd.onprem_service.markdown_generator import (
    generate_markdown_report,
)


class TestMarkdownGenerator(unittest.TestCase):
    def test_section_order_matches_onprem_contract(self) -> None:
        llm_response = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.88",
                "one_sentence_summary": "Suspicious auth activity appears adversarial.",
                "decision_drivers": ["failed logins then success"],
                "recommended_actions": ["disable account"],
            },
            "competing_hypotheses": [
                {
                    "hypothesis_type": "adversary",
                    "hypothesis": "Password spraying",
                    "evidence_support": ["user=admin"],
                    "evidence_gaps": ["missing MFA logs"],
                    "best_pivots": [
                        {"log_source": "auth", "key_fields": ["user", "src_ip"]}
                    ],
                }
            ],
            "evidence_vs_inference": {
                "evidence": ["user=admin"],
                "inferences": ["possible credential access"],
            },
            "ioc_extraction": {
                "ip_addresses": ["203.0.113.45"],
                "domains": [],
                "user_accounts": ["admin"],
                "hostnames": [],
                "process_names": [],
                "file_paths": [],
                "file_hashes": [],
                "event_ids": [],
                "urls": [],
            },
        }
        scored_ttps = [
            {
                "ttp_id": "T1110",
                "ttp_name": "Brute Force",
                "score": 0.81,
                "explanation": "Observed repeated failures. Uncertainty: lacks MFA telemetry.",
                "evidence_fields": ["user=admin"],
            }
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

    def test_alert_reconciliation_renders_with_missing_optional_fields(self) -> None:
        llm_response = {"alert_reconciliation": {"verdict": "uncertain"}}
        markdown = generate_markdown_report("alert", llm_response, [])

        self.assertIn("### Alert Reconciliation", markdown)
        self.assertIn("**Verdict:** uncertain", markdown)
        self.assertIn("**Confidence:** N/A", markdown)
        self.assertIn("**Summary:** N/A", markdown)

    def test_markdown_render_is_deterministic_for_same_input(self) -> None:
        llm_response = {
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [],
            "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
            "ioc_extraction": {
                "ip_addresses": [],
                "domains": [],
                "user_accounts": [],
                "hostnames": [],
                "process_names": [],
                "file_paths": [],
                "file_hashes": [],
                "event_ids": [],
                "urls": [],
            },
        }
        scored_ttps = [
            {
                "ttp_id": "T1110",
                "ttp_name": "Brute Force",
                "score": 0.6,
                "explanation": "x",
            }
        ]

        out1 = generate_markdown_report(
            "alert", deepcopy(llm_response), deepcopy(scored_ttps)
        )
        out2 = generate_markdown_report(
            "alert", deepcopy(llm_response), deepcopy(scored_ttps)
        )

        self.assertEqual(out1, out2)

    def test_poc_unstructured_output_renders_raw_block_first(self) -> None:
        llm_response = {
            "poc_unstructured_output": True,
            "poc_fallback_reason": "schema test",
            "raw_response": '{"partial": true}',
            "alert_reconciliation": {
                "verdict": "poc_raw_output_only",
                "confidence": "n/a",
                "one_sentence_summary": "stub",
                "decision_drivers": [],
                "recommended_actions": [],
            },
            "competing_hypotheses": [],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
        }
        md = generate_markdown_report("alert text", llm_response, [])
        pos_poc = md.find("## PoC: raw model output")
        pos_ar = md.find("### Alert Reconciliation")
        self.assertGreaterEqual(pos_poc, 0)
        self.assertGreater(pos_ar, pos_poc)
        self.assertIn("~~~text", md)
        self.assertIn('{"partial": true}', md)

    def test_hypothesis_spl_renders_when_enabled(self) -> None:
        llm_response = {
            "metadata": {"spl_query_generation_enabled": True},
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "hypothesis": "expected admin activity",
                    "evidence_support": ["user=admin"],
                    "evidence_gaps": ["missing baseline"],
                    "best_pivots": [],
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search user=admin host=wkstn-22 earliest=-7d",
                    "why_this_query": "tests historical frequency",
                    "supports_if": "pattern repeats",
                    "weakens_if": "pattern is first-seen",
                }
            ],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }
        markdown = generate_markdown_report("alert", llm_response, [])
        self.assertIn("**Query strategy:** resolve_unknown", markdown)
        self.assertIn("**Primary SPL query:**", markdown)
        self.assertIn("```spl", markdown)
        self.assertIn("supports hypothesis if", markdown.lower())

    def test_hypothesis_spl_not_rendered_when_disabled(self) -> None:
        llm_response = {
            "metadata": {"spl_query_generation_enabled": False},
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "hypothesis": "expected admin activity",
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search user=admin",
                    "why_this_query": "x",
                    "supports_if": "y",
                    "weakens_if": "z",
                }
            ],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }
        markdown = generate_markdown_report("alert", llm_response, [])
        self.assertNotIn("**Primary SPL query:**", markdown)
        self.assertNotIn("```spl", markdown)

    def test_hypothesis_spl_unavailable_note_renders(self) -> None:
        llm_response = {
            "metadata": {
                "spl_query_generation_enabled": True,
                "spl_query_generation_unavailable": True,
                "spl_query_generation_unavailable_reason": "contract validation failed",
            },
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [
                {"hypothesis_type": "benign", "hypothesis": "expected admin activity"}
            ],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }
        markdown = generate_markdown_report("alert", llm_response, [])
        self.assertIn("SPL query generation was enabled but unavailable", markdown)
        self.assertIn("contract validation failed", markdown)
        self.assertNotIn("**Primary SPL query:**", markdown)


if __name__ == "__main__":
    unittest.main()
