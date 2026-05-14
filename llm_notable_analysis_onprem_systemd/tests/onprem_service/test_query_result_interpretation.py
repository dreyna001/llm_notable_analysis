import unittest

from llm_notable_analysis_onprem_systemd.onprem_service.query_result_interpretation import (
    build_query_result_interpretation_prompt,
    merge_query_result_interpretation,
    validate_query_result_interpretation_payload,
)


class TestQueryResultInterpretation(unittest.TestCase):
    def _analysis_result(self) -> dict:
        return {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.82",
                "one_sentence_summary": "Possible beaconing observed.",
            },
            "competing_hypotheses": [
                {
                    "hypothesis_type": "adversary",
                    "hypothesis": "Periodic outbound beaconing",
                    "supports_if": "regular intervals to same destination",
                    "weakens_if": "traffic is one-off or user-initiated",
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
                        "query": "index=proxy src_ip=10.0.0.5 | stats count by dest_domain",
                        "result_count": 42,
                        "sample_columns": ["src_ip", "dest_domain", "count"],
                        "search_reference": "sid-beacon-1",
                    }
                ],
            },
            "ttp_analysis": [{"ttp_id": "T1071", "score": 0.82}],
        }

    def test_prompt_preserves_confidence_delta_boundary(self) -> None:
        prompt = build_query_result_interpretation_prompt(
            "beaconing alert",
            self._analysis_result(),
            context_budget_chars=4000,
            max_sample_rows=3,
        )

        self.assertIn("confidence_delta is an interpretation-only label", prompt)
        self.assertIn("Do not modify", prompt)
        self.assertIn("QUERY_RESULT_INTERPRETATION_INPUT", prompt)

    def test_validator_accepts_grounded_interpretation(self) -> None:
        payload = {
            "query_result_interpretation": [
                {
                    "hypothesis_index": 0,
                    "assessment": "supports",
                    "confidence_delta": "increase",
                    "rationale": "42 proxy matches support periodic outbound activity.",
                    "key_observations": ["42 matching proxy events"],
                    "remaining_gaps": ["Endpoint process context is unknown"],
                    "source_query_refs": ["sid-beacon-1"],
                }
            ]
        }

        ok, err, normalized = validate_query_result_interpretation_payload(
            payload,
            self._analysis_result(),
        )

        self.assertTrue(ok, err)
        self.assertEqual(
            normalized["query_result_interpretation"][0]["confidence_delta"],
            "increase",
        )

    def test_validator_rejects_unknown_ref_and_bad_delta(self) -> None:
        analysis = self._analysis_result()
        bad_ref = {
            "query_result_interpretation": [
                {
                    "hypothesis_index": 0,
                    "assessment": "supports",
                    "confidence_delta": "increase",
                    "rationale": "x",
                    "key_observations": [],
                    "remaining_gaps": [],
                    "source_query_refs": ["missing-sid"],
                }
            ]
        }
        ok, err, _ = validate_query_result_interpretation_payload(bad_ref, analysis)
        self.assertFalse(ok)
        self.assertIn("unknown ref", err or "")

        bad_delta = {
            "query_result_interpretation": [
                {
                    "hypothesis_index": 0,
                    "assessment": "supports",
                    "confidence_delta": "raise_score_to_99",
                    "rationale": "x",
                    "key_observations": [],
                    "remaining_gaps": [],
                    "source_query_refs": ["sid-beacon-1"],
                }
            ]
        }
        ok, err, _ = validate_query_result_interpretation_payload(bad_delta, analysis)
        self.assertFalse(ok)
        self.assertIn("confidence_delta", err or "")

    def test_merge_does_not_mutate_scores_or_confidence(self) -> None:
        analysis = self._analysis_result()
        payload = {
            "query_result_interpretation": [
                {
                    "hypothesis_index": 0,
                    "assessment": "supports",
                    "confidence_delta": "increase",
                    "rationale": "x",
                    "key_observations": [],
                    "remaining_gaps": [],
                    "source_query_refs": ["sid-beacon-1"],
                }
            ]
        }

        out = merge_query_result_interpretation(analysis, payload)

        self.assertEqual(out["alert_reconciliation"]["confidence"], "0.82")
        self.assertEqual(out["ttp_analysis"][0]["score"], 0.82)
        self.assertIn("query_result_interpretation", out)


if __name__ == "__main__":
    unittest.main()
