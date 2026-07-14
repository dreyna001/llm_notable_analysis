"""Behavior tests for Cosmos-backed distributed chat admission control."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from azure_notable_pipeline.chat_quota import CosmosChatQuota


class MemoryStore:
    def __init__(self) -> None:
        self.item = None
        self.etag = 0
        self.force_conflicts = 0

    def read_item(self, _container, *, item_id, partition_key):
        assert item_id == "chat-quota"
        if self.item is None or self.item["user_id"] != partition_key:
            return None
        value = deepcopy(self.item)
        value["_etag"] = str(self.etag)
        return value

    def create_if_absent(self, _container, item):
        if self.item is not None:
            return SimpleNamespace(created=False)
        self.item = deepcopy(item)
        self.etag += 1
        return SimpleNamespace(created=True)

    def replace_if_match(self, _container, item, *, expected_etag):
        if self.force_conflicts:
            self.force_conflicts -= 1
            return SimpleNamespace(applied=False, outcome="precondition_failed")
        if expected_etag != str(self.etag):
            return SimpleNamespace(applied=False, outcome="precondition_failed")
        self.item = deepcopy(item)
        self.item.pop("_etag", None)
        self.etag += 1
        return SimpleNamespace(applied=True, outcome="replaced")


def quota(store, clock, **overrides):
    values = {
        "container_name": "chat-quota",
        "max_concurrency": 2,
        "window_seconds": 60,
        "max_requests_per_window": 3,
        "max_budget_units_per_window": 100,
        "lease_seconds": 30,
        "dedupe_seconds": 60,
        "clock": lambda: clock[0],
    }
    values.update(overrides)
    return CosmosChatQuota(store, **values)


def test_concurrency_is_per_user_and_release_restores_capacity() -> None:
    store = MemoryStore()
    clock = [120]
    gate = quota(store, clock, max_concurrency=1)

    first = gate.acquire(user_id="analyst-1", request_id="request-0001", budget_units=10)
    denied = gate.acquire(user_id="analyst-1", request_id="request-0002", budget_units=10)
    gate.release(user_id="analyst-1", request_id=first.request_id)
    admitted = gate.acquire(user_id="analyst-1", request_id="request-0002", budget_units=10)

    assert denied.allowed is False
    assert denied.reason == "concurrency"
    assert denied.retry_after_seconds == 30
    assert admitted.allowed is True


def test_expired_lease_recovers_capacity_after_worker_crash() -> None:
    store = MemoryStore()
    clock = [120]
    gate = quota(store, clock, max_concurrency=1, dedupe_seconds=10)
    gate.acquire(user_id="analyst-1", request_id="request-0001", budget_units=10)

    clock[0] = 151
    decision = gate.acquire(
        user_id="analyst-1", request_id="request-0002", budget_units=10
    )

    assert decision.allowed is True
    assert [lease["request_id"] for lease in store.item["active_leases"]] == [
        "request-0002"
    ]


def test_request_and_budget_windows_return_stable_retry_after() -> None:
    store = MemoryStore()
    clock = [125]
    gate = quota(store, clock, max_concurrency=3, max_budget_units_per_window=20)
    gate.acquire(user_id="analyst-1", request_id="request-0001", budget_units=15)
    gate.release(user_id="analyst-1", request_id="request-0001")

    decision = gate.acquire(
        user_id="analyst-1", request_id="request-0002", budget_units=10
    )

    assert decision.allowed is False
    assert decision.reason == "budget_window"
    assert decision.retry_after_seconds == 55


def test_duplicate_request_is_not_charged_twice() -> None:
    store = MemoryStore()
    clock = [120]
    gate = quota(store, clock)
    gate.acquire(user_id="analyst-1", request_id="request-0001", budget_units=10)
    gate.release(user_id="analyst-1", request_id="request-0001")

    duplicate = gate.acquire(
        user_id="analyst-1", request_id="request-0001", budget_units=10
    )

    assert duplicate.allowed is False
    assert duplicate.reason == "duplicate_request"
    assert store.item["request_count"] == 1
    assert store.item["budget_units"] == 10


def test_etag_conflict_retries_without_lost_update() -> None:
    store = MemoryStore()
    clock = [120]
    gate = quota(store, clock)
    gate.acquire(user_id="analyst-1", request_id="request-0001", budget_units=10)
    gate.release(user_id="analyst-1", request_id="request-0001")
    store.force_conflicts = 1

    decision = gate.acquire(
        user_id="analyst-1", request_id="request-0002", budget_units=10
    )

    assert decision.allowed is True
    assert store.item["request_count"] == 2
    assert store.item["budget_units"] == 20
