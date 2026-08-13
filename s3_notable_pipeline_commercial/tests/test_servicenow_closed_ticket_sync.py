"""Tests for ServiceNow closed ticket sync (AWS)."""

from __future__ import annotations

import json
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
    ReconcileResult,
    _build_ticket_record,
    _content_hash,
    _cursor_clause,
    compute_ticket_retention_expires_at,
    fetch_closed_tickets,
    run_closed_ticket_sync,
    ticket_manifest_key,
    ticket_version_key,
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


def _sync_config(**overrides: Any) -> Config:
    values = {
        "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED": True,
        "SERVICENOW_BASE_URL": "https://example.service-now.com",
        "SERVICENOW_CLOSED_TICKET_TOKEN": "read-token",
        "SERVICENOW_CLOSED_TICKET_QUERY": "state=3",
        "SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS": False,
        "SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS": False,
        "OUTPUT_BUCKET_NAME": "pipeline-bucket",
        "CLOSED_TICKET_RAW_PREFIX": "closed_tickets",
        "CLOSED_TICKET_SYNC_STATE_TABLE": "closed-ticket-sync-state",
        "CLOSED_TICKET_REGISTRY_TABLE": "closed-ticket-registry",
    }
    values.update(overrides)
    return Config(**values)


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}"

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse(payload={"result": self.rows})


class FakeDynamoDbClient:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        table = kwargs["TableName"]
        key = kwargs["Key"]
        pk_name, pk_value = next(iter(key.items()))
        pk = pk_value.get("S") or pk_value.get("N") or str(pk_value)
        item = self.items.get((table, pk))
        return {"Item": item} if item else {}

    def put_item(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)
        table = kwargs["TableName"]
        item = kwargs["Item"]
        if "ticket_id" in item:
            pk = item["ticket_id"]["S"]
            self.items[(table, pk)] = item
        elif "job_name" in item:
            pk = item["job_name"]["S"]
            self.items[(table, pk)] = item

    def delete_item(self, **kwargs: Any) -> None:
        self.deletes.append(kwargs)
        table = kwargs["TableName"]
        pk = kwargs["Key"]["ticket_id"]["S"]
        self.items.pop((table, pk), None)

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        return {"Items": []}


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        body = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": MagicMock(read=lambda: body)}

    def delete_object(self, **kwargs: Any) -> None:
        self.deletes.append(kwargs)
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        prefix = kwargs["Prefix"]
        bucket = kwargs["Bucket"]
        keys = [
            {"Key": key}
            for (b, key) in self.objects
            if b == bucket and key.startswith(prefix)
        ]
        return {"Contents": keys, "IsTruncated": False}


class ServiceNowClosedTicketSyncTests(unittest.TestCase):
    def test_s3_key_layout_for_p4_consumer(self) -> None:
        manifest = ticket_manifest_key("closed_tickets", TICKET_SYS_ID)
        version = ticket_version_key("closed_tickets", TICKET_SYS_ID, "abc123")
        self.assertEqual(
            manifest,
            f"closed_tickets/tickets/{TICKET_SYS_ID}/manifest.json",
        )
        self.assertEqual(
            version,
            f"closed_tickets/tickets/{TICKET_SYS_ID}/versions/abc123/ticket.json",
        )

    def test_cursor_clause_backfill(self) -> None:
        backfill_start = datetime(2026, 3, 1, tzinfo=UTC)
        clause = _cursor_clause(
            CursorState(None, "", None),
            overlap_hours=24,
            backfill_start=backfill_start,
        )
        self.assertIn("sys_updated_on>=2026-03-01", clause)

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
        self.assertEqual(ticket.content_hash, _content_hash(ticket.raw_payload, journals))

    def test_fetch_closed_tickets_uses_full_records(self) -> None:
        config = _sync_config()
        response = FakeResponse(payload={"result": [_ticket_row()]})
        with patch(
            "s3_notable_pipeline.servicenow_closed_ticket_sync._request_with_retry",
            return_value=response,
        ) as request_mock:
            rows = list(
                fetch_closed_tickets(
                    config,
                    base_url=config.SERVICENOW_BASE_URL,
                    token="token",
                    customer_query="state=3",
                    source_table="sn_si_incident",
                    cursor=CursorState(None, "", None),
                    backfill_start=datetime(2026, 3, 1, tzinfo=UTC),
                    overlap_hours=24,
                )
            )
        self.assertEqual(len(rows), 1)
        params = request_mock.call_args.kwargs["params"]
        self.assertNotIn("sysparm_fields", params)
        self.assertEqual(params["sysparm_display_value"], "all")

    def test_run_sync_disabled(self) -> None:
        config = Config(SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=False)
        result = run_closed_ticket_sync(
            config=config,
            s3_client=FakeS3Client(),
            dynamodb_client=FakeDynamoDbClient(),
        )
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(result["skipped"])

    def test_run_sync_persists_and_advances_cursor(self) -> None:
        config = _sync_config()
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient()
        with patch(
            "s3_notable_pipeline.servicenow_closed_ticket_sync.fetch_closed_tickets",
            return_value=[_ticket_row()],
        ), patch(
            "s3_notable_pipeline.servicenow_closed_ticket_sync._reconcile_active_tickets",
            return_value=ReconcileResult(0, frozenset(), True),
        ):
            result = run_closed_ticket_sync(
                config=config,
                s3_client=s3,
                dynamodb_client=dynamodb,
                now=datetime(2026, 6, 2, tzinfo=UTC),
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(result["persisted"], 1)
        self.assertTrue(result["cursor_advanced"])
        self.assertEqual(len(s3.puts), 2)
        manifest_key = ticket_manifest_key(config.CLOSED_TICKET_RAW_PREFIX, TICKET_SYS_ID)
        self.assertIn(
            (config.OUTPUT_BUCKET_NAME, manifest_key),
            s3.objects,
        )

    def test_run_sync_skips_noop_hash(self) -> None:
        row = _ticket_row()
        ticket = _build_ticket_record(
            row,
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=[],
        )
        config = _sync_config()
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient()
        dynamodb.items[(config.CLOSED_TICKET_REGISTRY_TABLE, TICKET_SYS_ID)] = {
            "ticket_id": {"S": TICKET_SYS_ID},
            "record_type": {"S": "ticket"},
            "content_hash": {"S": ticket.content_hash},
        }

        with patch(
            "s3_notable_pipeline.servicenow_closed_ticket_sync.fetch_closed_tickets",
            return_value=[row],
        ), patch(
            "s3_notable_pipeline.servicenow_closed_ticket_sync._reconcile_active_tickets",
            return_value=ReconcileResult(0, frozenset(), True),
        ):
            result = run_closed_ticket_sync(
                config=config,
                s3_client=s3,
                dynamodb_client=dynamodb,
                now=datetime(2026, 6, 2, tzinfo=UTC),
            )

        self.assertEqual(result["skipped_noop"], 1)
        self.assertEqual(result["persisted"], 0)
        self.assertTrue(result["cursor_advanced"])
        self.assertEqual(len(s3.puts), 0)

    def test_auth_failure_surfaces_error(self) -> None:
        from s3_notable_pipeline.servicenow_disposition_sync import DispositionSyncAuthError

        config = _sync_config()
        with patch(
            "s3_notable_pipeline.servicenow_closed_ticket_sync.fetch_closed_tickets",
            side_effect=DispositionSyncAuthError("auth failed"),
        ):
            result = run_closed_ticket_sync(
                config=config,
                s3_client=FakeS3Client(),
                dynamodb_client=FakeDynamoDbClient(),
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("auth failed", result["errors"][0])

    def test_compute_retention_expires_at_prefers_closed_at(self) -> None:
        closed_at = datetime(2026, 6, 1, tzinfo=UTC)
        synced_at = datetime(2026, 6, 2, tzinfo=UTC)
        expires = compute_ticket_retention_expires_at(
            closed_at=closed_at,
            source_updated_at=datetime(2026, 6, 1, 12, tzinfo=UTC),
            retention_days=30,
            synced_at=synced_at,
        )
        self.assertEqual(expires, datetime(2026, 7, 1, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
