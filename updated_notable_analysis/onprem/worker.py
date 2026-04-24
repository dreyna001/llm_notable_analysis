"""Systemd-friendly worker loop for the on-prem notable analyzer."""

from __future__ import annotations

from dataclasses import dataclass
import signal
import time
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from updated_notable_analysis.core.validators import require_int_gt_zero, require_non_empty_string

from .config import OnPremRuntimeConfig
from .file_io import LocalJsonFileTransport
from .service import CoreAnalysisRunner, build_default_processor


class ReadinessProbe(Protocol):
    """Protocol for fail-closed local runtime readiness checks."""

    def check_ready(self) -> None:
        """Raise when the runtime dependency is unavailable."""


class NotableProcessor(Protocol):
    """Protocol for worker-compatible notable processors."""

    def process_next_available(self) -> dict[str, Any] | None:
        """Process the next available notable input file."""


@dataclass(slots=True)
class HttpReadinessProbe:
    """HTTP readiness probe for the analyzer-facing LiteLLM endpoint."""

    readiness_url: str
    timeout_seconds: int
    opener: Callable[..., Any] = urlopen

    def __post_init__(self) -> None:
        """Validate readiness probe configuration."""
        self.readiness_url = require_non_empty_string(self.readiness_url, "readiness_url")
        self.timeout_seconds = require_int_gt_zero(self.timeout_seconds, "timeout_seconds")
        if not callable(self.opener):
            raise ValueError("Field 'opener' must be callable.")

    def check_ready(self) -> None:
        """Raise RuntimeError unless the LiteLLM readiness endpoint responds successfully."""
        request = Request(self.readiness_url, method="GET")
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status < 200 or status >= 400:
                    raise RuntimeError(
                        f"LiteLLM readiness check failed with HTTP status {status}."
                    )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"LiteLLM readiness check failed for {self.readiness_url!r}."
            ) from exc


class StopSignal:
    """Small signal-compatible stop flag for graceful service shutdown."""

    def __init__(self) -> None:
        """Initialize an unset stop flag."""
        self._requested = False

    def request_stop(self, signum: int | None = None, frame: Any | None = None) -> None:
        """Mark the worker for shutdown.

        The signature intentionally matches Python signal handlers.
        """
        self._requested = True

    def is_set(self) -> bool:
        """Return whether shutdown has been requested."""
        return self._requested


def install_stop_signal_handlers(stop_signal: StopSignal) -> None:
    """Install SIGINT/SIGTERM handlers that request a clean worker shutdown."""
    signal.signal(signal.SIGINT, stop_signal.request_stop)
    signal.signal(signal.SIGTERM, stop_signal.request_stop)


class OnPremWorker:
    """Long-running worker loop around the one-file on-prem processor."""

    def __init__(
        self,
        *,
        processor: NotableProcessor,
        readiness_probe: ReadinessProbe,
        idle_sleep_seconds: int,
        max_files_per_poll: int,
        sleep_fn: Callable[[int], None] = time.sleep,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        """Initialize worker lifecycle dependencies."""
        if not callable(sleep_fn):
            raise ValueError("Field 'sleep_fn' must be callable.")
        if stop_requested is not None and not callable(stop_requested):
            raise ValueError("Field 'stop_requested' must be callable when present.")
        self._processor = processor
        self._readiness_probe = readiness_probe
        self._idle_sleep_seconds = require_int_gt_zero(
            idle_sleep_seconds,
            "idle_sleep_seconds",
        )
        self._max_files_per_poll = require_int_gt_zero(
            max_files_per_poll,
            "max_files_per_poll",
        )
        self._sleep_fn = sleep_fn
        self._stop_requested = stop_requested or (lambda: False)

    @property
    def readiness_probe(self) -> ReadinessProbe:
        """Return the configured readiness probe."""
        return self._readiness_probe

    @property
    def idle_sleep_seconds(self) -> int:
        """Return the configured idle sleep interval."""
        return self._idle_sleep_seconds

    @property
    def max_files_per_poll(self) -> int:
        """Return the configured per-poll file limit."""
        return self._max_files_per_poll

    def run_once(self) -> dict[str, Any]:
        """Process up to one configured batch of available files."""
        self._readiness_probe.check_ready()
        results: list[dict[str, Any]] = []
        for _ in range(self._max_files_per_poll):
            result = self._processor.process_next_available()
            if result is None:
                break
            results.append(result)
        return {
            "status": "processed" if results else "idle",
            "processed_count": len(results),
            "results": tuple(results),
        }

    def run_until_stopped(self, *, max_iterations: int | None = None) -> dict[str, int | str]:
        """Run the worker loop until a stop condition or optional iteration cap is reached."""
        if max_iterations is not None:
            max_iterations = require_int_gt_zero(max_iterations, "max_iterations")

        iterations = 0
        processed_count = 0
        idle_count = 0
        while not self._stop_requested():
            if max_iterations is not None and iterations >= max_iterations:
                break

            result = self.run_once()
            iterations += 1
            processed_count += int(result["processed_count"])
            if result["processed_count"] == 0:
                idle_count += 1
                should_continue = max_iterations is None or iterations < max_iterations
                if should_continue and not self._stop_requested():
                    self._sleep_fn(self._idle_sleep_seconds)

        status = "stopped" if self._stop_requested() else "max_iterations_exhausted"
        return {
            "status": status,
            "iterations": iterations,
            "processed_count": processed_count,
            "idle_count": idle_count,
        }


def build_default_worker(
    *,
    core_runner: CoreAnalysisRunner | None = None,
    config: OnPremRuntimeConfig | None = None,
    file_transport: LocalJsonFileTransport | None = None,
    readiness_probe: ReadinessProbe | None = None,
    stop_signal: StopSignal | None = None,
) -> OnPremWorker:
    """Build the default on-prem worker with explicit runtime seams."""
    resolved_config = config or OnPremRuntimeConfig.from_env()
    processor = build_default_processor(
        core_runner=core_runner,
        config=resolved_config,
        file_transport=file_transport,
    )
    resolved_probe = readiness_probe or HttpReadinessProbe(
        readiness_url=resolved_config.litellm_readiness_url,
        timeout_seconds=resolved_config.readiness_timeout_seconds,
    )
    resolved_stop_signal = stop_signal or StopSignal()
    return OnPremWorker(
        processor=processor,
        readiness_probe=resolved_probe,
        idle_sleep_seconds=resolved_config.worker_idle_sleep_seconds,
        max_files_per_poll=resolved_config.worker_max_files_per_poll,
        stop_requested=resolved_stop_signal.is_set,
    )
