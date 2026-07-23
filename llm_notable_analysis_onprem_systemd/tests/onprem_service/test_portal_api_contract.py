"""Portal API contract tests: OpenAPI snapshot and response-model alignment."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.portal_api_models import (
    CaseDetailResponse,
    CaseListResponse,
    CaseRawSectionResponse,
    PortalCapabilitiesResponse,
    portal_response,
)
from llm_notable_analysis_onprem_systemd.onprem_service.portal_app import build_portal_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = (
    PROJECT_ROOT
    / "frontend"
    / "analyst-portal"
    / "openapi"
    / "portal.openapi.json"
)
_AUTH_HEADERS = {
    "X-Forwarded-User": "analyst@example.com",
    "X-Notable-Portal-Proxy-Secret": "portal-secret",
}


class _FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        return [[1.0] + [0.0] * 1023 for _text in texts]


def _portal_config() -> Config:
    return Config(
        PORTAL_ENABLED=True,
        CASE_ARCHIVE_ENABLED=True,
        PORTAL_BIND_HOST="127.0.0.1",
        PORTAL_PAGE_SIZE=50,
        PORTAL_TRUSTED_USER_HEADER="X-Forwarded-User",
        PORTAL_PROXY_SECRET="portal-secret",
        CASE_QA_ENABLED=True,
        CASE_QA_CHAT_HISTORY_ENABLED=True,
        CASE_QA_MAX_QUESTION_CHARS=1234,
        CASE_QA_MAX_ANSWER_TOKENS=567,
        CASE_QA_MAX_SESSIONS_PER_USER=10,
    )


class TestPortalApiContract(unittest.TestCase):
    def test_committed_openapi_matches_live_app_schema(self) -> None:
        app = build_portal_app(_portal_config())
        live_schema = app.openapi()
        committed_schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        self.assertEqual(live_schema, committed_schema)

    def test_capabilities_json_validates_against_response_model(self) -> None:
        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.case_chat."
            "_get_embedding_model",
            side_effect=AssertionError(
                "Portal contract tests must inject an embedding test double."
            ),
        ):
            client = TestClient(
                build_portal_app(
                    _portal_config(),
                    connect=lambda _dsn: _FakeConnection(rows=[]),
                    chat_embedding_model=_FakeEmbeddingModel(),
                    chat_llm_gateway_ready=True,
                )
            )
            response = client.get("/api/capabilities", headers=_AUTH_HEADERS)
        self.assertEqual(response.status_code, 200)
        validated = portal_response(PortalCapabilitiesResponse, response.json())
        self.assertEqual(validated.model_dump(exclude_unset=True), response.json())

    def test_case_list_json_validates_against_response_model(self) -> None:
        record = build_case_archive_record(
            config=_portal_config(),
            case_id="case-1",
            finding_id="case-1",
            source_filename="case-1.json",
            alert_payload={"notable_id": "abc-123"},
            analysis={"alert_reconciliation": {"verdict": "likely_malicious"}},
            report_md_path="/reports/case-1.md",
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )
        client = TestClient(
            build_portal_app(
                _portal_config(),
                connect=lambda _dsn: _FakeConnection(rows=[_summary_row(record)]),
            )
        )
        response = client.get("/api/cases", headers=_AUTH_HEADERS)
        self.assertEqual(response.status_code, 200)
        validated = portal_response(CaseListResponse, response.json())
        self.assertEqual(
            validated.model_dump(mode="json", exclude_unset=True),
            response.json(),
        )

    def test_case_detail_json_validates_against_response_model(self) -> None:
        record = build_case_archive_record(
            config=_portal_config(),
            case_id="case-1",
            finding_id="case-1",
            source_filename="case-1.json",
            alert_payload={"notable_id": "abc-123"},
            analysis={"alert_reconciliation": {"verdict": "likely_malicious"}},
            report_md_path="/reports/case-1.md",
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )
        client = TestClient(
            build_portal_app(
                _portal_config(),
                connect=lambda _dsn: _FakeConnection(row=_detail_row(record)),
            )
        )
        response = client.get("/api/cases/case-1", headers=_AUTH_HEADERS)
        self.assertEqual(response.status_code, 200)
        validated = portal_response(CaseDetailResponse, response.json())
        self.assertEqual(
            validated.model_dump(mode="json", exclude_unset=True),
            response.json(),
        )

    def test_case_raw_section_json_validates_against_response_model(self) -> None:
        record = build_case_archive_record(
            config=_portal_config(),
            case_id="case-1",
            finding_id="case-1",
            source_filename="case-1.json",
            alert_payload={"notable_id": "abc-123"},
            analysis={
                "alert_reconciliation": {"verdict": "likely_malicious"},
                "raw_response": "archived raw output",
            },
            report_md_path="/reports/case-1.md",
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )
        client = TestClient(
            build_portal_app(
                _portal_config(),
                connect=lambda _dsn: _FakeConnection(row=_detail_row(record)),
            )
        )
        response = client.get(
            "/api/cases/case-1/raw/analysis",
            params={"key": "raw_response"},
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        validated = portal_response(CaseRawSectionResponse, response.json())
        self.assertEqual(
            validated.model_dump(mode="json", exclude_unset=True),
            response.json(),
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
    def __init__(self, *, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        del params
        if "WHERE case_id = %s" in sql:
            return _FakeResult(row=self.row)
        return _FakeResult(rows=self.rows)


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
