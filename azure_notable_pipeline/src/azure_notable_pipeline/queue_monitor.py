"""Keyless per-queue depth telemetry for Azure operational alerts."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .azure_clients import queue_client

logger = logging.getLogger(__name__)

QUEUE_DEPTH_TRACE_PREFIX = "notable.queue.depth.v1 "
INPUT_POISON_QUEUE = "webjobs-blobtrigger-poison"
OUTPUT_QUEUES = (
    "notable-analysis-jobs",
    "notable-analysis-jobs-poison",
    "case-embed-invocations",
    "case-embed-invocations-poison",
)
_QUEUE_PROPERTIES_TIMEOUT_SECONDS = 30

QueueClientFactory = Callable[[str, str], Any]
Clock = Callable[[], datetime]


def emit_queue_depth_traces(
    *,
    input_queue_service_uri: str | None = None,
    output_queue_service_uri: str | None = None,
    client_factory: QueueClientFactory = queue_client,
    clock: Clock | None = None,
    trace_logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Poll the locked operational queues and emit one AppTrace per queue.

    All five reads must succeed. A missing setting, malformed native response,
    authentication failure, or service failure propagates so Azure records a
    failed Function invocation in addition to stale-telemetry alerting.
    """

    input_uri = _required_uri(
        input_queue_service_uri
        if input_queue_service_uri is not None
        else os.getenv("INPUT_QUEUE_SERVICE_URI", ""),
        setting_name="INPUT_QUEUE_SERVICE_URI",
    )
    output_uri = _required_uri(
        output_queue_service_uri
        if output_queue_service_uri is not None
        else os.getenv("OUTPUT_QUEUE_SERVICE_URI", ""),
        setting_name="OUTPUT_QUEUE_SERVICE_URI",
    )
    selected_clock = clock or (lambda: datetime.now(UTC))
    selected_logger = trace_logger or logger
    samples: list[dict[str, Any]] = []

    for account_uri, queue_name in (
        (input_uri, INPUT_POISON_QUEUE),
        *((output_uri, queue_name) for queue_name in OUTPUT_QUEUES),
    ):
        properties = client_factory(account_uri, queue_name).get_queue_properties(
            timeout=_QUEUE_PROPERTIES_TIMEOUT_SECONDS
        )
        sample = {
            "schema_version": 1,
            "queue_name": queue_name,
            "storage_account": _storage_account_name(account_uri),
            "depth": _queue_depth(properties),
            "observed_at": _rfc3339_utc(selected_clock()),
        }
        selected_logger.info(
            "%s%s",
            QUEUE_DEPTH_TRACE_PREFIX,
            json.dumps(sample, separators=(",", ":"), sort_keys=True),
        )
        samples.append(sample)
    return samples


def _required_uri(value: str, *, setting_name: str) -> str:
    uri = str(value or "").strip().rstrip("/")
    parsed = urlparse(uri)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(f"{setting_name} must be an HTTPS queue service URI")
    return uri


def _storage_account_name(queue_service_uri: str) -> str:
    hostname = urlparse(queue_service_uri).hostname or ""
    account_name = hostname.split(".", 1)[0].strip()
    if not account_name:
        raise ValueError("queue service URI must identify a storage account")
    return account_name


def _queue_depth(properties: Any) -> int:
    raw = (
        properties.get("approximate_message_count")
        if isinstance(properties, Mapping)
        else getattr(properties, "approximate_message_count", None)
    )
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("approximate_message_count must be a nonnegative integer")
    if raw < 0:
        raise ValueError("approximate_message_count must be a nonnegative integer")
    return raw


def _rfc3339_utc(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("clock must return datetime")
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "INPUT_POISON_QUEUE",
    "OUTPUT_QUEUES",
    "QUEUE_DEPTH_TRACE_PREFIX",
    "emit_queue_depth_traces",
]
