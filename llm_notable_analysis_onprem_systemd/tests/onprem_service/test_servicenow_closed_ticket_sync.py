import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index import (
    ClosedTicketPendingIndexResult,
)
from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync import (
    CursorState,
    _build_ticket_record,
    _content_hash,
    _cursor_clause,
    _merge_attachment_source_metadata,
    fetch_closed_tickets,
    run_closed_ticket_sync,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ticket_row(
    sys_id: str,
    *,
    updated_on: str = "2026-06-01 12:00:00",
    number: str = "INC001",
    state: str = "3",
) -> dict:
    return {
        "sys_id": sys_id,
        "number": number,
        "state": state,
        "sys_updated_on": updated_on,
        "closed_at": "2026-06-01 11:00:00",
        "short_description": "test ticket",
    }


class TestServiceNowClosedTicketSync(unittest.TestCase):
    def test_cursor_clause_backfill(self) -> None:
        backfill_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        clause = _cursor_clause(
            CursorState(None, "", None),
            overlap_hours=24,
            backfill_start=backfill_start,
        )
        self.assertIn("sys_updated_on>=2026-03-01", clause)

    def test_cursor_clause_composite_with_overlap(self) -> None:
        cursor = CursorState(
            datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            "abc",
            None,
        )
        clause = _cursor_clause(
            cursor,
            overlap_hours=24,
            backfill_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        self.assertIn("^OR^", clause)
        self.assertIn("sys_id>abc", clause)

    def test_build_ticket_record_hashes_journals(self) -> None:
        row = _ticket_row("ticket-1")
        journals = [{"value": "note", "element": "comments"}]
        ticket = _build_ticket_record(
            row,
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=journals,
        )
        self.assertEqual(ticket.ticket_id, "ticket-1")
        self.assertEqual(ticket.ticket_number, "INC001")
        self.assertEqual(ticket.content_hash, _content_hash(ticket.raw_payload, journals))

    def test_fetch_closed_tickets_uses_customer_query_without_sysparm_fields(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
            SERVICENOW_CLOSED_TICKET_QUERY="state=3",
        )
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": [_ticket_row("ticket-1")]}
        response.raise_for_status = MagicMock()

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._request_with_retry",
            return_value=response,
        ) as request_mock:
            rows = list(
                fetch_closed_tickets(
                    config,
                    customer_query="state=3",
                    source_table="sn_si_incident",
                    cursor=CursorState(None, "", None),
                    backfill_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
                    overlap_hours=24,
                )
            )

        self.assertEqual(len(rows), 1)
        params = request_mock.call_args.kwargs["params"]
        self.assertNotIn("sysparm_fields", params)
        self.assertEqual(params["sysparm_display_value"], "all")
        self.assertIn("state=3", params["sysparm_query"])

    def test_run_closed_ticket_sync_disabled(self) -> None:
        config = Config(SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=False)
        summary = run_closed_ticket_sync(config, connect=MagicMock())
        self.assertTrue(summary.skipped)
        self.assertFalse(summary.enabled)

    def test_run_closed_ticket_sync_persists_and_advances_cursor(self) -> None:
        config = Config(
            SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=True,
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
            SERVICENOW_CLOSED_TICKET_QUERY="state=3",
            SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS=False,
            SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=False,
            CASE_POSTGRES_DSN="postgresql://user@127.0.0.1/db",
        )
        conn = MagicMock()

        def execute_side_effect(sql: str, *_args: object, **_kwargs: object) -> MagicMock:
            mock = MagicMock()
            if "sync_state" in sql:
                mock.fetchone.return_value = None
            else:
                mock.fetchone.return_value = None
            return mock

        conn.execute.side_effect = execute_side_effect

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.fetch_closed_tickets",
            return_value=[_ticket_row("ticket-1")],
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._reconcile_active_tickets",
            return_value=(0, set()),
        ):
            summary = run_closed_ticket_sync(config, connect=lambda _dsn: conn)

        self.assertEqual(summary.fetched, 1)
        self.assertEqual(summary.persisted, 1)
        self.assertTrue(summary.cursor_advanced)
        conn.commit.assert_called_once()

    def test_run_closed_ticket_sync_skips_noop_hash(self) -> None:
        row = _ticket_row("ticket-1")
        journals: list = []
        ticket = _build_ticket_record(
            row,
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=journals,
        )
        config = Config(
            SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=True,
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
            SERVICENOW_CLOSED_TICKET_QUERY="state=3",
            SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS=False,
            SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=False,
            CASE_POSTGRES_DSN="postgresql://user@127.0.0.1/db",
        )
        conn = MagicMock()

        def execute_side_effect(sql: str, *_args: object, **_kwargs: object) -> MagicMock:
            mock = MagicMock()
            if "sync_state" in sql:
                mock.fetchone.return_value = None
            elif "SELECT content_hash" in sql:
                mock.fetchone.return_value = (ticket.content_hash,)
            else:
                mock.fetchone.return_value = None
            return mock

        conn.execute.side_effect = execute_side_effect

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.fetch_closed_tickets",
            return_value=[row],
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._reconcile_active_tickets",
            return_value=(0, set()),
        ):
            summary = run_closed_ticket_sync(config, connect=lambda _dsn: conn)

        self.assertEqual(summary.skipped_noop, 1)
        self.assertEqual(summary.persisted, 0)
        self.assertTrue(summary.cursor_advanced)

    def test_merge_attachment_metadata_preserves_semantic_fields(self) -> None:
        existing = {
            "semantic_description": "decoded text",
            "semantic_extraction_status": "text_decoded",
            "sys_id": "old",
        }
        source = {"sys_id": "new", "file_name": "evidence.txt"}
        merged = _merge_attachment_source_metadata(existing, source)
        self.assertEqual(merged["semantic_description"], "decoded text")
        self.assertEqual(merged["semantic_extraction_status"], "text_decoded")
        self.assertEqual(merged["file_name"], "evidence.txt")

    def test_run_closed_ticket_sync_indexes_pending_when_rag_enabled(self) -> None:
        config = Config(
            SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=True,
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
            SERVICENOW_CLOSED_TICKET_QUERY="state=3",
            SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS=False,
            SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=False,
            CASE_POSTGRES_DSN="postgresql://user@127.0.0.1/db",
            CLOSED_TICKET_RAG_ENABLED=True,
        )
        conn = MagicMock()

        def execute_side_effect(sql: str, *_args: object, **_kwargs: object) -> MagicMock:
            mock = MagicMock()
            if "sync_state" in sql:
                mock.fetchone.return_value = None
            else:
                mock.fetchone.return_value = None
            return mock

        conn.execute.side_effect = execute_side_effect

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.fetch_closed_tickets",
            return_value=[_ticket_row("ticket-1")],
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._reconcile_active_tickets",
            return_value=(0, set()),
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index.index_pending_closed_tickets",
            return_value=ClosedTicketPendingIndexResult(selected=1, ready=1),
        ) as mock_index:
            summary = run_closed_ticket_sync(config, connect=lambda _dsn: conn)

        mock_index.assert_called_once()
        self.assertEqual(summary.index_selected, 1)
        self.assertEqual(summary.index_ready, 1)

    def test_config_requires_query_when_enabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "SERVICENOW_CLOSED_TICKET_QUERY"):
            Config(
                SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=True,
                SERVICENOW_CLOSED_TICKET_TOKEN="token",
            )

    def test_config_rejects_invalid_retention(self) -> None:
        with self.assertRaisesRegex(ValueError, "CLOSED_TICKET_RETENTION_DAYS"):
            Config(CLOSED_TICKET_RETENTION_DAYS=45)

    def test_config_requires_dsn_when_closed_ticket_rag_enabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "CASE_POSTGRES_DSN"):
            Config(CLOSED_TICKET_RAG_ENABLED=True, CASE_POSTGRES_DSN="")

    def test_config_vision_defaults_from_llm_when_enabled(self) -> None:
        config = Config(
            CLOSED_TICKET_VISION_ENABLED=True,
            LLM_API_URL="http://127.0.0.1:4000/v1/chat/completions",
            LLM_MODEL_NAME="gemma-test",
            LLM_API_TOKEN="llm-token",
        )
        self.assertEqual(config.CLOSED_TICKET_VISION_API_BASE, "http://127.0.0.1:4000/v1")
        self.assertEqual(config.CLOSED_TICKET_VISION_MODEL, "gemma-test")
        self.assertEqual(config.CLOSED_TICKET_VISION_API_KEY, "llm-token")

    def test_config_vision_rejects_non_loopback_http(self) -> None:
        with self.assertRaisesRegex(ValueError, "CLOSED_TICKET_VISION_API_BASE"):
            Config(
                CLOSED_TICKET_VISION_ENABLED=True,
                CLOSED_TICKET_VISION_API_BASE="http://example.com/v1",
                CLOSED_TICKET_VISION_MODEL="vision-model",
            )

    def test_closed_tickets_schema_contract(self) -> None:
        schema_text = (
            PROJECT_ROOT / "deploy" / "postgres" / "closed_tickets_schema.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE SCHEMA IF NOT EXISTS notable_closed_tickets", schema_text)
        self.assertIn("cursor_sys_id", schema_text)
        self.assertIn("ticket_chunks", schema_text)
        self.assertIn("embedding vector(1024)", schema_text)
        self.assertIn("ticket_chunks_embedding_hnsw_idx", schema_text)
        self.assertIn("attachments_download_status_idx", schema_text)
        self.assertIn("semantic_extraction_status", schema_text)
        self.assertIn("index_status IN ('pending', 'ready', 'failed', 'not_indexed')", schema_text)


if __name__ == "__main__":
    unittest.main()
