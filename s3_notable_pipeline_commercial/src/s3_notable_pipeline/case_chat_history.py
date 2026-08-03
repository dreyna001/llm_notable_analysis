"""Bounded DynamoDB persistence for AWS portal chat transcripts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .config import Config

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_VALID_ANSWER_STATUSES = frozenset(
    {"answered", "unknown", "refused", "insufficient_context"}
)
_USER_UPDATED_INDEX = "UserUpdatedIndex"
_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_MESSAGE_SORT_PREFIX = "s#"
_GET_MESSAGE_QUERY_PAGE_SIZE = 25
_UTC_NOW_PROVIDER: Callable[[], datetime] | None = None


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


def load_session_transcript(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
) -> list[dict[str, Any]]:
    """Return stored transcript rows for synthesis after request validation."""
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        return []
    return _list_messages(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=_validate_session_id(session_id),
    )


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


def get_idempotent_chat_response(
    *,
    config: Config,
    dynamodb_client: Any,
    mode: str,
    selected_case_id: str | None,
    question: str,
    requested_session_id: str | None,
    user_id: str | None,
    client_request_id: str,
) -> dict[str, Any] | None:
    """Return a previously stored response for a retry-stable client key."""

    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        return None
    normalized_user = _normalize_user_id(user_id)
    if normalized_user is None:
        raise ValueError("authenticated user is required for chat history.")
    request_id = _validate_client_request_id(client_request_id)
    session_id = _request_session_id(
        user_id=normalized_user,
        client_request_id=request_id,
        requested_session_id=requested_session_id,
    )
    if requested_session_id:
        _load_chat_session(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=_validate_session_id(session_id),
            user_id=normalized_user,
            require_owner=True,
            validate_scope=(mode, selected_case_id),
        )
    else:
        record = _load_chat_session_if_present(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=session_id,
        )
        if record is None:
            return None
        if _normalize_user_id(record.get("user_id")) != normalized_user:
            return None
        if record.get("mode") != mode or (record.get("selected_case_id") or None) != selected_case_id:
            raise ValueError("client_request_id scope does not match the chat request.")

    turn_id = _turn_id(request_id, session_id=session_id)
    item = _get_message_item(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
        turn_id=turn_id,
        role="assistant",
    )
    if not item:
        return None
    if item.get("request_fingerprint", {}).get("S") != _request_fingerprint(
        mode=mode,
        selected_case_id=selected_case_id,
        question=question,
    ):
        raise ValueError("client_request_id was reused for a different chat request.")
    payload: dict[str, Any] = {
        "answer": item.get("content", {}).get("S", ""),
        "answer_status": item.get("answer_status", {}).get("S", "answered"),
        "session_id": session_id,
    }
    context_usage = item.get("context_usage", {}).get("S")
    if context_usage:
        try:
            payload["context_usage"] = json.loads(context_usage)
        except (TypeError, ValueError):
            pass
    return payload


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
    client_request_id: str | None = None,
) -> str:
    """Persist one bounded chat turn and return the active session id."""
    if not config.CASE_QA_CHAT_HISTORY_ENABLED:
        raise RuntimeError("Chat history persistence is disabled.")

    normalized_user = _normalize_user_id(user_id)
    if normalized_user is None:
        raise ValueError("authenticated user is required for chat history.")

    normalized_request_id = (
        _validate_client_request_id(client_request_id)
        if client_request_id
        else None
    )

    session_id = _resolve_session_id(
        config=config,
        dynamodb_client=dynamodb_client,
        mode=mode,
        selected_case_id=selected_case_id,
        requested_session_id=requested_session_id,
        user_id=normalized_user,
        client_request_id=normalized_request_id,
    )
    turn_id = _turn_id(normalized_request_id, session_id=session_id)
    if normalized_request_id:
        existing = _get_message_item(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=session_id,
            turn_id=turn_id,
            role="assistant",
        )
        if existing:
            expected_fingerprint = _request_fingerprint(
                mode=mode,
                selected_case_id=selected_case_id,
                question=question,
            )
            if existing.get("request_fingerprint", {}).get("S") != expected_fingerprint:
                raise ValueError("client_request_id was reused for a different chat request.")
            return session_id

    reserved, reserved_base_sequence = _reserve_turn_capacity(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
        user_id=normalized_user,
        mode=mode,
        selected_case_id=selected_case_id,
        turn_id=turn_id,
    )
    max_bytes = max(1, int(config.CASE_QA_MAX_STORED_MESSAGE_BYTES))
    user_content = truncate_stored_message(question, max_bytes)
    assistant_content = truncate_stored_message(str(response.get("answer") or ""), max_bytes)
    assistant_answer_status = normalize_stored_answer_status(response.get("answer_status"))

    if reserved_base_sequence is not None:
        user_sequence = reserved_base_sequence
        assistant_sequence = reserved_base_sequence + 1
    else:
        user_sequence, assistant_sequence = _allocate_turn_sequences(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=session_id,
        )

    now = _utc_now()
    expires_at = _session_expires_at(config, now=now)
    expires_epoch = int(expires_at.timestamp())
    if normalized_request_id:
        expires_epoch = min(
            expires_epoch,
            int(now.timestamp()) + _idempotency_retention_seconds(config),
        )
    user_message_id = f"turn#{turn_id}#user" if normalized_request_id else str(uuid.uuid4())
    assistant_message_id = (
        f"turn#{turn_id}#assistant" if normalized_request_id else str(uuid.uuid4())
    )
    user_created = now.isoformat()
    assistant_created = (now + timedelta(microseconds=1)).isoformat()

    user_item: dict[str, Any] = {
        "session_id": {"S": session_id},
        "created_at_message_id": {
            "S": _message_sort_key(
                user_created,
                user_sequence,
                user_message_id,
            )
        },
        "message_id": {"S": user_message_id},
        "role": {"S": "user"},
        "content": {"S": user_content},
        "created_at": {"S": user_created},
        "expires_at_epoch": {"N": str(expires_epoch)},
        "message_sequence": {"N": str(user_sequence)},
    }
    assistant_item: dict[str, Any] = {
        "session_id": {"S": session_id},
        "created_at_message_id": {
            "S": _message_sort_key(
                assistant_created,
                assistant_sequence,
                assistant_message_id,
            )
        },
        "message_id": {"S": assistant_message_id},
        "role": {"S": "assistant"},
        "content": {"S": assistant_content},
        "created_at": {"S": assistant_created},
        "expires_at_epoch": {"N": str(expires_epoch)},
        "message_sequence": {"N": str(assistant_sequence)},
    }
    if normalized_request_id:
        fingerprint = _request_fingerprint(
            mode=mode,
            selected_case_id=selected_case_id,
            question=question,
        )
        user_item["client_request_id"] = {"S": normalized_request_id}
        user_item["request_fingerprint"] = {"S": fingerprint}
    if assistant_answer_status is not None:
        assistant_item["answer_status"] = {"S": assistant_answer_status}
    if normalized_request_id:
        assistant_item["client_request_id"] = {"S": normalized_request_id}
        assistant_item["request_fingerprint"] = {"S": fingerprint}
        if response.get("context_usage") is not None:
            assistant_item["context_usage"] = {
                "S": truncate_stored_message(
                    json.dumps(response["context_usage"], separators=(",", ":")),
                    max_bytes,
                )
            }
    created_keys: list[dict[str, Any]] = []
    try:
        if reserved and hasattr(dynamodb_client, "transact_write_items"):
            _transact_persist_turn(
                config=config,
                dynamodb_client=dynamodb_client,
                session_id=session_id,
                turn_id=turn_id,
                user_item=user_item,
                assistant_item=assistant_item,
                now=now,
                expires_at=expires_at,
            )
        else:
            dynamodb_client.put_item(
                TableName=config.CHAT_MESSAGES_TABLE,
                Item=user_item,
            )
            created_keys.append(
                {
                    "session_id": user_item["session_id"],
                    "created_at_message_id": user_item["created_at_message_id"],
                }
            )
            dynamodb_client.put_item(
                TableName=config.CHAT_MESSAGES_TABLE,
                Item=assistant_item,
            )
            created_keys.append(
                {
                    "session_id": assistant_item["session_id"],
                    "created_at_message_id": assistant_item["created_at_message_id"],
                }
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
    except Exception:
        for key in created_keys:
            dynamodb_client.delete_item(TableName=config.CHAT_MESSAGES_TABLE, Key=key)
        if reserved:
            _release_turn_capacity(
                config=config,
                dynamodb_client=dynamodb_client,
                session_id=session_id,
                turn_id=turn_id,
            )
        raise
    return session_id


def _resolve_session_id(
    *,
    config: Config,
    dynamodb_client: Any,
    mode: str,
    selected_case_id: str | None,
    requested_session_id: str | None,
    user_id: str,
    client_request_id: str | None = None,
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
    session_id = _request_session_id(
        user_id=user_id,
        client_request_id=client_request_id,
        requested_session_id=None,
    )
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
            "message_count": {"N": "0"},
            "pending_turns": {"M": {}},
        },
        ConditionExpression="attribute_not_exists(session_id)",
    )
    return session_id


def _reserve_turn_capacity(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
    user_id: str,
    mode: str,
    selected_case_id: str | None,
    turn_id: str,
    _attempt: int = 0,
) -> tuple[bool, int | None]:
    """Atomically reserve two message slots when the native client supports it."""

    if not hasattr(dynamodb_client, "transact_write_items"):
        return False, None
    record = _load_chat_session(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
        user_id=user_id,
        require_owner=True,
        validate_scope=(mode, selected_case_id),
    )
    _bootstrap_session_message_count(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
    )
    record = _load_chat_session(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
        user_id=user_id,
        require_owner=True,
        validate_scope=(mode, selected_case_id),
    )
    pending = record.get("pending_turns") or {}
    if isinstance(pending, dict) and turn_id in pending:
        return True, int(pending[turn_id])
    if "pending_turns" not in record:
        dynamodb_client.update_item(
            TableName=config.CHAT_SESSIONS_TABLE,
            Key={"session_id": {"S": session_id}},
            UpdateExpression="SET pending_turns = :empty",
            ConditionExpression="attribute_not_exists(pending_turns)",
            ExpressionAttributeValues={":empty": {"M": {}}},
        )
        record = _load_chat_session(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=session_id,
            user_id=user_id,
            require_owner=True,
            validate_scope=(mode, selected_case_id),
        )
    current = int(record.get("message_count") or 0)
    max_messages = max(1, int(config.CASE_QA_MAX_MESSAGES_PER_SESSION))
    if current + 2 > max_messages:
        raise ValueError(
            f"Chat session exceeded the configured message limit of {max_messages}."
        )
    try:
        dynamodb_client.update_item(
            TableName=config.CHAT_SESSIONS_TABLE,
            Key={"session_id": {"S": session_id}},
            UpdateExpression=(
                "SET message_count = if_not_exists(message_count, :current) + :two, "
                "pending_turns.#turn = :reserved"
            ),
            ConditionExpression=(
                "attribute_exists(session_id) AND "
                "message_count <= :maximum_before AND "
                "message_count = :current AND "
                "attribute_not_exists(pending_turns.#turn)"
            ),
            ExpressionAttributeNames={"#turn": turn_id},
            ExpressionAttributeValues={
                ":current": {"N": str(current)},
                ":two": {"N": "2"},
                ":maximum_before": {"N": str(max_messages - 2)},
                ":reserved": {"N": str(current)},
            },
        )
    except Exception as exc:
        latest = _load_chat_session(
            config=config,
            dynamodb_client=dynamodb_client,
            session_id=session_id,
            user_id=user_id,
            require_owner=True,
            validate_scope=(mode, selected_case_id),
        )
        if turn_id in (latest.get("pending_turns") or {}):
            return True, int(latest["pending_turns"][turn_id])
        if "ConditionalCheckFailed" in str(exc):
            latest_count = int(latest.get("message_count") or 0)
            if latest_count + 2 <= max_messages:
                if _attempt >= 4:
                    raise RuntimeError(
                        "Concurrent chat turn reservation contention; retry the request."
                    ) from exc
                return _reserve_turn_capacity(
                    config=config,
                    dynamodb_client=dynamodb_client,
                    session_id=session_id,
                    user_id=user_id,
                    mode=mode,
                    selected_case_id=selected_case_id,
                    turn_id=turn_id,
                    _attempt=_attempt + 1,
                )
            raise ValueError(
                f"Chat session exceeded the configured message limit of {max_messages}."
            ) from exc
        raise
    return True, current


def _release_turn_capacity(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
    turn_id: str,
) -> None:
    try:
        dynamodb_client.update_item(
            TableName=config.CHAT_SESSIONS_TABLE,
            Key={"session_id": {"S": session_id}},
            UpdateExpression="SET message_count = message_count - :two REMOVE pending_turns.#turn",
            ConditionExpression="attribute_exists(pending_turns.#turn)",
            ExpressionAttributeNames={"#turn": turn_id},
            ExpressionAttributeValues={":two": {"N": "2"}},
        )
    except Exception:
        return


def _transact_persist_turn(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
    turn_id: str,
    user_item: dict[str, Any],
    assistant_item: dict[str, Any],
    now: datetime,
    expires_at: datetime,
) -> None:
    expires_epoch = int(expires_at.timestamp())
    dynamodb_client.transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": config.CHAT_MESSAGES_TABLE,
                    "Item": user_item,
                    "ConditionExpression": "attribute_not_exists(session_id)",
                }
            },
            {
                "Put": {
                    "TableName": config.CHAT_MESSAGES_TABLE,
                    "Item": assistant_item,
                    "ConditionExpression": "attribute_not_exists(session_id)",
                }
            },
            {
                "Update": {
                    "TableName": config.CHAT_SESSIONS_TABLE,
                    "Key": {"session_id": {"S": session_id}},
                    "UpdateExpression": (
                        "SET updated_at = :updated_at, updated_at_session_id = :updated_sort, "
                        "expires_at = :expires_at, expires_at_epoch = :expires_at_epoch "
                        "REMOVE pending_turns.#turn"
                    ),
                    "ConditionExpression": "attribute_exists(pending_turns.#turn)",
                    "ExpressionAttributeNames": {"#turn": turn_id},
                    "ExpressionAttributeValues": {
                        ":updated_at": {"S": now.isoformat()},
                        ":updated_sort": {"S": _session_sort_key(now.isoformat(), session_id)},
                        ":expires_at": {"S": expires_at.isoformat()},
                        ":expires_at_epoch": {"N": str(expires_epoch)},
                    },
                }
            },
        ]
    )


def _request_session_id(
    *,
    user_id: str,
    client_request_id: str | None,
    requested_session_id: str | None,
) -> str:
    if requested_session_id:
        return _validate_session_id(requested_session_id)
    if client_request_id:
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"portal-chat-session:{user_id}:{client_request_id}",
            )
        )
    return str(uuid.uuid4())


def _turn_id(client_request_id: str | None, *, session_id: str) -> str:
    if client_request_id is None:
        return str(uuid.uuid4())
    normalized = _validate_client_request_id(client_request_id)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"portal-chat:{session_id}:{normalized}"))


def _validate_client_request_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not _CLIENT_REQUEST_ID_RE.fullmatch(normalized):
        raise ValueError("client_request_id must be 8-128 URL-safe characters")
    return normalized


def _idempotency_retention_seconds(config: Config) -> int:
    if hasattr(config, "PORTAL_CHAT_IDEMPOTENCY_RETENTION_SECONDS"):
        raw = getattr(config, "PORTAL_CHAT_IDEMPOTENCY_RETENTION_SECONDS")
    else:
        raw = os.getenv("PORTAL_CHAT_IDEMPOTENCY_RETENTION_SECONDS", "86400")
    try:
        return max(60, min(int(raw), 7 * 24 * 60 * 60))
    except (TypeError, ValueError):
        return 86400


def _request_fingerprint(
    *,
    mode: str,
    selected_case_id: str | None,
    question: str,
) -> str:
    body = json.dumps(
        [mode, selected_case_id or None, question],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _get_message_item(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
    turn_id: str,
    role: str,
) -> dict[str, Any] | None:
    target_message_id = f"turn#{turn_id}#{role}"
    exclusive_start_key: dict[str, Any] | None = None
    while True:
        request: dict[str, Any] = {
            "TableName": config.CHAT_MESSAGES_TABLE,
            "KeyConditionExpression": "session_id = :session_id",
            "FilterExpression": "message_id = :message_id",
            "ExpressionAttributeValues": {
                ":session_id": {"S": session_id},
                ":message_id": {"S": target_message_id},
            },
            "ConsistentRead": True,
            "Limit": _GET_MESSAGE_QUERY_PAGE_SIZE,
        }
        if exclusive_start_key is not None:
            request["ExclusiveStartKey"] = exclusive_start_key
        response = dynamodb_client.query(**request)
        for item in response.get("Items") or []:
            if item.get("message_id", {}).get("S") == target_message_id:
                return item
        exclusive_start_key = response.get("LastEvaluatedKey")
        if not exclusive_start_key:
            return None


def _bootstrap_session_message_count(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
) -> None:
    record = _load_chat_session_if_present(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
    )
    if record is None:
        return
    stored_count = (
        int(record["message_count"])
        if record.get("message_count") is not None
        else None
    )
    counted = _count_messages(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
    )
    if stored_count is not None and stored_count >= counted:
        return
    condition = (
        "attribute_not_exists(message_count)"
        if stored_count is None
        else "message_count = :observed"
    )
    values = {":counted": {"N": str(counted)}}
    if stored_count is not None:
        values[":observed"] = {"N": str(stored_count)}
    try:
        dynamodb_client.update_item(
            TableName=config.CHAT_SESSIONS_TABLE,
            Key={"session_id": {"S": session_id}},
            UpdateExpression="SET message_count = :counted",
            ConditionExpression=condition,
            ExpressionAttributeValues=values,
        )
    except Exception:
        return


def _allocate_turn_sequences(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
) -> tuple[int, int]:
    """Atomically reserve two monotonic message sequence numbers for one turn."""

    _bootstrap_session_message_count(
        config=config,
        dynamodb_client=dynamodb_client,
        session_id=session_id,
    )
    max_messages = max(1, int(config.CASE_QA_MAX_MESSAGES_PER_SESSION))
    try:
        response = dynamodb_client.update_item(
            TableName=config.CHAT_SESSIONS_TABLE,
            Key={"session_id": {"S": session_id}},
            UpdateExpression="ADD message_count :two",
            ConditionExpression=(
                "attribute_exists(session_id) AND "
                "message_count <= :maximum_before"
            ),
            ExpressionAttributeValues={
                ":two": {"N": "2"},
                ":maximum_before": {"N": str(max_messages - 2)},
            },
            ReturnValues="UPDATED_OLD",
        )
    except Exception as exc:
        if "ConditionalCheckFailed" in str(exc):
            raise ValueError(
                f"Chat session exceeded the configured message limit of {max_messages}."
            ) from exc
        raise
    attributes = response.get("Attributes") or {}
    if "message_count" in attributes:
        base_sequence = int(attributes["message_count"]["N"])
    else:
        base_sequence = 0
    return base_sequence, base_sequence + 1


def _load_chat_session_if_present(
    *,
    config: Config,
    dynamodb_client: Any,
    session_id: str,
) -> dict[str, Any] | None:
    response = dynamodb_client.get_item(
        TableName=config.CHAT_SESSIONS_TABLE,
        Key={"session_id": {"S": session_id}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return _from_item(item) if item else None


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
    _sort_message_rows(rows)
    return rows


def _sort_message_rows(rows: list[dict[str, Any]]) -> None:
    legacy_rows = [
        row for row in rows if _row_message_sequence(row) is None
    ]
    legacy_rows.sort(
        key=lambda row: (
            str(row.get("created_at") or _legacy_created_at_from_sort_key(row)),
            0 if row.get("role") == "user" else 1,
            str(row.get("message_id") or ""),
        )
    )
    legacy_order = {id(row): index for index, row in enumerate(legacy_rows)}

    def order_key(row: dict[str, Any]) -> int:
        sequence = _row_message_sequence(row)
        if sequence is not None:
            return sequence
        return legacy_order[id(row)]

    rows.sort(key=order_key)


def _row_message_sequence(row: dict[str, Any]) -> int | None:
    raw = row.get("message_sequence")
    if raw is not None and str(raw).isdigit():
        return int(raw)
    return _parse_sequence_from_sort_key(row.get("created_at_message_id"))


def _parse_sequence_from_sort_key(sort_key: Any) -> int | None:
    text = str(sort_key or "")
    if not text:
        return None
    if text.startswith(_MESSAGE_SORT_PREFIX):
        parts = text.split("#", 3)
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    head = text.split("#", 1)[0]
    if head.isdigit() and len(head) == 10:
        return int(head)
    return None


def _legacy_created_at_from_sort_key(row: dict[str, Any]) -> str:
    text = str(row.get("created_at_message_id") or "")
    if text.startswith(_MESSAGE_SORT_PREFIX):
        parts = text.split("#", 3)
        if len(parts) >= 3:
            return parts[2]
    if "#" in text:
        head = text.split("#", 1)[0]
        if not (head.isdigit() and len(head) == 10):
            return head
    return ""


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
        ConsistentRead=True,
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


def _message_sort_key(created_at: str, sequence: int, message_id: str) -> str:
    return (
        f"{_MESSAGE_SORT_PREFIX}{int(sequence):010d}#{created_at}#{message_id}"
    )


def _utc_now() -> datetime:
    provider = _UTC_NOW_PROVIDER
    if provider is not None:
        return provider()
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
        elif "M" in value:
            row[key] = _from_item(value["M"])
        elif "L" in value:
            row[key] = [
                _from_item(child["M"])
                if "M" in child
                else next(iter(child.values()), None)
                for child in value["L"]
            ]
    if "selected_case_id" in row and row["selected_case_id"] == "":
        row["selected_case_id"] = None
    return row
