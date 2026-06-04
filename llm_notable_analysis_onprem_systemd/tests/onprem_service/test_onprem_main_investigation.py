import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.onprem_main import process_notable
from llm_notable_analysis_onprem_systemd.onprem_service.onprem_main_nonsdk import (
    process_notable as process_notable_nonsdk,
)


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

    def test_process_notable_runs_elasticsearch_investigation_when_selected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "notable_elastic.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                INVESTIGATION_QUERY_EXECUTION_ENABLED=True,
                INVESTIGATION_QUERY_BACKEND="elasticsearch",
                ELASTICSEARCH_BASE_URL="https://elastic.internal:9200",
                ELASTICSEARCH_API_KEY="test-key",
                ELASTICSEARCH_INDEX_ALLOWLIST="logs-auth",
                ELASTICSEARCH_ALLOWED_FIELDS="@timestamp,user.name",
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_elasticsearch_investigation")
            query_results = [
                {
                    "hypothesis_index": 0,
                    "query_strategy": "resolve_unknown",
                    "query": '{"index_pattern":"logs-auth"}',
                    "status": "success",
                    "executor": "elasticsearch",
                    "result_count": 1,
                    "sample_columns": ["user.name"],
                    "raw_result_ref": "elasticsearch:logs-auth",
                }
            ]

            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.execute_hypothesis_elasticsearch_queries",
                return_value=query_results,
            ) as mock_execute:
                ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            mock_execute.assert_called_once()
            self.assertTrue((processed / "notable_elastic.json").exists())
            report_text = (reports / "notable_elastic.md").read_text(encoding="utf-8")
            self.assertIn("### Query Results", report_text)
            self.assertIn("attempted=1, executed=1", report_text)

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

    def test_nonsdk_process_notable_runs_query_result_interpretation_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "notable4.json"
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
            logger = logging.getLogger("test_onprem_main_nonsdk_interpretation")
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
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main_nonsdk.execute_hypothesis_queries",
                return_value=query_results,
            ):
                ok = process_notable_nonsdk(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            llm_client.interpret_query_results.assert_called_once()
            report_text = (reports / "notable4.md").read_text(encoding="utf-8")
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

    def test_process_notable_writes_case_archive_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "archive-case.json"
            alert_payload = {
                "summary": "alert",
                "notable_id": "abc-123",
                "search_name": "Suspicious PowerShell",
            }
            notable_file.write_text(json.dumps(alert_payload), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                CASE_ARCHIVE_ENABLED=True,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_archive")

            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.write_case_archive_record"
            ) as archive_write, patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.store_case_chunks"
            ) as store_chunks:
                archive_write.return_value = "case-record"
                store_chunks.return_value = 3
                ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            archive_write.assert_called_once()
            store_chunks.assert_called_once_with(record="case-record", config=config)
            kwargs = archive_write.call_args.kwargs
            self.assertEqual(kwargs["case_id"], "archive-case")
            self.assertEqual(kwargs["finding_id"], "archive-case")
            self.assertEqual(kwargs["source_filename"], "archive-case.json")
            self.assertEqual(kwargs["alert_payload"], alert_payload)
            self.assertEqual(kwargs["report_md_path"], reports / "archive-case.md")
            self.assertIsNone(kwargs["report_html_path"])
            self.assertTrue((processed / "archive-case.json").exists())

    def test_process_notable_quarantines_when_case_archive_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "archive-failure.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                CASE_ARCHIVE_ENABLED=True,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_archive_failure")

            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.write_case_archive_record",
                side_effect=RuntimeError("postgres unavailable"),
            ) as archive_write, patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.store_case_chunks"
            ) as store_chunks:
                ok = process_notable(notable_file, config, llm_client, logger)

            self.assertFalse(ok)
            archive_write.assert_called_once()
            store_chunks.assert_not_called()
            self.assertFalse((processed / "archive-failure.json").exists())
            self.assertTrue((quarantine / "archive-failure.json").exists())

    def test_process_notable_marks_failed_when_case_chunk_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "archive-chunk-failure.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                CASE_ARCHIVE_ENABLED=True,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_archive_chunk_failure")

            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.write_case_archive_record",
                return_value="case-record",
            ) as archive_write, patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.store_case_chunks",
                side_effect=RuntimeError("embedding failed"),
            ) as store_chunks, patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main.mark_case_retrieval_status"
            ) as mark_status:
                ok = process_notable(notable_file, config, llm_client, logger)

            self.assertFalse(ok)
            archive_write.assert_called_once()
            store_chunks.assert_called_once_with(record="case-record", config=config)
            mark_status.assert_called_once_with(
                config=config,
                case_id="archive-chunk-failure",
                status="failed",
            )
            self.assertFalse((processed / "archive-chunk-failure.json").exists())
            self.assertTrue((quarantine / "archive-chunk-failure.json").exists())

    def test_nonsdk_process_notable_writes_case_archive_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "archive-case-nonsdk.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                CASE_ARCHIVE_ENABLED=True,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_nonsdk_archive")

            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main_nonsdk.write_case_archive_record"
            ) as archive_write, patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main_nonsdk.store_case_chunks"
            ) as store_chunks:
                archive_write.return_value = "case-record"
                store_chunks.return_value = 3
                ok = process_notable_nonsdk(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            archive_write.assert_called_once()
            store_chunks.assert_called_once_with(record="case-record", config=config)
            kwargs = archive_write.call_args.kwargs
            self.assertEqual(kwargs["case_id"], "archive-case-nonsdk")
            self.assertEqual(kwargs["source_filename"], "archive-case-nonsdk.json")
            self.assertTrue((processed / "archive-case-nonsdk.json").exists())

    def test_process_notable_writes_html_report_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "notable-html.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                HTML_REPORT_ENABLED=True,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_html")

            ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            self.assertTrue((reports / "notable-html.md").exists())
            html_path = reports / "notable-html.html"
            self.assertTrue(html_path.exists())
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", html_text)
            self.assertIn("Alert Reconciliation", html_text)

    def test_process_notable_does_not_write_html_report_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "notable-md-only.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")

            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                HTML_REPORT_ENABLED=False,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = self._make_base_llm_response()
            logger = logging.getLogger("test_onprem_main_no_html")

            ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            self.assertTrue((reports / "notable-md-only.md").exists())
            self.assertFalse((reports / "notable-md-only.html").exists())


if __name__ == "__main__":
    unittest.main()
