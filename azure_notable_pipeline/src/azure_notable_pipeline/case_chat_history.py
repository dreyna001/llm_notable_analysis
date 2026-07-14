"""Bounded Cosmos persistence for portal chat transcripts."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Config
from .cosmos_store import CosmosStore

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_VALID_ANSWER_STATUSES = frozenset(
    {"answered", "unknown", "refused", "insufficient_context"}
)


class ChatSessionNotFoundError(LookupError):
    """Raised when a requested chat session id is missing."""


class ChatSessionExpiredError(LookupError):
    """Raised when a requested chat session id is past retention expiry."""


def truncate_stored_message(text: str, max_bytes: int) -> str:
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


def normalize_stored_answer_status(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in _VALID_ANSWER_STATUSES else None


def list_chat_sessions(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    user_id: str | None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        return []
    normalized_user = _require_user(user_id)
    rows = cosmos_store.list_chat_sessions(
        config.CHAT_SESSIONS_CONTAINER,
        user_id=normalized_user,
        now_epoch=_now_epoch(),
        limit=max(1, min(int(limit), 100)),
    )
    return [
        {
            "session_id": row["session_id"],
            "mode": row["mode"],
            "selected_case_id": row.get("selected_case_id") or None,
            "updated_at": row.get("updated_at"),
            "title": _session_title(row.get("title")),
        }
        for row in rows
    ]


def get_chat_session_messages(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    _require_enabled(config)
    record = _load_chat_session(
        config=config,
        cosmos_store=cosmos_store,
        session_id=_validate_session_id(session_id),
        user_id=user_id,
        validate_scope=None,
    )
    return {
        "session_id": record["session_id"],
        "mode": record["mode"],
        "selected_case_id": record.get("selected_case_id") or None,
        "messages": _list_messages(config, cosmos_store, record["session_id"]),
    }


def load_session_transcript(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
) -> list[dict[str, Any]]:
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        return []
    return _list_messages(config, cosmos_store, _validate_session_id(session_id))


def delete_chat_session(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str | None,
) -> bool:
    _require_enabled(config)
    normalized_id = _validate_session_id(session_id)
    normalized_user = _require_user(user_id)
    _load_chat_session(
        config=config,
        cosmos_store=cosmos_store,
        session_id=normalized_id,
        user_id=normalized_user,
        validate_scope=None,
    )
    _delete_messages_for_session(config, cosmos_store, normalized_id)
    return cosmos_store.delete_chat_session(
        config.CHAT_SESSIONS_CONTAINER,
        session_id=normalized_id,
        user_id=normalized_user,
    )


def delete_last_chat_turn(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str | None,
    expected_message_count: int | None = None,
) -> int:
    _require_enabled(config)
    normalized_id = _validate_session_id(session_id)
    _load_chat_session(
        config=config,
        cosmos_store=cosmos_store,
        session_id=normalized_id,
        user_id=user_id,
        validate_scope=None,
    )
    messages = _message_rows(config, cosmos_store, normalized_id)
    if expected_message_count is not None:
        if expected_message_count < 2 or expected_message_count % 2:
            raise ValueError("expected_message_count must be an even turn pair count of at least 2.")
        if len(messages) != expected_message_count:
            raise ValueError("Message count does not match the expected orphan cleanup snapshot.")
    user_idx = next(
        (index for index in range(len(messages) - 1, -1, -1) if messages[index]["role"] == "user"),
        None,
    )
    if user_idx is None:
        return 0
    targets = [messages[user_idx]]
    targets.extend(
        messages[index]
        for index in range(user_idx + 1, len(messages))
        if messages[index]["role"] == "assistant"
    )
    targets = targets[:2]
    for row in targets:
        cosmos_store.delete_chat_message(
            config.CHAT_MESSAGES_CONTAINER,
            session_id=normalized_id,
            message_id=row["message_id"],
        )
    _decrement_message_count(
        config=config,
        cosmos_store=cosmos_store,
        session_id=normalized_id,
        user_id=_require_user(user_id),
        decrement=len(targets),
    )
    return len(targets)


def validate_chat_history_request(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    mode: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str | None,
) -> None:
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        return
    normalized_user = _require_user(user_id)
    if not requested_session_id:
        return
    session_id = _validate_session_id(requested_session_id)
    _load_chat_session(
        config=config,
        cosmos_store=cosmos_store,
        session_id=session_id,
        user_id=normalized_user,
        validate_scope=(mode, selected_case_id),
    )
    if len(_message_rows(config, cosmos_store, session_id)) + 2 > _max_messages(config):
        raise ValueError(
            f"Chat session exceeded the configured message limit of {_max_messages(config)}."
        )


def persist_chat_history(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    mode: str,
    question: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str | None,
    response: dict[str, Any],
    client_request_id: str | None = None,
) -> str:
    _require_enabled(config)
    normalized_user = _require_user(user_id)
    session = _resolve_session(
        config=config,
        cosmos_store=cosmos_store,
        mode=mode,
        selected_case_id=selected_case_id,
        requested_session_id=requested_session_id,
        user_id=normalized_user,
        client_request_id=client_request_id,
    )
    session_id = session["session_id"]
    turn_id = _turn_id(client_request_id)
    user_message_id = f"{turn_id}-user"
    assistant_message_id = f"{turn_id}-assistant"
    if client_request_id and cosmos_store.get_chat_message(
        config.CHAT_MESSAGES_CONTAINER,
        session_id=session_id,
        message_id=assistant_message_id,
    ):
        return session_id
    _reserve_turn(
        config=config,
        cosmos_store=cosmos_store,
        session_id=session_id,
        user_id=normalized_user,
        mode=mode,
        selected_case_id=selected_case_id,
        turn_id=turn_id,
    )

    max_bytes = max(1, int(config.CASE_QA_MAX_STORED_MESSAGE_BYTES))
    now = _utc_now()
    expires_at = _session_expires_at(config, now=now)
    expires_epoch = int(expires_at.timestamp())
    messages = [
        {
            "message_id": user_message_id,
            "session_id": session_id,
            "role": "user",
            "content": truncate_stored_message(question, max_bytes),
            "created_at": now.isoformat(),
            "expires_at_epoch": expires_epoch,
        },
        {
            "message_id": assistant_message_id,
            "session_id": session_id,
            "role": "assistant",
            "content": truncate_stored_message(str(response.get("answer") or ""), max_bytes),
            "created_at": (now + timedelta(microseconds=1)).isoformat(),
            "expires_at_epoch": expires_epoch,
        },
    ]
    answer_status = normalize_stored_answer_status(response.get("answer_status"))
    if answer_status is not None:
        messages[1]["answer_status"] = answer_status
    created_ids: list[str] = []
    try:
        for message in messages:
            outcome = cosmos_store.create_chat_message(config.CHAT_MESSAGES_CONTAINER, message)
            if not outcome.created:
                if not client_request_id:
                    raise RuntimeError("generated chat message id already exists")
            else:
                created_ids.append(message["message_id"])
        _finish_turn(
            config=config,
            cosmos_store=cosmos_store,
            session_id=session_id,
            user_id=normalized_user,
            turn_id=turn_id,
            now=now,
            expires_at=expires_at,
        )
    except Exception:
        for message_id in created_ids:
            cosmos_store.delete_chat_message(
                config.CHAT_MESSAGES_CONTAINER,
                session_id=session_id,
                message_id=message_id,
            )
        _release_turn(
            config=config,
            cosmos_store=cosmos_store,
            session_id=session_id,
            user_id=normalized_user,
            turn_id=turn_id,
        )
        raise
    return session_id


def _resolve_session(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    mode: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str,
    client_request_id: str | None,
) -> dict[str, Any]:
    now = _utc_now()
    expires_at = _session_expires_at(config, now=now)
    if requested_session_id:
        record = _load_chat_session(
            config=config,
            cosmos_store=cosmos_store,
            session_id=_validate_session_id(requested_session_id),
            user_id=user_id,
            validate_scope=(mode, selected_case_id),
        )
        return record

    _enforce_user_session_cap(config, cosmos_store, user_id)
    session_id = (
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"portal-chat-session:{user_id}:{client_request_id}"))
        if client_request_id
        else str(uuid.uuid4())
    )
    created_at = now.isoformat()
    session = {
        "session_id": session_id,
        "user_id": user_id,
        "mode": mode,
        "selected_case_id": selected_case_id or "",
        "title": _session_title(selected_case_id or "New chat"),
        "created_at": created_at,
        "updated_at": created_at,
        "expires_at": expires_at.isoformat(),
        "expires_at_epoch": int(expires_at.timestamp()),
        "message_count": 0,
        "pending_turn_ids": [],
    }
    outcome = cosmos_store.create_chat_session(config.CHAT_SESSIONS_CONTAINER, session)
    if not outcome.created:
        if client_request_id:
            return _load_chat_session(
                config=config,
                cosmos_store=cosmos_store,
                session_id=session_id,
                user_id=user_id,
                validate_scope=(mode, selected_case_id),
            )
        raise RuntimeError("generated chat session id already exists")
    return outcome.item or session


def _reserve_turn(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str,
    mode: str,
    selected_case_id: str | None,
    turn_id: str,
) -> None:
    for _attempt in range(5):
        session = _load_chat_session(
            config=config,
            cosmos_store=cosmos_store,
            session_id=session_id,
            user_id=user_id,
            validate_scope=(mode, selected_case_id),
        )
        etag = str(session.get("_etag") or "")
        if not etag:
            raise RuntimeError("chat session is missing its concurrency token")
        pending = [str(value) for value in session.get("pending_turn_ids") or []]
        if turn_id in pending:
            return
        message_count = session.get("message_count")
        if not isinstance(message_count, int):
            message_count = len(_message_rows(config, cosmos_store, session_id))
        if message_count + 2 > _max_messages(config):
            raise ValueError(
                f"Chat session exceeded the configured message limit of {_max_messages(config)}."
            )
        replacement = dict(session)
        replacement["message_count"] = message_count + 2
        replacement["pending_turn_ids"] = pending + [turn_id]
        outcome = cosmos_store.replace_chat_session_if_match(
            config.CHAT_SESSIONS_CONTAINER,
            replacement,
            expected_etag=etag,
        )
        if outcome.applied:
            return
        if outcome.outcome != "precondition_failed":
            raise ChatSessionNotFoundError("session_id was not found.")
    raise RuntimeError("chat session concurrency retry limit was exceeded")


def _finish_turn(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str,
    turn_id: str,
    now: datetime,
    expires_at: datetime,
) -> None:
    _update_turn_reservation(
        config=config,
        cosmos_store=cosmos_store,
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        release_capacity=False,
        timestamp=now,
        expires_at=expires_at,
    )


def _release_turn(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str,
    turn_id: str,
) -> None:
    _update_turn_reservation(
        config=config,
        cosmos_store=cosmos_store,
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        release_capacity=True,
        timestamp=None,
        expires_at=None,
    )


def _update_turn_reservation(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str,
    turn_id: str,
    release_capacity: bool,
    timestamp: datetime | None,
    expires_at: datetime | None,
) -> None:
    for _attempt in range(5):
        session = cosmos_store.get_chat_session(
            config.CHAT_SESSIONS_CONTAINER,
            session_id=session_id,
            user_id=user_id,
        )
        if not session:
            return
        pending = [str(value) for value in session.get("pending_turn_ids") or []]
        if turn_id not in pending:
            return
        etag = str(session.get("_etag") or "")
        if not etag:
            raise RuntimeError("chat session is missing its concurrency token")
        replacement = dict(session)
        replacement["pending_turn_ids"] = [value for value in pending if value != turn_id]
        if release_capacity:
            replacement["message_count"] = max(0, int(session.get("message_count") or 0) - 2)
        if timestamp is not None and expires_at is not None:
            replacement.update(
                {
                    "updated_at": timestamp.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "expires_at_epoch": int(expires_at.timestamp()),
                }
            )
        outcome = cosmos_store.replace_chat_session_if_match(
            config.CHAT_SESSIONS_CONTAINER,
            replacement,
            expected_etag=etag,
        )
        if outcome.applied:
            return
        if outcome.outcome != "precondition_failed":
            return
    raise RuntimeError("chat session concurrency retry limit was exceeded")


def _turn_id(client_request_id: str | None) -> str:
    if client_request_id is None:
        return str(uuid.uuid4())
    normalized = _validate_session_id(client_request_id)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"portal-chat:{normalized}"))


def _decrement_message_count(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str,
    decrement: int,
) -> None:
    for _attempt in range(5):
        session = cosmos_store.get_chat_session(
            config.CHAT_SESSIONS_CONTAINER,
            session_id=session_id,
            user_id=user_id,
        )
        if not session:
            return
        etag = str(session.get("_etag") or "")
        if not etag:
            raise RuntimeError("chat session is missing its concurrency token")
        replacement = dict(session)
        stored_count = session.get("message_count")
        if isinstance(stored_count, int):
            next_count = max(0, stored_count - max(0, decrement))
        else:
            # Legacy sessions predate the counter. Messages have already been
            # deleted at this point, so use the remaining authoritative rows
            # rather than subtracting twice or incorrectly seeding zero.
            next_count = len(_message_rows(config, cosmos_store, session_id))
        replacement["message_count"] = next_count
        outcome = cosmos_store.replace_chat_session_if_match(
            config.CHAT_SESSIONS_CONTAINER,
            replacement,
            expected_etag=etag,
        )
        if outcome.applied:
            return
        if outcome.outcome != "precondition_failed":
            return
    raise RuntimeError("chat session concurrency retry limit was exceeded")


def _enforce_user_session_cap(config: Config, cosmos_store: CosmosStore, user_id: str) -> None:
    max_sessions = max(1, int(config.CASE_QA_MAX_SESSIONS_PER_USER))
    rows = cosmos_store.list_chat_sessions(
        config.CHAT_SESSIONS_CONTAINER,
        user_id=user_id,
        now_epoch=_now_epoch(),
        limit=max_sessions + 1,
        oldest_first=True,
    )
    if len(rows) < max_sessions:
        return
    for row in rows[: len(rows) - max_sessions + 1]:
        session_id = row["session_id"]
        _delete_messages_for_session(config, cosmos_store, session_id)
        cosmos_store.delete_chat_session(
            config.CHAT_SESSIONS_CONTAINER,
            session_id=session_id,
            user_id=user_id,
        )


def _load_chat_session(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    session_id: str,
    user_id: str | None,
    validate_scope: tuple[str, str | None] | None,
) -> dict[str, Any]:
    normalized_user = _require_user(user_id)
    record = cosmos_store.get_chat_session(
        config.CHAT_SESSIONS_CONTAINER,
        session_id=session_id,
        user_id=normalized_user,
    )
    if not record:
        raise ChatSessionNotFoundError("session_id was not found.")
    if str(record.get("user_id") or "") != normalized_user:
        raise ValueError("session_id does not belong to the authenticated user.")
    if int(record.get("expires_at_epoch") or 0) <= _now_epoch():
        raise ChatSessionExpiredError("session_id has expired.")
    if validate_scope is not None:
        mode, selected_case_id = validate_scope
        if record.get("mode") != mode or (record.get("selected_case_id") or None) != selected_case_id:
            raise ValueError("session_id scope does not match the chat request.")
    return record


def _list_messages(config: Config, store: CosmosStore, session_id: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for row in _message_rows(config, store, session_id):
        message = {
            "role": row["role"],
            "content": row["content"],
            "created_at": row.get("created_at"),
        }
        if row["role"] == "assistant" and row.get("answer_status"):
            message["answer_status"] = row["answer_status"]
        messages.append(message)
    return messages


def _message_rows(config: Config, store: CosmosStore, session_id: str) -> list[dict[str, Any]]:
    return store.list_chat_messages(
        config.CHAT_MESSAGES_CONTAINER,
        session_id=session_id,
        limit=_max_messages(config),
    )


def _delete_messages_for_session(config: Config, store: CosmosStore, session_id: str) -> int:
    return store.delete_chat_messages(
        config.CHAT_MESSAGES_CONTAINER,
        session_id=session_id,
        limit=_max_messages(config),
    )


def _require_enabled(config: Config) -> None:
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        raise RuntimeError("Chat history persistence is disabled.")


def _require_user(user_id: str | None) -> str:
    normalized = str(user_id or "").strip()
    if not normalized:
        raise ValueError("authenticated user is required for chat history.")
    return normalized


def _validate_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not _SESSION_ID_RE.fullmatch(normalized):
        raise ValueError("session_id is invalid.")
    return normalized


def _session_title(title: Any, *, max_chars: int = 48) -> str:
    text = str(title or "").strip()
    if not text:
        return "New chat"
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "..."


def _session_expires_at(config: Config, *, now: datetime) -> datetime:
    return now + timedelta(days=max(1, int(config.CASE_QA_CHAT_HISTORY_RETENTION_DAYS)))


def _max_messages(config: Config) -> int:
    return max(1, min(int(config.CASE_QA_MAX_MESSAGES_PER_SESSION), 200))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now_epoch() -> int:
    return int(_utc_now().timestamp())
