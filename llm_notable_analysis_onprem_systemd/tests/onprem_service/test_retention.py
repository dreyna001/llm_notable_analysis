import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.case_chat_history import (
    build_delete_expired_chat_sessions_sql,
    delete_expired_chat_sessions,
)
from llm_notable_analysis_onprem_systemd.onprem_service.retention import (
    build_delete_expired_cases_sql,
    delete_expired_cases,
    run_retention,
)


class _FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, *, rows=None, row_pages=None, fail=False):
        self.executed = []
        self.rows = rows or []
        self.row_pages = list(row_pages or [])
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        if self.fail:
            raise OSError("database unavailable")
        self.executed.append((sql, params))
        if "DELETE FROM" in sql:
            if self.row_pages:
                return _FakeResult(self.row_pages.pop(0))
            return _FakeResult(self.rows)
        return _FakeResult()


class TestRetention(unittest.TestCase):
    def test_build_delete_expired_cases_sql_targets_cases_for_cascade(self) -> None:
        sql = build_delete_expired_cases_sql("notable_cases")

        self.assertIn('FROM "notable_cases".cases', sql)
        self.assertIn("ORDER BY expires_at ASC, case_id ASC", sql)
        self.assertIn("LIMIT %s", sql)
        self.assertIn("DELETE FROM", sql)
        self.assertIn("RETURNING cases.case_id", sql)

    def test_delete_expired_cases_is_disabled_without_case_archive(self) -> None:
        connection = _FakeConnection(rows=[("case-1",)])

        stats = delete_expired_cases(
            config=Config(CASE_ARCHIVE_ENABLED=False),
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            connect=lambda _dsn: connection,
        )

        self.assertEqual(stats.deleted, 0)
        self.assertEqual(stats.errors, 0)
        self.assertEqual(connection.executed, [])

    def test_delete_expired_cases_counts_deleted_rows(self) -> None:
        connection = _FakeConnection(rows=[("case-1",), ("case-2",)])
        now = datetime(2026, 6, 4, tzinfo=timezone.utc)

        stats = delete_expired_cases(
            config=Config(
                CASE_ARCHIVE_ENABLED=True,
                CASE_POSTGRES_STATEMENT_TIMEOUT_MS=2500,
            ),
            now=now,
            connect=lambda _dsn: connection,
        )

        self.assertEqual(stats.deleted, 2)
        self.assertEqual(stats.errors, 0)
        self.assertEqual(
            connection.executed[0],
            ("SELECT set_config('statement_timeout', %s, true)", ("2500ms",)),
        )
        self.assertEqual(connection.executed[1][1], (now, 500))

    def test_delete_expired_cases_deletes_in_batches(self) -> None:
        connection = _FakeConnection(
            row_pages=[
                [("case-1",), ("case-2",)],
                [("case-3",)],
            ]
        )
        now = datetime(2026, 6, 4, tzinfo=timezone.utc)

        stats = delete_expired_cases(
            config=Config(
                CASE_ARCHIVE_ENABLED=True,
                CASE_RETENTION_DELETE_BATCH_SIZE=2,
            ),
            now=now,
            connect=lambda _dsn: connection,
        )

        self.assertEqual(stats.deleted, 3)
        self.assertEqual(stats.errors, 0)
        self.assertEqual(connection.executed[1][1], (now, 2))
        self.assertEqual(connection.executed[2][1], (now, 2))

    def test_build_delete_expired_chat_sessions_sql_targets_sessions(self) -> None:
        sql = build_delete_expired_chat_sessions_sql("notable_cases")

        self.assertIn('FROM "notable_cases".chat_sessions', sql)
        self.assertIn("RETURNING sessions.session_id", sql)

    def test_delete_expired_chat_sessions_skips_when_disabled(self) -> None:
        connection = _FakeConnection(rows=[("session-1",)])

        deleted = delete_expired_chat_sessions(
            config=Config(CASE_QA_CHAT_HISTORY_ENABLED=False),
            connect=lambda _dsn: connection,
        )

        self.assertEqual(deleted, 0)
        self.assertEqual(connection.executed, [])

    def test_delete_expired_cases_reports_database_error(self) -> None:
        connection = _FakeConnection(fail=True)

        stats = delete_expired_cases(
            config=Config(CASE_ARCHIVE_ENABLED=True),
            now=datetime(2026, 6, 4, tzinfo=timezone.utc),
            connect=lambda _dsn: connection,
        )

        self.assertEqual(stats.deleted, 0)
        self.assertEqual(stats.errors, 1)

    def test_run_retention_prunes_old_idempotency_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            idempotency_dir = root / "idempotency"
            idempotency_dir.mkdir()
            old_marker = idempotency_dir / "old.json"
            new_marker = idempotency_dir / "new.json"
            old_marker.write_text("{}", encoding="utf-8")
            new_marker.write_text("{}", encoding="utf-8")
            now = time.time()
            os.utime(old_marker, (now - 3 * 86400, now - 3 * 86400))
            os.utime(new_marker, (now, now))

            config = Config(
                PROCESSED_DIR=root / "processed",
                QUARANTINE_DIR=root / "quarantine",
                REPORT_DIR=root / "reports",
                ARCHIVE_DIR=root / "archive",
                SIDE_EFFECT_IDEMPOTENCY_DIR=idempotency_dir,
                SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS=2,
            )
            stats = run_retention(config)

            self.assertEqual(stats.deleted, 1)
            self.assertFalse(old_marker.exists())
            self.assertTrue(new_marker.exists())

    def test_run_retention_includes_expired_case_deletes_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connection = _FakeConnection(rows=[("case-1",)])

            config = Config(
                CASE_ARCHIVE_ENABLED=True,
                PROCESSED_DIR=root / "processed",
                QUARANTINE_DIR=root / "quarantine",
                REPORT_DIR=root / "reports",
                ARCHIVE_DIR=root / "archive",
                SIDE_EFFECT_IDEMPOTENCY_DIR=root / "idempotency",
            )
            stats = run_retention(config, connect=lambda _dsn: connection)

            self.assertEqual(stats.deleted, 1)
            self.assertIn("DELETE FROM", connection.executed[1][0])


if __name__ == "__main__":
    unittest.main()
