import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import LocalLLMClient
from llm_notable_analysis_onprem_systemd.onprem_service.sinks import update_splunk_notable
from llm_notable_analysis_onprem_systemd.onprem_service.ttp_validator import TTPValidator


class _DummyValidator:
    def filter_valid_ttps(self, scored_ttps):
        return scored_ttps


class TestIntegrationMocks(unittest.TestCase):
    @patch("llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.requests.post")
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

    @patch("llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.requests.post")
    def test_analyze_alert_runs_second_llm_call_for_spl_generation(
        self, mock_post: MagicMock
    ) -> None:
        base_hypotheses = [
            {
                "hypothesis_type": "benign",
                "hypothesis": "admin maintenance",
                "evidence_support": [],
                "evidence_gaps": [],
                "best_pivots": [],
            },
            {
                "hypothesis_type": "benign",
                "hypothesis": "scheduled task",
                "evidence_support": [],
                "evidence_gaps": [],
                "best_pivots": [],
            },
            {
                "hypothesis_type": "benign",
                "hypothesis": "service account routine",
                "evidence_support": [],
                "evidence_gaps": [],
                "best_pivots": [],
            },
            {
                "hypothesis_type": "adversary",
                "hypothesis": "credential theft",
                "evidence_support": [],
                "evidence_gaps": [],
                "best_pivots": [],
            },
            {
                "hypothesis_type": "adversary",
                "hypothesis": "privilege misuse",
                "evidence_support": [],
                "evidence_gaps": [],
                "best_pivots": [],
            },
            {
                "hypothesis_type": "adversary",
                "hypothesis": "remote execution",
                "evidence_support": [],
                "evidence_gaps": [],
                "best_pivots": [],
            },
        ]
        base_payload = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.84",
                "one_sentence_summary": "Likely credential access in progress.",
                "decision_drivers": ["failed logins then success"],
                "recommended_actions": ["disable account"],
            },
            "competing_hypotheses": base_hypotheses,
            "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
            "ioc_extraction": {"urls": []},
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
        spl_payload = {
            "competing_hypotheses": [
                {
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search user=admin | head 50",
                    "why_this_query": "check baseline",
                    "supports_if": "similar events exist",
                    "weakens_if": "no similar events",
                },
                {
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search task_name=*backup* | head 50",
                    "why_this_query": "validate scheduler pattern",
                    "supports_if": "task appears regularly",
                    "weakens_if": "task absent historically",
                },
                {
                    "query_strategy": "check_contradiction",
                    "primary_spl_query": "search user=svc_backup action=logon | head 50",
                    "why_this_query": "confirm prior behavior",
                    "supports_if": "history exists",
                    "weakens_if": "no prior history",
                },
                {
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search EventCode=4624 user=admin | stats count by src_ip",
                    "why_this_query": "check concentration",
                    "supports_if": "new source dominates",
                    "weakens_if": "source profile is normal",
                },
                {
                    "query_strategy": "check_contradiction",
                    "primary_spl_query": "search EventCode=4672 user=admin | head 50",
                    "why_this_query": "look for elevated actions",
                    "supports_if": "elevated activity appears",
                    "weakens_if": "no elevated activity",
                },
                {
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search process_name=powershell.exe parent_process=wmiprvse.exe | head 50",
                    "why_this_query": "check suspicious ancestry",
                    "supports_if": "suspicious parent-child exists",
                    "weakens_if": "ancestry absent",
                },
            ]
        }

        first_response = MagicMock()
        first_response.raise_for_status.return_value = None
        first_response.json.return_value = {"choices": [{"text": json.dumps(base_payload)}]}
        second_response = MagicMock()
        second_response.raise_for_status.return_value = None
        second_response.json.return_value = {"choices": [{"text": json.dumps(spl_payload)}]}
        mock_post.side_effect = [first_response, second_response]

        config = Config(
            LLM_API_URL="http://127.0.0.1:8000/v1/chat/completions",
            SPL_QUERY_GENERATION_ENABLED=True,
        )
        client = LocalLLMClient(config=config, ttp_validator=_DummyValidator())
        result = client.analyze_alert("alert_text", "2026-01-01T00:00:00Z")

        self.assertNotIn("error", result)
        self.assertEqual(mock_post.call_count, 2)
        self.assertTrue(result["metadata"]["spl_query_generation_attempted"])
        self.assertFalse(result["metadata"]["spl_query_generation_unavailable"])
        self.assertIn("primary_spl_query", result["competing_hypotheses"][0])
        self.assertEqual(
            result["competing_hypotheses"][0]["primary_spl_query"],
            "search user=admin | head 50",
        )

        first_call_text = str(mock_post.call_args_list[0])
        second_call_text = str(mock_post.call_args_list[1])
        self.assertNotIn("SPL QUERY GENERATION (Enabled)", first_call_text)
        self.assertIn("SPL QUERY GENERATION (Enabled)", second_call_text)

    @patch("llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.requests.post")
    def test_analyze_alert_suppresses_spl_when_second_call_contract_fails(
        self, mock_post: MagicMock
    ) -> None:
        base_payload = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.84",
                "one_sentence_summary": "Likely credential access in progress.",
                "decision_drivers": ["failed logins then success"],
                "recommended_actions": ["disable account"],
            },
            "competing_hypotheses": [
                {"hypothesis_type": "benign", "hypothesis": "h1"},
                {"hypothesis_type": "benign", "hypothesis": "h2"},
                {"hypothesis_type": "benign", "hypothesis": "h3"},
                {"hypothesis_type": "adversary", "hypothesis": "h4"},
                {"hypothesis_type": "adversary", "hypothesis": "h5"},
                {"hypothesis_type": "adversary", "hypothesis": "h6"},
            ],
            "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
            "ioc_extraction": {"urls": []},
            "ttp_analysis": [],
        }
        bad_spl_payload = {
            "competing_hypotheses": [
                {
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search index=main user=admin",
                    "why_this_query": "x",
                    "supports_if": "y",
                    "weakens_if": "z",
                }
            ]
        }
        bad_spl_repair_payload = {
            "competing_hypotheses": [
                {
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search index=main user=admin",
                    "why_this_query": "x",
                    "supports_if": "y",
                    "weakens_if": "z",
                }
            ]
        }

        responses = []
        for payload in (base_payload, bad_spl_payload, bad_spl_repair_payload):
            response = MagicMock()
            response.raise_for_status.return_value = None
            response.json.return_value = {"choices": [{"text": json.dumps(payload)}]}
            responses.append(response)
        mock_post.side_effect = responses

        config = Config(
            LLM_API_URL="http://127.0.0.1:8000/v1/chat/completions",
            SPL_QUERY_GENERATION_ENABLED=True,
        )
        client = LocalLLMClient(config=config, ttp_validator=_DummyValidator())
        result = client.analyze_alert("alert_text")

        self.assertNotIn("error", result)
        self.assertTrue(result["metadata"]["spl_query_generation_unavailable"])
        self.assertIn(
            "spl_query_generation_unavailable_reason",
            result["metadata"],
        )
        self.assertNotIn("primary_spl_query", result["competing_hypotheses"][0])
        self.assertEqual(mock_post.call_count, 3)

    @patch("llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.requests.post")
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

    @patch("llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.requests.post")
    def test_analyze_alert_poc_fallback_when_repair_still_invalid(
        self, mock_post: MagicMock
    ) -> None:
        """Primary + repair both fail content policy → PoC raw fallback (no quarantine)."""
        policy_bad = {
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

        def _resp(text: str) -> MagicMock:
            m = MagicMock()
            m.raise_for_status.return_value = None
            m.json.return_value = {"choices": [{"text": text}]}
            return m

        body = json.dumps(policy_bad)
        mock_post.side_effect = [_resp(body), _resp(body)]
        config = Config(LLM_API_URL="http://127.0.0.1:8000/v1/chat/completions")
        client = LocalLLMClient(config=config, ttp_validator=_DummyValidator())
        result = client.analyze_alert("alert_text")

        self.assertNotIn("error", result)
        self.assertTrue(result.get("poc_unstructured_output"))
        self.assertIn("raw_response", result)
        self.assertIn("ttp_analysis", result)
        self.assertEqual(mock_post.call_count, 2)

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.time.sleep",
        return_value=None,
    )
    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.requests.post",
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

    @patch("llm_notable_analysis_onprem_systemd.onprem_service.sinks.requests.post")
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

    @patch("llm_notable_analysis_onprem_systemd.onprem_service.sinks.requests.post")
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
        "llm_notable_analysis_onprem_systemd.onprem_service.sinks.requests.post",
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

    @patch("llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.requests.post")
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
