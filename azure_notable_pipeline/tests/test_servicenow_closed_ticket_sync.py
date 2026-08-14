"""Tests for ServiceNow closed ticket sync (Azure)."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from azure_notable_pipeline.config import Config
from azure_notable_pipeline.servicenow_closed_ticket_sync import (
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


class MemoryCosmosStore:
    def __init__(self) -> None:
        self.tickets: dict[str, dict[str, Any]] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}

    def get_closed_ticket(self, _container: str, ticket_id: str) -> dict[str, Any] | None:
        row = self.tickets.get(ticket_id)
        return dict(row) if row else None

    def upsert_closed_ticket(self, _container: str, ticket: dict[str, Any]) -> dict[str, Any]:
        ticket_id = ticket["ticket_id"]
        self.tickets[ticket_id] = dict(ticket)
        return ticket

    def get_sync_checkpoint(self, _container: str, job_name: str) -> dict[str, Any] | None:
        row = self.checkpoints.get(job_name)
        return dict(row) if row else None

    def upsert_sync_checkpoint(self, _container: str, checkpoint: dict[str, Any]) -> dict[str, Any]:
        self.checkpoints[checkpoint["job_name"]] = dict(checkpoint)
        return checkpoint

    def list_expired_closed_tickets(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def list_active_closed_tickets_updated_since(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def deactivate_closed_ticket(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def delete_closed_ticket(self, *_args: Any, **_kwargs: Any) -> bool:
        return False


class FakeBlobStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}


def _sync_config(**overrides: Any) -> Config:
    values = {
        "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED": True,
        "SERVICENOW_BASE_URL": "https://example.service-now.com",
        "SERVICENOW_CLOSED_TICKET_TOKEN": "read-token",
        "SERVICENOW_CLOSED_TICKET_QUERY": "state=3",
        "CLOSED_TICKET_CONTAINER": "closed-tickets",
        "CLOSED_TICKET_SYNC_STATE_CONTAINER": "closed-ticket-sync-state",
        "CLOSED_TICKET_ARCHIVE_CONTAINER": "output",
        "CLOSED_TICKET_ARCHIVE_PREFIX": "closed_tickets",
        "OUTPUT_CONTAINER_NAME": "output",
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
            "azure_notable_pipeline.servicenow_closed_ticket_sync._request_with_retry",
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
            cosmos_store=MemoryCosmosStore(),  # type: ignore[arg-type]
            blob_service=FakeBlobStore(),
        )
        self.assertTrue(result["skipped"])

    @patch("azure_notable_pipeline.servicenow_closed_ticket_sync.write_blob")
    @patch("azure_notable_pipeline.servicenow_closed_ticket_sync.fetch_closed_tickets")
    def test_run_closed_ticket_sync_persists_ticket(self, mock_fetch, mock_write) -> None:
        mock_fetch.return_value = iter([_ticket_row()])
        store = MemoryCosmosStore()
        blob = FakeBlobStore()
        config = _sync_config(
            SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS=False,
            SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=False,
        )

        def _capture_write(container: str, blob_name: str, body: bytes, **kwargs: Any) -> None:
            blob.objects[(container, blob_name)] = body

        mock_write.side_effect = _capture_write

        result = run_closed_ticket_sync(
            config=config,
            cosmos_store=store,  # type: ignore[arg-type]
            blob_service=blob,
            now=datetime(2026, 6, 2, tzinfo=UTC),
        )

        self.assertEqual(result["persisted"], 1)
        self.assertTrue(result["cursor_advanced"])
        self.assertIn(TICKET_SYS_ID, store.tickets)
        envelope_key = f"closed_tickets/{TICKET_SYS_ID}/envelope.json"
        self.assertIn((config.CLOSED_TICKET_ARCHIVE_CONTAINER, envelope_key), blob.objects)

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
