"""Tests for ServiceNow closed ticket sync (AWS)."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.servicenow_closed_ticket_sync import (
    CursorState,
    TicketRecord,
    _build_ticket_record,
    _content_hash,
    _cursor_clause,
    compute_ticket_retention_expires_at,
    fetch_closed_tickets,
    run_closed_ticket_sync,
)

TICKET_SYS_ID = "a1b2c3d4e5f6789012345678abcdef01"


def _ticket_row(
    sys_id: str = TICKET_SYS_ID,
    *,
    updated_on: str = "2026-06-01 12:00:00",
    closed_at: str = "2026-06-01 11:00:00",
    number: str = "INC001",
    state: str = "3",
) -> dict[str, Any]:
    return {
        "sys_id": sys_id,
        "number": number,
        "state": state,
        "sys_updated_on": updated_on,
        "closed_at": closed_at,
        "short_description": "test ticket",
    }


class FakeDynamoDB:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        table = kwargs["TableName"]
        key_name = next(iter(kwargs["Key"]))
        key_value = kwargs["Key"][key_name]["S"]
        item = self.items.get((table, key_value))
        return {"Item": item} if item else {}

    def put_item(self, **kwargs: Any) -> None:
        table = kwargs["TableName"]
        item = kwargs["Item"]
        key_name = next(iter(item))
        key_value = item[key_name]["S"]
        self.items[(table, key_value)] = item

    def update_item(self, **kwargs: Any) -> None:
        table = kwargs["TableName"]
        key_value = kwargs["Key"]["ticket_id"]["S"]
        existing = self.items.get((table, key_value), {"ticket_id": {"S": key_value}})
        for name, value in kwargs.get("ExpressionAttributeValues", {}).items():
            if name == ":status":
                existing["index_status"] = value
        self.items[(table, key_value)] = existing

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        table = kwargs["TableName"]
        matches = [item for (tbl, _), item in self.items.items() if tbl == table]
        return {"Items": matches}

    def delete_item(self, **kwargs: Any) -> None:
        table = kwargs["TableName"]
        key_value = kwargs["Key"]["ticket_id"]["S"]
        self.items.pop((table, key_value), None)

    def query(self, **kwargs: Any) -> dict[str, Any]:
        return {"Items": []}


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        body = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": MagicMock(read=MagicMock(return_value=body))}

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        prefix = kwargs.get("Prefix", "")
        bucket = kwargs["Bucket"]
        keys = [
            {"Key": key}
            for (bkt, key) in self.objects
            if bkt == bucket and key.startswith(prefix)
        ]
        return {"Contents": keys, "IsTruncated": False}

    def delete_objects(self, **kwargs: Any) -> None:
        bucket = kwargs["Bucket"]
        for entry in kwargs["Delete"]["Objects"]:
            self.objects.pop((bucket, entry["Key"]), None)


def _sync_config(**overrides: Any) -> Config:
    values = {
        "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED": True,
        "SERVICENOW_BASE_URL": "https://example.service-now.com",
        "SERVICENOW_CLOSED_TICKET_TOKEN": "read-token",
        "SERVICENOW_CLOSED_TICKET_QUERY": "state=3",
        "CLOSED_TICKET_TABLE": "closed-tickets",
        "CLOSED_TICKET_SYNC_STATE_TABLE": "closed-ticket-sync-state",
        "CLOSED_TICKET_ARCHIVE_BUCKET": "archive-bucket",
        "CLOSED_TICKET_ARCHIVE_PREFIX": "closed_tickets",
        "OUTPUT_BUCKET_NAME": "archive-bucket",
    }
    values.update(overrides)
    return Config(**values)


class TestServiceNowClosedTicketSync(unittest.TestCase):
    def test_cursor_clause_backfill(self) -> None:
        backfill_start = datetime(2026, 3, 1, tzinfo=UTC)
        clause = _cursor_clause(
            CursorState(None, "", None),
            overlap_hours=24,
            backfill_start=backfill_start,
        )
        self.assertIn("sys_updated_on>=2026-03-01", clause)

    def test_cursor_clause_composite_with_overlap(self) -> None:
        cursor = CursorState(
            datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            "abc",
            None,
        )
        clause = _cursor_clause(
            cursor,
            overlap_hours=24,
            backfill_start=datetime(2026, 3, 1, tzinfo=UTC),
        )
        self.assertIn("^OR^", clause)
        self.assertIn("sys_id>abc", clause)

    def test_build_ticket_record_hashes_journals(self) -> None:
        row = _ticket_row()
        journals = [{"value": "note", "element": "comments"}]
        ticket = _build_ticket_record(
            row,
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=journals,
        )
        self.assertEqual(ticket.ticket_id, TICKET_SYS_ID)
        self.assertEqual(ticket.ticket_number, "INC001")
        self.assertEqual(ticket.content_hash, _content_hash(ticket.raw_payload, journals))

    def test_fetch_closed_tickets_uses_customer_query_without_sysparm_fields(self) -> None:
        config = _sync_config()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": [_ticket_row()]}

        with patch(
            "s3_notable_pipeline.servicenow_closed_ticket_sync._request_with_retry",
            return_value=response,
        ) as request_mock:
            rows = list(
                fetch_closed_tickets(
                    config,
                    customer_query="state=3",
                    source_table="sn_si_incident",
                    cursor=CursorState(None, "", None),
                    backfill_start=datetime(2026, 3, 1, tzinfo=UTC),
                    overlap_hours=24,
                    token="token",
                    base_url="https://example.service-now.com",
                )
            )

        self.assertEqual(len(rows), 1)
        params = request_mock.call_args.kwargs["params"]
        self.assertNotIn("sysparm_fields", params)
        self.assertEqual(params["sysparm_display_value"], "all")
        self.assertIn("state=3", params["sysparm_query"])

    def test_run_closed_ticket_sync_disabled(self) -> None:
        config = Config(SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=False)
        result = run_closed_ticket_sync(
            config=config,
            dynamodb_client=FakeDynamoDB(),
            s3_client=FakeS3(),
        )
        self.assertTrue(result["skipped"])

    @patch("s3_notable_pipeline.servicenow_closed_ticket_sync.fetch_closed_tickets")
    def test_run_closed_ticket_sync_persists_ticket(self, mock_fetch) -> None:
        mock_fetch.return_value = iter([_ticket_row()])
        dynamodb = FakeDynamoDB()
        s3 = FakeS3()
        config = _sync_config(
            SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS=False,
            SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=False,
        )

        result = run_closed_ticket_sync(
            config=config,
            dynamodb_client=dynamodb,
            s3_client=s3,
            now=datetime(2026, 6, 2, tzinfo=UTC),
        )

        self.assertEqual(result["persisted"], 1)
        self.assertTrue(result["cursor_advanced"])
        self.assertIn((config.CLOSED_TICKET_TABLE, TICKET_SYS_ID), dynamodb.items)
        envelope_key = f"closed_tickets/{TICKET_SYS_ID}/envelope.json"
        self.assertIn((config.CLOSED_TICKET_ARCHIVE_BUCKET, envelope_key), s3.objects)

    def test_compute_ticket_retention_expires_at_prefers_closed_at(self) -> None:
        closed_at = datetime(2026, 1, 1, tzinfo=UTC)
        synced_at = datetime(2026, 1, 2, tzinfo=UTC)
        expires = compute_ticket_retention_expires_at(
            closed_at=closed_at,
            source_updated_at=datetime(2026, 1, 3, tzinfo=UTC),
            retention_days=30,
            synced_at=synced_at,
        )
        self.assertEqual(expires, datetime(2026, 1, 31, tzinfo=UTC))
