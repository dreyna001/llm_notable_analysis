from datetime import datetime, timezone
import json
import unittest

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from fastapi.testclient import TestClient

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.portal_app import (
    build_portal_app,
    check_case_archive_ready,
    parse_iso8601_timestamp,
)


class _FakeResult:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, *, rows=None, row=None, ready=True, fail=False):
        self.executed = []
        self.rows = rows or []
        self.row = row
        self.ready = ready
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        if self.fail:
            raise OSError("database unavailable")
        self.executed.append((sql, params))
        if "to_regclass" in sql:
            return _FakeResult(row=(self.ready, self.ready))
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
        alert_payload={"notable_id": "abc-123", "search_name": "Suspicious PowerShell"},
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


class TestPortalApp(unittest.TestCase):
    def _config(self) -> Config:
        return Config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            PORTAL_BIND_HOST="127.0.0.1",
            PORTAL_PAGE_SIZE=50,
            PORTAL_TRUSTED_USER_HEADER="X-Forwarded-User",
        )

    def test_parse_iso8601_timestamp_accepts_zulu_suffix(self) -> None:
        parsed = parse_iso8601_timestamp("2026-06-04T00:00:00Z", "start")
        self.assertEqual(parsed, datetime(2026, 6, 4, tzinfo=timezone.utc))

    def test_check_case_archive_ready_requires_both_tables(self) -> None:
        ready = check_case_archive_ready(
            config=self._config(),
            connect=lambda _dsn: _FakeConnection(ready=True),
        )
        not_ready = check_case_archive_ready(
            config=self._config(),
            connect=lambda _dsn: _FakeConnection(ready=False),
        )
        self.assertTrue(ready)
        self.assertFalse(not_ready)

    def test_health_and_ready_endpoints(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(ready=True),
            )
        )

        health = client.get("/health")
        ready = client.get("/ready")
        not_ready = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(ready=False),
            )
        ).get("/ready")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json(), {"status": "ready"})
        self.assertEqual(not_ready.status_code, 503)

    def test_api_cases_returns_paginated_items(self) -> None:
        record = _record(self._config())
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[_summary_row(record)]),
            )
        )

        response = client.get("/api/cases")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["limit"], 50)
        self.assertEqual(payload["offset"], 0)
        self.assertFalse(payload["has_more"])
        self.assertEqual(payload["items"][0]["case_id"], "case-1")

    def test_api_cases_rejects_invalid_filters(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.get("/api/cases", params={"limit": "0"})

        self.assertEqual(response.status_code, 400)

    def test_api_case_detail_returns_404_for_unknown_case(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(row=None),
            )
        )

        response = client.get("/api/cases/missing-case")

        self.assertEqual(response.status_code, 404)

    def test_api_case_detail_returns_canonical_payload(self) -> None:
        record = _record(self._config())
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(row=_detail_row(record)),
            )
        )

        response = client.get("/api/cases/case-1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["case_id"], "case-1")
        self.assertEqual(payload["metadata"]["retrieval_status"], "pending")
        self.assertEqual(payload["alert_payload"]["notable_id"], "abc-123")

    def test_trusted_user_header_optional_on_loopback(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.get("/api/cases")

        self.assertEqual(response.status_code, 200)

    def test_trusted_user_header_required_off_loopback(self) -> None:
        config = Config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            PORTAL_BIND_HOST="0.0.0.0",
            PORTAL_TRUSTED_USER_HEADER="X-Forwarded-User",
        )
        client = TestClient(
            build_portal_app(
                config,
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        missing = client.get("/api/cases")
        allowed = client.get(
            "/api/cases",
            headers={"X-Forwarded-User": "analyst@example.com"},
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    def test_portal_has_no_mutating_routes(self) -> None:
        app = build_portal_app(
            self._config(),
            connect=lambda _dsn: _FakeConnection(rows=[]),
        )
        methods = {
            (route.path, method)
            for route in app.routes
            if hasattr(route, "methods")
            for method in route.methods
        }
        mutating = {
            item
            for item in methods
            if item[1] in {"POST", "PUT", "PATCH", "DELETE"}
        }
        self.assertEqual(mutating, set())


if __name__ == "__main__":
    unittest.main()
