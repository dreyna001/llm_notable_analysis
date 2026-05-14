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

    def test_query_results_section_renders_when_present(self) -> None:
        llm_response = {
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "hypothesis": "expected admin activity",
                    "query_result_summary": "Query executed with 2 result(s).",
                    "query_result_reference": "sid-123",
                }
            ],
            "query_result_section": {
                "summary": {
                    "attempted": 2,
                    "executed": 1,
                    "denied": 1,
                    "failed": 0,
                    "skipped": 0,
                },
                "queries": [
                    {
                        "hypothesis_index": 0,
                        "status": "executed",
                        "query_strategy": "resolve_unknown",
                        "query": "search index=main user=admin | head 50",
                        "result_count": 2,
                        "sample_columns": ["host", "user"],
                        "search_reference": "sid-123",
                    },
                    {
                        "hypothesis_index": 1,
                        "status": "denied",
                        "query_strategy": "check_contradiction",
                        "query": "search index=secret user=admin | head 50",
                        "message": "query index is not in allowed index policy",
                    },
                ],
            },
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }
        markdown = generate_markdown_report("alert", llm_response, [])
        self.assertIn("### Query Results", markdown)
        self.assertIn("attempted=2, executed=1, denied=1", markdown)
        self.assertIn("status=executed, hypothesis=1", markdown)
        self.assertIn("**Search reference:** sid-123", markdown)
        self.assertIn("query index is not in allowed index policy", markdown)

    def test_query_result_annotations_render_under_hypotheses(self) -> None:
        llm_response = {
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "hypothesis": "expected admin activity",
                    "query_result_summary": "Query executed with 2 result(s).",
                    "query_result_reference": "sid-123",
                }
            ],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }
        markdown = generate_markdown_report("alert", llm_response, [])
        self.assertIn("Query result summary", markdown)
        self.assertIn("Query executed with 2 result(s).", markdown)
        self.assertIn("Query result reference", markdown)
        self.assertIn("sid-123", markdown)

    def test_query_result_interpretation_renders_after_deterministic_results(self) -> None:
        llm_response = {
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "adversary",
                    "hypothesis": "periodic beaconing",
                    "query_result_summary": "Query executed with 42 result(s).",
                    "query_result_reference": "sid-beacon-1",
                }
            ],
            "query_result_section": {
                "summary": {
                    "attempted": 1,
                    "executed": 1,
                    "denied": 0,
                    "failed": 0,
                    "skipped": 0,
                },
                "queries": [
                    {
                        "hypothesis_index": 0,
                        "status": "executed",
                        "query_strategy": "resolve_unknown",
                        "query": "search index=proxy src_ip=10.0.0.5 | head 50",
                        "result_count": 42,
                        "sample_columns": ["src_ip", "dest_domain"],
                        "search_reference": "sid-beacon-1",
                    }
                ],
            },
            "query_result_interpretation": [
                {
                    "hypothesis_index": 0,
                    "assessment": "supports",
                    "confidence_delta": "increase",
                    "rationale": "Repeated proxy events support periodic beaconing.",
                    "key_observations": ["42 matching proxy events"],
                    "remaining_gaps": ["Endpoint process was not returned"],
                    "source_query_refs": ["sid-beacon-1"],
                }
            ],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }

        markdown = generate_markdown_report("alert", llm_response, [])

        self.assertIn("### Query Results", markdown)
        self.assertIn("### Query Result Interpretation", markdown)
        self.assertLess(
            markdown.find("### Query Results"),
            markdown.find("### Query Result Interpretation"),
        )
        self.assertIn("confidence movement=increase", markdown)
        self.assertIn("Confidence movement is not a score update", markdown)

    def test_query_result_interpretation_escapes_model_markdown(self) -> None:
        llm_response = {
            "query_result_interpretation": [
                {
                    "hypothesis_index": 0,
                    "assessment": "supports",
                    "confidence_delta": "increase",
                    "rationale": "[click](http://evil.example) <script>alert(1)</script>",
                    "key_observations": ["![x](http://evil.example/img.png)"],
                    "remaining_gaps": ["`code` and *emphasis*"],
                    "source_query_refs": ["sid-[1]"],
                }
            ],
            "ttp_analysis": [],
        }

        markdown = generate_markdown_report("alert", llm_response, [])

        self.assertNotIn("[click](http://evil.example)", markdown)
        self.assertNotIn("![x](http://evil.example/img.png)", markdown)
        self.assertIn("\\[click\\]\\(http://evil\\.example\\)", markdown)
        self.assertIn("\\<script\\>alert\\(1\\)\\</script\\>", markdown)

    def test_servicenow_section_renders_when_present(self) -> None:
        llm_response = {
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [],
            "servicenow_section": {
                "draft": {"status": "success", "message": "ServiceNow draft created"},
                "create": {
                    "status": "denied",
                    "message": "ServiceNow create denied: explicit approval is required",
                    "number": "",
                    "sys_id": "",
                    "approval": {},
                },
            },
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }
        markdown = generate_markdown_report("alert", llm_response, [])
        self.assertIn("### ServiceNow", markdown)
        self.assertIn("Draft status", markdown)
        self.assertIn("Create status", markdown)
        self.assertIn("explicit approval is required", markdown)


if __name__ == "__main__":
    unittest.main()
