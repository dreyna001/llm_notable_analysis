"""Tests for DynamoDB side-effect idempotency helpers."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.idempotency import (
    begin_side_effect,
    complete_side_effect_success,
    release_side_effect_lock,
)


class ConditionalCheckFailed(Exception):
    """Fake boto3 conditional failure."""

    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeDynamoDb:
    """Small fake DynamoDB client for idempotency behavior."""

    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.put_calls = 0
        self.update_calls = 0
        self.delete_calls = 0

    def put_item(self, **_kwargs):
        self.put_calls += 1
        if self.duplicate:
            raise ConditionalCheckFailed()
        return {}

    def get_item(self, **_kwargs):
        return {
            "Item": {
                "operation": {"S": "splunk_notable_update"},
                "side_effect_key": {"S": "finding-1"},
                "status": {"S": "completed"},
                "metadata": {"S": '{"finding_id": "finding-1"}'},
            }
        }

    def update_item(self, **_kwargs):
        self.update_calls += 1
        return {}

    def delete_item(self, **_kwargs):
        self.delete_calls += 1
        return {}


class IdempotencyTests(unittest.TestCase):
    """DynamoDB reservation tests."""

    def test_disabled_idempotency_executes_without_client(self) -> None:
        reservation = begin_side_effect(
            Config(SIDE_EFFECT_IDEMPOTENCY_ENABLED=False),
            operation="splunk_notable_update",
            key="finding-1",
        )

        self.assertFalse(reservation.enabled)
        self.assertTrue(reservation.should_execute)

    def test_duplicate_conditional_write_skips_execution(self) -> None:
        client = FakeDynamoDb(duplicate=True)
        reservation = begin_side_effect(
            Config(
                SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
                SIDE_EFFECT_IDEMPOTENCY_TABLE="idem",
            ),
            operation="splunk_notable_update",
            key="finding-1",
            client=client,
        )

        self.assertTrue(reservation.enabled)
        self.assertFalse(reservation.should_execute)
        self.assertEqual(reservation.existing_marker["metadata"]["finding_id"], "finding-1")

    def test_success_records_completion_and_failure_releases_lock(self) -> None:
        client = FakeDynamoDb()
        reservation = begin_side_effect(
            Config(
                SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
                SIDE_EFFECT_IDEMPOTENCY_TABLE="idem",
            ),
            operation="servicenow_incident_create",
            key="incident-1",
            client=client,
        )

        self.assertTrue(complete_side_effect_success(reservation, metadata={"number": "INC1"}))
        self.assertEqual(client.update_calls, 1)

        release_side_effect_lock(reservation)
        self.assertEqual(client.delete_calls, 1)


if __name__ == "__main__":
    unittest.main()
