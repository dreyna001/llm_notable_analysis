"""Deterministic tests for the on-prem worker lifecycle."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError

from updated_notable_analysis.onprem.config import OnPremRuntimeConfig
from updated_notable_analysis.onprem.worker import (
    HttpReadinessProbe,
    OnPremWorker,
    StopSignal,
    build_default_worker,
)


class _FakeProcessor:
    """Small processor test double with a finite result queue."""

    def __init__(self, results: list[dict[str, object] | None]) -> None:
        self.results = list(results)
        self.calls = 0

    def process_next_available(self) -> dict[str, object] | None:
        self.calls += 1
        if not self.results:
            return None
        return self.results.pop(0)


class _FakeReadinessProbe:
    """Readiness probe test double."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def check_ready(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class _FakeResponse:
    """Context-manager response test double for HTTP readiness tests."""

    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # noqa: ANN001
        return None


class TestOnPremWorker(unittest.TestCase):
    """Behavior-focused tests for worker polling and readiness handling."""

    def test_run_once_processes_up_to_configured_batch_size(self) -> None:
        """One poll should stop at the configured per-poll file limit."""
        processor = _FakeProcessor(
            [
                {"status": "ok", "source_record_ref": "one"},
                {"status": "ok", "source_record_ref": "two"},
                {"status": "ok", "source_record_ref": "three"},
            ]
        )
        probe = _FakeReadinessProbe()
        worker = OnPremWorker(
            processor=processor,
            readiness_probe=probe,
            idle_sleep_seconds=5,
            max_files_per_poll=2,
        )

        result = worker.run_once()

        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["processed_count"], 2)
        self.assertEqual(processor.calls, 2)
        self.assertEqual(probe.calls, 1)
        self.assertEqual(len(processor.results), 1)

    def test_run_until_stopped_sleeps_when_idle_and_exits_cleanly(self) -> None:
        """The worker should sleep on idle polls and stop on the injected stop condition."""
        sleeps: list[int] = []
        processor = _FakeProcessor([])
        probe = _FakeReadinessProbe()

        worker = OnPremWorker(
            processor=processor,
            readiness_probe=probe,
            idle_sleep_seconds=5,
            max_files_per_poll=10,
            sleep_fn=sleeps.append,
            stop_requested=lambda: bool(sleeps),
        )

        result = worker.run_until_stopped()

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["iterations"], 1)
        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(result["idle_count"], 1)
        self.assertEqual(sleeps, [5])

    def test_run_until_stopped_does_not_sleep_after_final_capped_idle_poll(self) -> None:
        """A bounded one-shot loop should not sleep after its final idle poll."""
        sleeps: list[int] = []
        worker = OnPremWorker(
            processor=_FakeProcessor([]),
            readiness_probe=_FakeReadinessProbe(),
            idle_sleep_seconds=5,
            max_files_per_poll=10,
            sleep_fn=sleeps.append,
        )

        result = worker.run_until_stopped(max_iterations=1)

        self.assertEqual(result["status"], "max_iterations_exhausted")
        self.assertEqual(result["iterations"], 1)
        self.assertEqual(result["idle_count"], 1)
        self.assertEqual(sleeps, [])

    def test_worker_fails_closed_when_readiness_probe_fails(self) -> None:
        """Readiness failures should prevent processing instead of running degraded."""
        processor = _FakeProcessor([{"status": "ok"}])
        worker = OnPremWorker(
            processor=processor,
            readiness_probe=_FakeReadinessProbe(error=RuntimeError("litellm unavailable")),
            idle_sleep_seconds=5,
            max_files_per_poll=10,
        )

        with self.assertRaises(RuntimeError):
            worker.run_once()

        self.assertEqual(processor.calls, 0)

    def test_stop_signal_is_compatible_with_worker_stop_callback(self) -> None:
        """StopSignal should let the service lifecycle request a clean worker exit."""
        stop_signal = StopSignal()
        stop_signal.request_stop()
        worker = OnPremWorker(
            processor=_FakeProcessor([{"status": "ok"}]),
            readiness_probe=_FakeReadinessProbe(),
            idle_sleep_seconds=5,
            max_files_per_poll=10,
            stop_requested=stop_signal.is_set,
        )

        result = worker.run_until_stopped()

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["iterations"], 0)

    def test_http_readiness_probe_wraps_unavailable_endpoint_errors(self) -> None:
        """HTTP readiness should raise a deterministic RuntimeError on endpoint failure."""

        def failing_opener(*args, **kwargs):  # noqa: ANN002, ANN003
            raise URLError("connection refused")

        probe = HttpReadinessProbe(
            readiness_url="http://127.0.0.1:4000/v1/models",
            timeout_seconds=2,
            opener=failing_opener,
        )

        with self.assertRaisesRegex(RuntimeError, "LiteLLM readiness check failed"):
            probe.check_ready()

    def test_http_readiness_probe_accepts_successful_response(self) -> None:
        """HTTP readiness should accept successful LiteLLM responses."""

        def passing_opener(*args, **kwargs):  # noqa: ANN002, ANN003
            return _FakeResponse(status=200)

        probe = HttpReadinessProbe(
            readiness_url="http://127.0.0.1:4000/v1/models",
            timeout_seconds=2,
            opener=passing_opener,
        )

        probe.check_ready()

    def test_config_from_env_parses_worker_and_litellm_settings(self) -> None:
        """Environment config should include worker controls and LiteLLM readiness URL."""
        config = OnPremRuntimeConfig.from_env(
            {
                "UPDATED_NOTABLE_ONPREM_INCOMING_DIR": "/var/notables/incoming",
                "UPDATED_NOTABLE_ONPREM_PROCESSED_DIR": "/var/notables/processed",
                "UPDATED_NOTABLE_ONPREM_QUARANTINE_DIR": "/var/notables/quarantine",
                "UPDATED_NOTABLE_ONPREM_REPORT_OUTPUT_DIR": "/var/notables/reports",
                "UPDATED_NOTABLE_ONPREM_ADVISORY_CONTEXT_DIR": "/var/notables/context",
                "UPDATED_NOTABLE_ONPREM_LITELLM_BASE_URL": "http://localhost:4000/",
                "UPDATED_NOTABLE_ONPREM_LITELLM_READINESS_PATH": "/v1/models",
                "UPDATED_NOTABLE_ONPREM_LITELLM_CHAT_COMPLETIONS_PATH": "/v1/chat/completions",
                "UPDATED_NOTABLE_ONPREM_LITELLM_MODEL_NAME": "gemma-4-31B-it",
                "UPDATED_NOTABLE_ONPREM_READINESS_TIMEOUT_SECONDS": "3",
                "UPDATED_NOTABLE_ONPREM_LITELLM_REQUEST_TIMEOUT_SECONDS": "11",
                "UPDATED_NOTABLE_ONPREM_WORKER_IDLE_SLEEP_SECONDS": "7",
                "UPDATED_NOTABLE_ONPREM_WORKER_MAX_FILES_PER_POLL": "4",
            }
        )

        self.assertEqual(config.litellm_base_url, "http://localhost:4000")
        self.assertEqual(config.advisory_context_dir, "/var/notables/context")
        self.assertEqual(config.litellm_readiness_url, "http://localhost:4000/v1/models")
        self.assertEqual(
            config.litellm_chat_completions_url,
            "http://localhost:4000/v1/chat/completions",
        )
        self.assertEqual(config.litellm_model_name, "gemma-4-31B-it")
        self.assertEqual(config.readiness_timeout_seconds, 3)
        self.assertEqual(config.litellm_request_timeout_seconds, 11)
        self.assertEqual(config.worker_idle_sleep_seconds, 7)
        self.assertEqual(config.worker_max_files_per_poll, 4)

    def test_config_constructor_requires_keywords(self) -> None:
        """Runtime config should avoid positional ABI drift as fields are added."""
        with self.assertRaises(TypeError):
            OnPremRuntimeConfig(  # type: ignore[misc]
                "/var/notables/incoming",
                "/var/notables/processed",
                "/var/notables/quarantine",
                "/var/notables/reports",
            )

    def test_config_rejects_non_loopback_litellm_url(self) -> None:
        """Analyzer-facing LiteLLM config should stay on loopback by default."""
        with self.assertRaises(ValueError):
            OnPremRuntimeConfig(litellm_base_url="http://10.0.0.5:4000")

    def test_build_default_worker_uses_litellm_readiness_config(self) -> None:
        """The default worker should point readiness at the configured LiteLLM endpoint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = OnPremRuntimeConfig(
                incoming_dir=str(root / "incoming"),
                processed_dir=str(root / "processed"),
                quarantine_dir=str(root / "quarantine"),
                report_output_dir=str(root / "reports"),
                litellm_base_url="http://127.0.0.1:4000",
                litellm_readiness_path="/v1/models",
                readiness_timeout_seconds=3,
                worker_idle_sleep_seconds=7,
                worker_max_files_per_poll=4,
            )
            stop_signal = StopSignal()

            worker = build_default_worker(config=config, stop_signal=stop_signal)

            self.assertIsInstance(worker.readiness_probe, HttpReadinessProbe)
            assert isinstance(worker.readiness_probe, HttpReadinessProbe)
            self.assertEqual(worker.readiness_probe.readiness_url, "http://127.0.0.1:4000/v1/models")
            self.assertEqual(worker.readiness_probe.timeout_seconds, 3)
            self.assertEqual(worker.idle_sleep_seconds, 7)
            self.assertEqual(worker.max_files_per_poll, 4)


if __name__ == "__main__":
    unittest.main()
