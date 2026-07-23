"""Regression tests for the fail-closed offline unit-test contract."""

from __future__ import annotations

import os
import socket
import unittest


class TestOfflineTestContract(unittest.TestCase):
    def test_model_and_dataset_clients_are_forced_offline(self) -> None:
        self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
        self.assertEqual(os.environ["TRANSFORMERS_OFFLINE"], "1")
        self.assertEqual(os.environ["HF_DATASETS_OFFLINE"], "1")
        self.assertEqual(os.environ["HF_HUB_DISABLE_TELEMETRY"], "1")
        self.assertEqual(os.environ["AWS_EC2_METADATA_DISABLED"], "true")

    def test_external_network_resolution_fails_before_connection(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "Network access is prohibited during tests",
        ):
            socket.getaddrinfo("example.com", 443)

    def test_loopback_network_resolution_is_also_prohibited(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "Network access is prohibited during tests",
        ):
            socket.getaddrinfo("127.0.0.1", 4000)


if __name__ == "__main__":
    unittest.main()
