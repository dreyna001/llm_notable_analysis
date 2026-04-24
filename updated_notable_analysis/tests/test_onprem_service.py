"""Deterministic tests for the on-prem deployment wrapper."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from updated_notable_analysis.core.models import AnalysisReport, EvidenceSection, InvestigationHypothesis
from updated_notable_analysis.core.vocabulary import EvidenceType, HypothesisType
from updated_notable_analysis.onprem.config import OnPremRuntimeConfig
from updated_notable_analysis.onprem.file_io import StdlibLocalJsonFileTransport
from updated_notable_analysis.onprem.service import OnPremNotableProcessor, build_report_output_path


class _FakeCoreRunner:
    """Simple in-memory core runner test double."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        normalized_alert,  # noqa: ANN001 - protocol compatibility for tests
        *,
        profile_name: str | None,
        customer_bundle_name: str | None,
    ) -> AnalysisReport:
        self.calls.append(
            {
                "source_record_ref": normalized_alert.source_record_ref,
                "profile_name": profile_name,
                "customer_bundle_name": customer_bundle_name,
            }
        )
        return AnalysisReport(
            schema_version="1.0",
            alert_reconciliation={"status": "triaged"},
            competing_hypotheses=(
                InvestigationHypothesis(
                    hypothesis_type=HypothesisType.ADVERSARY,
                    hypothesis="Credential misuse activity is likely.",
                    evidence_support=("suspicious process chain",),
                    evidence_gaps=("authentication log pivot pending",),
                ),
            ),
            evidence_sections=(
                EvidenceSection(
                    evidence_type=EvidenceType.ALERT_DIRECT,
                    summary="Alert evidence indicates suspicious behavior.",
                ),
            ),
            ioc_extraction={"ips": ["10.1.2.3"]},
            ttp_analysis=({"technique_id": "T1110", "confidence": "medium"},),
        )


class TestOnPremService(unittest.TestCase):
    """Behavior-focused tests for on-prem file ingest and report handling."""

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        """Write one JSON object to disk for tests."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _valid_alert_payload(self, source_record_ref: str = "notable-123") -> dict[str, object]:
        """Return a valid normalized-alert payload fixture."""
        return {
            "schema_version": "1.0",
            "source_system": "splunk",
            "source_type": "notable",
            "source_record_ref": source_record_ref,
            "received_at": "2026-04-21T10:11:12Z",
            "raw_content_type": "json",
            "raw_content": '{"notable_id":"n-123"}',
        }

    def test_process_next_available_moves_successful_file_and_writes_report(self) -> None:
        """Successful processing should move the input file and write a report."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = OnPremRuntimeConfig(
                incoming_dir=str(root / "incoming"),
                processed_dir=str(root / "processed"),
                quarantine_dir=str(root / "quarantine"),
                report_output_dir=str(root / "reports"),
                default_profile_name="analysis_only",
                default_customer_bundle_name="acme_default",
            )
            incoming_path = Path(config.incoming_dir) / "alert.json"
            self._write_json(incoming_path, self._valid_alert_payload())

            fake_runner = _FakeCoreRunner()
            processor = OnPremNotableProcessor(
                config=config,
                core_runner=fake_runner,
                file_transport=StdlibLocalJsonFileTransport(),
            )

            result = processor.process_next_available()

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["status"], "ok")
            self.assertEqual(fake_runner.calls[0]["profile_name"], "analysis_only")
            self.assertEqual(fake_runner.calls[0]["customer_bundle_name"], "acme_default")
            self.assertFalse(incoming_path.exists())
            self.assertTrue(Path(str(result["processed_path"])).exists())
            report_path = Path(str(result["report_path"]))
            self.assertTrue(report_path.exists())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["schema_version"], "1.0")

    def test_process_file_allows_top_level_runtime_overrides(self) -> None:
        """Top-level override fields should win over config defaults."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = OnPremRuntimeConfig(
                incoming_dir=str(root / "incoming"),
                processed_dir=str(root / "processed"),
                quarantine_dir=str(root / "quarantine"),
                report_output_dir=str(root / "reports"),
                default_profile_name="analysis_only",
                default_customer_bundle_name="acme_default",
            )
            incoming_path = Path(config.incoming_dir) / "alert.json"
            self._write_json(
                incoming_path,
                {
                    "normalized_alert": self._valid_alert_payload(),
                    "profile_name": "analysis_plus_rag",
                    "customer_bundle_name": "acme_executive",
                },
            )

            fake_runner = _FakeCoreRunner()
            processor = OnPremNotableProcessor(
                config=config,
                core_runner=fake_runner,
                file_transport=StdlibLocalJsonFileTransport(),
            )

            result = processor.process_file(incoming_path)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(fake_runner.calls[0]["profile_name"], "analysis_plus_rag")
            self.assertEqual(fake_runner.calls[0]["customer_bundle_name"], "acme_executive")

    def test_invalid_payload_is_quarantined_with_error_sidecar(self) -> None:
        """Invalid input payloads should be moved to quarantine with an error file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = OnPremRuntimeConfig(
                incoming_dir=str(root / "incoming"),
                processed_dir=str(root / "processed"),
                quarantine_dir=str(root / "quarantine"),
                report_output_dir=str(root / "reports"),
            )
            incoming_path = Path(config.incoming_dir) / "bad.json"
            self._write_json(incoming_path, {"normalized_alert": "not-a-mapping"})

            processor = OnPremNotableProcessor(
                config=config,
                core_runner=_FakeCoreRunner(),
                file_transport=StdlibLocalJsonFileTransport(),
            )

            result = processor.process_file(incoming_path)

            self.assertEqual(result["status"], "quarantined")
            self.assertFalse(incoming_path.exists())
            quarantine_path = Path(str(result["quarantine_path"]))
            error_path = Path(str(result["error_path"]))
            self.assertTrue(quarantine_path.exists())
            self.assertTrue(error_path.exists())
            self.assertIn("normalized_alert", json.loads(error_path.read_text(encoding="utf-8"))["message"])

    def test_process_next_available_returns_none_when_queue_is_empty(self) -> None:
        """No-op poll should return None when there are no incoming files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processor = OnPremNotableProcessor(
                config=OnPremRuntimeConfig(
                    incoming_dir=str(root / "incoming"),
                    processed_dir=str(root / "processed"),
                    quarantine_dir=str(root / "quarantine"),
                    report_output_dir=str(root / "reports"),
                ),
                core_runner=_FakeCoreRunner(),
                file_transport=StdlibLocalJsonFileTransport(),
            )

            self.assertIsNone(processor.process_next_available())

    def test_build_report_output_path_normalizes_source_ref(self) -> None:
        """Report output paths should sanitize source references for filesystem safety."""
        path = build_report_output_path(
            report_output_dir="/tmp/reports",
            source_record_ref=" notable/123 ??? ",
            received_at=datetime.fromisoformat("2026-04-21T10:11:12+00:00"),
        )
        self.assertEqual(str(path).replace("\\", "/"), "/tmp/reports/20260421T101112Z_notable_123.json")

    def test_from_env_requires_explicit_runtime_directories(self) -> None:
        """Runtime env loading should fail closed when required directory keys are absent."""
        with self.assertRaises(ValueError):
            OnPremRuntimeConfig.from_env({})


if __name__ == "__main__":
    unittest.main()
