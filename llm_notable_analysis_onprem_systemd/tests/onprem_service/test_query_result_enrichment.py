import unittest

from llm_notable_analysis_onprem_systemd.onprem_service.query_result_enrichment import (
    enrich_analysis_with_query_results,
)


class TestQueryResultEnrichment(unittest.TestCase):
    def test_enrichment_adds_query_result_section_and_annotations(self) -> None:
        llm_response = {
            "competing_hypotheses": [
                {"hypothesis_type": "benign", "hypothesis": "h1"},
                {"hypothesis_type": "adversary", "hypothesis": "h2"},
            ],
            "evidence_vs_inference": {"evidence": ["src_ip=10.0.0.1"], "inferences": []},
        }
        query_results = [
            {
                "hypothesis_index": 0,
                "status": "success",
                "query_strategy": "resolve_unknown",
                "query": "search index=main user=admin | head 50",
                "result_count": 4,
                "sample_columns": ["host", "user"],
                "search_id": "sid-1",
            },
            {
                "hypothesis_index": 1,
                "status": "denied",
                "query_strategy": "check_contradiction",
                "query": "search index=secret user=admin | head 50",
                "message": "query index is not in allowed index policy",
            },
        ]

        out = enrich_analysis_with_query_results(llm_response, query_results)

        self.assertIn("query_result_section", out)
        summary = out["query_result_section"]["summary"]
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["executed"], 1)
        self.assertEqual(summary["denied"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["skipped"], 0)

        hypotheses = out["competing_hypotheses"]
        self.assertEqual(hypotheses[0]["query_result_status"], "executed")
        self.assertIn("4 result(s)", hypotheses[0]["query_result_summary"])
        self.assertEqual(hypotheses[0]["query_result_reference"], "sid-1")
        self.assertEqual(hypotheses[1]["query_result_status"], "denied")
        self.assertIn("denied by policy", hypotheses[1]["query_result_summary"])

    def test_enrichment_preserves_evidence_vs_inference(self) -> None:
        llm_response = {
            "competing_hypotheses": [{"hypothesis": "h1"}],
            "evidence_vs_inference": {"evidence": ["literal fact"], "inferences": ["x"]},
        }
        query_results = [
            {
                "hypothesis_index": 0,
                "status": "error",
                "query": "search index=main user=admin",
                "message": "timeout",
            }
        ]

        out = enrich_analysis_with_query_results(llm_response, query_results)
        self.assertEqual(
            out["evidence_vs_inference"],
            {"evidence": ["literal fact"], "inferences": ["x"]},
        )
        self.assertIn("failed", out["query_result_section"]["summary"])

    def test_enrichment_no_results_returns_copy_without_section(self) -> None:
        llm_response = {"competing_hypotheses": [{"hypothesis": "h1"}]}
        out = enrich_analysis_with_query_results(llm_response, [])

        self.assertIn("competing_hypotheses", out)
        self.assertNotIn("query_result_section", out)


if __name__ == "__main__":
    unittest.main()
