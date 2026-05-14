import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.onprem_main import process_notable


class TestOnpremMainInvestigation(unittest.TestCase):
    def _make_base_llm_response(self) -> dict:
        return {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.81",
                "one_sentence_summary": "Suspicious auth chain observed.",
                "decision_drivers": ["failed logins followed by success"],
                "recommended_actions": ["disable account", "reset credentials"],
            },
            "competing_hypotheses": [
                {
                    "hypothesis_type": "adversary",
                    "hypothesis": "credential access",
                    "evidence_support": ["user=admin"],
                    "evidence_gaps": ["missing MFA logs"],
                    "best_pivots": [],
                }
            ],
            "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
            "ioc_extraction": {
                "ip_addresses": [],
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
                    "explanation": "Repeated failures observed. Uncertainty: limited context.",
                    "evidence_fields": ["user=admin"],
                }
            ],
        }

    def test_process_notable_runs_investigation_and_enrichment_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "notable1.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                INVESTIGATION_QUERY_EXECUTION_ENABLED=True,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_investigation")

            query_results = [
                {
                    "hypothesis_index": 0,
                    "query_strategy": "resolve_unknown",
                    "query": "search index=main user=admin | head 50",
                    "status": "success",
                    "result_count": 2,
                    "sample_columns": ["host", "user"],
                    "search_id": "sid-123",
                }
            ]
            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.execute_hypothesis_queries",
                return_value=query_results,
            ) as mock_execute:
                ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            mock_execute.assert_called_once()
            self.assertTrue((processed / "notable1.json").exists())
            report_text = (reports / "notable1.md").read_text(encoding="utf-8")
            self.assertIn("### Query Results", report_text)
            self.assertIn("attempted=1, executed=1", report_text)
            self.assertIn("Query result summary", report_text)

    def test_process_notable_runs_query_result_interpretation_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "notable3.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                INVESTIGATION_QUERY_EXECUTION_ENABLED=True,
                QUERY_RESULT_INTERPRETATION_ENABLED=True,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()

            def _interpret(_alert_text: str, analysis: dict) -> dict:
                enriched = dict(analysis)
                enriched["query_result_interpretation"] = [
                    {
                        "hypothesis_index": 0,
                        "assessment": "supports",
                        "confidence_delta": "increase",
                        "rationale": "Results support the hypothesis.",
                        "key_observations": ["2 matching events"],
                        "remaining_gaps": [],
                        "source_query_refs": ["sid-123"],
                    }
                ]
                return enriched

            llm_client.interpret_query_results.side_effect = _interpret
            logger = logging.getLogger("test_onprem_main_interpretation")

            query_results = [
                {
                    "hypothesis_index": 0,
                    "query_strategy": "resolve_unknown",
                    "query": "search index=main user=admin | head 50",
                    "status": "success",
                    "result_count": 2,
                    "sample_columns": ["host", "user"],
                    "search_id": "sid-123",
                }
            ]
            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.execute_hypothesis_queries",
                return_value=query_results,
            ):
                ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            llm_client.interpret_query_results.assert_called_once()
            report_text = (reports / "notable3.md").read_text(encoding="utf-8")
            self.assertIn("### Query Results", report_text)
            self.assertIn("### Query Result Interpretation", report_text)

    def test_process_notable_skips_investigation_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "notable2.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                INVESTIGATION_QUERY_EXECUTION_ENABLED=False,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_investigation")

            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.execute_hypothesis_queries"
            ) as mock_execute:
                ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            mock_execute.assert_not_called()
            report_text = (reports / "notable2.md").read_text(encoding="utf-8")
            self.assertNotIn("### Query Results", report_text)


if __name__ == "__main__":
    unittest.main()
