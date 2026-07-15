"""Tests for DynamoDB-backed portal chat history."""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.case_chat_history import (  # noqa: E402
    ChatSessionExpiredError,
    ChatSessionNotFoundError,
    delete_last_chat_turn,
    get_chat_session_messages,
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


class FakeChatDynamoDbClient:
    """Minimal DynamoDB client for chat-history unit tests."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.messages: dict[tuple[str, str], dict[str, Any]] = {}

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
        **_kwargs: Any,
    ) -> None:
        if not TableName.endswith("sessions"):
            raise AssertionError("unexpected update target")
        item = dict(self.sessions[Key["session_id"]["S"]])
        for key, value in ExpressionAttributeValues.items():
            field = {
                ":updated_at": "updated_at",
                ":updated_sort": "updated_at_session_id",
                ":expires_at": "expires_at",
                ":expires_at_epoch": "expires_at_epoch",
            }[key]
            item[field] = value
        self.sessions[Key["session_id"]["S"]] = item

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
        return {"Items": items}

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


if __name__ == "__main__":
    unittest.main()
