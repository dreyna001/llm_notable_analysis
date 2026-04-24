"""Deterministic tests for the AWS deployment wrapper."""

from __future__ import annotations

from datetime import datetime
import unittest

from updated_notable_analysis.aws.config import AwsRuntimeConfig
from updated_notable_analysis.aws.handler import AwsNotableLambdaHandler, build_report_object_key
from updated_notable_analysis.core.models import AnalysisReport, EvidenceSection, InvestigationHypothesis
from updated_notable_analysis.core.vocabulary import EvidenceType, HypothesisType


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


class _FakeS3Transport:
    """Simple in-memory S3 JSON transport test double."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.writes: list[dict[str, object]] = []

    def get_json_object(self, *, bucket: str, key: str):  # noqa: ANN201
        return self.objects[(bucket, key)]

    def put_json_object(self, *, bucket: str, key: str, payload):  # noqa: ANN001, ANN201
        self.writes.append({"bucket": bucket, "key": key, "payload": payload})


class TestAwsHandler(unittest.TestCase):
    """Behavior-focused tests for AWS wrapper request and output handling."""

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

    def test_handle_accepts_direct_alert_payload_and_writes_report_to_s3(self) -> None:
        """Direct invoke payload should route through core and write report JSON."""
        fake_runner = _FakeCoreRunner()
        fake_s3 = _FakeS3Transport()
        handler = AwsNotableLambdaHandler(
            config=AwsRuntimeConfig(
                report_output_bucket="soc-report-bucket",
                report_output_prefix="reports",
                default_profile_name="analysis_only",
                default_customer_bundle_name="acme_default",
            ),
            core_runner=fake_runner,
            s3_transport=fake_s3,
        )

        response = handler.handle(
            {
                "normalized_alert": self._valid_alert_payload(),
                "profile_name": "analysis_plus_rag",
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["output_bucket"], "soc-report-bucket")
        self.assertEqual(response["input_ref"], "event:normalized_alert")
        self.assertEqual(len(fake_s3.writes), 1)
        self.assertEqual(fake_runner.calls[0]["profile_name"], "analysis_plus_rag")
        self.assertEqual(fake_runner.calls[0]["customer_bundle_name"], "acme_default")
        self.assertTrue(str(fake_s3.writes[0]["key"]).startswith("reports/"))

    def test_handle_accepts_s3_trigger_payload_and_uses_config_defaults(self) -> None:
        """S3 trigger payload should load object content and apply default profile settings."""
        fake_runner = _FakeCoreRunner()
        fake_s3 = _FakeS3Transport()
        fake_s3.objects[("incoming-alerts", "alerts/n-55.json")] = {
            "normalized_alert": self._valid_alert_payload(source_record_ref="notable-55")
        }
        handler = AwsNotableLambdaHandler(
            config=AwsRuntimeConfig(
                report_output_bucket="soc-report-bucket",
                report_output_prefix="reports",
                default_profile_name="analysis_only",
                default_customer_bundle_name="acme_default",
            ),
            core_runner=fake_runner,
            s3_transport=fake_s3,
        )

        response = handler.handle(
            {
                "Records": [
                    {
                        "s3": {
                            "bucket": {"name": "incoming-alerts"},
                            "object": {"key": "alerts%2Fn-55.json"},
                        }
                    }
                ]
            }
        )

        self.assertEqual(response["input_ref"], "s3://incoming-alerts/alerts/n-55.json")
        self.assertEqual(fake_runner.calls[0]["profile_name"], "analysis_only")
        self.assertEqual(fake_runner.calls[0]["customer_bundle_name"], "acme_default")
        self.assertEqual(len(fake_s3.writes), 1)

    def test_handle_rejects_event_without_supported_input_shape(self) -> None:
        """Events without direct payload or S3 records should fail fast."""
        handler = AwsNotableLambdaHandler(
            config=AwsRuntimeConfig(report_output_bucket="soc-report-bucket"),
            core_runner=_FakeCoreRunner(),
            s3_transport=_FakeS3Transport(),
        )

        with self.assertRaises(ValueError):
            handler.handle({"unexpected": "payload"})

    def test_build_report_object_key_normalizes_source_ref(self) -> None:
        """Output key generation should sanitize source references for S3 safety."""
        key = build_report_object_key(
            source_record_ref=" notable/123 ??? ",
            received_at=datetime.fromisoformat("2026-04-21T10:11:12+00:00"),
            output_prefix="reports",
        )
        self.assertEqual(key, "reports/20260421T101112Z_notable_123.json")

    def test_config_from_env_requires_output_bucket(self) -> None:
        """Missing required output bucket should fail with deterministic ValueError."""
        with self.assertRaises(ValueError):
            AwsRuntimeConfig.from_env({})

    def test_config_rejects_slash_only_output_prefix(self) -> None:
        """Slash-only prefixes should fail after normalization."""
        with self.assertRaises(ValueError):
            AwsRuntimeConfig(
                report_output_bucket="soc-report-bucket",
                report_output_prefix="///",
            )


if __name__ == "__main__":
    unittest.main()
