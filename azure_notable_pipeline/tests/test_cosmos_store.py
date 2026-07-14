"""Offline tests for the native Cosmos persistence boundary."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from azure_notable_pipeline.case_chat_history import (
    ChatSessionNotFoundError,
    get_chat_session_messages,
    list_chat_sessions,
    persist_chat_history,
)
from azure_notable_pipeline.case_index import list_cases
from azure_notable_pipeline.config import Config
from azure_notable_pipeline.cosmos_store import (
    CONTAINER_PARTITION_KEYS,
    ConditionalOutcome,
    CosmosStore,
    ttl_from_expiry,
)
from azure_notable_pipeline.idempotency import (
    begin_side_effect,
    complete_side_effect_success,
    release_side_effect_lock,
)
from azure_notable_pipeline.servicenow_disposition_sync import run_disposition_sync


class FakeCosmosError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Cosmos HTTP {status_code}")


class FakeContainer:
    def __init__(self, name: str, partition_field: str) -> None:
        self.name = name
        self.partition_field = partition_field
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.query_calls: list[dict[str, Any]] = []
        self._etag_counter = 0

    def _etagged(self, body: dict[str, Any]) -> dict[str, Any]:
        self._etag_counter += 1
        result = dict(body)
        result["_etag"] = f'etag-{self._etag_counter}'
        return result

    def _key(self, body: dict[str, Any]) -> tuple[str, str]:
        return str(body[self.partition_field]), str(body["id"])

    @staticmethod
    def _hook(kwargs: dict[str, Any], charge: str = "2.5") -> None:
        hook = kwargs.get("response_hook")
        if hook:
            hook({"x-ms-request-charge": charge}, None)

    def create_item(self, *, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self._hook(kwargs)
        key = self._key(body)
        if key in self.items:
            raise FakeCosmosError(409)
        result = self._etagged(body)
        self.items[key] = result
        return dict(result)

    def read_item(self, *, item: str, partition_key: str, **kwargs: Any) -> dict[str, Any]:
        self._hook(kwargs, "1.0")
        result = self.items.get((str(partition_key), str(item)))
        if result is None:
            raise FakeCosmosError(404)
        return dict(result)

    def upsert_item(self, *, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self._hook(kwargs)
        result = self._etagged(body)
        self.items[self._key(result)] = result
        return dict(result)

    def replace_item(
        self,
        *,
        item: str,
        body: dict[str, Any],
        etag: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._hook(kwargs)
        key = self._key(body)
        current = self.items.get(key)
        if current is None:
            raise FakeCosmosError(404)
        if current["_etag"] != etag:
            raise FakeCosmosError(412)
        result = self._etagged(body)
        self.items[key] = result
        return dict(result)

    def delete_item(self, *, item: str, partition_key: str, etag: str | None = None, **kwargs: Any) -> None:
        self._hook(kwargs)
        key = (str(partition_key), str(item))
        current = self.items.get(key)
        if current is None:
            raise FakeCosmosError(404)
        if etag is not None and current["_etag"] != etag:
            raise FakeCosmosError(412)
        del self.items[key]

    def query_items(self, **kwargs: Any):
        self._hook(kwargs, "4.75")
        self.query_calls.append(dict(kwargs))
        params = {entry["name"]: entry["value"] for entry in kwargs["parameters"]}
        rows = [dict(item) for item in self.items.values()]
        query = kwargs["query"]
        if "c.user_id = @user_id" in query:
            rows = [
                row for row in rows
                if row["user_id"] == params["@user_id"]
                and row["expires_at_epoch"] > params["@now_epoch"]
            ]
            reverse = " DESC" in query
            rows.sort(key=lambda row: (row["updated_at"], row["session_id"]), reverse=reverse)
        elif "c.session_id = @session_id" in query:
            rows = [row for row in rows if row["session_id"] == params["@session_id"]]
            rows.sort(key=lambda row: (row["created_at"], row["message_id"]))
        elif "c.correlation_id = @correlation_id" in query:
            rows = [row for row in rows if row.get("correlation_id") == params["@correlation_id"]]
            rows.sort(key=lambda row: (row["processed_at"], row["case_id"]), reverse=True)
        elif "ORDER BY c.processed_at" in query:
            before = (params.get("@processed_at"), params.get("@case_id"))
            if before[0] is not None:
                rows = [row for row in rows if (row["processed_at"], row["case_id"]) < before]
            rows.sort(key=lambda row: (row["processed_at"], row["case_id"]), reverse=True)
        return rows[: int(params["@limit"])]


class FakeDatabase:
    def __init__(self) -> None:
        fields = {
            "idem": "id",
            "cases": "case_id",
            "dispositions": "snow_sys_id",
            "sync": "job_name",
            "sessions": "user_id",
            "messages": "session_id",
        }
        self.containers = {name: FakeContainer(name, field) for name, field in fields.items()}

    def get_container_client(self, name: str) -> FakeContainer:
        return self.containers[name]


def _store(*, now: int = 2_000_000_000) -> tuple[CosmosStore, FakeDatabase]:
    database = FakeDatabase()
    return CosmosStore(database, clock=lambda: now), database


def _history_config(**overrides: Any) -> Config:
    values = {
        "CASE_QA_CHAT_HISTORY_ENABLED": True,
        "CASE_QA_CHAT_HISTORY_RETENTION_DAYS": 30,
        "CASE_QA_MAX_SESSIONS_PER_USER": 2,
        "CASE_QA_MAX_MESSAGES_PER_SESSION": 6,
        "CASE_QA_MAX_STORED_MESSAGE_BYTES": 4000,
        "CHAT_SESSIONS_CONTAINER": "sessions",
        "CHAT_MESSAGES_CONTAINER": "messages",
    }
    values.update(overrides)
    return Config(**values)


def test_container_partition_keys_match_native_aggregate_contract() -> None:
    assert CONTAINER_PARTITION_KEYS == {
        "side_effect_idempotency": "/id",
        "case_index": "/case_id",
        "disposition": "/snow_sys_id",
        "disposition_sync_state": "/job_name",
        "chat_sessions": "/user_id",
        "chat_messages": "/session_id",
    }


def test_ttl_is_derived_from_business_expiry() -> None:
    store, database = _store(now=1000)
    store.upsert_case(
        "cases",
        {"case_id": "case-1", "processed_at": "2026-01-01T00:00:00Z", "expires_at_epoch": 1300},
    )
    assert ttl_from_expiry(1300, now_epoch=1000) == 300
    assert database.containers["cases"].items[("case-1", "case-1")]["ttl"] == 300


def test_native_create_conflict_and_etag_precondition_are_typed_outcomes() -> None:
    store, _ = _store()
    first = store.create_if_absent("idem", {"id": "lock-1", "expires_at": 2_000_000_100})
    duplicate = store.create_if_absent("idem", {"id": "lock-1", "expires_at": 2_000_000_100})
    stale = store.replace_if_match("idem", first.item or {}, expected_etag="wrong")
    assert first.created is True
    assert duplicate.created is False
    assert (stale.applied, stale.outcome) == (False, "precondition_failed")


def test_case_listing_uses_bounded_keyset_and_logs_charge(caplog: pytest.LogCaptureFixture) -> None:
    store, database = _store()
    for case_id, processed_at in (("c", "2026-01-03Z"), ("b", "2026-01-02Z"), ("a", "2026-01-01Z")):
        store.upsert_case("cases", {"case_id": case_id, "processed_at": processed_at})
    caplog.set_level(logging.INFO, logger="azure_notable_pipeline.cosmos_store")
    rows = store.list_cases("cases", limit=2, before=("2026-01-03Z", "c"))
    call = database.containers["cases"].query_calls[-1]
    assert [row["case_id"] for row in rows] == ["b", "a"]
    assert call["enable_cross_partition_query"] is True
    assert call["max_item_count"] == 2
    assert "continuation" not in repr(call).lower()
    assert "request_charge=4.75" in caplog.text


def test_case_listing_applies_filters_in_parameterized_cosmos_query() -> None:
    store, database = _store()
    store.list_cases(
        "cases",
        limit=10,
        start_date="2026-07-01T00:00:00Z",
        end_date="2026-07-14T23:59:59Z",
        verdict="Likely_True_Positive",
        search_name="Suspicious Login",
    )
    call = database.containers["cases"].query_calls[-1]
    query = call["query"]
    params = {entry["name"]: entry["value"] for entry in call["parameters"]}
    assert "c.processed_at >= @start_date" in query
    assert "c.processed_at <= @end_date" in query
    assert "LOWER(c.verdict) = @verdict" in query
    assert "CONTAINS(LOWER(c.search_name), @search_name)" in query
    assert params["@verdict"] == "likely_true_positive"
    assert params["@search_name"] == "suspicious login"


def test_public_case_filters_validate_dates_before_query() -> None:
    store, _ = _store()
    config = Config(CASE_INDEX_CONTAINER="cases")
    with pytest.raises(ValueError, match="start_date"):
        list_cases(config=config, cosmos_store=store, start_date="not-a-date")
    with pytest.raises(ValueError, match="must not be after"):
        list_cases(
            config=config,
            cosmos_store=store,
            start_date="2026-07-15",
            end_date="2026-07-14",
        )


def test_public_case_pagination_returns_keyset_not_cosmos_continuation() -> None:
    store, _ = _store()
    for case_id, processed_at in (("c", "2026-01-03Z"), ("b", "2026-01-02Z"), ("a", "2026-01-01Z")):
        store.upsert_case("cases", {"case_id": case_id, "processed_at": processed_at})
    config = Config(CASE_INDEX_CONTAINER="cases", PORTAL_PAGE_SIZE=2)
    first = list_cases(config=config, cosmos_store=store)
    cursor = base64.urlsafe_b64encode(json.dumps(first["next_cursor"]).encode()).decode()
    second = list_cases(config=config, cosmos_store=store, cursor=cursor)
    assert [row["case_id"] for row in first["items"]] == ["c", "b"]
    assert [row["case_id"] for row in second["items"]] == ["a"]
    assert set(first["next_cursor"]) == {"processed_at", "case_id"}


def test_idempotency_duplicate_completion_and_release_use_native_outcomes() -> None:
    store, database = _store(now=int(datetime.now(timezone.utc).timestamp()))
    config = Config(
        SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
        SIDE_EFFECT_IDEMPOTENCY_CONTAINER="idem",
        SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS=30,
    )
    reservation = begin_side_effect(
        config,
        operation="splunk_notable_update",
        key="finding-1",
        client=store,
    )
    duplicate = begin_side_effect(
        config,
        operation="splunk_notable_update",
        key="finding-1",
        client=store,
    )
    assert reservation.should_execute is True
    assert duplicate.should_execute is False
    assert duplicate.existing_marker["status"] == "in_progress"
    assert complete_side_effect_success(reservation, metadata={"finding_id": "finding-1"}) is True
    release_side_effect_lock(reservation)
    assert len(database.containers["idem"].items) == 1


def test_stale_idempotency_lock_is_reclaimed_without_old_owner_deleting_new_lock() -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    store, database = _store(now=now)
    config = Config(
        SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
        SIDE_EFFECT_IDEMPOTENCY_CONTAINER="idem",
        SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS=1,
    )
    old = begin_side_effect(config, operation="writeback", key="finding-2", client=store)
    key = next(iter(database.containers["idem"].items))
    database.containers["idem"].items[key]["started_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat()
    reclaimed = begin_side_effect(config, operation="writeback", key="finding-2", client=store)
    assert reclaimed.should_execute is True
    assert reclaimed.etag != old.etag
    release_side_effect_lock(old)
    assert len(database.containers["idem"].items) == 1


def test_chat_history_enforces_partition_ownership_and_prunes_oldest_session() -> None:
    store, _ = _store(now=int(datetime.now(timezone.utc).timestamp()))
    config = _history_config()
    first = persist_chat_history(
        config=config, cosmos_store=store, mode="selected_case", question="one",
        selected_case_id="case-1", requested_session_id=None, user_id="user-1",
        response={"answer": "answer one", "answer_status": "answered"},
    )
    second = persist_chat_history(
        config=config, cosmos_store=store, mode="selected_case", question="two",
        selected_case_id="case-2", requested_session_id=None, user_id="user-1",
        response={"answer": "answer two", "answer_status": "answered"},
    )
    third = persist_chat_history(
        config=config, cosmos_store=store, mode="selected_case", question="three",
        selected_case_id="case-3", requested_session_id=None, user_id="user-1",
        response={"answer": "answer three", "answer_status": "answered"},
    )
    assert len(list_chat_sessions(config=config, cosmos_store=store, user_id="user-1")) == 2
    with pytest.raises(ChatSessionNotFoundError):
        get_chat_session_messages(
            config=config, cosmos_store=store, session_id=first, user_id="user-1"
        )
    with pytest.raises(ChatSessionNotFoundError):
        get_chat_session_messages(
            config=config, cosmos_store=store, session_id=second, user_id="user-2"
        )
    assert get_chat_session_messages(
        config=config, cosmos_store=store, session_id=third, user_id="user-1"
    )["messages"][1]["answer_status"] == "answered"


def test_disposition_sync_upserts_native_documents_and_advances_checkpoint(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_map = tmp_path / "fields.json"
    field_map.write_text(
        json.dumps(
            {
                "table": "sn_si_incident",
                "fields": {
                    "sys_id": "sys_id",
                    "number": "number",
                    "state": "state",
                    "closed_at": "closed_at",
                    "sys_updated_on": "sys_updated_on",
                    "close_code": "close_code",
                    "close_notes": "close_notes",
                    "correlation_id": "correlation_id",
                },
                "closed_state_values": ["3"],
            }
        ),
        encoding="utf-8",
    )
    code_map = tmp_path / "codes.json"
    code_map.write_text(
        json.dumps(
            {
                "likely_malicious": ["true positive"],
                "likely_benign": ["false positive"],
                "unknown": ["inconclusive"],
            }
        ),
        encoding="utf-8",
    )
    config = Config(
        SERVICENOW_DISPOSITION_SYNC_ENABLED=True,
        SERVICENOW_BASE_URL="https://example.service-now.com",
        SERVICENOW_DISPOSITION_SYNC_TOKEN="token",
        SERVICENOW_DISPOSITION_FIELD_MAP=str(field_map),
        SERVICENOW_DISPOSITION_CODE_MAP=str(code_map),
        DISPOSITION_CONTAINER="dispositions",
        DISPOSITION_SYNC_STATE_CONTAINER="sync",
        CASE_INDEX_CONTAINER="cases",
    )
    store, database = _store(now=int(datetime.now(timezone.utc).timestamp()))
    store.upsert_case(
        "cases",
        {
            "case_id": "case-1",
            "processed_at": "2026-01-01T00:00:00Z",
            "correlation_id": "corr-1",
        },
    )
    rows = [
        {
            "sys_id": "snow-1",
            "number": "SIR001",
            "state": "3",
            "closed_at": "2026-01-01 09:00:00",
            "sys_updated_on": "2026-01-01 10:00:00",
            "close_code": "true positive",
            "close_notes": "confirmed",
            "correlation_id": "corr-1",
        }
    ]
    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages",
        lambda **_kwargs: iter([rows]),
    )
    result = run_disposition_sync(
        config=config,
        cosmos_store=store,
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    disposition = database.containers["dispositions"].items[("snow-1", "snow-1")]
    checkpoint = database.containers["sync"].items[("servicenow_closed", "servicenow_closed")]
    assert result["status"] == "success"
    assert result["cursor_advanced"] is True
    assert disposition["case_id"] == "case-1"
    assert disposition["disposition_normalized"] == "likely_malicious"
    assert disposition["ttl"] > 0
    assert checkpoint["cursor_value"] == "2026-01-01T10:00:00Z"
    correlation_query = database.containers["cases"].query_calls[-1]
    assert correlation_query["enable_cross_partition_query"] is True
    assert correlation_query["max_item_count"] == 200


def test_case_create_and_retrieval_status_use_native_conditional_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    store, database = _store()
    created = store.create_case_if_absent(
        "cases",
        {
            "case_id": "case-1",
            "processed_at": "2026-01-01T00:00:00Z",
            "expires_at_epoch": 2_000_001_000,
            "retrieval_status": "pending",
        },
    )
    duplicate = store.create_case_if_absent(
        "cases",
        {"case_id": "case-1", "processed_at": "2026-01-01T00:00:00Z"},
    )
    assert created.created is True
    assert duplicate.created is False

    native_replace = store.replace_if_match
    attempts = 0
    def conflict_once(container_name, item, *, expected_etag):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return ConditionalOutcome(False, "precondition_failed")
        return native_replace(container_name, item, expected_etag=expected_etag)
    monkeypatch.setattr(store, "replace_if_match", conflict_once)

    updated = store.update_case_retrieval_status(
        "cases",
        case_id="case-1",
        status="ready",
        message="embedded 2 chunk(s)",
        updated_at="2026-01-01T00:01:00Z",
    )
    assert attempts == 2
    assert updated["retrieval_status"] == "ready"
    assert database.containers["cases"].items[("case-1", "case-1")][
        "retrieval_status_message"
    ] == "embedded 2 chunk(s)"


@pytest.mark.skip(reason="Optional Cosmos emulator integration test; unit CI is network-free")
def test_cosmos_emulator_optional() -> None:
    """Reserved for the private-network/emulator integration profile."""
