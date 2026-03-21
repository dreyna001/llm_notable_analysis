import unittest
from copy import deepcopy

from llm_notable_analysis_onprem.onprem_service.markdown_generator import (
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


if __name__ == "__main__":
    unittest.main()
