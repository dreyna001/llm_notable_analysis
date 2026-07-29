"""Tests for preview portal fake Postgres and chunk fixtures."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SRC_DIR = PROJECT_ROOT / "src"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (  # noqa: E402
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config  # noqa: E402
from preview_fake_db import (  # noqa: E402
    PREVIEW_FAKE_VECTOR_DIMENSIONS,
    PreviewCaseStore,
    PreviewFakeConnection,
    PreviewFakeEmbeddingModel,
    build_chunk_rows,
    build_preview_connect_factory,
    detail_row,
    summary_row,
)
from preview_synthetic_pipeline import (  # noqa: E402
    build_synthetic_preview_record,
    ensure_preview_bundles_present,
)


def _rich_analysis() -> dict:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
            "confidence": "0.82",
            "one_sentence_summary": "Suspicious PowerShell from admin host.",
        },
        "competing_hypotheses": [
            {
                "hypothesis_type": "benign",
                "summary": "Admin script.",
                "supporting_evidence": ["known admin host"],
            },
            {
                "hypothesis_type": "adversary",
                "summary": "Credentialed execution.",
                "supporting_evidence": ["encoded command"],
            },
        ],
        "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
        "ioc_extraction": {"ips": ["10.0.0.1"], "domains": ["example.test"]},
        "ttp_analysis": [{"ttp_id": "T1059.001", "confidence_score": 0.8}],
        "query_result_section": {"status": "not_run", "results": []},
        "servicenow_section": {"draft": {"status": "skipped"}},
    }


def _minimal_record(*, case_id: str, config: Config):
    processed_at = datetime(2026, 6, 4, tzinfo=timezone.utc)
    return build_case_archive_record(
        config=config,
        case_id=case_id,
        finding_id=case_id,
        source_filename=f"{case_id}.json",
        alert_payload={
            "notable_id": "abc-001",
            "search_name": "Suspicious PowerShell",
        },
        analysis={
            "alert_reconciliation": {
                "verdict": "unknown",
                "confidence": "0.50",
                "one_sentence_summary": "Minimal preview filler.",
            },
            "competing_hypotheses": [],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {},
            "ttp_analysis": [],
        },
        report_md_path=f"/reports/{case_id}.md",
        report_html_path=None,
        processed_at=processed_at,
    )


class PreviewFakeDbTests(unittest.TestCase):
    def test_fake_embedding_returns_768_dimensions(self) -> None:
        model = PreviewFakeEmbeddingModel()
        vectors = model.encode(["question one", "question two"])
        self.assertEqual(len(vectors), 2)
        for vector in vectors:
            self.assertEqual(len(vector), PREVIEW_FAKE_VECTOR_DIMENSIONS)
            self.assertEqual(vector[0], 1.0)
            self.assertTrue(all(value == 0.0 for value in vector[1:]))

    def test_build_chunk_rows_produces_multiple_chunks_for_rich_record(self) -> None:
        config = Config()
        record = build_case_archive_record(
            config=config,
            case_id="case-rich",
            finding_id="case-rich",
            source_filename="case-rich.json",
            alert_payload={
                "notable_id": "abc-123",
                "search_name": "Suspicious PowerShell",
                "user": "admin",
                "command_line": "powershell -enc AAAA",
            },
            analysis=_rich_analysis(),
            report_md_path="/reports/case-rich.md",
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        rows = build_chunk_rows([record], config)

        self.assertGreater(len(rows), 1)
        case_ids = {row[1] for row in rows}
        self.assertEqual(case_ids, {"case-rich"})

    def test_build_chunk_rows_minimal_filler_has_at_least_one_chunk(self) -> None:
        config = Config()
        record = _minimal_record(case_id="case-42", config=config)

        rows = build_chunk_rows([record], config)

        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "case-42")

    def test_mutable_case_store_publishes_new_case_and_chunks(self) -> None:
        config = Config()
        store = PreviewCaseStore(
            [_minimal_record(case_id="case-1", config=config)],
            config,
        )
        store.upsert(_minimal_record(case_id="case-live", config=config))

        connection = store.connect("preview://fake")
        detail = connection.execute(
            "SELECT * FROM cases WHERE case_id = %s",
            ("case-live",),
        ).fetchone()
        chunks = connection.execute(
            "SELECT * FROM case_chunks ch WHERE ch.case_id = %s LIMIT %s",
            ("case-live", 100),
        ).fetchall()

        self.assertIsNotNone(detail)
        self.assertEqual(detail[0], "case-live")
        self.assertGreaterEqual(len(chunks), 1)

    def test_preview_connect_factory_indexes_pipeline_backed_cases(self) -> None:
        ensure_preview_bundles_present()
        config = Config()
        processed_at = datetime(2026, 6, 4, tzinfo=timezone.utc)
        records = [
            build_synthetic_preview_record(
                config=config,
                scenario_index=index,
                case_id=f"case-{index}",
                finding_id=f"syn-{index:03d}",
                source_filename=f"syn-case-{index}.json",
                processed_at=processed_at - timedelta(hours=index),
            )
            for index in range(1, 6)
        ]
        connect = build_preview_connect_factory(records, config)
        connection = connect("preview://fake")

        case_one_chunks = connection.execute(
            "SELECT ch.chunk_id FROM case_chunks ch WHERE ch.case_id = %s LIMIT %s",
            ("case-1", 100),
        ).fetchall()

        self.assertGreater(len(case_one_chunks), 1)

    def test_fake_connection_supports_chat_session_insert_and_list(self) -> None:
        config = Config()
        record = _minimal_record(case_id="case-1", config=config)
        connection = PreviewFakeConnection(
            summary_rows=[summary_row(record)],
            details_by_case_id={"case-1": detail_row(record)},
            chunk_rows=build_chunk_rows([record], config),
        )
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection.execute(
            "INSERT INTO chat_sessions VALUES (%s, %s, %s, %s, %s)",
            ("session-1", "user@test", "selected_case", "case-1", expires_at),
        )
        connection.execute(
            "INSERT INTO chat_messages VALUES (%s, %s, %s, %s, %s, %s)",
            ("msg-1", "session-1", "user", "What happened?", None, "answered"),
        )

        sessions = connection.execute(
            "SELECT FROM chat_sessions ORDER BY s.updated_at DESC LIMIT %s",
            ("user@test", 10),
        ).fetchall()
        messages = connection.execute(
            "SELECT FROM chat_messages ORDER BY created_at ASC LIMIT %s",
            ("session-1",),
        ).fetchall()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0][0], "session-1")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][0], "user")
        self.assertEqual(messages[0][1], "What happened?")

    def test_connect_factory_shares_session_state_across_connections(self) -> None:
        config = Config()
        record = _minimal_record(case_id="case-1", config=config)
        connect = build_preview_connect_factory([record], config)
        write_conn = connect("preview://fake")
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        write_conn.execute(
            "INSERT INTO chat_sessions VALUES (%s, %s, %s, %s, %s)",
            ("session-shared", "user@test", "selected_case", "case-1", expires_at),
        )
        write_conn.execute(
            "INSERT INTO chat_messages VALUES (%s, %s, %s, %s, %s, %s)",
            ("msg-1", "session-shared", "user", "First question", None, "answered"),
        )

        read_conn = connect("preview://fake")
        sessions = read_conn.execute(
            "SELECT FROM chat_sessions ORDER BY s.updated_at DESC LIMIT %s",
            ("user@test", 10),
        ).fetchall()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0][0], "session-shared")


class PreviewPortalSessionPersistenceTests(unittest.TestCase):
    def test_build_preview_app_persists_chat_sessions_across_requests(self) -> None:
        from fastapi.testclient import TestClient

        from preview_portal_ui import build_preview_app, preview_auth_headers

        client = TestClient(build_preview_app(inject_loopback_auth=False))
        headers = preview_auth_headers()

        first = client.post(
            "/api/chat",
            json={
                "mode": "selected_case",
                "selected_case_id": "case-1",
                "question": "What is the verdict?",
            },
            headers=headers,
        )
        self.assertEqual(first.status_code, 200, first.text)
        session_id = first.json().get("session_id")
        self.assertTrue(session_id)

        listed = client.get("/api/chat/sessions", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        payload = listed.json()
        self.assertTrue(payload.get("history_enabled"))
        items = payload.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["session_id"], session_id)


if __name__ == "__main__":
    unittest.main()
