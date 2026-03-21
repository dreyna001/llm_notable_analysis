"""Core client behavior unit tests.

Run this module directly:
  PYTHONPATH=src python -m unittest tests.test_client -v
"""

from __future__ import annotations

import unittest

import requests

from onprem_llm_sdk.client import VLLMClient
from onprem_llm_sdk.config import SDKConfig
from onprem_llm_sdk.errors import ClientRequestError, RequestTimeoutError
from onprem_llm_sdk.metrics import InMemoryMetricsSink
from tests.conftest import FakeResponse, FakeSession


class TestVLLMClient(unittest.TestCase):
    def _cfg(self) -> SDKConfig:
        return SDKConfig.from_env(
            overrides={
                "llm_model_name": "test-model",
                "llm_max_retries": 2,
                "llm_retry_backoff_sec": 0.0,
                "llm_max_inflight": 2,
                "llm_verify_tls": False,
            }
        )

    def test_success_on_first_attempt(self) -> None:
        session = FakeSession(
            responses=[FakeResponse(200, {"choices": [{"text": "ok"}]})],
        )
        metrics = InMemoryMetricsSink()
        client = VLLMClient(self._cfg(), session=session, metrics_sink=metrics)

        result = client.complete("hello")

        self.assertEqual(result.text, "ok")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(metrics.success_count, 1)

    def test_retry_on_500_then_success(self) -> None:
        session = FakeSession(
            responses=[
                FakeResponse(500, text="temporary"),
                FakeResponse(200, {"choices": [{"text": "recovered"}]}),
            ],
        )
        sleeps = []
        client = VLLMClient(self._cfg(), session=session, sleep_fn=lambda s: sleeps.append(s))

        result = client.complete("hello")

        self.assertEqual(result.text, "recovered")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(session.call_count, 2)
        self.assertEqual(len(sleeps), 0)

    def test_no_retry_on_400(self) -> None:
        session = FakeSession(responses=[FakeResponse(400, text="bad request")])
        client = VLLMClient(self._cfg(), session=session)

        with self.assertRaises(ClientRequestError):
            client.complete("hello")

        self.assertEqual(session.call_count, 1)

    def test_timeout_exhausts_retries(self) -> None:
        session = FakeSession(
            exceptions=[
                requests.exceptions.Timeout("timeout 1"),
                requests.exceptions.Timeout("timeout 2"),
                requests.exceptions.Timeout("timeout 3"),
            ]
        )
        cfg = SDKConfig.from_env(
            overrides={
                "llm_max_retries": 2,
                "llm_retry_backoff_sec": 0.0,
            }
        )
        client = VLLMClient(cfg, session=session)

        with self.assertRaises(RequestTimeoutError):
            client.complete("hello")
        self.assertEqual(session.call_count, 3)


if __name__ == "__main__":
    unittest.main()
