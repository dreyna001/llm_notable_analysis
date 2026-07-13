"""Cosmos-backed portal chat ownership, retention, and limit behavior."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from azure_notable_pipeline.case_chat_history import (
    ChatSessionExpiredError,
    ChatSessionNotFoundError,
    delete_last_chat_turn,
    get_chat_session_messages,
    list_chat_sessions,
    persist_chat_history,
    truncate_stored_message,
    validate_chat_history_request,
)
from azure_notable_pipeline.config import Config
from azure_notable_pipeline.cosmos_store import CreateOutcome


class FakeChatStore:
    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.messages: dict[str, dict[str, dict]] = {}

    def create_chat_session(self, _container, item):
        session_id = item["session_id"]
        if session_id in self.sessions:
            return CreateOutcome(created=False)
        self.sessions[session_id] = dict(item)
        return CreateOutcome(created=True, item=dict(item))

    def upsert_chat_session(self, _container, item):
        self.sessions[item["session_id"]] = dict(item)
        return dict(item)

    def get_chat_session(self, _container, *, session_id, user_id):
        item = self.sessions.get(session_id)
        if item is None or item["user_id"] != user_id:
            return None
        return dict(item)

    def list_chat_sessions(
        self,
        _container,
        *,
        user_id,
        now_epoch,
        limit,
        oldest_first=False,
    ):
        rows = [
            dict(row)
            for row in self.sessions.values()
            if row["user_id"] == user_id and row["expires_at_epoch"] > now_epoch
        ]
        rows.sort(key=lambda row: (row["updated_at"], row["session_id"]), reverse=not oldest_first)
        return rows[:limit]

    def delete_chat_session(self, _container, *, session_id, user_id):
        item = self.sessions.get(session_id)
        if item is None or item["user_id"] != user_id:
            return False
        del self.sessions[session_id]
        return True

    def create_chat_message(self, _container, item):
        session = self.messages.setdefault(item["session_id"], {})
        if item["message_id"] in session:
            return CreateOutcome(created=False)
        session[item["message_id"]] = dict(item)
        return CreateOutcome(created=True, item=dict(item))

    def list_chat_messages(self, _container, *, session_id, limit):
        rows = list(self.messages.get(session_id, {}).values())
        rows.sort(key=lambda row: (row["created_at"], row["message_id"]))
        return [dict(row) for row in rows[:limit]]

    def delete_chat_message(self, _container, *, session_id, message_id):
        return self.messages.get(session_id, {}).pop(message_id, None) is not None

    def delete_chat_messages(self, _container, *, session_id, limit):
        rows = self.list_chat_messages(_container, session_id=session_id, limit=limit)
        for row in rows:
            self.delete_chat_message(
                _container,
                session_id=session_id,
                message_id=row["message_id"],
            )
        return len(rows)


def history_config(**overrides) -> Config:
    values = {
        "CASE_QA_CHAT_HISTORY_ENABLED": True,
        "CASE_QA_CHAT_HISTORY_RETENTION_DAYS": 30,
        "CASE_QA_MAX_SESSIONS_PER_USER": 10,
        "CASE_QA_MAX_MESSAGES_PER_SESSION": 30,
        "CASE_QA_MAX_STORED_MESSAGE_BYTES": 4_000,
        "CHAT_SESSIONS_CONTAINER": "chat-sessions",
        "CHAT_MESSAGES_CONTAINER": "chat-messages",
    }
    values.update(overrides)
    return Config(**values)


def persist(store: FakeChatStore, config: Config, *, user: str, session_id=None) -> str:
    return persist_chat_history(
        config=config,
        cosmos_store=store,
        mode="selected_case",
        question="What happened?",
        selected_case_id="case-1",
        requested_session_id=session_id,
        user_id=user,
        response={"answer": "Suspicious login.", "answer_status": "answered"},
    )


def test_persist_and_read_session_keeps_public_message_contract() -> None:
    store = FakeChatStore()
    config = history_config()
    session_id = persist(store, config, user="user-1")
    payload = get_chat_session_messages(
        config=config,
        cosmos_store=store,
        session_id=session_id,
        user_id="user-1",
    )
    assert payload["mode"] == "selected_case"
    assert payload["selected_case_id"] == "case-1"
    assert [message["role"] for message in payload["messages"]] == ["user", "assistant"]
    assert payload["messages"][1]["answer_status"] == "answered"


def test_session_ownership_isolated_by_authenticated_user() -> None:
    store = FakeChatStore()
    config = history_config()
    session_id = persist(store, config, user="user-1")
    with pytest.raises(ChatSessionNotFoundError):
        get_chat_session_messages(
            config=config,
            cosmos_store=store,
            session_id=session_id,
            user_id="user-2",
        )


def test_expired_session_cannot_be_reused() -> None:
    store = FakeChatStore()
    config = history_config()
    session_id = persist(store, config, user="user-1")
    store.sessions[session_id]["expires_at_epoch"] = int(
        datetime.now(timezone.utc).timestamp()
    ) - 1
    with pytest.raises(ChatSessionExpiredError):
        validate_chat_history_request(
            config=config,
            cosmos_store=store,
            mode="selected_case",
            selected_case_id="case-1",
            requested_session_id=session_id,
            user_id="user-1",
        )


def test_message_limit_checked_before_model_request() -> None:
    store = FakeChatStore()
    config = history_config(CASE_QA_MAX_MESSAGES_PER_SESSION=2)
    session_id = persist(store, config, user="user-1")
    with pytest.raises(ValueError, match="message limit"):
        validate_chat_history_request(
            config=config,
            cosmos_store=store,
            mode="selected_case",
            selected_case_id="case-1",
            requested_session_id=session_id,
            user_id="user-1",
        )


def test_session_cap_prunes_oldest_session_and_messages() -> None:
    store = FakeChatStore()
    config = history_config(CASE_QA_MAX_SESSIONS_PER_USER=1)
    first_id = persist(store, config, user="user-1")
    second_id = persist(store, config, user="user-1")
    assert first_id != second_id
    assert first_id not in store.sessions
    assert store.messages.get(first_id, {}) == {}
    assert [item["session_id"] for item in list_chat_sessions(
        config=config,
        cosmos_store=store,
        user_id="user-1",
    )] == [second_id]


def test_delete_last_turn_removes_latest_pair() -> None:
    store = FakeChatStore()
    config = history_config()
    session_id = persist(store, config, user="user-1")
    persist(store, config, user="user-1", session_id=session_id)
    assert delete_last_chat_turn(
        config=config,
        cosmos_store=store,
        session_id=session_id,
        user_id="user-1",
    ) == 2
    assert len(store.messages[session_id]) == 2


def test_utf8_storage_truncation_never_splits_codepoint() -> None:
    clipped = truncate_stored_message("café" * 2_000, 10)
    assert len(clipped.encode("utf-8")) <= 10
