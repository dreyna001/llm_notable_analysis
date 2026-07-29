"""Tests for direct-Bedrock file-drop behavior in portal preview mode."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SRC_DIR = PROJECT_ROOT / "src"
for path in (SCRIPTS_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config  # noqa: E402
from preview_bedrock_llm import BedrockPreviewSettings  # noqa: E402
from preview_fake_db import PreviewCaseStore  # noqa: E402
from preview_file_drop import (  # noqa: E402
    PreviewBedrockAnalysisClient,
    PreviewFileDropRuntime,
    build_preview_file_drop_config,
    preview_file_drop_enabled,
)


def _analysis() -> dict:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
            "confidence": "0.91",
            "one_sentence_summary": "The dropped alert warrants investigation.",
            "decision_drivers": ["encoded command"],
            "recommended_actions": ["isolate the host"],
        },
        "competing_hypotheses": [],
        "evidence_vs_inference": {
            "evidence": ["powershell -enc was observed"],
            "inferences": [],
        },
        "ioc_extraction": {},
        "ttp_analysis": [],
    }


class _SuccessfulClient:
    def analyze_alert(self, alert_text: str, alert_time: str) -> dict:
        if not alert_text or not alert_time:
            raise AssertionError("alert text and time are required")
        return _analysis()

    def interpret_query_results(self, alert_text: str, analysis_result: dict) -> dict:
        return analysis_result


class _FailingClient(_SuccessfulClient):
    def analyze_alert(self, alert_text: str, alert_time: str) -> dict:
        raise RuntimeError("simulated Bedrock failure")


class _FakeBedrockAnalyzer:
    """Minimal stand-in for s3 BedrockAnalyzer last_llm_response contract."""

    def __init__(self) -> None:
        self.last_llm_response: dict | None = None
        self.calls: list[tuple[str, str | None]] = []

    def analyze_ttp(self, alert_text: str, alert_time: str | None = None) -> list:
        self.calls.append((alert_text, alert_time))
        self.last_llm_response = _analysis()
        return []


class PreviewFileDropTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = BedrockPreviewSettings(model_id="test-model")

    def test_bedrock_settings_enable_file_drop_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(preview_file_drop_enabled(self.settings))
            self.assertFalse(preview_file_drop_enabled(None))

    def test_bedrock_analysis_client_uses_analyzer_last_llm_response(self) -> None:
        analyzer = _FakeBedrockAnalyzer()
        client = PreviewBedrockAnalysisClient(analyzer)
        result = client.analyze_alert("alert body", "2026-01-01T00:00:00Z")

        self.assertEqual(len(analyzer.calls), 1)
        self.assertEqual(analyzer.calls[0][0], "alert body")
        self.assertEqual(analyzer.calls[0][1], "2026-01-01T00:00:00Z")
        self.assertTrue(result["metadata"]["preview_file_drop"])
        self.assertEqual(result["metadata"]["preview_analysis_provider"], "bedrock")

    def test_processes_drop_writes_report_and_publishes_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"PORTAL_PREVIEW_FILE_DROP_ROOT": temp_dir},
            clear=False,
        ):
            config = build_preview_file_drop_config(Config())
            config.INCOMING_DIR.mkdir(parents=True)
            incoming = config.INCOMING_DIR / "live-alert.json"
            incoming.write_text(
                json.dumps(
                    {
                        "notable_id": "live-001",
                        "search_name": "Suspicious PowerShell",
                        "command_line": "powershell -enc AAAA",
                    }
                ),
                encoding="utf-8",
            )
            store = PreviewCaseStore([], config)
            runtime = PreviewFileDropRuntime(
                config=config,
                case_store=store,
                bedrock_settings=self.settings,
                analysis_client_factory=lambda _settings: _SuccessfulClient(),
            )

            processed, failed = runtime.process_pending_once()

            self.assertEqual((processed, failed), (1, 0))
            self.assertFalse(incoming.exists())
            self.assertTrue((config.PROCESSED_DIR / incoming.name).is_file())
            self.assertTrue((config.REPORT_DIR / "live-alert.md").is_file())
            self.assertEqual(len(store.summary_rows), 1)
            case_id = store.summary_rows[0][0]
            self.assertIsNotNone(
                store.connect("preview://fake")
                .execute("SELECT * FROM cases WHERE case_id = %s", (case_id,))
                .fetchone()
            )

    def test_failed_bedrock_analysis_quarantines_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"PORTAL_PREVIEW_FILE_DROP_ROOT": temp_dir},
            clear=False,
        ):
            config = build_preview_file_drop_config(Config())
            config.INCOMING_DIR.mkdir(parents=True)
            incoming = config.INCOMING_DIR / "failed.txt"
            incoming.write_text("suspicious alert", encoding="utf-8")
            store = PreviewCaseStore([], config)
            runtime = PreviewFileDropRuntime(
                config=config,
                case_store=store,
                bedrock_settings=self.settings,
                analysis_client_factory=lambda _settings: _FailingClient(),
            )

            processed, failed = runtime.process_pending_once()

            self.assertEqual((processed, failed), (0, 1))
            self.assertTrue((config.QUARANTINE_DIR / incoming.name).is_file())
            self.assertEqual(store.summary_rows, [])


if __name__ == "__main__":
    unittest.main()
