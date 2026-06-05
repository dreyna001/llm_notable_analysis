import unittest
import uuid
from datetime import datetime, timedelta, timezone

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.case_chat import answer_case_chat
from llm_notable_analysis_onprem_systemd.onprem_service.case_chat_history import (
    build_delete_chat_session_query,
    build_delete_expired_chat_sessions_sql,
    build_list_chat_messages_query,
    build_list_chat_sessions_query,
    delete_chat_session,
    delete_expired_chat_sessions,
    list_chat_sessions,
    persist_chat_history,
    truncate_stored_message,
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


class _HistoryFakeConnection:
    def __init__(
        self,
        *,
        row_pages=None,
        case_exists=True,
        sessions=None,
        messages=None,
        fail=False,
    ):
        self.executed = []
        self.row_pages = list(row_pages or [])
        self.case_exists = case_exists
        self.sessions = dict(sessions or {})
        self.messages = list(messages or [])
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        if self.fail:
            raise OSError("database unavailable")
        self.executed.append((sql, params))
        if "case_chunks" in sql:
            rows = self.row_pages.pop(0) if self.row_pages else []
            return _FakeResult(rows)
        if "DELETE FROM" in sql and "chat_sessions" in sql:
            if "user_id IS NOT DISTINCT FROM" in sql:
                session_id, user_id = params
                existing = self.sessions.get(session_id)
                if existing is None:
                    return _FakeResult(row=None)
                stored_user = existing[1]
                if stored_user and user_id and stored_user != user_id:
                    return _FakeResult(row=None)
                del self.sessions[session_id]
                self.messages = [
                    message for message in self.messages if message[1] != session_id
                ]
                return _FakeResult(row=(session_id,))
            return _FakeResult(rows=[("session-1",)])
        if "cases" in sql and "case_id = %s" in sql and "chat_sessions" not in sql:
            return _FakeResult(row=(1,) if self.case_exists else None)
        if "chat_sessions" in sql and "SELECT" in sql and "session_id," in sql:
            return _FakeResult(row=self.sessions.get(params[0]))
        if "chat_sessions" in sql and "INSERT INTO" in sql:
            session_id, user_id, mode, selected_case_id, expires_at = params
            self.sessions[session_id] = (
                session_id,
                user_id,
                mode,
                selected_case_id,
                expires_at,
            )
            return _FakeResult()
        if "chat_sessions" in sql and "UPDATE" in sql:
            user_id, mode, selected_case_id, expires_at, session_id = params
            existing = self.sessions[session_id]
            self.sessions[session_id] = (
                session_id,
                user_id,
                mode,
                selected_case_id,
                expires_at,
            )
            return _FakeResult()
        if "chat_messages" in sql and "COUNT" in sql:
            count = sum(1 for message in self.messages if message[1] == params[0])
            return _FakeResult(row=(count,))
        if "chat_messages" in sql and "INSERT INTO" in sql:
            self.messages.append(params)
            return _FakeResult()
        return _FakeResult()


def _config(*, history_enabled: bool = True) -> Config:
    return Config(
        CASE_ARCHIVE_ENABLED=True,
        CASE_QA_ENABLED=True,
        CASE_QA_GLOBAL_RETRIEVAL_ENABLED=True,
        CASE_QA_CHAT_HISTORY_ENABLED=history_enabled,
        CASE_QA_CHAT_HISTORY_RETENTION_DAYS=7,
        CASE_QA_MAX_MESSAGES_PER_SESSION=4,
        CASE_QA_MAX_STORED_MESSAGE_BYTES=32,
        CASE_QA_LEXICAL_TOP_K=5,
        CASE_QA_VECTOR_TOP_K=5,
        CASE_QA_RRF_K=60,
        CASE_QA_MAX_CHUNKS_PER_LANE=3,
        CASE_QA_MAX_TOTAL_CHUNKS=6,
        CASE_QA_CONTEXT_BUDGET_CHARS=12000,
    )


class TestCaseChatHistory(unittest.TestCase):
    def test_truncate_stored_message_limits_utf8_bytes(self) -> None:
        truncated = truncate_stored_message("abcdé", 5)
        self.assertLessEqual(len(truncated.encode("utf-8")), 5)

    def test_build_delete_expired_chat_sessions_sql_targets_sessions(self) -> None:
        sql = build_delete_expired_chat_sessions_sql("notable_cases")
        self.assertIn('FROM "notable_cases".chat_sessions', sql)
        self.assertIn("RETURNING sessions.session_id", sql)

    def test_build_delete_chat_session_query_scopes_by_user(self) -> None:
        sql = build_delete_chat_session_query("notable_cases")
        self.assertIn('DELETE FROM "notable_cases".chat_sessions', sql)
        self.assertIn("user_id IS NOT DISTINCT FROM %s", sql)
        self.assertIn("RETURNING session_id", sql)

    def test_delete_chat_session_removes_session_and_messages(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "global_archive",
                    None,
                    expires_at,
                )
            },
            messages=[
                ("m1", session_id, "user", "one", "[]"),
                ("m2", session_id, "assistant", "two", "[]"),
            ],
        )
        deleted = delete_chat_session(
            config=_config(),
            session_id=session_id,
            user_id="analyst@example.com",
            connect=lambda _dsn: connection,
        )
        self.assertTrue(deleted)
        self.assertNotIn(session_id, connection.sessions)
        self.assertEqual(connection.messages, [])

    def test_delete_chat_session_is_disabled_without_history(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            delete_chat_session(
                config=_config(history_enabled=False),
                session_id=str(uuid.uuid4()),
                user_id="analyst@example.com",
                connect=lambda _dsn: _HistoryFakeConnection(),
            )

    def test_delete_chat_session_returns_false_for_unknown_session(self) -> None:
        deleted = delete_chat_session(
            config=_config(),
            session_id=str(uuid.uuid4()),
            user_id="analyst@example.com",
            connect=lambda _dsn: _HistoryFakeConnection(),
        )
        self.assertFalse(deleted)

    def test_build_list_chat_sessions_query_filters_by_user(self) -> None:
        sql = build_list_chat_sessions_query("notable_cases")
        self.assertIn("s.user_id IS NOT DISTINCT FROM %s", sql)
        self.assertIn("ORDER BY s.updated_at DESC", sql)

    def test_build_list_chat_messages_query_orders_messages(self) -> None:
        sql = build_list_chat_messages_query("notable_cases")
        self.assertIn('FROM "notable_cases".chat_messages', sql)
        self.assertIn("ORDER BY created_at ASC", sql)

    def test_list_chat_sessions_returns_empty_when_disabled(self) -> None:
        items = list_chat_sessions(
            config=Config(CASE_QA_CHAT_HISTORY_ENABLED=False),
            user_id="analyst@example.com",
        )
        self.assertEqual(items, [])

    def test_persist_chat_history_creates_new_session_and_messages(self) -> None:
        connection = _HistoryFakeConnection()
        session_id = persist_chat_history(
            config=_config(),
            mode="global_archive",
            question="What happened?",
            selected_case_id=None,
            requested_session_id=None,
            user_id="analyst@example.com",
            response={
                "answer": "Grounded answer.",
                "answer_status": "answered",
            },
            connect=lambda _dsn: connection,
        )

        self.assertTrue(session_id)
        self.assertEqual(len(connection.sessions), 1)
        self.assertEqual(len(connection.messages), 2)
        self.assertEqual(connection.messages[0][2], "user")
        self.assertEqual(connection.messages[1][2], "assistant")
        self.assertEqual(connection.messages[1][4], "[]")

    def test_persist_chat_history_resumes_existing_session(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "global_archive",
                    None,
                    expires_at,
                )
            }
        )
        resumed = persist_chat_history(
            config=_config(),
            mode="selected_case",
            question="Follow-up?",
            selected_case_id="case-1",
            requested_session_id=session_id,
            user_id="analyst@example.com",
            response={
                "answer": "Follow-up answer.",
                "answer_status": "answered",
            },
            connect=lambda _dsn: connection,
        )

        self.assertEqual(resumed, session_id)
        self.assertEqual(connection.sessions[session_id][2], "selected_case")
        self.assertEqual(connection.sessions[session_id][3], "case-1")

    def test_persist_chat_history_rejects_unknown_session(self) -> None:
        with self.assertRaisesRegex(ValueError, "session_id was not found"):
            persist_chat_history(
                config=_config(),
                mode="global_archive",
                question="What happened?",
                selected_case_id=None,
                requested_session_id="00000000-0000-0000-0000-000000000001",
                user_id="analyst@example.com",
                response={"answer": "x", "answer_status": "answered"},
                connect=lambda _dsn: _HistoryFakeConnection(),
            )

    def test_persist_chat_history_rejects_expired_session(self) -> None:
        session_id = str(uuid.uuid4())
        expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "global_archive",
                    None,
                    expired_at,
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "session_id has expired"):
            persist_chat_history(
                config=_config(),
                mode="global_archive",
                question="What happened?",
                selected_case_id=None,
                requested_session_id=session_id,
                user_id="analyst@example.com",
                response={"answer": "x", "answer_status": "answered"},
                connect=lambda _dsn: connection,
            )

    def test_persist_chat_history_rejects_user_mismatch(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst-a@example.com",
                    "global_archive",
                    None,
                    expires_at,
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "does not belong"):
            persist_chat_history(
                config=_config(),
                mode="global_archive",
                question="What happened?",
                selected_case_id=None,
                requested_session_id=session_id,
                user_id="analyst-b@example.com",
                response={"answer": "x", "answer_status": "answered"},
                connect=lambda _dsn: connection,
            )

    def test_persist_chat_history_enforces_message_limit(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "global_archive",
                    None,
                    expires_at,
                )
            },
            messages=[
                ("m1", session_id, "user", "one", "[]"),
                ("m2", session_id, "assistant", "two", "[]"),
                ("m3", session_id, "user", "three", "[]"),
            ],
        )
        with self.assertRaisesRegex(ValueError, "message limit"):
            persist_chat_history(
                config=_config(),
                mode="global_archive",
                question="What happened?",
                selected_case_id=None,
                requested_session_id=session_id,
                user_id="analyst@example.com",
                response={"answer": "x", "answer_status": "answered"},
                connect=lambda _dsn: connection,
            )

    def test_delete_expired_chat_sessions_is_disabled_without_history(self) -> None:
        connection = _HistoryFakeConnection()
        deleted = delete_expired_chat_sessions(
            config=_config(history_enabled=False),
            connect=lambda _dsn: connection,
        )
        self.assertEqual(deleted, 0)
        self.assertEqual(connection.executed, [])

    def test_delete_expired_chat_sessions_counts_deleted_rows(self) -> None:
        connection = _HistoryFakeConnection()
        deleted = delete_expired_chat_sessions(
            config=_config(),
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            connect=lambda _dsn: connection,
        )
        self.assertEqual(deleted, 1)

    def test_answer_case_chat_returns_session_id_when_history_enabled(self) -> None:
        connection = _HistoryFakeConnection(
            row_pages=[
                [
                    (
                        "case-1:case_analysis:analysis.evidence_vs_inference:0",
                        "case-1",
                        "case_analysis",
                        "analysis.evidence_vs_inference",
                        "$.evidence_vs_inference.evidence[0]",
                        "Evidence text.",
                        {"field_path": "$.evidence_vs_inference.evidence[0]"},
                        0.9,
                    )
                ],
                [],
            ]
        )
        response = answer_case_chat(
            payload={
                "mode": "selected_case",
                "question": "What evidence supports this?",
                "selected_case_id": "case-1",
            },
            config=_config(),
            connect=lambda _dsn: connection,
            user_id="analyst@example.com",
            synthesize=lambda _question, _sources: "Grounded answer.",
        )

        self.assertEqual(response["answer_status"], "answered")
        self.assertIsNotNone(response["session_id"])
        self.assertEqual(len(connection.messages), 2)


if __name__ == "__main__":
    unittest.main()
