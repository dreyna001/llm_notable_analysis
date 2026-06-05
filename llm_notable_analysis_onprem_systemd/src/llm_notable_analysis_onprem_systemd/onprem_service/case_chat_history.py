"""Bounded Postgres persistence for portal chat transcripts."""

# Optional database dependency is imported lazily for portal chat history.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .case_store import quote_identifier
from .config import Config

logger = logging.getLogger(__name__)

ConnectionFactory = Callable[[str], Any]

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


@dataclass(frozen=True)
class ChatSessionRecord:
    """One persisted portal chat session."""

    session_id: str
    user_id: str | None
    mode: str
    selected_case_id: str | None
    expires_at: datetime


def _default_connect(dsn: str) -> Any:
    """Open a psycopg connection for chat history writes."""
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is unavailable in the runtime.") from exc
    return psycopg.connect(dsn, connect_timeout=5)


def _set_statement_timeout(conn: Any, timeout_ms: int) -> None:
    """Set a transaction-local Postgres statement timeout."""
    if int(timeout_ms) > 0:
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{int(timeout_ms)}ms",),
        )


def _fetchone(result: Any) -> Any:
    """Read one row from a cursor-like result."""
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    return None


def _fetchall(result: Any) -> list[Any]:
    """Read all rows from a cursor-like result."""
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        return list(fetchall())
    return []


def _row_get(row: Any, index: int, key: str) -> Any:
    """Read one value from a row object or sequence."""
    if row is None:
        return None
    try:
        mapping = row._mapping  # type: ignore[attr-defined]
        if key in mapping:
            return mapping[key]
    except Exception:
        pass
    try:
        return row[index]
    except Exception:
        return getattr(row, key, None)


def _normalize_user_id(user_id: str | None) -> str | None:
    text = str(user_id or "").strip()
    return text or None


def _validate_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not _SESSION_ID_RE.fullmatch(normalized):
        raise ValueError("session_id is invalid.")
    return normalized


def truncate_stored_message(text: str, max_bytes: int) -> str:
    """Truncate stored transcript text to a UTF-8 byte budget."""
    raw = str(text or "")
    limit = max(1, int(max_bytes))
    encoded = raw.encode("utf-8")
    if len(encoded) <= limit:
        return raw
    clipped = encoded[:limit]
    while clipped:
        try:
            return clipped.decode("utf-8")
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return ""


def build_get_chat_session_query(schema: str) -> str:
    """Build SQL to fetch one chat session by id."""
    table = f"{quote_identifier(schema, 'schema')}.chat_sessions"
    return f"""
SELECT
    session_id,
    user_id,
    mode,
    selected_case_id,
    expires_at
FROM {table}
WHERE session_id = %s
""".strip()


def build_count_chat_messages_query(schema: str) -> str:
    """Build SQL to count persisted messages in one session."""
    table = f"{quote_identifier(schema, 'schema')}.chat_messages"
    return f"""
SELECT COUNT(*)::bigint
FROM {table}
WHERE session_id = %s
""".strip()


def build_insert_chat_session_query(schema: str) -> str:
    """Build SQL to insert one chat session."""
    table = f"{quote_identifier(schema, 'schema')}.chat_sessions"
    return f"""
INSERT INTO {table} (
    session_id,
    user_id,
    mode,
    selected_case_id,
    expires_at
) VALUES (%s, %s, %s, %s, %s)
""".strip()


def build_touch_chat_session_query(schema: str) -> str:
    """Build SQL to refresh one chat session metadata and expiry."""
    table = f"{quote_identifier(schema, 'schema')}.chat_sessions"
    return f"""
UPDATE {table}
SET
    user_id = %s,
    mode = %s,
    selected_case_id = %s,
    expires_at = %s,
    updated_at = now()
WHERE session_id = %s
""".strip()


def build_insert_chat_message_query(schema: str) -> str:
    """Build SQL to insert one chat transcript message."""
    table = f"{quote_identifier(schema, 'schema')}.chat_messages"
    return f"""
INSERT INTO {table} (
    message_id,
    session_id,
    role,
    content,
    cited_sources
) VALUES (%s, %s, %s, %s, %s::jsonb)
""".strip()


def build_list_chat_sessions_query(schema: str) -> str:
    """Build SQL to list non-expired chat sessions for one user."""
    sessions = f"{quote_identifier(schema, 'schema')}.chat_sessions"
    messages = f"{quote_identifier(schema, 'schema')}.chat_messages"
    return f"""
SELECT
    s.session_id,
    s.mode,
    s.selected_case_id,
    s.updated_at,
    (
        SELECT m.content
        FROM {messages} AS m
        WHERE m.session_id = s.session_id
          AND m.role = 'user'
        ORDER BY m.created_at ASC
        LIMIT 1
    ) AS title
FROM {sessions} AS s
WHERE s.expires_at > now()
  AND s.user_id IS NOT DISTINCT FROM %s
ORDER BY s.updated_at DESC, s.session_id DESC
LIMIT %s
""".strip()


def build_list_chat_messages_query(schema: str) -> str:
    """Build SQL to list ordered messages for one chat session."""
    table = f"{quote_identifier(schema, 'schema')}.chat_messages"
    return f"""
SELECT
    role,
    content,
    created_at
FROM {table}
WHERE session_id = %s
ORDER BY created_at ASC, message_id ASC
""".strip()


def _session_title(title: Any, *, max_chars: int = 48) -> str:
    text = str(title or "").strip()
    if not text:
        return "New chat"
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def list_chat_sessions(
    *,
    config: Config,
    user_id: str | None,
    connect: ConnectionFactory | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return bounded chat session summaries for the authenticated user."""
    if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
        return []

    connect_fn = connect or _default_connect
    normalized_user = _normalize_user_id(user_id)
    page_size = max(1, min(int(limit), 100))
    sql = build_list_chat_sessions_query(config.CASE_POSTGRES_SCHEMA)
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        rows = _fetchall(conn.execute(sql, (normalized_user, page_size)))

    items: list[dict[str, Any]] = []
    for row in rows:
        updated_at = _row_get(row, 3, "updated_at")
        if isinstance(updated_at, datetime) and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        items.append(
            {
                "session_id": str(_row_get(row, 0, "session_id")),
                "mode": str(_row_get(row, 1, "mode")),
                "selected_case_id": _row_get(row, 2, "selected_case_id"),
                "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else None,
                "title": _session_title(_row_get(row, 4, "title")),
            }
        )
    return items


def get_chat_session_messages(
    *,
    config: Config,
    session_id: str,
    user_id: str | None,
    connect: ConnectionFactory | None = None,
) -> dict[str, Any]:
    """Return one chat session transcript for the authenticated user."""
    if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
        raise RuntimeError("Chat history persistence is disabled.")

    normalized_id = _validate_session_id(session_id)
    record = _load_chat_session(
        config=config,
        session_id=normalized_id,
        connect=connect or _default_connect,
    )
    if record is None:
        raise ValueError("session_id was not found.")
    now = datetime.now(timezone.utc)
    if record.expires_at <= now:
        raise ValueError("session_id has expired.")

    normalized_user = _normalize_user_id(user_id)
    stored_user = _normalize_user_id(record.user_id)
    if stored_user and normalized_user and stored_user != normalized_user:
        raise ValueError("session_id does not belong to the authenticated user.")

    sql = build_list_chat_messages_query(config.CASE_POSTGRES_SCHEMA)
    connect_fn = connect or _default_connect
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        rows = _fetchall(conn.execute(sql, (normalized_id,)))

    messages: list[dict[str, Any]] = []
    for row in rows:
        created_at = _row_get(row, 2, "created_at")
        if isinstance(created_at, datetime) and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        messages.append(
            {
                "role": str(_row_get(row, 0, "role")),
                "content": str(_row_get(row, 1, "content")),
                "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
            }
        )

    return {
        "session_id": record.session_id,
        "mode": record.mode,
        "selected_case_id": record.selected_case_id,
        "messages": messages,
    }


def delete_chat_session(
    *,
    config: Config,
    session_id: str,
    user_id: str | None,
    connect: ConnectionFactory | None = None,
) -> bool:
    """Delete one chat session and cascade messages for the authenticated user."""
    if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
        raise RuntimeError("Chat history persistence is disabled.")

    normalized_id = _validate_session_id(session_id)
    normalized_user = _normalize_user_id(user_id)
    connect_fn = connect or _default_connect
    sql = build_delete_chat_session_query(config.CASE_POSTGRES_SCHEMA)
    with connect_fn(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        row = _fetchone(conn.execute(sql, (normalized_id, normalized_user)))
    if row is None:
        return False
    return True


def build_delete_expired_chat_sessions_sql(schema: str) -> str:
    """Build SQL that deletes expired chat sessions and cascades messages."""
    table = f"{quote_identifier(schema, 'schema')}.chat_sessions"
    return f"""
WITH expired AS (
    SELECT session_id
    FROM {table}
    WHERE expires_at < %s
    ORDER BY expires_at ASC, session_id ASC
    LIMIT %s
)
DELETE FROM {table} AS sessions
USING expired
WHERE sessions.session_id = expired.session_id
RETURNING sessions.session_id
""".strip()


def build_delete_chat_session_query(schema: str) -> str:
    """Build SQL that deletes one chat session for the authenticated user."""
    table = f"{quote_identifier(schema, 'schema')}.chat_sessions"
    return f"""
DELETE FROM {table}
WHERE session_id = %s
  AND user_id IS NOT DISTINCT FROM %s
RETURNING session_id
""".strip()


def _session_expires_at(config: Config, *, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    days = max(1, int(config.CASE_QA_CHAT_HISTORY_RETENTION_DAYS))
    return current + timedelta(days=days)


def _load_chat_session(
    *,
    config: Config,
    session_id: str,
    connect: ConnectionFactory,
) -> ChatSessionRecord | None:
    sql = build_get_chat_session_query(config.CASE_POSTGRES_SCHEMA)
    with connect(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        row = _fetchone(conn.execute(sql, (session_id,)))
    if row is None:
        return None
    expires_at = _row_get(row, 4, "expires_at")
    if not isinstance(expires_at, datetime):
        raise RuntimeError("Chat session expiry is unavailable.")
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return ChatSessionRecord(
        session_id=str(_row_get(row, 0, "session_id")),
        user_id=_row_get(row, 1, "user_id"),
        mode=str(_row_get(row, 2, "mode")),
        selected_case_id=_row_get(row, 3, "selected_case_id"),
        expires_at=expires_at,
    )


def _count_chat_messages(
    *,
    config: Config,
    session_id: str,
    connect: ConnectionFactory,
) -> int:
    sql = build_count_chat_messages_query(config.CASE_POSTGRES_SCHEMA)
    with connect(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        row = _fetchone(conn.execute(sql, (session_id,)))
    if row is None:
        return 0
    count = _row_get(row, 0, "count")
    return int(count or 0)


def _ensure_session_capacity(
    *,
    config: Config,
    session_id: str,
    connect: ConnectionFactory,
) -> None:
    max_messages = max(1, int(config.CASE_QA_MAX_MESSAGES_PER_SESSION))
    current = _count_chat_messages(
        config=config,
        session_id=session_id,
        connect=connect,
    )
    if current + 2 > max_messages:
        raise ValueError(
            f"Chat session exceeded the configured message limit of {max_messages}."
        )


def _resolve_session_id(
    *,
    config: Config,
    mode: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str | None,
    connect: ConnectionFactory,
) -> str:
    normalized_user = _normalize_user_id(user_id)
    expires_at = _session_expires_at(config)

    if requested_session_id:
        session_id = _validate_session_id(requested_session_id)
        record = _load_chat_session(
            config=config,
            session_id=session_id,
            connect=connect,
        )
        if record is None:
            raise ValueError("session_id was not found.")
        now = datetime.now(timezone.utc)
        if record.expires_at <= now:
            raise ValueError("session_id has expired.")
        stored_user = _normalize_user_id(record.user_id)
        if stored_user and normalized_user and stored_user != normalized_user:
            raise ValueError("session_id does not belong to the authenticated user.")
        touch_sql = build_touch_chat_session_query(config.CASE_POSTGRES_SCHEMA)
        with connect(config.CASE_POSTGRES_DSN) as conn:
            _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
            conn.execute(
                touch_sql,
                (
                    normalized_user,
                    mode,
                    selected_case_id,
                    expires_at,
                    session_id,
                ),
            )
        return session_id

    session_id = str(uuid.uuid4())
    insert_sql = build_insert_chat_session_query(config.CASE_POSTGRES_SCHEMA)
    with connect(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        conn.execute(
            insert_sql,
            (
                session_id,
                normalized_user,
                mode,
                selected_case_id,
                expires_at,
            ),
        )
    return session_id


def persist_chat_history(
    *,
    config: Config,
    mode: str,
    question: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str | None,
    response: dict[str, Any],
    connect: ConnectionFactory | None = None,
) -> str:
    """Persist one bounded chat turn and return the active session id."""
    if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
        raise RuntimeError("Chat history persistence is disabled.")

    connect_fn = connect or _default_connect
    session_id = _resolve_session_id(
        config=config,
        mode=mode,
        selected_case_id=selected_case_id,
        requested_session_id=requested_session_id,
        user_id=user_id,
        connect=connect_fn,
    )
    _ensure_session_capacity(
        config=config,
        session_id=session_id,
        connect=connect_fn,
    )

    max_bytes = max(1, int(config.CASE_QA_MAX_STORED_MESSAGE_BYTES))
    user_content = truncate_stored_message(question, max_bytes)
    assistant_content = truncate_stored_message(
        str(response.get("answer") or ""),
        max_bytes,
    )

    insert_sql = build_insert_chat_message_query(config.CASE_POSTGRES_SCHEMA)
    with connect(config.CASE_POSTGRES_DSN) as conn:
        _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
        conn.execute(
            insert_sql,
            (
                str(uuid.uuid4()),
                session_id,
                "user",
                user_content,
                "[]",
            ),
        )
        conn.execute(
            insert_sql,
            (
                str(uuid.uuid4()),
                session_id,
                "assistant",
                assistant_content,
                "[]",
            ),
        )
    return session_id


def delete_expired_chat_sessions(
    *,
    config: Config,
    now: datetime | None = None,
    connect: ConnectionFactory | None = None,
) -> int:
    """Delete expired chat sessions, relying on cascade for messages."""
    if not bool(config.CASE_QA_CHAT_HISTORY_ENABLED):
        return 0

    cutoff = now or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)

    connect_fn = connect or _default_connect
    sql = build_delete_expired_chat_sessions_sql(config.CASE_POSTGRES_SCHEMA)
    batch_size = max(1, int(config.CASE_RETENTION_DELETE_BATCH_SIZE))
    deleted = 0
    try:
        with connect_fn(config.CASE_POSTGRES_DSN) as conn:
            _set_statement_timeout(conn, config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS)
            while True:
                rows = _fetchall(conn.execute(sql, (cutoff, batch_size)))
                deleted += len(rows)
                if len(rows) < batch_size:
                    break
        return deleted
    except Exception:
        logger.exception("Failed to delete expired chat history sessions")
        return 0
