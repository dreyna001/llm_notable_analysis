from datetime import datetime, timezone
import json
import unittest
import uuid

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
        self.assertEqual(
            health.json(),
            {"status": "ok", "case_retention_days": 30},
        )
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json(), {"status": "ready"})
        self.assertEqual(not_ready.status_code, 503)

    def test_portal_home_renders_html(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(rows=[]),
            )
        )

        response = client.get("/", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Notable Analyst Portal", response.text)
        self.assertIn('href="/cases"', response.text)

    def test_ready_includes_chat_retrieval_dependencies_when_enabled(self) -> None:
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

        self.assertEqual(response.status_code, 503)

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
        self.assertEqual(payload["offset"], 0)
        self.assertFalse(payload["has_more"])
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

    def test_portal_case_detail_maps_database_failures_to_unavailable(self) -> None:
        client = TestClient(
            build_portal_app(
                self._config(),
                connect=lambda _dsn: _FakeConnection(fail=True),
            )
        )

        response = client.get("/cases/case-1", headers=_AUTH_HEADERS)

        self.assertEqual(response.status_code, 503)

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


if __name__ == "__main__":
    unittest.main()
