"""Metrics hooks for host application observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol


class MetricsSink(Protocol):
    """Pluggable metrics sink interface."""

    def record_inflight(self, *, app_name: str, inflight: int) -> None:
        """Record current inflight count."""

    def record_request_result(
        self,
        *,
        app_name: str,
        success: bool,
        status_code: int,
        attempts: int,
        latency_seconds: float,
        error_type: str = "",
    ) -> None:
        """Record request completion metrics."""


class NoOpMetricsSink:
    """Default sink when metrics are not configured by the host app."""

    def record_inflight(self, *, app_name: str, inflight: int) -> None:
        return None

    def record_request_result(
        self,
        *,
        app_name: str,
        success: bool,
        status_code: int,
        attempts: int,
        latency_seconds: float,
        error_type: str = "",
    ) -> None:
        return None


@dataclass
class InMemoryMetricsSink:
    """Simple in-memory sink useful for testing and smoke checks."""

    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    last_status_code: int = 0
    last_attempts: int = 0
    last_latency_seconds: float = 0.0
    last_error_type: str = ""
    current_inflight: int = 0
    max_observed_inflight: int = 0

    _lock: Lock = field(default_factory=Lock)

    def record_inflight(self, *, app_name: str, inflight: int) -> None:
        del app_name
        with self._lock:
            self.current_inflight = inflight
            if inflight > self.max_observed_inflight:
                self.max_observed_inflight = inflight

    def record_request_result(
        self,
        *,
        app_name: str,
        success: bool,
        status_code: int,
        attempts: int,
        latency_seconds: float,
        error_type: str = "",
    ) -> None:
        del app_name
        with self._lock:
            self.request_count += 1
            if success:
                self.success_count += 1
            else:
                self.error_count += 1
            self.last_status_code = status_code
            self.last_attempts = attempts
            self.last_latency_seconds = latency_seconds
            self.last_error_type = error_type

