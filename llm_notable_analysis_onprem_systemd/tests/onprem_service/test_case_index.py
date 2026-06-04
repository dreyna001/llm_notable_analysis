from datetime import datetime, timezone
import json
import unittest

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.case_index import (
    CaseListFilters,
    build_get_case_query,
    build_list_cases_query,
    get_case,
    list_cases,
)
from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config


class _FakeResult:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, *, rows=None, row=None):
        self.executed = []
        self.rows = rows or []
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "WHERE case_id = %s" in sql:
            return _FakeResult(row=self.row)
        return _FakeResult(rows=self.rows)


def _analysis() -> dict:
    return {
        "alert_reconciliation": {
            "verdict": "likely malicious",
            "confidence": "0.82",
            "one_sentence_summary": "Suspicious PowerShell from admin host.",
        },
        "competing_hypotheses": [],
        "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
        "ioc_extraction": {},
        "ttp_analysis": [],
    }


def _record(config: Config):
    return build_case_archive_record(
        config=config,
        case_id="case-1",
        finding_id="case-1",
        source_filename="case-1.json",
        alert_payload={
            "notable_id": "abc-123",
            "search_name": "Suspicious PowerShell",
            "riskScore": "42",
        },
        analysis=_analysis(),
        report_md_path="/reports/case-1.md",
        report_html_path=None,
        processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )


def _summary_row(record):
    return (
        record.case_id,
        record.finding_id,
        record.source_filename,
        record.processed_at,
        record.expires_at,
        record.verdict,
        record.confidence,
        record.search_name,
        record.risk_score,
        record.retrieval_status,
        record.source_completeness,
        record.report_md_path,
        record.report_html_path,
    )


def _detail_row(record):
    return (
        record.case_id,
        record.finding_id,
        record.source_filename,
        record.processed_at,
        record.expires_at,
        record.correlation_id,
        json.dumps(record.capability_snapshot),
        json.dumps(record.archive_metadata),
        json.dumps(record.alert_payload),
        json.dumps(record.analysis),
        record.case_schema_version,
        record.analysis_schema_version,
        record.verdict,
        record.confidence,
        record.search_name,
        record.risk_score,
        record.report_md_path,
        record.report_html_path,
        record.retrieval_status,
        record.backfill_status,
        record.source_completeness,
    )


class TestCaseIndex(unittest.TestCase):
    def test_build_list_cases_query_applies_filters_and_ordering(self) -> None:
        processed_from = datetime(2026, 6, 1, tzinfo=timezone.utc)
        processed_to = datetime(2026, 6, 5, tzinfo=timezone.utc)

        sql, params = build_list_cases_query(
            "notable_cases",
            CaseListFilters(
                processed_from=processed_from,
                processed_to=processed_to,
                verdict="likely malicious",
                search_name_prefix=r"Power_%Shell",
                offset=10,
            ),
            page_size=25,
        )

        self.assertIn('FROM "notable_cases".cases', sql)
        self.assertIn("processed_at >= %s", sql)
        self.assertIn("processed_at <= %s", sql)
        self.assertIn("verdict = %s", sql)
        self.assertIn("search_name ILIKE %s", sql)
        self.assertIn("ORDER BY processed_at DESC, case_id ASC", sql)
        self.assertEqual(
            params,
            (
                processed_from,
                processed_to,
                "likely malicious",
                r"Power\_\%Shell%",
                25,
                10,
            ),
        )

    def test_build_get_case_query_targets_one_case(self) -> None:
        sql = build_get_case_query("notable_cases")

        self.assertIn('FROM "notable_cases".cases', sql)
        self.assertIn("WHERE case_id = %s", sql)

    def test_list_cases_maps_summary_rows_and_bounds_limit(self) -> None:
        config = Config(PORTAL_PAGE_SIZE=50, CASE_POSTGRES_STATEMENT_TIMEOUT_MS=2500)
        record = _record(config)
        connection = _FakeConnection(rows=[_summary_row(record)])

        results = list_cases(
            config=config,
            filters=CaseListFilters(limit=500),
            connect=lambda _dsn: connection,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].case_id, "case-1")
        self.assertEqual(results[0].search_name, "Suspicious PowerShell")
        self.assertEqual(
            connection.executed[0],
            ("SELECT set_config('statement_timeout', %s, true)", ("2500ms",)),
        )
        self.assertEqual(connection.executed[1][1], (100, 0))

    def test_get_case_maps_detail_row(self) -> None:
        config = Config()
        record = _record(config)
        connection = _FakeConnection(row=_detail_row(record))

        result = get_case(
            config=config,
            case_id=" case-1 ",
            connect=lambda _dsn: connection,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.case_id, "case-1")
        self.assertEqual(result.alert_payload["notable_id"], "abc-123")
        self.assertEqual(result.analysis["alert_reconciliation"]["confidence"], "0.82")
        self.assertEqual(connection.executed[1][1], ("case-1",))

    def test_get_case_returns_none_for_blank_case_id(self) -> None:
        connection = _FakeConnection()

        result = get_case(
            config=Config(),
            case_id="  ",
            connect=lambda _dsn: connection,
        )

        self.assertIsNone(result)
        self.assertEqual(connection.executed, [])


if __name__ == "__main__":
    unittest.main()
