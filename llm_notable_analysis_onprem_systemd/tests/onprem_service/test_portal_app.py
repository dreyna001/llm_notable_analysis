from datetime import date, datetime, timezone
import inspect
import json
import threading
import unittest
import uuid
from unittest.mock import patch

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from fastapi.testclient import TestClient

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.openai_transport_nonsdk import (
    RateLimitError,
    RequestTimeoutError,
    ServerError,
    TransportError,
)
from llm_notable_analysis_onprem_systemd.onprem_service.portal_app import (
    _parse_list_filters,
    build_portal_app,
    check_case_archive_ready,
    parse_iso8601_timestamp,
    parse_utc_calendar_date,
    utc_day_end,
    utc_day_start,
)

_USER_HEADERS = {"X-Forwarded-User": "analyst@example.com"}
_AUTH_HEADERS = {
    **_USER_HEADERS,
    "X-Notable-Portal-Proxy-Secret": "portal-secret",
}


class _FakeResult:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class _ProgrammingErrorConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        del sql, params
        raise AttributeError("simulated row-mapping bug")


class _FakeConnection:
    def __init__(self, *, rows=None, row=None, row_pages=None, ready=True, fail=False):
        self.executed = []
        self.rows = rows or []
        self.row = row
        self.row_pages = list(row_pages or [])
        self.ready = ready
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        if self.fail or (not self.ready and "set_config" not in sql):
            raise OSError("database unavailable")
        self.executed.append((sql, params))
        if "to_regclass" in sql:
            return _FakeResult(row=(self.ready, self.ready))
        if "case_chunks" in sql:
            rows = self.row_pages.pop(0) if self.row_pages else []
            return _FakeResult(rows=rows)
        if "WHERE case_id = %s" in sql:
            return _FakeResult(row=self.row)
        return _FakeResult(rows=self.rows)


class _FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del texts, show_progress_bar, convert_to_numpy
        return [[1.0] + [0.0] * 767]


class _BadEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del texts, show_progress_bar, convert_to_numpy
        return [[1.0, 0.0]]


def _analysis() -> dict:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
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


def _chunk_row(record):
    return (
        "case-1:case_analysis:analysis.evidence_vs_inference:0",
        record.case_id,
        "case_analysis",
        "analysis.evidence_vs_inference",
        "$.evidence_vs_inference.evidence[0]",
        "The alert contains admin PowerShell execution evidence.",
        {"field_path": "$.evidence_vs_inference.evidence[0]"},
        0.9,
    )


class TestPortalApp(unittest.TestCase):
    def _config(self) -> Config:
        return Config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            PORTAL_BIND_HOST="127.0.0.1",
            PORTAL_PAGE_SIZE=50,
            PORTAL_TRUSTED_USER_HEADER="X-Forwarded-User",
            PORTAL_PROXY_SECRET="portal-secret",
        )

    def test_parse_iso8601_timestamp_accepts_zulu_suffix(self) -> None:
        parsed = parse_iso8601_timestamp("2026-06-04T00:00:00Z", "start")
        self.assertEqual(parsed, datetime(2026, 6, 4, tzinfo=timezone.utc))

    def test_parse_utc_calendar_date_accepts_yyyy_mm_dd(self) -> None:
        parsed = parse_utc_calendar_date("2026-06-04", "start_date")
        self.assertEqual(parsed, date(2026, 6, 4))

    def test_parse_list_filters_maps_utc_calendar_dates_to_day_bounds(self) -> None:
        filters = _parse_list_filters(
            limit=None,
            cursor_processed_at=None,
            cursor_case_id=None,
            start=None,
            end=None,
            start_date="2026-06-01",
            end_date="2026-06-04",
            verdict=None,
            search_name=None,
        )
        self.assertEqual(
            filters.processed_from,
            utc_day_start(date(2026, 6, 1)),
        )
        self.assertEqual(
            filters.processed_to,
            utc_day_end(date(2026, 6, 4)),
        )

    def test_parse_list_filters_rejects_mixed_date_parameters(self) -> None:
        with self.assertRaisesRegex(ValueError, "start_date"):
            _parse_list_filters(
                limit=None,
                cursor_processed_at=None,
                cursor_case_id=None,
                start="2026-06-01T00:00:00Z",
                end=None,
                start_date="2026-06-01",
                end_date=None,
                verdict=None,
                search_name=None,
            )

    def test_api_cases_accepts_utc_calendar_date_filters(self) -> None:
        connections: list[_FakeConnection] = []

        def connect(_dsn):
            connection = _FakeConnection(rows=[_summary_row(_record(self._config()))])
            connections.append(connection)
            return connection

        client = TestClient(
            build_portal_app(
                self._config(),
                connect=connect,
            )
        )

        response = client.get(
            "/api/cases",
            params={"start_date": "2026-06-04", "end_date": "2026-06-04"},
            headers=_AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 200)
        list_queries = [
            params
            for sql, params in connections[0].executed
            if "processed_at >=" in sql
        ]
        self.assertEqual(len(list_queries), 1)
        self.assertEqual(
            list_queries[0][0],
            datetime(2026, 6, 4, tzinfo=timezone.utc),
        )
        self.assertEqual(
            list_queries[0][1],
            utc_day_end(date(2026, 6, 4)),
        )

    def test_check_case_archive_ready_requires_read_access(self) -> None:
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

    def test_fastapi_portal_does_not_serve_html_ui_routes(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.get("/", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 404)

    def test_ready_does_not_run_expensive_chat_retrieval_check(self) -> None:
        config = Config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            CASE_QA_ENABLED=True,
            PORTAL_PROXY_SECRET="portal-secret",
        )

        response = TestClient(
            build_portal_app(
                config,
                connect=lambda _dsn: _FakeConnection(row_pages=[[], []]),
                chat_embedding_model=_BadEmbeddingModel(),
            )
        ).get("/ready")

        self.assertEqual(response.status_code, 200)

    def test_chat_readiness_diagnostic_checks_retrieval_dependencies(self) -> None:
        config = Config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            CASE_QA_ENABLED=True,
            PORTAL_PROXY_SECRET="portal-secret",
        )

        response = TestClient(
            build_portal_app(
                config,
                connect=lambda _dsn: _FakeConnection(row_pages=[[], []]),
                chat_embedding_model=_BadEmbeddingModel(),
            )
        ).get("/api/diagnostics/chat-readiness", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 503)

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.case_chat._probe_llm_reachable",
        return_value=True,
    )
    def test_api_capabilities_returns_chat_runtime_contract(
        self,
        _mock_llm_probe,
    ) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    CASE_QA_GLOBAL_RETRIEVAL_ENABLED=False,
                    CASE_QA_CHAT_HISTORY_ENABLED=True,
                    CASE_QA_MAX_QUESTION_CHARS=1234,
                    CASE_QA_MAX_ANSWER_TOKENS=567,
                    CASE_QA_MAX_SESSIONS_PER_USER=10,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(row_pages=[[], []]),
                chat_embedding_model=_FakeEmbeddingModel(),
            )
        )

        response = client.get("/api/capabilities", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "case_qa_enabled": True,
                "global_retrieval_enabled": False,
                "chat_history_enabled": True,
                "general_knowledge_enabled": True,
                "max_question_chars": 1234,
                "max_answer_tokens": 567,
                "max_chat_sessions_per_user": 10,
                "case_retention_days": 30,
                "chat_ready": True,
            },
        )

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.case_chat._probe_llm_reachable",
        return_value=True,
    )
    def test_api_capabilities_reports_chat_not_ready_when_dependencies_fail(
        self,
        _mock_llm_probe,
    ) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(row_pages=[[], []]),
                chat_embedding_model=_BadEmbeddingModel(),
            )
        )

        response = client.get("/api/capabilities", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["chat_ready"])
        self.assertIn("chat_degraded_reason", payload)

    def test_api_cases_returns_paginated_items(self) -> None:
        record = _record(self._config())
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[_summary_row(record)]),
            )
        )

        response = client.get("/api/cases", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["limit"], 50)
        self.assertFalse(payload["has_more"])
        self.assertIsNone(payload["next_cursor"])
        self.assertEqual(payload["items"][0]["case_id"], "case-1")

    def test_api_cases_uses_extra_row_for_has_more(self) -> None:
        record = _record(self._config())
        full_page_client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[_summary_row(record)] * 50),
            )
        )
        extra_row_client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[_summary_row(record)] * 51),
            )
        )

        full_page = full_page_client.get("/api/cases", headers=_AUTH_HEADERS).json()
        extra_row = extra_row_client.get("/api/cases", headers=_AUTH_HEADERS).json()

        self.assertEqual(len(full_page["items"]), 50)
        self.assertFalse(full_page["has_more"])
        self.assertEqual(len(extra_row["items"]), 50)
        self.assertTrue(extra_row["has_more"])
        self.assertEqual(
            extra_row["next_cursor"],
            {
                "processed_at": extra_row["items"][-1]["processed_at"],
                "case_id": extra_row["items"][-1]["case_id"],
            },
        )

    def test_api_cases_rejects_invalid_filters(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.get(
            "/api/cases",
            params={"limit": "0"},
            headers=_AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 400)

    def test_api_case_detail_returns_404_for_unknown_case(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(row=None),
            )
        )

        response = client.get("/api/cases/missing-case", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 404)

    def test_api_case_detail_maps_database_failures_to_unavailable(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(fail=True),
            )
        )

        response = client.get("/api/cases/case-1", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Case archive unavailable.")

    def test_api_case_detail_maps_programming_errors_to_internal_error(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _ProgrammingErrorConnection(),
            )
        )

        response = client.get("/api/cases/case-1", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Internal server error.")

    def test_api_cases_maps_transient_database_failures_to_unavailable(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(fail=True),
            )
        )

        response = client.get("/api/cases", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Case archive unavailable.")

    def test_api_cases_maps_programming_errors_to_internal_error(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _ProgrammingErrorConnection(),
            )
        )

        response = client.get("/api/cases", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Internal server error.")

    def test_api_case_detail_returns_canonical_payload(self) -> None:
        record = _record(self._config())
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(row=_detail_row(record)),
            )
        )

        response = client.get("/api/cases/case-1", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["case_id"], "case-1")
        self.assertEqual(payload["metadata"]["retrieval_status"], "pending")
        self.assertEqual(payload["alert_payload"]["notable_id"], "abc-123")

    def test_api_case_detail_returns_null_analysis_for_missing_structured_output(self) -> None:
        record = _record(self._config())
        row = list(_detail_row(record))
        row[9] = json.dumps(None)
        row[18] = "not_indexed"
        row[20] = "missing_analysis"
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(row=tuple(row)),
            )
        )

        response = client.get("/api/cases/case-1", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["analysis"])
        self.assertEqual(payload["metadata"]["retrieval_status"], "not_indexed")
        self.assertEqual(payload["metadata"]["source_completeness"], "missing_analysis")
        self.assertIn("archive_notices", payload["metadata"])
        self.assertGreaterEqual(len(payload["metadata"]["archive_notices"]), 2)

    def test_api_case_detail_includes_archive_notices_for_failed_indexing(self) -> None:
        record = _record(self._config())
        row = list(_detail_row(record))
        row[18] = "failed"
        row[20] = "complete"
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(row=tuple(row)),
            )
        )

        response = client.get("/api/cases/case-1", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        notices = payload["metadata"]["archive_notices"]
        self.assertEqual(len(notices), 1)
        self.assertIn("chat indexing failed", notices[0])

    def test_trusted_user_header_required_on_loopback(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        missing = client.get("/api/cases")
        forged_user = client.get("/api/cases", headers=_USER_HEADERS)
        allowed = client.get("/api/cases", headers=_AUTH_HEADERS)

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(forged_user.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    def test_mutating_routes_reject_cross_site_browser_requests(self) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.post(
            "/api/chat",
            json={"mode": "global_archive", "question": "What happened?"},
            headers={
                **_AUTH_HEADERS,
                "Origin": "https://attacker.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_mutating_routes_allow_same_origin_browser_requests(self) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    CASE_QA_GLOBAL_RETRIEVAL_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.post(
            "/api/chat",
            json={
                "mode": "global_archive",
                "question": "Run a Splunk search and create a ticket",
            },
            headers={
                **_AUTH_HEADERS,
                "Origin": "http://testserver",
                "Sec-Fetch-Site": "same-origin",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer_status"], "refused")

    def test_non_loopback_bind_requires_explicit_allow(self) -> None:
        config = Config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            PORTAL_BIND_HOST="0.0.0.0",
            PORTAL_TRUSTED_USER_HEADER="X-Forwarded-User",
            PORTAL_PROXY_SECRET="portal-secret",
        )

        with self.assertRaisesRegex(ValueError, "PORTAL_BIND_HOST"):
            build_portal_app(config, connect=lambda _dsn: _FakeConnection(rows=[]))

    def test_non_loopback_bind_requires_proxy_secret(self) -> None:
        with self.assertRaisesRegex(ValueError, "PORTAL_PROXY_SECRET"):
            Config(
                PORTAL_ENABLED=True,
                CASE_ARCHIVE_ENABLED=True,
                PORTAL_BIND_HOST="0.0.0.0",
                PORTAL_TRUSTED_USER_HEADER="X-Forwarded-User",
                PORTAL_ALLOW_NON_LOOPBACK_BIND=True,
            )

    def test_non_loopback_proxy_secret_required_for_requests(self) -> None:
        config = Config(
            PORTAL_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            PORTAL_BIND_HOST="0.0.0.0",
            PORTAL_TRUSTED_USER_HEADER="X-Forwarded-User",
            PORTAL_ALLOW_NON_LOOPBACK_BIND=True,
            PORTAL_PROXY_SECRET="portal-secret",
        )
        client = TestClient(
            build_portal_app(
                config,
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        missing = client.get("/api/cases", headers=_USER_HEADERS)
        allowed = client.get("/api/cases", headers=_AUTH_HEADERS)

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    def test_portal_has_no_mutating_routes(self) -> None:
        """Case archive routes stay read-only; chat history has bounded mutations only."""
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
        self.assertEqual(
            mutating,
            {
                ("/api/chat", "POST"),
                ("/api/chat/sessions/{session_id}", "DELETE"),
                ("/api/chat/sessions/{session_id}/turns/last", "DELETE"),
            },
        )

    def test_api_list_chat_sessions_when_history_disabled(self) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    CASE_QA_CHAT_HISTORY_ENABLED=False,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.get("/api/chat/sessions", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["history_enabled"])
        self.assertEqual(payload["items"], [])

    def test_api_delete_chat_session_when_history_disabled(self) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    CASE_QA_CHAT_HISTORY_ENABLED=False,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.delete(
            f"/api/chat/sessions/{uuid.uuid4()}",
            headers=_AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Chat history is disabled.")

    def test_api_chat_returns_refusal_for_action_request(self) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    CASE_QA_GLOBAL_RETRIEVAL_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.post(
            "/api/chat",
            json={
                "mode": "global_archive",
                "question": "Run a Splunk search and create a ticket",
            },
            headers=_AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer_status"], "refused")

    def test_api_chat_validates_request(self) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.post(
            "/api/chat",
            json={"mode": "selected_case", "question": "What happened?"},
            headers=_AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 400)

    def test_api_chat_returns_404_for_unknown_selected_case(self) -> None:
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(row=None),
            )
        )

        response = client.post(
            "/api/chat",
            json={
                "mode": "selected_case",
                "question": "What evidence supports this?",
                "selected_case_id": "missing-case",
            },
            headers=_AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Case not found.")

    def test_api_chat_handler_is_async(self) -> None:
        app = build_portal_app(
            Config(
                PORTAL_ENABLED=True,
                CASE_ARCHIVE_ENABLED=True,
                CASE_QA_ENABLED=True,
                PORTAL_PROXY_SECRET="portal-secret",
            ),
            connect=lambda _dsn: _FakeConnection(rows=[]),
        )
        route = next(route for route in app.routes if getattr(route, "path", None) == "/api/chat")
        self.assertTrue(inspect.iscoroutinefunction(route.endpoint))

    def test_api_chat_returns_429_when_concurrency_exhausted(self) -> None:
        started = threading.Event()
        release = threading.Event()
        record = _record(
            Config(
                PORTAL_ENABLED=True,
                CASE_ARCHIVE_ENABLED=True,
                CASE_QA_ENABLED=True,
                PORTAL_PROXY_SECRET="portal-secret",
                PORTAL_CHAT_MAX_CONCURRENCY=1,
            )
        )

        def slow_synthesize(_question, _sources):
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("timed out waiting for chat release")
            return "slow answer"

        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                    PORTAL_CHAT_MAX_CONCURRENCY=1,
                ),
                connect=lambda _dsn: _FakeConnection(
                    row=_detail_row(record),
                    row_pages=[[_chunk_row(record)], []],
                ),
                chat_embedding_model=_FakeEmbeddingModel(),
                chat_synthesizer=slow_synthesize,
            )
        )
        chat_payload = {
            "mode": "selected_case",
            "question": "What evidence supports this?",
            "selected_case_id": "case-1",
        }

        first = threading.Thread(
            target=lambda: client.post(
                "/api/chat",
                json=chat_payload,
                headers=_AUTH_HEADERS,
            )
        )
        first.start()
        self.assertTrue(started.wait(timeout=5))

        blocked = client.post("/api/chat", json=chat_payload, headers=_AUTH_HEADERS)

        release.set()
        first.join(timeout=10)
        self.assertFalse(first.is_alive())
        self.assertEqual(blocked.status_code, 429)

    def test_api_chat_returns_answer(self) -> None:
        record = _record(self._config())
        client = TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(
                    row=_detail_row(record),
                    row_pages=[[_chunk_row(record)], []],
                ),
                chat_embedding_model=_FakeEmbeddingModel(),
                chat_synthesizer=lambda _question, sources: (
                    f"Answered with {len(sources)} source."
                ),
            )
        )

        response = client.post(
            "/api/chat",
            json={
                "mode": "selected_case",
                "question": "What evidence supports this?",
                "selected_case_id": "case-1",
            },
            headers=_AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer_status"], "answered")
        self.assertNotIn("citations", payload)
        self.assertNotIn("retrieved_case_ids", payload)

    def _chat_client_with_synthesizer(self, synthesizer):
        record = _record(self._config())
        return TestClient(
            build_portal_app(
                Config(
                    PORTAL_ENABLED=True,
                    CASE_ARCHIVE_ENABLED=True,
                    CASE_QA_ENABLED=True,
                    PORTAL_PROXY_SECRET="portal-secret",
                ),
                connect=lambda _dsn: _FakeConnection(
                    row=_detail_row(record),
                    row_pages=[[_chunk_row(record)], []],
                ),
                chat_embedding_model=_FakeEmbeddingModel(),
                chat_synthesizer=synthesizer,
            )
        )

    def _post_chat(self, client: TestClient) -> object:
        return client.post(
            "/api/chat",
            json={
                "mode": "selected_case",
                "question": "What evidence supports this?",
                "selected_case_id": "case-1",
            },
            headers=_AUTH_HEADERS,
        )

    def test_api_chat_maps_llm_rate_limit_to_429(self) -> None:
        def _raise_rate_limit(_question, _sources):
            raise RateLimitError("LLM API rate limited (429)")

        response = self._post_chat(
            self._chat_client_with_synthesizer(_raise_rate_limit),
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.json()["detail"],
            "LLM rate limit reached. Try again shortly.",
        )

    def test_api_chat_maps_llm_timeout_to_504(self) -> None:
        def _raise_timeout(_question, _sources):
            raise RequestTimeoutError("LLM request timed out")

        response = self._post_chat(
            self._chat_client_with_synthesizer(_raise_timeout),
        )

        self.assertEqual(response.status_code, 504)
        self.assertIn("timed out", response.json()["detail"])

    def test_api_chat_maps_llm_server_error_to_503(self) -> None:
        def _raise_server_error(_question, _sources):
            raise ServerError("LLM server error: HTTP 502")

        response = self._post_chat(
            self._chat_client_with_synthesizer(_raise_server_error),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "LLM service unavailable.")

    def test_api_chat_maps_llm_transport_error_to_503(self) -> None:
        def _raise_transport_error(_question, _sources):
            raise TransportError("LLM transport error: connection reset")

        response = self._post_chat(
            self._chat_client_with_synthesizer(_raise_transport_error),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "LLM service unavailable.")


if __name__ == "__main__":
    unittest.main()
