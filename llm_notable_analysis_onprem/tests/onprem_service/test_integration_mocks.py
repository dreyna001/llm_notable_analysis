import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from llm_notable_analysis_onprem.onprem_service.config import Config
from llm_notable_analysis_onprem.onprem_service.local_llm_client import LocalLLMClient
from llm_notable_analysis_onprem.onprem_service.sinks import update_splunk_notable
from llm_notable_analysis_onprem.onprem_service.ttp_validator import TTPValidator


class _DummyValidator:
    def filter_valid_ttps(self, scored_ttps):
        return scored_ttps


class TestIntegrationMocks(unittest.TestCase):
    @patch("llm_notable_analysis_onprem.onprem_service.local_llm_client.requests.post")
    def test_analyze_alert_success_with_mocked_llm(self, mock_post: MagicMock) -> None:
        payload = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.84",
                "one_sentence_summary": "Likely credential access in progress.",
                "decision_drivers": ["failed logins then success"],
                "recommended_actions": ["disable account"],
            },
            "competing_hypotheses": [],
            "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
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
                    "confidence_score": 0.81,
                    "explanation": "Repeated failures. Uncertainty: limited context.",
                    "evidence_fields": ["user=admin"],
                }
            ],
        }

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"text": json.dumps(payload)}]}
        mock_post.return_value = response

        with tempfile.TemporaryDirectory():
            config = Config(LLM_API_URL="http://127.0.0.1:8000/v1/chat/completions")
            client = LocalLLMClient(config=config, ttp_validator=_DummyValidator())
            result = client.analyze_alert("alert_text", "2026-01-01T00:00:00Z")

        self.assertNotIn("error", result)
        self.assertEqual(len(result["ttp_analysis"]), 1)
        self.assertIn("metadata", result)
        self.assertFalse(result["metadata"]["repair_attempted"])
        self.assertEqual(mock_post.call_count, 1)

    @patch("llm_notable_analysis_onprem.onprem_service.local_llm_client.requests.post")
    def test_analyze_alert_uses_repair_flow_when_initial_response_invalid(
        self, mock_post: MagicMock
    ) -> None:
        invalid_payload = {
            "alert_reconciliation": {
                "verdict": "unknown",
                "confidence": "0.2",
                "one_sentence_summary": "N/A",
                "decision_drivers": [],
                "recommended_actions": [],
            },
            "competing_hypotheses": [],
            "evidence_vs_inference": {
                "evidence": ["see https://bad.example/path"],
                "inferences": [],
            },
            "ioc_extraction": {"urls": []},
            "ttp_analysis": [],
        }
        invalid_response = MagicMock()
        invalid_response.raise_for_status.return_value = None
        invalid_response.json.return_value = {
            "choices": [{"text": json.dumps(invalid_payload)}]
        }

        repaired_payload = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.84",
                "one_sentence_summary": "Likely credential access in progress.",
                "decision_drivers": ["failed logins then success"],
                "recommended_actions": ["disable account"],
            },
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
            "ttp_analysis": [
                {
                    "ttp_id": "T1110",
                    "ttp_name": "Brute Force",
                    "confidence_score": 0.81,
                    "explanation": "Repeated failures. Uncertainty: limited context.",
                    "evidence_fields": ["user=admin"],
                }
            ],
        }
        repaired_response = MagicMock()
        repaired_response.raise_for_status.return_value = None
        repaired_response.json.return_value = {
            "choices": [{"text": json.dumps(repaired_payload)}]
        }
        mock_post.side_effect = [invalid_response, repaired_response]

        config = Config(LLM_API_URL="http://127.0.0.1:8000/v1/chat/completions")
        client = LocalLLMClient(config=config, ttp_validator=_DummyValidator())
        result = client.analyze_alert("alert_text")

        self.assertNotIn("error", result)
        self.assertTrue(result["metadata"]["repair_attempted"])
        self.assertEqual(mock_post.call_count, 2)

    @patch(
        "llm_notable_analysis_onprem.onprem_service.local_llm_client.time.sleep",
        return_value=None,
    )
    @patch(
        "llm_notable_analysis_onprem.onprem_service.local_llm_client.requests.post",
        side_effect=requests.exceptions.Timeout,
    )
    def test_analyze_alert_timeout_returns_error(
        self, mock_post: MagicMock, _mock_sleep: MagicMock
    ) -> None:
        config = Config(
            LLM_API_URL="http://127.0.0.1:8000/v1/chat/completions", LLM_TIMEOUT=1
        )
        client = LocalLLMClient(config=config, ttp_validator=_DummyValidator())

        result = client.analyze_alert("alert_text")

        self.assertIn("error", result)
        self.assertIn("timeout", result["error"].lower())
        self.assertGreaterEqual(mock_post.call_count, 3)

    @patch("llm_notable_analysis_onprem.onprem_service.sinks.requests.post")
    def test_update_splunk_notable_builds_expected_payload(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.status_code = 200
        response.text = "ok"
        mock_post.return_value = response

        config = Config(
            SPLUNK_SINK_ENABLED=True,
            SPLUNK_BASE_URL="https://splunk.internal:8089",
            SPLUNK_API_TOKEN="token",
            SPLUNK_CA_BUNDLE="/tmp/ca.pem",
        )

        result = update_splunk_notable(
            notable_id="n1",
            markdown="# Report",
            finding_id="rule-123",
            config=config,
        )

        self.assertEqual(result["status"], "success")
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["verify"], "/tmp/ca.pem")
        self.assertEqual(kwargs["data"]["finding_id"], "rule-123")
        self.assertEqual(kwargs["data"]["status"], "2")
        self.assertEqual(kwargs["data"]["comment"], "# Report")

    def test_update_splunk_notable_skips_when_sink_disabled(self) -> None:
        result = update_splunk_notable(
            notable_id="n1",
            markdown="# Report",
            finding_id="rule-123",
            config=Config(SPLUNK_SINK_ENABLED=False),
        )
        self.assertEqual(result["status"], "skipped")

    @patch("llm_notable_analysis_onprem.onprem_service.sinks.requests.post")
    def test_update_splunk_notable_uses_finding_id_only(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.status_code = 200
        response.text = "ok"
        mock_post.return_value = response

        config = Config(
            SPLUNK_SINK_ENABLED=True,
            SPLUNK_BASE_URL="https://splunk.internal:8089",
            SPLUNK_API_TOKEN="token",
        )

        result = update_splunk_notable(
            notable_id="n1",
            markdown="# Report",
            finding_id="finding-42",
            config=config,
        )

        self.assertEqual(result["status"], "success")
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["finding_id"], "finding-42")
        self.assertNotIn("ruleUIDs", kwargs["data"])
        self.assertNotIn("search_name", kwargs["data"])

    @patch(
        "llm_notable_analysis_onprem.onprem_service.sinks.requests.post",
        side_effect=requests.RequestException("splunk down"),
    )
    def test_update_splunk_notable_returns_error_on_request_exception(
        self, _mock_post: MagicMock
    ) -> None:
        config = Config(
            SPLUNK_SINK_ENABLED=True,
            SPLUNK_BASE_URL="https://splunk.internal:8089",
            SPLUNK_API_TOKEN="token",
        )
        result = update_splunk_notable(
            notable_id="n1",
            markdown="# Report",
            finding_id="rule-123",
            config=config,
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("splunk down", result["message"])

    @patch("llm_notable_analysis_onprem.onprem_service.local_llm_client.requests.post")
    def test_analyze_alert_filters_invalid_ttps_with_real_validator(
        self, mock_post: MagicMock
    ) -> None:
        payload = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.84",
                "one_sentence_summary": "Likely credential access in progress.",
                "decision_drivers": ["failed logins then success"],
                "recommended_actions": ["disable account"],
            },
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
            "ttp_analysis": [
                {
                    "ttp_id": "T1110",
                    "ttp_name": "Brute Force",
                    "confidence_score": 0.81,
                    "explanation": "Repeated failures. Uncertainty: limited context.",
                    "evidence_fields": ["user=admin"],
                },
                {
                    "ttp_id": "T9999",
                    "ttp_name": "Invalid ID",
                    "confidence_score": 0.9,
                    "explanation": "Invalid. Uncertainty: invalid.",
                    "evidence_fields": [],
                },
            ],
        }

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"text": json.dumps(payload)}]}
        mock_post.return_value = response

        with tempfile.TemporaryDirectory() as td:
            ids_path = Path(td) / "ids.json"
            ids_path.write_text(json.dumps(["T1110"]), encoding="utf-8")
            validator = TTPValidator(ids_path)
            client = LocalLLMClient(
                config=Config(LLM_API_URL="http://127.0.0.1:8000/v1/chat/completions"),
                ttp_validator=validator,
            )
            result = client.analyze_alert("alert_text")

        self.assertNotIn("error", result)
        self.assertEqual([t["ttp_id"] for t in result["ttp_analysis"]], ["T1110"])


if __name__ == "__main__":
    unittest.main()
