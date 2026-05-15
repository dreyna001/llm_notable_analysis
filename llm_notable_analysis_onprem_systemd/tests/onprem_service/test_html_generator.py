import unittest

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.html_generator import (
    generate_html_report,
)


class TestHtmlGenerator(unittest.TestCase):
    def _base_response(self) -> dict:
        return {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.81",
                "one_sentence_summary": "Suspicious auth chain observed.",
                "decision_drivers": ["failed logins followed by success"],
                "recommended_actions": ["disable account"],
            },
            "competing_hypotheses": [
                {
                    "hypothesis_type": "adversary",
                    "hypothesis": "Credential access",
                    "evidence_support": ["user=admin"],
                    "evidence_gaps": ["missing MFA logs"],
                    "best_pivots": [{"log_source": "auth", "key_fields": ["user"]}],
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
            "ttp_analysis": [
                {
                    "ttp_id": "T1110",
                    "ttp_name": "Brute Force",
                    "score": 0.81,
                    "explanation": "Repeated failures observed.",
                }
            ],
        }

    def test_base_report_renders_core_tabs_without_optional_sections(self) -> None:
        html = generate_html_report(
            "alert text",
            self._base_response(),
            self._base_response()["ttp_analysis"],
        )

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Alert Reconciliation", html)
        self.assertIn('data-tab="verdict"', html)
        self.assertIn('data-tab="hypotheses"', html)
        self.assertIn('data-tab="ttps"', html)
        self.assertIn('data-tab="iocs"', html)
        self.assertNotIn('data-tab="queries"', html)
        self.assertNotIn('data-tab="servicenow"', html)
        self.assertIn("overflow-y: scroll", html)

    def test_optional_query_interpretation_and_servicenow_sections_render_when_present(
        self,
    ) -> None:
        response = self._base_response()
        response["query_result_section"] = {
            "summary": {"attempted": 1, "executed": 1, "denied": 0, "failed": 0},
            "queries": [
                {
                    "hypothesis_index": 0,
                    "status": "executed",
                    "query": "search index=main user=admin | head 50",
                    "result_count": 2,
                    "search_reference": "sid-123",
                }
            ],
        }
        response["query_result_interpretation"] = [
            {
                "hypothesis_index": 0,
                "assessment": "supports",
                "confidence_delta": "increase",
                "rationale": "Results support the hypothesis.",
                "key_observations": ["2 matching events"],
                "remaining_gaps": [],
            }
        ]
        response["servicenow_section"] = {
            "draft": {"status": "success", "message": "draft created"},
            "create": {
                "status": "skipped",
                "message": "create disabled",
                "number": "",
                "approval": {},
            },
        }

        html = generate_html_report("alert text", response, response["ttp_analysis"])

        self.assertIn('data-tab="queries"', html)
        self.assertIn('data-tab="interpretation"', html)
        self.assertIn('data-tab="servicenow"', html)
        self.assertIn("sid-123", html)
        self.assertIn("draft created", html)
        self.assertIn('class="detail-label">Assessment</span>', html)
        self.assertIn('class="detail-label">Status</span>', html)

    def test_untrusted_model_text_is_escaped(self) -> None:
        response = self._base_response()
        response["alert_reconciliation"][
            "one_sentence_summary"
        ] = '<img src=x onerror="alert(1)">'
        response["competing_hypotheses"][0]["hypothesis"] = "<script>alert(1)</script>"

        html = generate_html_report("alert text", response, response["ttp_analysis"])

        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_poc_raw_output_renders_as_review_section(self) -> None:
        response = self._base_response()
        response["poc_unstructured_output"] = True
        response["poc_fallback_reason"] = "schema failed"
        response["raw_response"] = '{"html":"<b>unsafe</b>"}'

        html = generate_html_report("alert text", response, response["ttp_analysis"])

        self.assertIn('data-tab="raw-output"', html)
        self.assertIn("schema failed", html)
        self.assertIn("&lt;b&gt;unsafe&lt;/b&gt;", html)

    def test_empty_optional_sections_do_not_create_tabs(self) -> None:
        response = {
            "alert_reconciliation": {"verdict": "uncertain"},
            "competing_hypotheses": [],
            "evidence_vs_inference": {},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }

        html = generate_html_report("alert text", response, [])

        self.assertIn('data-tab="verdict"', html)
        self.assertNotIn('data-tab="hypotheses"', html)
        self.assertNotIn('data-tab="actions"', html)
        self.assertNotIn('data-tab="ttps"', html)
        self.assertNotIn('data-tab="iocs"', html)


if __name__ == "__main__":
    unittest.main()
