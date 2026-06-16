"""Bounded DynamoDB persistence for AWS portal chat transcripts."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Config

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_VALID_ANSWER_STATUSES = frozenset(
    {"answered", "unknown", "refused", "insufficient_context"}
)
_USER_UPDATED_INDEX = "UserUpdatedIndex"


class ChatSessionNotFoundError(LookupError):
    """Raised when a requested chat session id is missing."""


class ChatSessionExpiredError(LookupError):
    """Raised when a requested chat session id is past retention expiry."""


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


def normalize_stored_answer_status(value: Any) -> str | None:
    """Return a bounded answer_status value for persisted assistant messages."""
    text = str(value or "").strip()
    if text in _VALID_ANSWER_STATUSES:
        return text
    return None


def list_chat_sessions(
    *,
    config: Config,
    dynamodb_client: Any,
    user_id: str | None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return bounded chat session summaries for the authenticated user."""
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        return []

    normalized_user = _normalize_user_id(user_id)
    if normalized_user is None:
        raise ValueError("authenticated user is required for chat history.")

    page_size = max(1, min(int(limit), 100))
    now_epoch = _now_epoch()
    response = dynamodb_client.query(
        TableName=config.CHAT_SESSIONS_TABLE,
        IndexName=_USER_UPDATED_INDEX,
        KeyConditionExpression="user_id = :user_id",
        FilterExpression="expires_at_epoch > :now_epoch",
        ExpressionAttributeValues={
            ":user_id": {"S": normalized_user},
            ":now_epoch": {"N": str(now_epoch)},
        },
        ScanIndexForward=False,
        Limit=page_size,
    )
    items: list[dict[str, Any]] = []
    for item in response.get("Items", []):
        row = _from_item(item)
        items.append(
            {
                "session_id": row["session_id"],
                "mode": row["mode"],
                "selected_case_id": row.get("selected_case_id"),
                "updated_at": row.get("updated_at"),
                "title": _session_title(row.get("title")),
            }
        )
    return items


def get_chat_session_messages(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    """Return one chat session transcript for the authenticated user."""
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        raise RuntimeError("Chat history persistence is disabled.")

    record = _load_chat_session(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=_validate_session_id(session_id),
        user_id=user_id,
        require_owner=True,
    )
    messages = _list_messages(config=config, dynamodb_client=dynamodb_client, session_id=record["session_id"])
    return {
        "session_id": record["session_id"],
        "mode": record["mode"],
        "selected_case_id": record.get("selected_case_id"),
        "messages": messages,
    }


def delete_chat_session(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
    user_id: str | None,
) -> bool:
    """Delete one chat session and its messages for the authenticated user."""
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        raise RuntimeError("Chat history persistence is disabled.")

    normalized_id = _validate_session_id(session_id)
    _load_chat_session(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=normalized_id,
        user_id=user_id,
        require_owner=True,
    )
    _delete_messages_for_session(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=normalized_id,
    )
    dynamodb_client.delete_item(
        TableName=config.CHAT_SESSIONS_TABLE,
        Key={"session_id": {"S": normalized_id}},
        ConditionExpression="attribute_exists(session_id)",
    )
    return True


def delete_last_chat_turn(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
    user_id: str | None,
    expected_message_count: int | None = None,
) -> int:
    """Delete the latest persisted chat turn for the authenticated user."""
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        raise RuntimeError("Chat history persistence is disabled.")

    normalized_id = _validate_session_id(session_id)
    _load_chat_session(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=normalized_id,
        user_id=user_id,
        require_owner=True,
    )
    if expected_message_count is not None:
        if expected_message_count < 2:
            raise ValueError("expected_message_count must be at least 2.")
        if expected_message_count % 2 != 0:
            raise ValueError("expected_message_count must be an even turn pair count.")
        current = _count_messages(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=normalized_id,
        )
        if current != expected_message_count:
            raise ValueError(
                "Message count does not match the expected orphan cleanup snapshot."
            )

    messages = _list_message_rows(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=normalized_id,
    )
    user_idx = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index]["role"] == "user":
            user_idx = index
            break
    if user_idx is None:
        return 0

    delete_keys = [messages[user_idx]["key"]]
    for index in range(user_idx + 1, len(messages)):
        if messages[index]["role"] == "assistant":
            delete_keys.append(messages[index]["key"])
            break

    for key in delete_keys:
        dynamodb_client.delete_item(
            TableName=config.CHAT_MESSAGES_TABLE,
            Key=key,
        )
    return len(delete_keys)


def validate_chat_history_request(
    *,
    config: Config,
    dynamodb_client: Any,
    mode: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str | None,
) -> None:
    """Validate chat-history ownership and capacity before expensive chat work."""
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        return

    normalized_user = _normalize_user_id(user_id)
    if normalized_user is None:
        raise ValueError("authenticated user is required for chat history.")
    if not requested_session_id:
        return

    session_id = _validate_session_id(requested_session_id)
    _load_chat_session(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
        user_id=normalized_user,
        require_owner=True,
        validate_scope=(mode, selected_case_id),
    )
    current = _count_messages(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
    )
    max_messages = max(1, int(config.CASE_QA_MAX_MESSAGES_PER_SESSION))
    if current + 2 > max_messages:
        raise ValueError(
            f"Chat session exceeded the configured message limit of {max_messages}."
        )


def persist_chat_history(
    *,
    config: Config,
    dynamodb_client: Any,
    mode: str,
    question: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str | None,
    response: dict[str, Any],
) -> str:
    """Persist one bounded chat turn and return the active session id."""
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        raise RuntimeError("Chat history persistence is disabled.")

    normalized_user = _normalize_user_id(user_id)
    if normalized_user is None:
        raise ValueError("authenticated user is required for chat history.")

    session_id = _resolve_session_id(
        config=config,
        dynamodb_client=dynamodb_client,
        mode=mode,
        selected_case_id=selected_case_id,
        requested_session_id=requested_session_id,
        user_id=normalized_user,
    )
    max_bytes = max(1, int(config.CASE_QA_MAX_STORED_MESSAGE_BYTES))
    user_content = truncate_stored_message(question, max_bytes)
    assistant_content = truncate_stored_message(str(response.get("answer") or ""), max_bytes)
    assistant_answer_status = normalize_stored_answer_status(response.get("answer_status"))

    current = _count_messages(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
    )
    max_messages = max(1, int(config.CASE_QA_MAX_MESSAGES_PER_SESSION))
    if current + 2 > max_messages:
        raise ValueError(
            f"Chat session exceeded the configured message limit of {max_messages}."
        )

    now = _utc_now()
    expires_at = _session_expires_at(config, now=now)
    expires_epoch = int(expires_at.timestamp())
    user_message_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())
    user_created = now.isoformat()
    assistant_created = (now + timedelta(microseconds=1)).isoformat()

    dynamodb_client.put_item(
        TableName=config.CHAT_MESSAGES_TABLE,
        Item={
            "session_id": {"S": session_id},
            "created_at_message_id": {"S": _message_sort_key(user_created, user_message_id)},
            "message_id": {"S": user_message_id},
            "role": {"S": "user"},
            "content": {"S": user_content},
            "created_at": {"S": user_created},
            "expires_at_epoch": {"N": str(expires_epoch)},
        },
    )
    assistant_item: dict[str, Any] = {
        "session_id": {"S": session_id},
        "created_at_message_id": {"S": _message_sort_key(assistant_created, assistant_message_id)},
        "message_id": {"S": assistant_message_id},
        "role": {"S": "assistant"},
        "content": {"S": assistant_content},
        "created_at": {"S": assistant_created},
        "expires_at_epoch": {"N": str(expires_epoch)},
    }
    if assistant_answer_status is not None:
        assistant_item["answer_status"] = {"S": assistant_answer_status}
    dynamodb_client.put_item(
        TableName=config.CHAT_MESSAGES_TABLE,
        Item=assistant_item,
    )
    dynamodb_client.update_item(
        TableName=config.CHAT_SESSIONS_TABLE,
        Key={"session_id": {"S": session_id}},
        UpdateExpression=(
            "SET updated_at = :updated_at, updated_at_session_id = :updated_sort, "
            "expires_at = :expires_at, expires_at_epoch = :expires_at_epoch"
        ),
        ExpressionAttributeValues={
            ":updated_at": {"S": now.isoformat()},
            ":updated_sort": {"S": _session_sort_key(now.isoformat(), session_id)},
            ":expires_at": {"S": expires_at.isoformat()},
            ":expires_at_epoch": {"N": str(expires_epoch)},
        },
    )
    return session_id


def _resolve_session_id(
    *,
    config: Config,
    dynamodb_client: Any,
    mode: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str,
) -> str:
    now = _utc_now()
    expires_at = _session_expires_at(config, now=now)
    expires_epoch = int(expires_at.timestamp())

    if requested_session_id:
        session_id = _validate_session_id(requested_session_id)
        _load_chat_session(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=session_id,
            user_id=user_id,
            require_owner=True,
            validate_scope=(mode, selected_case_id),
        )
        dynamodb_client.update_item(
            TableName=config.CHAT_SESSIONS_TABLE,
            Key={"session_id": {"S": session_id}},
            UpdateExpression=(
                "SET expires_at = :expires_at, expires_at_epoch = :expires_at_epoch, "
                "updated_at = :updated_at, updated_at_session_id = :updated_sort"
            ),
            ExpressionAttributeValues={
                ":expires_at": {"S": expires_at.isoformat()},
                ":expires_at_epoch": {"N": str(expires_epoch)},
                ":updated_at": {"S": now.isoformat()},
                ":updated_sort": {"S": _session_sort_key(now.isoformat(), session_id)},
            },
        )
        return session_id

    _enforce_user_session_cap(
        config=config,
        dynamodb_client=dynamodb_client,
        user_id=user_id,
    )
    session_id = str(uuid.uuid4())
    created_at = now.isoformat()
    dynamodb_client.put_item(
        TableName=config.CHAT_SESSIONS_TABLE,
        Item={
            "session_id": {"S": session_id},
            "user_id": {"S": user_id},
            "mode": {"S": mode},
            "selected_case_id": {"S": selected_case_id or ""},
            "title": {"S": _session_title(selected_case_id or "New chat")},
            "created_at": {"S": created_at},
            "updated_at": {"S": created_at},
            "updated_at_session_id": {"S": _session_sort_key(created_at, session_id)},
            "expires_at": {"S": expires_at.isoformat()},
            "expires_at_epoch": {"N": str(expires_epoch)},
        },
        ConditionExpression="attribute_not_exists(session_id)",
    )
    return session_id


def _enforce_user_session_cap(
    *,
    config: Config,
    dynamodb_client: Any,
    user_id: str,
) -> None:
    max_sessions = max(1, int(config.CASE_QA_MAX_SESSIONS_PER_USER))
    now_epoch = _now_epoch()
    response = dynamodb_client.query(
        TableName=config.CHAT_SESSIONS_TABLE,
        IndexName=_USER_UPDATED_INDEX,
        KeyConditionExpression="user_id = :user_id",
        FilterExpression="expires_at_epoch > :now_epoch",
        ExpressionAttributeValues={
            ":user_id": {"S": user_id},
            ":now_epoch": {"N": str(now_epoch)},
        },
        ScanIndexForward=True,
    )
    rows = [_from_item(item) for item in response.get("Items", [])]
    if len(rows) < max_sessions:
        return
    delete_count = len(rows) - max_sessions + 1
    for row in rows[:delete_count]:
        session_id = row["session_id"]
        _delete_messages_for_session(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=session_id,
        )
        dynamodb_client.delete_item(
            TableName=config.CHAT_SESSIONS_TABLE,
            Key={"session_id": {"S": session_id}},
        )


def _load_chat_session(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
    user_id: str | None,
    require_owner: bool,
    validate_scope: tuple[str, str | None] | None = None,
) -> dict[str, Any]:
    response = dynamodb_client.get_item(
        TableName=config.CHAT_SESSIONS_TABLE,
        Key={"session_id": {"S": session_id}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        raise ChatSessionNotFoundError("session_id was not found.")
    record = _from_item(item)
    expires_epoch = int(record.get("expires_at_epoch") or 0)
    if expires_epoch <= _now_epoch():
        raise ChatSessionExpiredError("session_id has expired.")
    if require_owner:
        normalized_user = _normalize_user_id(user_id)
        stored_user = _normalize_user_id(record.get("user_id"))
        if normalized_user is None or stored_user != normalized_user:
            raise ValueError("session_id does not belong to the authenticated user.")
    if validate_scope is not None:
        mode, selected_case_id = validate_scope
        stored_case_id = record.get("selected_case_id") or None
        if record.get("mode") != mode or stored_case_id != selected_case_id:
            raise ValueError("session_id scope does not match the chat request.")
    return record


def _list_messages(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for row in _list_message_rows(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
    ):
        message: dict[str, Any] = {
            "role": row["role"],
            "content": row["content"],
            "created_at": row.get("created_at"),
        }
        if row["role"] == "assistant" and row.get("answer_status"):
            message["answer_status"] = row["answer_status"]
        messages.append(message)
    return messages


def _list_message_rows(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
) -> list[dict[str, Any]]:
    response = dynamodb_client.query(
        TableName=config.CHAT_MESSAGES_TABLE,
        KeyConditionExpression="session_id = :session_id",
        ExpressionAttributeValues={":session_id": {"S": session_id}},
        ScanIndexForward=True,
    )
    rows: list[dict[str, Any]] = []
    for item in response.get("Items", []):
        row = _from_item(item)
        row["key"] = {
            "session_id": item["session_id"],
            "created_at_message_id": item["created_at_message_id"],
        }
        rows.append(row)
    return rows


def _count_messages(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
) -> int:
    response = dynamodb_client.query(
        TableName=config.CHAT_MESSAGES_TABLE,
        KeyConditionExpression="session_id = :session_id",
        ExpressionAttributeValues={":session_id": {"S": session_id}},
        Select="COUNT",
    )
    return int(response.get("Count", 0))


def _delete_messages_for_session(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
) -> None:
    while True:
        response = dynamodb_client.query(
            TableName=config.CHAT_MESSAGES_TABLE,
            KeyConditionExpression="session_id = :session_id",
            ExpressionAttributeValues={":session_id": {"S": session_id}},
            ProjectionExpression="session_id, created_at_message_id",
            Limit=25,
        )
        items = response.get("Items", [])
        if not items:
            return
        for item in items:
            dynamodb_client.delete_item(
                TableName=config.CHAT_MESSAGES_TABLE,
                Key={
                    "session_id": item["session_id"],
                    "created_at_message_id": item["created_at_message_id"],
                },
            )


def _session_title(title: Any, *, max_chars: int = 48) -> str:
    text = str(title or "").strip()
    if not text:
        return "New chat"
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _normalize_user_id(user_id: str | None) -> str | None:
    text = str(user_id or "").strip()
    return text or None


def _validate_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not _SESSION_ID_RE.fullmatch(normalized):
        raise ValueError("session_id is invalid.")
    return normalized


def _session_expires_at(config: Config, *, now: datetime) -> datetime:
    days = max(1, int(config.CASE_QA_CHAT_HISTORY_RETENTION_DAYS))
    return now + timedelta(days=days)


def _session_sort_key(updated_at: str, session_id: str) -> str:
    return f"{updated_at}#{session_id}"


def _message_sort_key(created_at: str, message_id: str) -> str:
    return f"{created_at}#{message_id}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now_epoch() -> int:
    return int(_utc_now().timestamp())


def _from_item(item: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in item.items():
        if "S" in value:
            row[key] = value["S"]
        elif "N" in value:
            row[key] = value["N"]
        elif "NULL" in value:
            row[key] = None
    if "selected_case_id" in row and row["selected_case_id"] == "":
        row["selected_case_id"] = None
    return row
