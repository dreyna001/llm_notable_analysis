"""Tests for DynamoDB side-effect idempotency helpers."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
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

    def __init__(self, *, duplicate: bool = False, status: str = "completed", started_at: str = "") -> None:
        self.duplicate = duplicate
        self.status = status
        self.started_at = started_at
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
                "status": {"S": self.status},
                "started_at": {"S": self.started_at},
                "metadata": {"S": '{"finding_id": "finding-1"}'},
            }
        }

    def update_item(self, **_kwargs):
        self.update_calls += 1
        return {}

    def delete_item(self, **_kwargs):
        self.delete_calls += 1
        self.duplicate = False
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
        self.assertEqual(reservation.existing_marker["status"], "completed")
        self.assertEqual(reservation.existing_marker["metadata"]["finding_id"], "finding-1")

    def test_in_progress_marker_reports_locked_without_claiming_completion(self) -> None:
        client = FakeDynamoDb(duplicate=True, status="in_progress")
        reservation = begin_side_effect(
            Config(
                SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
                SIDE_EFFECT_IDEMPOTENCY_TABLE="idem",
            ),
            operation="splunk_notable_update",
            key="finding-1",
            client=client,
        )

        self.assertFalse(reservation.should_execute)
        self.assertEqual(reservation.existing_marker["status"], "in_progress")

    def test_stale_in_progress_marker_is_reclaimed(self) -> None:
        stale_started_at = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        client = FakeDynamoDb(duplicate=True, status="in_progress", started_at=stale_started_at)

        reservation = begin_side_effect(
            Config(
                SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
                SIDE_EFFECT_IDEMPOTENCY_TABLE="idem",
                SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS=1,
            ),
            operation="splunk_notable_update",
            key="finding-1",
            client=client,
        )

        self.assertTrue(reservation.should_execute)
        self.assertTrue(reservation.fencing_token)
        self.assertEqual(client.delete_calls, 0)
        self.assertEqual(client.update_calls, 1)

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
