from __future__ import annotations

import threading
import time
import unittest

from onprem_llm_sdk.client import VLLMClient
from onprem_llm_sdk.config import SDKConfig
from onprem_llm_sdk.metrics import InMemoryMetricsSink
from tests.conftest import FakeResponse


class BlockingSession:
    def __init__(self, entered_event: threading.Event, release_event: threading.Event) -> None:
        self._entered_event = entered_event
        self._release_event = release_event

    def post(self, *args, **kwargs) -> FakeResponse:
        del args, kwargs
        self._entered_event.set()
        self._release_event.wait(timeout=5)
        return FakeResponse(200, {"choices": [{"text": "ok"}]})


class TestSemaphoreLimits(unittest.TestCase):
    def test_max_inflight_enforced(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        metrics = InMemoryMetricsSink()
        cfg = SDKConfig.from_env(
            overrides={
                "llm_max_inflight": 1,
                "llm_retry_backoff_sec": 0.0,
                "llm_verify_tls": False,
            }
        )
        client = VLLMClient(
            cfg,
            session=BlockingSession(entered, release),
            metrics_sink=metrics,
        )

        results = []

        def worker() -> None:
            results.append(client.complete("hello").text)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        self.assertTrue(entered.wait(timeout=2))
        t2.start()

        time.sleep(0.2)
        # While thread 1 holds the semaphore, max inflight should remain 1.
        self.assertEqual(metrics.max_observed_inflight, 1)

        release.set()
        t1.join(timeout=5)
        t2.join(timeout=5)

        self.assertEqual(len(results), 2)
        self.assertEqual(metrics.max_observed_inflight, 1)


if __name__ == "__main__":
    unittest.main()

