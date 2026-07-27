"""Tests for DynamoDB-backed portal chat history."""

from __future__ import annotations

import sys
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline import case_chat_history as chat_history_module  # noqa: E402
from s3_notable_pipeline.case_chat_history import (  # noqa: E402
    ChatSessionExpiredError,
    ChatSessionNotFoundError,
    _UTC_NOW_PROVIDER,
    _get_message_item,
    delete_last_chat_turn,
    get_chat_session_messages,
    get_idempotent_chat_response,
    list_chat_sessions,
    normalize_stored_answer_status,
    persist_chat_history,
    truncate_stored_message,
)
from s3_notable_pipeline.config import Config  # noqa: E402


def history_config(**overrides: Any) -> Config:
    values = {
        "CASE_QA_CHAT_HISTORY_ENABLED": True,
        "CASE_QA_CHAT_HISTORY_RETENTION_DAYS": 30,
        "CASE_QA_MAX_SESSIONS_PER_USER": 10,
        "CASE_QA_MAX_MESSAGES_PER_SESSION": 30,
        "CASE_QA_MAX_STORED_MESSAGE_BYTES": 4000,
        "CHAT_SESSIONS_TABLE": "chat-sessions",
        "CHAT_MESSAGES_TABLE": "chat-messages",
    }
    values.update(overrides)
    return Config(**values)


def _ddb_str(value: str) -> dict[str, str]:
    return {"S": value}


def _ddb_num(value: int) -> dict[str, str]:
    return {"N": str(value)}


class ConditionalCheckFailedError(Exception):
    """Minimal stand-in for DynamoDB conditional failures."""


class FakeChatDynamoDbClient:
    """Minimal DynamoDB client for chat-history unit tests."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.messages: dict[tuple[str, str], dict[str, Any]] = {}
        self._session_lock = threading.Lock()

    def put_item(self, *, TableName: str, Item: dict[str, Any], **_kwargs: Any) -> None:
        if TableName.endswith("sessions"):
            session_id = Item["session_id"]["S"]
            self.sessions[session_id] = Item
            return
        session_id = Item["session_id"]["S"]
        sort_key = Item["created_at_message_id"]["S"]
        self.messages[(session_id, sort_key)] = Item

    def get_item(
        self,
        *,
        TableName: str,
        Key: dict[str, Any],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if TableName.endswith("sessions"):
            item = self.sessions.get(Key["session_id"]["S"])
            return {"Item": item} if item else {}
        item = self.messages.get((Key["session_id"]["S"], Key["created_at_message_id"]["S"]))
        return {"Item": item} if item else {}

    def update_item(
        self,
        *,
        TableName: str,
        Key: dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        ExpressionAttributeNames: dict[str, str] | None = None,
        ConditionExpression: str | None = None,
        ReturnValues: str | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if not TableName.endswith("sessions"):
            raise AssertionError("unexpected update target")
        session_id = Key["session_id"]["S"]
        with self._session_lock:
            item = dict(self.sessions[session_id])
            if ConditionExpression:
                self._assert_session_condition(
                    item=item,
                    condition=ConditionExpression,
                    values=ExpressionAttributeValues,
                    names=ExpressionAttributeNames or {},
                )
            old_item = dict(item)
            item = self._apply_session_update(
                item=item,
                update_expression=UpdateExpression,
                values=ExpressionAttributeValues,
                names=ExpressionAttributeNames or {},
            )
            self.sessions[session_id] = item
        if ReturnValues == "UPDATED_OLD":
            return {"Attributes": self._project_attributes(old_item, UpdateExpression, names=ExpressionAttributeNames or {})}
        return {}

    def _assert_session_condition(
        self,
        *,
        item: dict[str, Any],
        condition: str,
        values: dict[str, Any],
        names: dict[str, str],
    ) -> None:
        if "attribute_exists(session_id)" in condition and "session_id" not in item:
            raise ConditionalCheckFailedError("missing session")
        if condition == "attribute_not_exists(message_count)" and "message_count" in item:
            raise ConditionalCheckFailedError("message_count exists")
        if "attribute_not_exists(pending_turns)" in condition and "pending_turns" in item:
            raise ConditionalCheckFailedError("pending_turns exists")
        turn_name = names.get("#turn")
        if turn_name and "attribute_not_exists(pending_turns.#turn)" in condition:
            pending = item.get("pending_turns", {}).get("M", {})
            if turn_name in pending:
                raise ConditionalCheckFailedError("pending turn exists")
        if "message_count <= :maximum_before" in condition:
            current = int(item.get("message_count", {"N": "0"})["N"])
            maximum_before = int(values[":maximum_before"]["N"])
            if current > maximum_before:
                raise ConditionalCheckFailedError("message limit")
        if "message_count = :current" in condition and "message_count" in item:
            current = int(item["message_count"]["N"])
            expected = int(values[":current"]["N"])
            if current != expected:
                raise ConditionalCheckFailedError("message count changed")
        if "message_count = :observed" in condition:
            current = int(item.get("message_count", {"N": "0"})["N"])
            observed = int(values[":observed"]["N"])
            if current != observed:
                raise ConditionalCheckFailedError("message count changed")

    def _apply_session_update(
        self,
        *,
        item: dict[str, Any],
        update_expression: str,
        values: dict[str, Any],
        names: dict[str, str],
    ) -> dict[str, Any]:
        if update_expression.startswith("ADD message_count"):
            current = int(item.get("message_count", {"N": "0"})["N"])
            increment = int(values[":two"]["N"])
            item["message_count"] = {"N": str(current + increment)}
            return item
        if "SET message_count = if_not_exists(message_count, :current) + :two" in update_expression:
            current = int(item.get("message_count", {"N": values[":current"]["N"]})["N"])
            increment = int(values[":two"]["N"])
            item["message_count"] = {"N": str(current + increment)}
            if "pending_turns.#turn = :reserved" in update_expression:
                turn_name = names["#turn"]
                pending = dict(item.get("pending_turns", {"M": {}}).get("M", {}))
                pending[turn_name] = values[":reserved"]
                item["pending_turns"] = {"M": pending}
            return item
        if update_expression.startswith("SET message_count = message_count - :two"):
            current = int(item["message_count"]["N"])
            decrement = int(values[":two"]["N"])
            item["message_count"] = {"N": str(current - decrement)}
            turn_name = names["#turn"]
            pending = dict(item.get("pending_turns", {"M": {}}).get("M", {}))
            pending.pop(turn_name, None)
            item["pending_turns"] = {"M": pending}
            return item
        if update_expression == "SET pending_turns = :empty":
            item["pending_turns"] = values[":empty"]
            return item
        if update_expression.startswith("SET message_count = :counted"):
            item["message_count"] = values[":counted"]
            return item
        for key, value in values.items():
            field = {
                ":updated_at": "updated_at",
                ":updated_sort": "updated_at_session_id",
                ":expires_at": "expires_at",
                ":expires_at_epoch": "expires_at_epoch",
            }.get(key)
            if field:
                item[field] = value
        return item

    def _project_attributes(
        self,
        item: dict[str, Any],
        update_expression: str,
        *,
        names: dict[str, str],
    ) -> dict[str, Any]:
        if update_expression.startswith("ADD message_count"):
            if "message_count" in item:
                return {"message_count": item["message_count"]}
            return {}
        if "SET message_count = if_not_exists(message_count, :current) + :two" in update_expression:
            return {"message_count": item.get("message_count", {"N": "0"})}
        return {}

    def delete_item(self, *, TableName: str, Key: dict[str, Any], **_kwargs: Any) -> None:
        if TableName.endswith("sessions"):
            self.sessions.pop(Key["session_id"]["S"], None)
            return
        self.messages.pop((Key["session_id"]["S"], Key["created_at_message_id"]["S"]), None)

    def query(self, *, TableName: str, **_kwargs: Any) -> dict[str, Any]:
        if TableName.endswith("sessions"):
            user_id = _kwargs["ExpressionAttributeValues"][":user_id"]["S"]
            now_epoch = int(_kwargs["ExpressionAttributeValues"][":now_epoch"]["N"])
            items = [
                item
                for item in self.sessions.values()
                if item["user_id"]["S"] == user_id
                and int(item["expires_at_epoch"]["N"]) > now_epoch
            ]
            reverse = not _kwargs.get("ScanIndexForward", True)
            items.sort(
                key=lambda item: item["updated_at_session_id"]["S"],
                reverse=reverse,
            )
            limit = _kwargs.get("Limit")
            if limit is not None:
                items = items[: int(limit)]
            return {"Items": items}
        session_id = _kwargs["ExpressionAttributeValues"][":session_id"]["S"]
        items = [
            item
            for (stored_session_id, _), item in self.messages.items()
            if stored_session_id == session_id
        ]
        items.sort(key=lambda item: item["created_at_message_id"]["S"])
        if _kwargs.get("Select") == "COUNT":
            return {"Count": len(items)}
        start_key = _kwargs.get("ExclusiveStartKey")
        if start_key is not None:
            start_sort = start_key["created_at_message_id"]["S"]
            items = [
                item
                for item in items
                if item["created_at_message_id"]["S"] > start_sort
            ]
        limit = _kwargs.get("Limit")
        if limit is not None:
            page_items = items[: int(limit)]
            has_more = len(items) > int(limit)
        else:
            page_items = items
            has_more = False
        filtered = self._apply_message_filter(page_items, _kwargs)
        result: dict[str, Any] = {"Items": filtered}
        if has_more and page_items:
            last = page_items[-1]
            result["LastEvaluatedKey"] = {
                "session_id": last["session_id"],
                "created_at_message_id": last["created_at_message_id"],
            }
        return result

    @staticmethod
    def _apply_message_filter(items: list[dict[str, Any]], query_kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        filter_expression = query_kwargs.get("FilterExpression")
        if filter_expression == "message_id = :message_id":
            target = query_kwargs["ExpressionAttributeValues"][":message_id"]["S"]
            return [item for item in items if item.get("message_id", {}).get("S") == target]
        return items


class CaseChatHistoryTests(unittest.TestCase):
    """Chat history persistence behavior."""

    def test_truncate_stored_message_respects_utf8_byte_budget(self) -> None:
        text = "café" * 2000
        truncated = truncate_stored_message(text, 10)
        self.assertLessEqual(len(truncated.encode("utf-8")), 10)

    def test_normalize_stored_answer_status_accepts_bounded_values(self) -> None:
        self.assertEqual(normalize_stored_answer_status("answered"), "answered")
        self.assertEqual(
            normalize_stored_answer_status("insufficient_context"),
            "insufficient_context",
        )
        self.assertIsNone(normalize_stored_answer_status("unexpected"))

    def test_persist_chat_history_creates_session_and_messages(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="What happened?",
            selected_case_id="case-1",
            requested_session_id=None,
            user_id="user-1",
            response={"answer": "Suspicious login.", "answer_status": "answered"},
        )
        self.assertTrue(session_id)
        payload = get_chat_session_messages(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
        )
        self.assertEqual(payload["mode"], "selected_case")
        self.assertEqual(payload["selected_case_id"], "case-1")
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(payload["messages"][1]["answer_status"], "answered")

    def test_list_chat_sessions_returns_user_sessions(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="Question one",
            selected_case_id="case-1",
            requested_session_id=None,
            user_id="user-1",
            response={"answer": "Answer one", "answer_status": "answered"},
        )
        items = list_chat_sessions(
            config=config,
            dynamodb_client=client,
            user_id="user-1",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["mode"], "selected_case")

    def test_delete_last_chat_turn_removes_latest_pair(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="First question",
            selected_case_id="case-1",
            requested_session_id=None,
            user_id="user-1",
            response={"answer": "First answer", "answer_status": "answered"},
        )
        persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="Second question",
            selected_case_id="case-1",
            requested_session_id=session_id,
            user_id="user-1",
            response={"answer": "Second answer", "answer_status": "answered"},
        )
        deleted = delete_last_chat_turn(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
        )
        self.assertEqual(deleted, 2)
        payload = get_chat_session_messages(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
        )
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["messages"][0]["content"], "First question")

    def test_delete_last_chat_turn_with_repeated_timestamp(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        fixed_now = datetime.now(timezone.utc)
        original_provider = _UTC_NOW_PROVIDER
        try:
            chat_history_module._UTC_NOW_PROVIDER = lambda: fixed_now
            session_id = persist_chat_history(
                config=config,
                dynamodb_client=client,
                mode="selected_case",
                question="First question",
                selected_case_id="case-1",
                requested_session_id=None,
                user_id="user-1",
                response={"answer": "First answer", "answer_status": "answered"},
            )
            persist_chat_history(
                config=config,
                dynamodb_client=client,
                mode="selected_case",
                question="Second question",
                selected_case_id="case-1",
                requested_session_id=session_id,
                user_id="user-1",
                response={"answer": "Second answer", "answer_status": "answered"},
            )
            deleted = delete_last_chat_turn(
                config=config,
                dynamodb_client=client,
                session_id=session_id,
                user_id="user-1",
            )
            payload = get_chat_session_messages(
                config=config,
                dynamodb_client=client,
                session_id=session_id,
                user_id="user-1",
            )
        finally:
            chat_history_module._UTC_NOW_PROVIDER = original_provider

        self.assertEqual(deleted, 2)
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["messages"][0]["content"], "First question")
        self.assertEqual(payload["messages"][1]["content"], "First answer")

    def test_expired_session_is_rejected(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = str(uuid.uuid4())
        expired_epoch = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
        client.sessions[session_id] = {
            "session_id": _ddb_str(session_id),
            "user_id": _ddb_str("user-1"),
            "mode": _ddb_str("selected_case"),
            "selected_case_id": _ddb_str("case-1"),
            "expires_at_epoch": _ddb_num(expired_epoch),
        }
        with self.assertRaises(ChatSessionExpiredError):
            get_chat_session_messages(
                config=config,
                dynamodb_client=client,
                session_id=session_id,
                user_id="user-1",
            )

    def test_missing_session_raises_not_found(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        with self.assertRaises(ChatSessionNotFoundError):
            get_chat_session_messages(
                config=config,
                dynamodb_client=client,
                session_id="00000000-0000-0000-0000-000000000001",
                user_id="user-1",
            )

    def test_client_request_id_is_idempotent(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        kwargs = {
            "config": config,
            "dynamodb_client": client,
            "mode": "selected_case",
            "question": "What happened?",
            "selected_case_id": "case-1",
            "requested_session_id": None,
            "user_id": "user-1",
            "response": {"answer": "Suspicious login.", "answer_status": "answered"},
            "client_request_id": "request-0001",
        }
        first = persist_chat_history(**kwargs)
        second = persist_chat_history(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(
            len(
                get_chat_session_messages(
                    config=config,
                    dynamodb_client=client,
                    session_id=first,
                    user_id="user-1",
                )["messages"]
            ),
            2,
        )

    def test_get_message_item_paginates_with_limit_before_filter(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        decoy_id = str(uuid.uuid4())
        client.messages[(session_id, f"{created_at}#{decoy_id}")] = {
            "session_id": _ddb_str(session_id),
            "created_at_message_id": _ddb_str(f"{created_at}#{decoy_id}"),
            "message_id": _ddb_str(decoy_id),
            "role": _ddb_str("user"),
            "content": _ddb_str("decoy"),
            "created_at": _ddb_str(created_at),
        }
        target_turn = str(uuid.uuid4())
        target_message_id = f"turn#{target_turn}#assistant"
        client.messages[(session_id, f"s#0000000001#{created_at}#{target_message_id}")] = {
            "session_id": _ddb_str(session_id),
            "created_at_message_id": _ddb_str(
                f"s#0000000001#{created_at}#{target_message_id}"
            ),
            "message_id": _ddb_str(target_message_id),
            "role": _ddb_str("assistant"),
            "content": _ddb_str("found me"),
            "created_at": _ddb_str(created_at),
        }
        item = _get_message_item(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            turn_id=target_turn,
            role="assistant",
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["content"]["S"], "found me")

    def test_client_request_id_idempotent_after_many_prior_messages(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="Seed question",
            selected_case_id="case-1",
            requested_session_id=None,
            user_id="user-1",
            response={"answer": "Seed answer", "answer_status": "answered"},
        )
        for index in range(6):
            persist_chat_history(
                config=config,
                dynamodb_client=client,
                mode="selected_case",
                question=f"Follow-up {index}",
                selected_case_id="case-1",
                requested_session_id=session_id,
                user_id="user-1",
                response={"answer": f"Answer {index}", "answer_status": "answered"},
            )
        kwargs = {
            "config": config,
            "dynamodb_client": client,
            "mode": "selected_case",
            "question": "Retry question",
            "selected_case_id": "case-1",
            "requested_session_id": session_id,
            "user_id": "user-1",
            "response": {"answer": "Retry answer", "answer_status": "answered"},
            "client_request_id": "request-retry-01",
        }
        session_after_first = persist_chat_history(**kwargs)
        session_after_second = persist_chat_history(**kwargs)
        self.assertEqual(session_after_first, session_after_second)
        payload = get_chat_session_messages(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
        )
        self.assertEqual(len(payload["messages"]), 16)
        cached = get_idempotent_chat_response(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            selected_case_id="case-1",
            question="Retry question",
            requested_session_id=session_id,
            user_id="user-1",
            client_request_id="request-retry-01",
        )
        self.assertEqual(cached["answer"], "Retry answer")

    def test_mixed_legacy_and_new_message_order(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = str(uuid.uuid4())
        expires_epoch = int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
        client.sessions[session_id] = {
            "session_id": _ddb_str(session_id),
            "user_id": _ddb_str("user-1"),
            "mode": _ddb_str("selected_case"),
            "selected_case_id": _ddb_str("case-1"),
            "expires_at_epoch": _ddb_num(expires_epoch),
            "message_count": _ddb_num(2),
        }
        legacy_created = "2026-01-01T00:00:00+00:00"
        legacy_user_id = str(uuid.uuid4())
        legacy_assistant_id = str(uuid.uuid4())
        client.messages[(session_id, f"{legacy_created}#{legacy_user_id}")] = {
            "session_id": _ddb_str(session_id),
            "created_at_message_id": _ddb_str(f"{legacy_created}#{legacy_user_id}"),
            "message_id": _ddb_str(legacy_user_id),
            "role": _ddb_str("user"),
            "content": _ddb_str("legacy question"),
            "created_at": _ddb_str(legacy_created),
        }
        client.messages[
            (session_id, f"{legacy_created}#{legacy_assistant_id}")
        ] = {
            "session_id": _ddb_str(session_id),
            "created_at_message_id": _ddb_str(f"{legacy_created}#{legacy_assistant_id}"),
            "message_id": _ddb_str(legacy_assistant_id),
            "role": _ddb_str("assistant"),
            "content": _ddb_str("legacy answer"),
            "created_at": _ddb_str(legacy_created),
        }
        persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="new question",
            selected_case_id="case-1",
            requested_session_id=session_id,
            user_id="user-1",
            response={"answer": "new answer", "answer_status": "answered"},
        )
        payload = get_chat_session_messages(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
        )
        contents = [message["content"] for message in payload["messages"]]
        self.assertEqual(
            contents,
            ["legacy question", "legacy answer", "new question", "new answer"],
        )

    def test_delete_last_chat_turn_on_mixed_legacy_and_new_session(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = str(uuid.uuid4())
        expires_epoch = int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
        client.sessions[session_id] = {
            "session_id": _ddb_str(session_id),
            "user_id": _ddb_str("user-1"),
            "mode": _ddb_str("selected_case"),
            "selected_case_id": _ddb_str("case-1"),
            "expires_at_epoch": _ddb_num(expires_epoch),
            "message_count": _ddb_num(2),
        }
        legacy_created = "2026-01-01T00:00:00+00:00"
        legacy_user_id = str(uuid.uuid4())
        legacy_assistant_id = str(uuid.uuid4())
        client.messages[(session_id, f"{legacy_created}#{legacy_user_id}")] = {
            "session_id": _ddb_str(session_id),
            "created_at_message_id": _ddb_str(f"{legacy_created}#{legacy_user_id}"),
            "message_id": _ddb_str(legacy_user_id),
            "role": _ddb_str("user"),
            "content": _ddb_str("legacy question"),
            "created_at": _ddb_str(legacy_created),
        }
        client.messages[
            (session_id, f"{legacy_created}#{legacy_assistant_id}")
        ] = {
            "session_id": _ddb_str(session_id),
            "created_at_message_id": _ddb_str(f"{legacy_created}#{legacy_assistant_id}"),
            "message_id": _ddb_str(legacy_assistant_id),
            "role": _ddb_str("assistant"),
            "content": _ddb_str("legacy answer"),
            "created_at": _ddb_str(legacy_created),
        }
        persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="new question",
            selected_case_id="case-1",
            requested_session_id=session_id,
            user_id="user-1",
            response={"answer": "new answer", "answer_status": "answered"},
        )
        deleted = delete_last_chat_turn(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
        )
        self.assertEqual(deleted, 2)
        payload = get_chat_session_messages(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
        )
        contents = [message["content"] for message in payload["messages"]]
        self.assertEqual(contents, ["legacy question", "legacy answer"])

    def test_back_to_back_sequence_allocation_is_monotonic(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="First question",
            selected_case_id="case-1",
            requested_session_id=None,
            user_id="user-1",
            response={"answer": "First answer", "answer_status": "answered"},
        )
        persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="Second question",
            selected_case_id="case-1",
            requested_session_id=session_id,
            user_id="user-1",
            response={"answer": "Second answer", "answer_status": "answered"},
        )
        sequences = sorted(
            int(item["message_sequence"]["N"])
            for item in client.messages.values()
            if item["session_id"]["S"] == session_id
        )
        self.assertEqual(sequences, [0, 1, 2, 3])

    def test_concurrent_sequence_allocation_allows_harmless_gaps(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="Seed",
            selected_case_id="case-1",
            requested_session_id=None,
            user_id="user-1",
            response={"answer": "Seed answer", "answer_status": "answered"},
        )
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []
        sequences: list[int] = []
        lock = threading.Lock()

        def worker(question: str) -> None:
            try:
                barrier.wait(timeout=5)
                persist_chat_history(
                    config=config,
                    dynamodb_client=client,
                    mode="selected_case",
                    question=question,
                    selected_case_id="case-1",
                    requested_session_id=session_id,
                    user_id="user-1",
                    response={"answer": question, "answer_status": "answered"},
                )
                with lock:
                    for item in client.messages.values():
                        if item["session_id"]["S"] != session_id:
                            continue
                        if item["role"]["S"] != "user":
                            continue
                        if item["content"]["S"] == question:
                            sequences.append(int(item["message_sequence"]["N"]))
            except BaseException as exc:  # pragma: no cover - surfaced via errors list
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=("Concurrent A",)),
            threading.Thread(target=worker, args=("Concurrent B",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(len(sequences), 2)
        self.assertEqual(sorted(sequences), [2, 4])
        payload = get_chat_session_messages(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
        )
        self.assertEqual(len(payload["messages"]), 6)

    def test_pending_turn_retry_reuses_original_sequence_after_later_reservation(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="Seed",
            selected_case_id="case-1",
            requested_session_id=None,
            user_id="user-1",
            response={"answer": "Seed answer", "answer_status": "answered"},
        )
        client.transact_write_items = lambda **_kwargs: None  # type: ignore[attr-defined]

        first = chat_history_module._reserve_turn_capacity(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
            mode="selected_case",
            selected_case_id="case-1",
            turn_id="turn-a",
        )
        second = chat_history_module._reserve_turn_capacity(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
            mode="selected_case",
            selected_case_id="case-1",
            turn_id="turn-b",
        )
        first_retry = chat_history_module._reserve_turn_capacity(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
            user_id="user-1",
            mode="selected_case",
            selected_case_id="case-1",
            turn_id="turn-a",
        )

        self.assertEqual(first, (True, 2))
        self.assertEqual(second, (True, 4))
        self.assertEqual(first_retry, first)

    def test_stale_zero_message_count_is_reconciled_before_allocation(self) -> None:
        config = history_config()
        client = FakeChatDynamoDbClient()
        session_id = persist_chat_history(
            config=config,
            dynamodb_client=client,
            mode="selected_case",
            question="Existing question",
            selected_case_id="case-1",
            requested_session_id=None,
            user_id="user-1",
            response={"answer": "Existing answer", "answer_status": "answered"},
        )
        client.sessions[session_id]["message_count"] = {"N": "0"}

        allocated = chat_history_module._allocate_turn_sequences(
            config=config,
            dynamodb_client=client,
            session_id=session_id,
        )

        self.assertEqual(allocated, (2, 3))
        self.assertEqual(client.sessions[session_id]["message_count"], {"N": "4"})


if __name__ == "__main__":
    unittest.main()
