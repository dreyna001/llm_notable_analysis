"""In-memory fake Postgres for analyst portal UI preview."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from llm_notable_analysis_onprem_systemd.onprem_service.case_search import (
    CaseChunkRecord,
    build_case_chunks,
)
from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    CaseArchiveRecord,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config

# Matches production CASE_QA_VECTOR_DIMENSIONS / RAG_VECTOR_DIMENSIONS v1 contract.
PREVIEW_FAKE_VECTOR_DIMENSIONS = 768


class PreviewFakeResult:
    """Minimal psycopg-like result wrapper for preview fakes."""

    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class PreviewFakeConnection:
    """Fake Postgres connection for preview case archive and chat history."""

    def __init__(
        self,
        *,
        summary_rows: list[tuple[Any, ...]],
        details_by_case_id: dict[str, tuple[Any, ...]],
        chunk_rows: list[tuple[Any, ...]],
        ready: bool = True,
        fail: bool = False,
        sessions: dict[str, tuple[Any, ...]] | None = None,
        messages: list[tuple[Any, ...]] | None = None,
    ):
        self.summary_rows = summary_rows
        self.details_by_case_id = details_by_case_id
        self.chunk_rows = chunk_rows
        self.ready = ready
        self.fail = fail
        self.sessions = {} if sessions is None else sessions
        self.messages = [] if messages is None else messages
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
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
        if not self.ready and "set_config" not in sql:
            raise OSError("database unavailable")
        self.executed.append((sql, params))

        if "set_config" in sql:
            return PreviewFakeResult()
        if "to_regclass" in sql:
            return PreviewFakeResult(row=(self.ready, self.ready))
        if "case_chunks" in sql:
            rows = list(self.chunk_rows)
            case_id = self._chunk_case_filter(sql, params)
            if case_id is not None and "ch.case_id = %s" in sql:
                rows = [row for row in rows if row[1] == case_id]
            if case_id is not None and "ch.case_id <> %s" in sql:
                rows = [row for row in rows if row[1] != case_id]
            limit = int(params[-1]) if params else 1
            return PreviewFakeResult(rows=rows[:limit], row=rows[0] if rows else None)
        if "DELETE FROM" in sql and "chat_messages" in sql and "to_delete" in sql:
            session_id, user_id = params
            existing = self.sessions.get(session_id)
            if existing is None or existing[1] != user_id:
                return PreviewFakeResult(rows=[])
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
            return PreviewFakeResult(rows=[(message_id,) for message_id in removed_ids])
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
                return PreviewFakeResult(rows=removed_rows)
            if "user_id IS NOT DISTINCT FROM" in sql:
                session_id, user_id = params
                existing = self.sessions.get(session_id)
                if existing is None:
                    return PreviewFakeResult(row=None)
                stored_user = existing[1]
                if stored_user != user_id:
                    return PreviewFakeResult(row=None)
                del self.sessions[session_id]
                self.messages = [
                    message for message in self.messages if message[1] != session_id
                ]
                return PreviewFakeResult(row=(session_id,))
            return PreviewFakeResult(rows=[("session-1",)])
        if "cases" in sql and "case_id = %s" in sql and "chat_sessions" not in sql:
            case_id = str((params or ("",))[0])
            detail_row = self.details_by_case_id.get(case_id)
            if "SELECT 1" in sql.replace("\n", " "):
                return PreviewFakeResult(row=(1,) if detail_row is not None else None)
            return PreviewFakeResult(row=detail_row)
        if "chat_sessions" in sql and "FOR UPDATE" in sql:
            self._write_lock.acquire()
            self._holds_write_lock = True
            session = self.sessions.get(params[0])
            if session is None:
                return PreviewFakeResult(row=None)
            return PreviewFakeResult(row=(session[0],))
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
            return PreviewFakeResult(rows=rows[: int(limit)])
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
            return PreviewFakeResult(rows=rows)
        if "chat_sessions" in sql and "SELECT" in sql and "session_id," in sql:
            session = self.sessions.get(params[0])
            if session is None:
                return PreviewFakeResult(row=None)
            return PreviewFakeResult(row=session)
        if "chat_sessions" in sql and "INSERT INTO" in sql:
            session_id, user_id, mode, selected_case_id, expires_at = params
            self.sessions[session_id] = (
                session_id,
                user_id,
                mode,
                selected_case_id,
                expires_at,
            )
            return PreviewFakeResult()
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
            return PreviewFakeResult()
        if (
            "chat_sessions" in sql
            and "COUNT" in sql
            and "user_id IS NOT DISTINCT FROM" in sql
        ):
            user_id = params[0]
            count = sum(1 for session in self.sessions.values() if session[1] == user_id)
            return PreviewFakeResult(row=(count,))
        if "chat_messages" in sql and "COUNT" in sql:
            count = sum(1 for message in self.messages if message[1] == params[0])
            return PreviewFakeResult(row=(count,))
        if "chat_messages" in sql and "INSERT INTO" in sql:
            self.messages.append(params)
            return PreviewFakeResult()
        if (
            "ORDER BY processed_at DESC, case_id ASC" in sql
            and "LIMIT %s" in sql
            and "OFFSET %s" not in sql
            and params
        ):
            limit = int(params[-1])
            rows = list(self.summary_rows)
            filter_params = list(params[:-1])
            param_index = 0
            if "processed_at >= %s" in sql:
                processed_from = filter_params[param_index]
                param_index += 1
                rows = [row for row in rows if row[3] >= processed_from]
            if "processed_at <= %s" in sql:
                processed_to = filter_params[param_index]
                param_index += 1
                rows = [row for row in rows if row[3] <= processed_to]
            if "verdict = %s" in sql:
                verdict = filter_params[param_index]
                param_index += 1
                rows = [row for row in rows if row[5] == verdict]
            if "search_name ILIKE %s" in sql:
                pattern = filter_params[param_index]
                param_index += 1
                needle = str(pattern)[1:-1]
                needle = (
                    needle.replace("\\%", "%")
                    .replace("\\_", "_")
                    .replace("\\\\", "\\")
                )
                rows = [
                    row
                    for row in rows
                    if row[7] and needle.lower() in str(row[7]).lower()
                ]
            if "processed_at < %s OR (processed_at = %s AND case_id > %s)" in sql:
                cursor_processed_at = filter_params[param_index]
                cursor_case_id = filter_params[param_index + 2]
                rows = [
                    row
                    for row in rows
                    if row[3] < cursor_processed_at
                    or (
                        row[3] == cursor_processed_at
                        and str(row[0]) > str(cursor_case_id)
                    )
                ]
            rows.sort(key=lambda row: str(row[0]))
            rows.sort(key=lambda row: row[3], reverse=True)
            return PreviewFakeResult(rows=rows[:limit])
        return PreviewFakeResult(rows=self.summary_rows)

    def _chunk_case_filter(
        self,
        sql: str,
        params: tuple[Any, ...] | list[Any] | None,
    ) -> str | None:
        """Resolve a case_id filter from lexical/vector or direct chunk SQL."""
        if not params:
            return None
        if "ch.case_id = %s" not in sql and "ch.case_id <> %s" not in sql:
            return None
        candidate_params = list(params[:-1]) if "LIMIT %s" in sql else list(params)
        for param in candidate_params:
            normalized = str(param).strip()
            if normalized in self.details_by_case_id:
                return normalized
        if len(params) > 1:
            return str(params[1])
        return str(params[0])


class PreviewFakeEmbeddingModel:
    """Deterministic embedding stub for preview chat retrieval."""

    def encode(self, values, **_kwargs):
        vector = [1.0] + [0.0] * (PREVIEW_FAKE_VECTOR_DIMENSIONS - 1)
        return [vector for _value in values]


def summary_row(record: CaseArchiveRecord) -> tuple[Any, ...]:
    """Build one case list row from an archive record."""
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


def detail_row(record: CaseArchiveRecord) -> tuple[Any, ...]:
    """Build one case detail row from an archive record."""
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


def chunk_retrieval_row(
    chunk: CaseChunkRecord,
    *,
    score: float = 1.0,
) -> tuple[Any, ...]:
    """Build one fake retrieval row for lexical/vector chunk queries."""
    return (
        chunk.chunk_id,
        chunk.case_id,
        chunk.source_lane,
        chunk.section,
        chunk.field_path,
        chunk.text,
        json.dumps(chunk.metadata, ensure_ascii=True, sort_keys=True),
        score,
    )


def build_chunk_rows(
    records: Sequence[CaseArchiveRecord],
    config: Config,
) -> list[tuple[Any, ...]]:
    """Build fake chunk retrieval rows using production chunk construction."""
    rows: list[tuple[Any, ...]] = []
    for record in records:
        for chunk in build_case_chunks(record, config):
            rows.append(chunk_retrieval_row(chunk))
    return rows


class PreviewCaseStore:
    """Mutable in-memory case archive used by the preview API and file drop."""

    def __init__(self, records: Sequence[CaseArchiveRecord], config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()
        self.summary_rows = [summary_row(record) for record in records]
        self.details_by_case_id = {
            record.case_id: detail_row(record) for record in records
        }
        self.chunk_rows = build_chunk_rows(records, config)
        self.sessions: dict[str, tuple[Any, ...]] = {}
        self.messages: list[tuple[Any, ...]] = []

    def upsert(self, record: CaseArchiveRecord) -> None:
        """Insert or replace one case and its retrieval chunks atomically."""
        new_summary = summary_row(record)
        new_detail = detail_row(record)
        new_chunks = build_chunk_rows([record], self._config)
        with self._lock:
            self.summary_rows[:] = [
                row for row in self.summary_rows if row[0] != record.case_id
            ]
            self.summary_rows.append(new_summary)
            self.details_by_case_id[record.case_id] = new_detail
            self.chunk_rows[:] = [
                row for row in self.chunk_rows if row[1] != record.case_id
            ]
            self.chunk_rows.extend(new_chunks)

    def connect(self, _dsn: str) -> PreviewFakeConnection:
        """Return a fake connection backed by the shared mutable store."""
        del _dsn
        return PreviewFakeConnection(
            summary_rows=self.summary_rows,
            details_by_case_id=self.details_by_case_id,
            chunk_rows=self.chunk_rows,
            sessions=self.sessions,
            messages=self.messages,
        )


def build_preview_connect_factory(
    records: Sequence[CaseArchiveRecord],
    config: Config,
) -> Callable[[str], PreviewFakeConnection]:
    """Return a connect factory wired with preview archive and chunk rows.

    Session and message state is shared across every ``connect()`` call so chat
    history persists between portal HTTP requests (each opens its own connection).
    """
    return PreviewCaseStore(records, config).connect
