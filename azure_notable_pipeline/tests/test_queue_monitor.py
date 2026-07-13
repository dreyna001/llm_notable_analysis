"""Offline tests for native Storage Queue operational telemetry."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from azure_notable_pipeline.queue_monitor import (
    INPUT_POISON_QUEUE,
    OUTPUT_QUEUES,
    QUEUE_DEPTH_TRACE_PREFIX,
    emit_queue_depth_traces,
)


class FakeQueueClient:
    def __init__(self, depth: int, *, failure: Exception | None = None) -> None:
        self.depth = depth
        self.failure = failure
        self.timeouts: list[int] = []

    def get_queue_properties(self, *, timeout: int):
        self.timeouts.append(timeout)
        if self.failure:
            raise self.failure
        return SimpleNamespace(approximate_message_count=self.depth)


def test_monitor_polls_exact_queues_and_emits_exact_trace_schema(caplog) -> None:
    calls = []
    clients = []

    def factory(account_uri: str, queue_name: str):
        calls.append((account_uri, queue_name))
        client = FakeQueueClient(len(calls) - 1)
        clients.append(client)
        return client

    caplog.set_level(logging.INFO, logger="azure_notable_pipeline.queue_monitor")
    observed_at = datetime(2026, 7, 13, 12, 34, 56, tzinfo=UTC)
    samples = emit_queue_depth_traces(
        input_queue_service_uri="https://inputacct.queue.core.windows.net",
        output_queue_service_uri="https://outputacct.queue.core.windows.net",
        client_factory=factory,
        clock=lambda: observed_at,
    )

    assert calls == [
        ("https://inputacct.queue.core.windows.net", INPUT_POISON_QUEUE),
        *[
            ("https://outputacct.queue.core.windows.net", queue_name)
            for queue_name in OUTPUT_QUEUES
        ],
    ]
    assert all(client.timeouts == [30] for client in clients)
    assert [sample["depth"] for sample in samples] == [0, 1, 2, 3, 4]
    assert samples[0]["storage_account"] == "inputacct"
    assert all(sample["observed_at"] == "2026-07-13T12:34:56Z" for sample in samples)
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 5
    for message, sample in zip(messages, samples, strict=True):
        assert message.startswith(QUEUE_DEPTH_TRACE_PREFIX)
        payload = json.loads(message.removeprefix(QUEUE_DEPTH_TRACE_PREFIX))
        assert payload == sample
        assert set(payload) == {
            "schema_version",
            "queue_name",
            "storage_account",
            "depth",
            "observed_at",
        }


def test_monitor_reads_locked_environment_settings(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("INPUT_QUEUE_SERVICE_URI", "https://inputacct.queue.core.windows.net")
    monkeypatch.setenv("OUTPUT_QUEUE_SERVICE_URI", "https://outputacct.queue.core.windows.net")

    emit_queue_depth_traces(
        client_factory=lambda uri, name: calls.append((uri, name)) or FakeQueueClient(0),
        clock=lambda: datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert len(calls) == 5


def test_monitor_raises_on_any_polling_failure_without_actions() -> None:
    calls = []

    def factory(_uri: str, queue_name: str):
        calls.append(queue_name)
        failure = RuntimeError("queue unavailable") if len(calls) == 3 else None
        return FakeQueueClient(0, failure=failure)

    with pytest.raises(RuntimeError, match="queue unavailable"):
        emit_queue_depth_traces(
            input_queue_service_uri="https://inputacct.queue.core.windows.net",
            output_queue_service_uri="https://outputacct.queue.core.windows.net",
            client_factory=factory,
        )

    assert calls == [INPUT_POISON_QUEUE, OUTPUT_QUEUES[0], OUTPUT_QUEUES[1]]


@pytest.mark.parametrize("depth", [-1, True, None, 1.5, "3", "not-an-integer"])
def test_monitor_rejects_invalid_native_queue_depth(depth) -> None:
    with pytest.raises(ValueError, match="nonnegative integer"):
        emit_queue_depth_traces(
            input_queue_service_uri="https://inputacct.queue.core.windows.net",
            output_queue_service_uri="https://outputacct.queue.core.windows.net",
            client_factory=lambda _uri, _name: FakeQueueClient(depth),
        )
