from datetime import datetime, timezone
from pathlib import Path
import unittest

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    CaseArchiveConflictError,
    CaseArchiveWriteError,
    build_native_case_id,
    build_case_archive_record,
    build_upsert_case_sql,
    write_case_record_once,
    write_case_record_with_retries,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config


class _FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, *, upsert_row=("case-1",)):
        self.executed = []
        self.upsert_row = upsert_row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "RETURNING case_id" in sql:
            return _FakeResult(self.upsert_row)
        return _FakeResult(None)


class TestCaseStore(unittest.TestCase):
    def _analysis(self, confidence="0.81") -> dict:
        return {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": confidence,
                "one_sentence_summary": "Suspicious auth chain observed.",
            },
            "competing_hypotheses": [],
            "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }

    def test_build_native_case_id_prefers_upstream_identity_over_filename(self) -> None:
        first_id = build_native_case_id(
            {"notable_id": "abc-123", "summary": "alert"},
            "transport-a.json",
        )
        replay_id = build_native_case_id(
            {"notable_id": "abc-123", "summary": "alert"},
            "transport-b.json",
        )

        self.assertEqual(first_id, "abc-123")
        self.assertEqual(replay_id, "abc-123")

    def test_build_native_case_id_falls_back_to_sanitized_filename(self) -> None:
        case_id = build_native_case_id("raw text alert", "raw alert!.txt")

        self.assertTrue(case_id.startswith("raw_alert_"))
        self.assertEqual(len(case_id.rsplit("_", 1)[-1]), 12)

    def test_build_native_case_id_ignores_generic_id_field(self) -> None:
        case_id = build_native_case_id(
            {"id": "generic-row-1", "summary": "alert"},
            "transport-a.json",
        )

        self.assertEqual(case_id, "transport-a")

    def test_build_case_archive_record_extracts_filter_columns(self) -> None:
        config = Config(CASE_RETENTION_DAYS=90)
        processed_at = datetime(2026, 6, 4, tzinfo=timezone.utc)

        record = build_case_archive_record(
            config=config,
            case_id="notable1",
            finding_id="notable1",
            source_filename="notable1.json",
            alert_payload={
                "notable_id": "abc-123",
                "searchName": "Suspicious PowerShell",
                "riskScore": "42",
            },
            analysis=self._analysis(),
            report_md_path=Path("/reports/notable1.md"),
            report_html_path=None,
            processed_at=processed_at,
        )

        self.assertEqual(record.case_id, "notable1")
        self.assertEqual(record.correlation_id, "abc-123")
        self.assertEqual(record.verdict, "likely_malicious")
        self.assertIsNotNone(record.analysis)
        analysis = record.analysis or {}
        self.assertEqual(
            analysis["alert_reconciliation"]["verdict"],
            "likely_malicious",
        )
        self.assertEqual(record.confidence, 0.81)
        self.assertEqual(record.search_name, "Suspicious PowerShell")
        self.assertEqual(record.risk_score, 42.0)
        self.assertEqual(record.report_md_path, str(Path("/reports/notable1.md")))
        self.assertEqual(record.retrieval_status, "pending")
        self.assertEqual(record.source_completeness, "complete")
        self.assertEqual(record.expires_at.day, 2)
        self.assertEqual(record.capability_snapshot["llm_model_name"], config.LLM_MODEL_NAME)

    def test_poc_fallback_is_visible_but_not_authoritative_analysis(self) -> None:
        config = Config()
        analysis = self._analysis(confidence="n/a")
        analysis.update(
            {
                "poc_unstructured_output": True,
                "poc_fallback_reason": "schema repair failed",
                "raw_response": "unvalidated text",
            }
        )

        record = build_case_archive_record(
            config=config,
            case_id="raw-case",
            finding_id="raw-case",
            source_filename="raw-case.txt",
            alert_payload="raw alert text",
            analysis=analysis,
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        self.assertIsNone(record.analysis)
        self.assertEqual(record.alert_payload, {"input_type": "text", "text": "raw alert text"})
        self.assertEqual(record.confidence, None)
        self.assertEqual(record.retrieval_status, "not_indexed")
        self.assertEqual(record.source_completeness, "missing_analysis")
        self.assertTrue(record.archive_metadata["poc_unstructured_output"])
        self.assertEqual(record.archive_metadata["poc_fallback_reason"], "schema repair failed")
        self.assertNotIn("raw_response", record.archive_metadata)

    def test_poc_fallback_writes_sql_null_for_analysis_jsonb(self) -> None:
        config = Config()
        connection = _FakeConnection()
        analysis = self._analysis(confidence="n/a")
        analysis.update({"poc_unstructured_output": True})
        record = build_case_archive_record(
            config=config,
            case_id="raw-case",
            finding_id="raw-case",
            source_filename="raw-case.txt",
            alert_payload="raw alert text",
            analysis=analysis,
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        write_case_record_once(
            record=record,
            config=config,
            connect=lambda _dsn: connection,
        )

        upsert_params = connection.executed[1][1]
        self.assertIsNone(upsert_params[9])

    def test_upsert_sql_enforces_same_source_identity(self) -> None:
        sql = build_upsert_case_sql("notable_cases")

        self.assertIn('INSERT INTO "notable_cases".cases', sql)
        self.assertIn("ON CONFLICT (case_id) DO UPDATE", sql)
        self.assertIn("source_filename = EXCLUDED.source_filename", sql)
        self.assertIn("correlation_id = EXCLUDED.correlation_id", sql)
        self.assertIn("finding_id = EXCLUDED.finding_id", sql)

    def test_write_case_record_sets_timeout_upserts_and_clears_chunks(self) -> None:
        config = Config(CASE_POSTGRES_STATEMENT_TIMEOUT_MS=2500)
        connection = _FakeConnection()
        record = build_case_archive_record(
            config=config,
            case_id="case-1",
            finding_id="case-1",
            source_filename="case-1.json",
            alert_payload={"search_name": "Rule"},
            analysis=self._analysis(),
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        write_case_record_once(
            record=record,
            config=config,
            connect=lambda _dsn: connection,
        )

        self.assertEqual(
            connection.executed[0],
            ("SELECT set_config('statement_timeout', %s, true)", ("2500ms",)),
        )
        self.assertIn("RETURNING case_id", connection.executed[1][0])
        self.assertIn("DELETE FROM", connection.executed[2][0])
        self.assertEqual(connection.executed[2][1], ("case-1",))

    def test_write_case_record_rejects_unrelated_case_id_collision(self) -> None:
        config = Config()
        connection = _FakeConnection(upsert_row=None)
        record = build_case_archive_record(
            config=config,
            case_id="case-1",
            finding_id="case-1",
            source_filename="case-1.json",
            alert_payload={"search_name": "Rule"},
            analysis=self._analysis(),
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        with self.assertRaises(CaseArchiveConflictError):
            write_case_record_once(
                record=record,
                config=config,
                connect=lambda _dsn: connection,
            )

    def test_write_case_record_retries_transient_failures(self) -> None:
        config = Config(
            CASE_ARCHIVE_WRITE_MAX_ATTEMPTS=2,
            CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS=1,
        )
        connection = _FakeConnection()
        attempts = {"count": 0}
        sleeps = []
        record = build_case_archive_record(
            config=config,
            case_id="case-1",
            finding_id="case-1",
            source_filename="case-1.json",
            alert_payload={"search_name": "Rule"},
            analysis=self._analysis(),
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        def connect(_dsn):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise OSError("temporary network failure")
            return connection

        write_case_record_with_retries(
            record=record,
            config=config,
            connect=connect,
            sleep=sleeps.append,
        )

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(sleeps, [1.0])

    def test_write_case_record_does_not_retry_non_retryable_failures(self) -> None:
        config = Config(CASE_ARCHIVE_WRITE_MAX_ATTEMPTS=3)
        attempts = {"count": 0}
        record = build_case_archive_record(
            config=config,
            case_id="case-1",
            finding_id="case-1",
            source_filename="case-1.json",
            alert_payload={"search_name": "Rule"},
            analysis=self._analysis(),
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        def connect(_dsn):
            attempts["count"] += 1
            raise ValueError("bad schema")

        with self.assertRaises(CaseArchiveWriteError):
            write_case_record_with_retries(
                record=record,
                config=config,
                connect=connect,
                sleep=lambda _seconds: None,
            )

        self.assertEqual(attempts["count"], 1)


if __name__ == "__main__":
    unittest.main()
