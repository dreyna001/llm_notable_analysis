import threading
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.case_chat import answer_case_chat
from llm_notable_analysis_onprem_systemd.onprem_service.case_chat_history import (
    ChatSessionExpiredError,
    ChatSessionNotFoundError,
    build_count_active_user_chat_sessions_query,
    build_delete_chat_session_query,
    build_delete_expired_chat_sessions_sql,
    build_delete_last_chat_turn_query,
    build_delete_oldest_user_chat_sessions_query,
    build_lock_chat_session_row_query,
    build_list_chat_messages_query,
    build_list_chat_sessions_query,
    delete_chat_session,
    delete_expired_chat_sessions,
    delete_last_chat_turn,
    get_chat_session_messages,
    list_chat_sessions,
    normalize_stored_answer_status,
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
        self._write_lock = threading.Lock()
        self._holds_write_lock = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._holds_write_lock:
            self._write_lock.release()
            self._holds_write_lock = False
        return False

    def execute(self, sql, params=None):
        if self.fail:
            raise OSError("database unavailable")
        self.executed.append((sql, params))
        if "case_chunks" in sql:
            rows = self.row_pages.pop(0) if self.row_pages else []
            return _FakeResult(rows)
        if "DELETE FROM" in sql and "chat_messages" in sql and "to_delete" in sql:
            session_id, user_id = params
            existing = self.sessions.get(session_id)
            if existing is None or existing[1] != user_id:
                return _FakeResult(rows=[])
            session_messages = [
                message for message in self.messages if message[1] == session_id
            ]
            latest_user_index = None
            for index in range(len(session_messages) - 1, -1, -1):
                if session_messages[index][2] == "user":
                    latest_user_index = index
                    break
            to_remove = []
            if latest_user_index is not None:
                to_remove.append(session_messages[latest_user_index])
                for message in session_messages[latest_user_index + 1 :]:
                    if message[2] == "assistant":
                        to_remove.append(message)
                        break
            removed_ids = {message[0] for message in to_remove}
            self.messages = [
                message for message in self.messages if message[0] not in removed_ids
            ]
            return _FakeResult(rows=[(message_id,) for message_id in removed_ids])
        if "DELETE FROM" in sql and "chat_sessions" in sql:
            if "oldest" in sql:
                user_id, limit = params
                removable = [
                    session_id
                    for session_id, session in self.sessions.items()
                    if session[1] == user_id
                ][: int(limit)]
                removed_rows = []
                for session_id in removable:
                    del self.sessions[session_id]
                    self.messages = [
                        message
                        for message in self.messages
                        if message[1] != session_id
                    ]
                    removed_rows.append((session_id,))
                return _FakeResult(rows=removed_rows)
            if "user_id IS NOT DISTINCT FROM" in sql:
                session_id, user_id = params
                existing = self.sessions.get(session_id)
                if existing is None:
                    return _FakeResult(row=None)
                stored_user = existing[1]
                if stored_user != user_id:
                    return _FakeResult(row=None)
                del self.sessions[session_id]
                self.messages = [
                    message for message in self.messages if message[1] != session_id
                ]
                return _FakeResult(row=(session_id,))
            return _FakeResult(rows=[("session-1",)])
        if "cases" in sql and "case_id = %s" in sql and "chat_sessions" not in sql:
            return _FakeResult(row=(1,) if self.case_exists else None)
        if "chat_sessions" in sql and "FOR UPDATE" in sql:
            self._write_lock.acquire()
            self._holds_write_lock = True
            session = self.sessions.get(params[0])
            if session is None:
                return _FakeResult(row=None)
            return _FakeResult(row=(session[0],))
        if "chat_sessions" in sql and "ORDER BY s.updated_at DESC" in sql:
            user_id, limit = params
            now = datetime.now(timezone.utc)
            rows = []
            for session in self.sessions.values():
                if session[1] != user_id:
                    continue
                expires_at = session[4]
                if not isinstance(expires_at, datetime):
                    continue
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at <= now:
                    continue
                title = None
                for message in self.messages:
                    if message[1] == session[0] and message[2] == "user":
                        title = message[3]
                        break
                rows.append(
                    (
                        session[0],
                        session[2],
                        session[3],
                        expires_at,
                        title,
                    )
                )
            rows.sort(key=lambda row: (row[3], row[0]), reverse=True)
            return _FakeResult(rows=rows[: int(limit)])
        if "chat_messages" in sql and "ORDER BY created_at ASC" in sql:
            session_id = params[0]
            session_messages = [
                message for message in self.messages if message[1] == session_id
            ]
            created_at = datetime.now(timezone.utc)
            rows = [
                (
                    message[2],
                    message[3],
                    created_at,
                    message[5] if len(message) > 5 else None,
                )
                for message in session_messages
            ]
            return _FakeResult(rows=rows)
        if "chat_sessions" in sql and "SELECT" in sql and "session_id," in sql:
            session = self.sessions.get(params[0])
            if session is None:
                return _FakeResult(row=None)
            return _FakeResult(row=session)
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
            expires_at, session_id = params
            existing = self.sessions[session_id]
            self.sessions[session_id] = (
                session_id,
                existing[1],
                existing[2],
                existing[3],
                expires_at,
            )
            return _FakeResult()
        if "chat_sessions" in sql and "COUNT" in sql and "user_id IS NOT DISTINCT FROM" in sql:
            user_id = params[0]
            count = sum(1 for session in self.sessions.values() if session[1] == user_id)
            return _FakeResult(row=(count,))
        if "chat_messages" in sql and "COUNT" in sql:
            count = sum(1 for message in self.messages if message[1] == params[0])
            return _FakeResult(row=(count,))
        if "chat_messages" in sql and "INSERT INTO" in sql:
            self.messages.append(params)
            return _FakeResult()
        return _FakeResult()


class _FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        return [[1.0] + [0.0] * 767 for _text in texts]


def _config(*, history_enabled: bool = True) -> Config:
    return Config(
        CASE_ARCHIVE_ENABLED=True,
        CASE_QA_ENABLED=True,
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

    def test_normalize_stored_answer_status_accepts_known_values(self) -> None:
        self.assertEqual(normalize_stored_answer_status("answered"), "answered")
        self.assertEqual(normalize_stored_answer_status(" refused "), "refused")
        self.assertIsNone(normalize_stored_answer_status("ok"))
        self.assertIsNone(normalize_stored_answer_status(""))

    def test_build_delete_expired_chat_sessions_sql_targets_sessions(self) -> None:
        sql = build_delete_expired_chat_sessions_sql("notable_cases")
        self.assertIn('FROM "notable_cases".chat_sessions', sql)
        self.assertIn("RETURNING sessions.session_id", sql)

    def test_build_delete_chat_session_query_scopes_by_user(self) -> None:
        sql = build_delete_chat_session_query("notable_cases")
        self.assertIn('DELETE FROM "notable_cases".chat_sessions', sql)
        self.assertIn("user_id IS NOT DISTINCT FROM %s", sql)
        self.assertIn("RETURNING session_id", sql)

    def test_build_count_active_user_chat_sessions_query_scopes_by_user(self) -> None:
        sql = build_count_active_user_chat_sessions_query("notable_cases")
        self.assertIn('FROM "notable_cases".chat_sessions', sql)
        self.assertIn("user_id IS NOT DISTINCT FROM %s", sql)
        self.assertIn("expires_at > now()", sql)

    def test_build_delete_oldest_user_chat_sessions_query_orders_oldest_first(self) -> None:
        sql = build_delete_oldest_user_chat_sessions_query("notable_cases")
        self.assertIn("ORDER BY updated_at ASC, session_id ASC", sql)
        self.assertIn("LIMIT %s", sql)

    def test_build_lock_chat_session_row_query_locks_one_session(self) -> None:
        sql = build_lock_chat_session_row_query("notable_cases")
        self.assertIn('FROM "notable_cases".chat_sessions', sql)
        self.assertIn("WHERE session_id = %s", sql)
        self.assertIn("FOR UPDATE", sql)

    def test_resolve_session_id_trims_oldest_when_user_session_cap_reached(self) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        session_ids = [str(uuid.uuid4()) for _ in range(3)]
        connection = _HistoryFakeConnection(
            sessions={
                session_ids[0]: (
                    session_ids[0],
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                ),
                session_ids[1]: (
                    session_ids[1],
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                ),
            },
            messages=[],
        )
        config = replace(_config(), CASE_QA_MAX_SESSIONS_PER_USER=2)
        new_session_id = persist_chat_history(
            config=config,
            mode="selected_case",
            question="hello",
                selected_case_id="case-1",
            requested_session_id=None,
            user_id="analyst@example.com",
            response={"answer": "hi", "answer_status": "ok"},
            connect=lambda _dsn: connection,
        )
        self.assertTrue(new_session_id)
        self.assertEqual(len(connection.sessions), 2)
        self.assertNotIn(session_ids[0], connection.sessions)

    def test_build_delete_last_chat_turn_query_scopes_by_user(self) -> None:
        sql = build_delete_last_chat_turn_query("notable_cases")
        self.assertIn('FROM "notable_cases".chat_sessions', sql)
        self.assertIn('DELETE FROM "notable_cases".chat_messages', sql)
        self.assertIn("user_id IS NOT DISTINCT FROM %s", sql)
        self.assertIn("latest_user", sql)
        self.assertIn("m.role = 'user'", sql)
        self.assertIn("m.role = 'assistant'", sql)

    def test_delete_last_chat_turn_removes_latest_pair(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            },
            messages=[
                ("m1", session_id, "user", "one", "[]"),
                ("m2", session_id, "assistant", "two", "[]"),
                ("m3", session_id, "user", "three", "[]"),
                ("m4", session_id, "assistant", "four", "[]"),
            ],
        )
        deleted = delete_last_chat_turn(
            config=_config(),
            session_id=session_id,
            user_id="analyst@example.com",
            connect=lambda _dsn: connection,
        )
        self.assertEqual(deleted, 2)
        self.assertEqual(
            connection.messages,
            [
                ("m1", session_id, "user", "one", "[]"),
                ("m2", session_id, "assistant", "two", "[]"),
            ],
        )

    def test_delete_last_chat_turn_rejects_message_count_mismatch(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            },
            messages=[
                ("m1", session_id, "user", "one", "[]"),
                ("m2", session_id, "assistant", "two", "[]"),
                ("m3", session_id, "user", "three", "[]"),
                ("m4", session_id, "assistant", "four", "[]"),
            ],
        )
        with self.assertRaisesRegex(ValueError, "does not match the expected orphan"):
            delete_last_chat_turn(
                config=_config(),
                session_id=session_id,
                user_id="analyst@example.com",
                expected_message_count=2,
                connect=lambda _dsn: connection,
            )
        self.assertEqual(len(connection.messages), 4)

    def test_delete_last_chat_turn_honors_expected_message_count(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            },
            messages=[
                ("m1", session_id, "user", "one", "[]"),
                ("m2", session_id, "assistant", "two", "[]"),
                ("m3", session_id, "user", "three", "[]"),
                ("m4", session_id, "assistant", "four", "[]"),
            ],
        )
        deleted = delete_last_chat_turn(
            config=_config(),
            session_id=session_id,
            user_id="analyst@example.com",
            expected_message_count=4,
            connect=lambda _dsn: connection,
        )
        self.assertEqual(deleted, 2)
        self.assertEqual(len(connection.messages), 2)

    def test_delete_chat_session_removes_session_and_messages(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
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

    def test_delete_chat_session_requires_authenticated_user(self) -> None:
        with self.assertRaisesRegex(ValueError, "authenticated user"):
            delete_chat_session(
                config=_config(),
                session_id=str(uuid.uuid4()),
                user_id=None,
                connect=lambda _dsn: _HistoryFakeConnection(),
            )

    def test_build_list_chat_sessions_query_filters_by_user(self) -> None:
        sql = build_list_chat_sessions_query("notable_cases")
        self.assertIn("s.user_id IS NOT DISTINCT FROM %s", sql)
        self.assertIn("ORDER BY s.updated_at DESC", sql)

    def test_build_list_chat_messages_query_orders_messages(self) -> None:
        sql = build_list_chat_messages_query("notable_cases")
        self.assertIn('FROM "notable_cases".chat_messages', sql)
        self.assertIn("answer_status", sql)
        self.assertIn("ORDER BY created_at ASC", sql)

    def test_delete_last_chat_turn_rejects_short_expected_message_count(self) -> None:
        session_id = str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError, "expected_message_count must be at least 2"):
            delete_last_chat_turn(
                config=_config(),
                session_id=session_id,
                user_id="analyst@example.com",
                expected_message_count=1,
                connect=lambda _dsn: _HistoryFakeConnection(),
            )

    def test_delete_last_chat_turn_returns_zero_for_wrong_user(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "owner@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            },
            messages=[
                ("m1", session_id, "user", "one", "[]"),
                ("m2", session_id, "assistant", "two", "[]"),
            ],
        )
        deleted = delete_last_chat_turn(
            config=_config(),
            session_id=session_id,
            user_id="other@example.com",
            connect=lambda _dsn: connection,
        )
        self.assertEqual(deleted, 0)
        self.assertEqual(len(connection.messages), 2)

    def test_list_chat_sessions_returns_user_sessions(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            },
            messages=[("m1", session_id, "user", "First question", "[]")],
        )
        items = list_chat_sessions(
            config=_config(),
            user_id="analyst@example.com",
            connect=lambda _dsn: connection,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["session_id"], session_id)
        self.assertEqual(items[0]["title"], "First question")

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
            mode="selected_case",
            question="What happened?",
                selected_case_id="case-1",
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
        self.assertEqual(connection.messages[1][5], "answered")

    def test_persist_chat_history_requires_authenticated_user(self) -> None:
        with self.assertRaisesRegex(ValueError, "authenticated user"):
            persist_chat_history(
                config=_config(),
                mode="selected_case",
                question="What happened?",
                selected_case_id="case-1",
                requested_session_id=None,
                user_id=None,
                response={"answer": "x", "answer_status": "answered"},
                connect=lambda _dsn: _HistoryFakeConnection(),
            )

    def test_persist_chat_history_resumes_existing_session_without_rewriting_scope(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
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

    def test_persist_chat_history_rejects_session_scope_mismatch(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "scope does not match"):
            persist_chat_history(
                config=_config(),
                mode="selected_case",
                question="Follow-up?",
                selected_case_id="case-2",
                requested_session_id=session_id,
                user_id="analyst@example.com",
                response={"answer": "x", "answer_status": "answered"},
                connect=lambda _dsn: connection,
            )

    def test_persist_chat_history_rejects_unknown_session(self) -> None:
        with self.assertRaises(ChatSessionNotFoundError):
            persist_chat_history(
                config=_config(),
                mode="selected_case",
                question="What happened?",
                selected_case_id="case-1",
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
                    "selected_case",
                    "case-1",
                    expired_at,
                )
            }
        )
        with self.assertRaises(ChatSessionExpiredError):
            persist_chat_history(
                config=_config(),
                mode="selected_case",
                question="What happened?",
                selected_case_id="case-1",
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
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "does not belong"):
            persist_chat_history(
                config=_config(),
                mode="selected_case",
                question="What happened?",
                selected_case_id="case-1",
                requested_session_id=session_id,
                user_id="analyst-b@example.com",
                response={"answer": "x", "answer_status": "answered"},
                connect=lambda _dsn: connection,
            )

    def test_get_chat_session_messages_rejects_null_user_session(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    None,
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "does not belong"):
            get_chat_session_messages(
                config=_config(),
                session_id=session_id,
                user_id="analyst@example.com",
                connect=lambda _dsn: connection,
            )

    def test_get_chat_session_messages_returns_answer_status(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            },
            messages=[
                ("m1", session_id, "user", "What happened?", "[]", None),
                ("m2", session_id, "assistant", "Grounded answer.", "[]", "answered"),
            ],
        )
        payload = get_chat_session_messages(
            config=_config(),
            session_id=session_id,
            user_id="analyst@example.com",
            connect=lambda _dsn: connection,
        )
        self.assertEqual(len(payload["messages"]), 2)
        self.assertNotIn("answer_status", payload["messages"][0])
        self.assertEqual(payload["messages"][1]["answer_status"], "answered")

    def test_persist_chat_history_enforces_message_limit(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
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
                mode="selected_case",
                question="What happened?",
                selected_case_id="case-1",
                requested_session_id=session_id,
                user_id="analyst@example.com",
                response={"answer": "x", "answer_status": "answered"},
                connect=lambda _dsn: connection,
            )
        self.assertEqual(len(connection.messages), 3)

    def test_persist_chat_history_serializes_capacity_check_under_contention(self) -> None:
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        connection = _HistoryFakeConnection(
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "selected_case",
                    "case-1",
                    expires_at,
                )
            },
            messages=[
                ("m1", session_id, "user", "one", "[]"),
                ("m2", session_id, "assistant", "two", "[]"),
            ],
        )
        barrier = threading.Barrier(2)
        results: list[str] = []
        errors: list[BaseException] = []

        def worker(question: str) -> None:
            try:
                barrier.wait(timeout=5)
                persist_chat_history(
                    config=_config(),
                    mode="selected_case",
                    question=question,
                selected_case_id="case-1",
                    requested_session_id=session_id,
                    user_id="analyst@example.com",
                    response={"answer": "ok", "answer_status": "answered"},
                    connect=lambda _dsn: connection,
                )
                results.append("ok")
            except ValueError as exc:
                errors.append(exc)
                results.append("limit")
            except BaseException as exc:  # pragma: no cover - test guard
                errors.append(exc)
                results.append("error")

        threads = [
            threading.Thread(target=worker, args=("first?",)),
            threading.Thread(target=worker, args=("second?",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())

        self.assertEqual(sorted(results), ["limit", "ok"])
        self.assertEqual(len(connection.messages), 4)
        self.assertTrue(any("FOR UPDATE" in sql for sql, _ in connection.executed))

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
            embedding_model=_FakeEmbeddingModel(),
            user_id="analyst@example.com",
            synthesize=lambda _question, _sources: "Grounded answer.",
        )

        self.assertEqual(response["answer_status"], "answered")
        self.assertIsNotNone(response["session_id"])
        self.assertEqual(len(connection.messages), 2)


if __name__ == "__main__":
    unittest.main()
