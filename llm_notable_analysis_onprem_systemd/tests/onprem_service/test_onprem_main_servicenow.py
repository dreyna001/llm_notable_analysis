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
            "one_sentence_summary": "Potential credential misuse detected.",
            "decision_drivers": ["failed logins then success"],
            "recommended_actions": ["disable account"],
        },
        "competing_hypotheses": [],
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
        "ttp_analysis": [],
    }


class TestOnpremMainServiceNow(unittest.TestCase):
    def test_process_notable_renders_servicenow_draft_section(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "snow1.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")
            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                SERVICENOW_DRAFT_ENABLED=True,
                SERVICENOW_CREATE_ENABLED=False,
                SERVICENOW_ASSIGNMENT_GROUP="SOC Tier 1",
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = _base_llm_response()
            logger = logging.getLogger("test_onprem_main_servicenow")

            ok = process_notable(notable_file, config, llm_client, logger)
            self.assertTrue(ok)
            report_text = (reports / "snow1.md").read_text(encoding="utf-8")
            self.assertIn("### ServiceNow", report_text)
            self.assertIn("Draft status", report_text)
            self.assertIn("success", report_text)
            self.assertIn("Create status", report_text)

    @patch("llm_notable_analysis_onprem_systemd.onprem_service.servicenow.requests.post")
    def test_process_notable_servicenow_create_success_with_approval(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result": {"sys_id": "abc123", "number": "INC100"}}
        mock_post.return_value = response

        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "snow2.json"
            payload = {
                "summary": "alert",
                "servicenow_create_approval": {
                    "approved": True,
                    "approved_by": "analyst@example.com",
                    "approval_ref": "SNOW-APPROVAL-1",
                    "approved_at": "2026-04-29T18:00:00Z",
                },
            }
            notable_file.write_text(json.dumps(payload), encoding="utf-8")
            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                SERVICENOW_DRAFT_ENABLED=True,
                SERVICENOW_CREATE_ENABLED=True,
                SERVICENOW_CREATE_REQUIRES_APPROVAL=True,
                SERVICENOW_ASSIGNMENT_GROUP="SOC Tier 1",
                SERVICENOW_BASE_URL="https://example.service-now.com",
                SERVICENOW_CREATE_PATH="/api/now/table/incident",
                SERVICENOW_API_TOKEN="token",
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = _base_llm_response()
            logger = logging.getLogger("test_onprem_main_servicenow")

            ok = process_notable(notable_file, config, llm_client, logger)
            self.assertTrue(ok)
            report_text = (reports / "snow2.md").read_text(encoding="utf-8")
            self.assertIn("Create status", report_text)
            self.assertIn("success", report_text)
            self.assertIn("INC100", report_text)
            self.assertEqual(mock_post.call_count, 1)

    def test_process_notable_servicenow_create_denied_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            processed = Path(td) / "processed"
            quarantine = Path(td) / "quarantine"
            reports = Path(td) / "reports"
            for d in (incoming, processed, quarantine, reports):
                d.mkdir(parents=True, exist_ok=True)

            notable_file = incoming / "snow3.json"
            notable_file.write_text(json.dumps({"summary": "alert"}), encoding="utf-8")
            config = Config(
                INCOMING_DIR=incoming,
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                SERVICENOW_DRAFT_ENABLED=True,
                SERVICENOW_CREATE_ENABLED=True,
                SERVICENOW_CREATE_REQUIRES_APPROVAL=True,
                SERVICENOW_ASSIGNMENT_GROUP="SOC Tier 1",
                SERVICENOW_BASE_URL="https://example.service-now.com",
                SERVICENOW_CREATE_PATH="/api/now/table/incident",
                SERVICENOW_API_TOKEN="token",
            )
            llm_client = MagicMock()
            llm_client.analyze_alert.return_value = _base_llm_response()
            logger = logging.getLogger("test_onprem_main_servicenow")

            ok = process_notable(notable_file, config, llm_client, logger)
            self.assertTrue(ok)
            report_text = (reports / "snow3.md").read_text(encoding="utf-8")
            self.assertIn("Create status", report_text)
            self.assertIn("denied", report_text)


if __name__ == "__main__":
    unittest.main()
