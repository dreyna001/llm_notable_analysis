import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.onprem_main import process_notable


def _base_llm_response() -> dict:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
            "confidence": "0.82",
            "one_sentence_summary": "Summary.",
            "decision_drivers": ["signal"],
            "recommended_actions": ["review"],
        },
        "competing_hypotheses": [],
        "evidence_vs_inference": {"evidence": [], "inferences": []},
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
        "ttp_analysis": [],
    }


class TestNotableOutputSinks(unittest.TestCase):
    def test_process_notable_skips_markdown_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "portal-only.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")
            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                MARKDOWN_REPORT_ENABLED=False,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = _base_llm_response()
            logger = logging.getLogger("test_notable_output_sinks")

            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.notable_output_sinks.generate_markdown_report"
            ) as mock_md:
                ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            mock_md.assert_not_called()
            self.assertEqual(list(reports.glob("*.md")), [])

    def test_process_notable_writes_markdown_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "with-md.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")
            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                MARKDOWN_REPORT_ENABLED=True,
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = _base_llm_response()
            logger = logging.getLogger("test_notable_output_sinks")

            ok = process_notable(notable_file, config, llm_client, logger)

            self.assertTrue(ok)
            self.assertTrue((reports / "with-md.md").is_file())
