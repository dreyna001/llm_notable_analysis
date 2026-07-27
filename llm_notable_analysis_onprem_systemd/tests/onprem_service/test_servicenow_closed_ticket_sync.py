import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index import (
    ClosedTicketPendingIndexResult,
)
from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync import (
    CursorState,
    MAX_CHILD_RECORDS_PER_TICKET,
    MAX_RECONCILE_IDS_PER_RUN,
    ReconcileResult,
    TicketChildFetchResult,
    _attachment_metadata_hash,
    _build_ticket_record,
    _content_hash,
    _cursor_clause,
    _enrich_display_values,
    _fetch_table_rows_list,
    _merge_attachment_source_metadata,
    _process_attachments,
    _resolve_attachment_target_path,
    _validate_servicenow_sys_id,
    fetch_closed_tickets,
    _upsert_ticket,
    compute_ticket_retention_expires_at,
    delete_purged_closed_ticket_files,
    purge_expired_closed_tickets,
    purge_expired_closed_tickets_db,
    run_closed_ticket_sync,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TICKET_SYS_ID = "a1b2c3d4e5f6789012345678abcdef01"
ATTACH_SYS_ID = "b2c3d4e5f6789012345678abcdef0123"
OTHER_TICKET_SYS_ID = "c3d4e5f6789012345678abcdef012345"


def _ticket_row(
    sys_id: str = TICKET_SYS_ID,
    *,
    updated_on: str = "2026-06-01 12:00:00",
    closed_at: str = "2026-06-01 11:00:00",
    number: str = "INC001",
    state: str = "3",
) -> dict:
    return {
        "sys_id": sys_id,
        "number": number,
        "state": state,
        "sys_updated_on": updated_on,
        "closed_at": closed_at,
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
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
            SERVICENOW_CLOSED_TICKET_QUERY="state=3",
        )
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": [_ticket_row()]}
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
            return_value=[_ticket_row()],
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._reconcile_active_tickets",
            return_value=ReconcileResult(0, frozenset(), True),
        ):
            summary = run_closed_ticket_sync(config, connect=lambda _dsn: conn)

        self.assertEqual(summary.fetched, 1)
        self.assertEqual(summary.persisted, 1)
        self.assertTrue(summary.cursor_advanced)
        conn.commit.assert_called_once()

    def test_run_closed_ticket_sync_skips_noop_hash(self) -> None:
        row = _ticket_row()
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
            return_value=ReconcileResult(0, frozenset(), True),
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
            return_value=[_ticket_row()],
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._reconcile_active_tickets",
            return_value=ReconcileResult(0, frozenset(), True),
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index.index_pending_closed_tickets",
            return_value=ClosedTicketPendingIndexResult(selected=1, ready=1),
        ) as mock_index:
            summary = run_closed_ticket_sync(config, connect=lambda _dsn: conn)

        mock_index.assert_called_once()
        call_kwargs = mock_index.call_args.kwargs
        self.assertEqual(call_kwargs.get("max_tickets"), 500)
        self.assertEqual(summary.index_selected, 1)
        self.assertEqual(summary.index_ready, 1)

    def test_reconcile_skips_deactivation_when_source_truncated(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
        )
        conn = MagicMock()
        fake_rows = [_ticket_row(OTHER_TICKET_SYS_ID)]
        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._fetch_table_rows_list",
            return_value=(fake_rows, True),
        ):
            from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync import (
                _reconcile_active_tickets,
            )

            result = _reconcile_active_tickets(
                config,
                conn,
                "notable_closed_tickets",
                customer_query="state=3",
                source_table="sn_si_incident",
                retention_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        self.assertFalse(result.complete)
        self.assertEqual(result.deactivated, 0)
        conn.execute.assert_not_called()

    def test_reconcile_deactivates_when_source_complete(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
        )
        conn = MagicMock()
        stale_mock = MagicMock()
        stale_mock.fetchall.return_value = [(OTHER_TICKET_SYS_ID,)]
        deactivate_mock = MagicMock()
        deactivate_mock.rowcount = 1
        conn.execute.side_effect = [stale_mock, deactivate_mock]
        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._fetch_table_rows_list",
            return_value=([_ticket_row()], False),
        ):
            from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync import (
                _reconcile_active_tickets,
            )

            result = _reconcile_active_tickets(
                config,
                conn,
                "notable_closed_tickets",
                customer_query="state=3",
                source_table="sn_si_incident",
                retention_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        self.assertTrue(result.complete)
        self.assertEqual(result.deactivated, 1)

    def test_fetch_table_rows_list_marks_truncated_at_cap(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
        )
        cap = 3
        fake_rows = [_ticket_row() for _ in range(cap)]
        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._fetch_table_rows",
            return_value=iter(fake_rows),
        ):
            rows, truncated = _fetch_table_rows_list(
                config,
                table="sn_si_incident",
                encoded_query="state=3",
                max_records=cap,
            )
        self.assertEqual(len(rows), cap)
        self.assertTrue(truncated)

    def test_journal_fetch_paginates_beyond_page_size(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
        )

        def request_side_effect(*_args: object, **kwargs: object) -> MagicMock:
            offset = int(kwargs.get("params", {}).get("sysparm_offset", "0"))
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            if offset == 0:
                resp.json.return_value = {
                    "result": [{"sys_id": f"j{i:02d}"} for i in range(100)]
                }
            else:
                resp.json.return_value = {
                    "result": [{"sys_id": f"j{i:02d}"} for i in range(100, 150)]
                }
            return resp

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._request_with_retry",
            side_effect=request_side_effect,
        ):
            from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync import (
                fetch_ticket_journals,
            )

            result = fetch_ticket_journals(config, ticket_sys_id=TICKET_SYS_ID)
        self.assertEqual(len(result.rows), 150)
        self.assertFalse(result.truncated)

    def test_journal_fetch_truncated_at_per_ticket_cap(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_CLOSED_TICKET_TOKEN="token",
        )
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "result": [{"sys_id": f"j{i:02d}"} for i in range(100)]
        }
        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._request_with_retry",
            return_value=response,
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.MAX_CHILD_RECORDS_PER_TICKET",
            50,
        ):
            from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync import (
                fetch_ticket_journals,
            )

            result = fetch_ticket_journals(config, ticket_sys_id=TICKET_SYS_ID)
        self.assertEqual(len(result.rows), 50)
        self.assertTrue(result.truncated)

    def test_resolve_attachment_target_path_rejects_traversal(self) -> None:
        root = Path("/var/notables/closed_ticket_attachments")
        with self.assertRaises(ValueError):
            _resolve_attachment_target_path(
                root,
                ticket_id="../evil",
                attachment_id=ATTACH_SYS_ID,
                file_name="x.txt",
            )

    def test_validate_servicenow_sys_id_accepts_32_hex(self) -> None:
        self.assertEqual(
            _validate_servicenow_sys_id(TICKET_SYS_ID, "ticket_id"),
            TICKET_SYS_ID.lower(),
        )

    def test_process_attachments_skips_redownload_when_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attachment_dir = Path(tmp)
            config = Config(
                SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=True,
                CLOSED_TICKET_ATTACHMENT_DIR=attachment_dir,
                SERVICENOW_BASE_URL="https://example.service-now.com",
                SERVICENOW_CLOSED_TICKET_TOKEN="token",
            )
            conn = MagicMock()
            existing_path = str(
                _resolve_attachment_target_path(
                    attachment_dir,
                    ticket_id=TICKET_SYS_ID,
                    attachment_id=ATTACH_SYS_ID,
                    file_name="evidence.txt",
                )
            )
            attachment_row = {
                "sys_id": ATTACH_SYS_ID,
                "file_name": "evidence.txt",
                "size_bytes": "10",
            }
            metadata_hash = _attachment_metadata_hash(_enrich_display_values(attachment_row))

            def execute_side_effect(sql: str, *_args: object, **_kwargs: object) -> MagicMock:
                mock = MagicMock()
                if "FROM notable_closed_tickets.attachments" in sql:
                    mock.fetchone.return_value = (
                        metadata_hash,
                        "downloaded",
                        existing_path,
                        {},
                    )
                return mock

            conn.execute.side_effect = execute_side_effect
            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.fetch_ticket_attachment_rows",
                return_value=TicketChildFetchResult(rows=[attachment_row], truncated=False),
            ), patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._download_attachment_bytes",
            ) as download_mock:
                fetched, downloaded, truncated = _process_attachments(
                    config,
                    conn,
                    "notable_closed_tickets",
                    ticket_id=TICKET_SYS_ID,
                    source_table="sn_si_incident",
                )
            download_mock.assert_not_called()
            self.assertEqual(downloaded, 0)
            self.assertEqual(fetched, 1)
            self.assertFalse(truncated)

    def test_process_attachments_preserves_path_on_failed_redownload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attachment_dir = Path(tmp)
            config = Config(
                SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=True,
                CLOSED_TICKET_ATTACHMENT_DIR=attachment_dir,
                SERVICENOW_BASE_URL="https://example.service-now.com",
                SERVICENOW_CLOSED_TICKET_TOKEN="token",
            )
            conn = MagicMock()
            existing_path = str(
                _resolve_attachment_target_path(
                    attachment_dir,
                    ticket_id=TICKET_SYS_ID,
                    attachment_id=ATTACH_SYS_ID,
                    file_name="evidence.txt",
                )
            )
            Path(existing_path).parent.mkdir(parents=True, exist_ok=True)
            Path(existing_path).write_bytes(b"keep-me")
            attachment_row = {
                "sys_id": ATTACH_SYS_ID,
                "file_name": "evidence.txt",
                "size_bytes": "10",
            }
            metadata_hash = _attachment_metadata_hash(_enrich_display_values(attachment_row))

            def execute_side_effect(sql: str, *_args: object, **_kwargs: object) -> MagicMock:
                mock = MagicMock()
                if "FROM notable_closed_tickets.attachments" in sql:
                    mock.fetchone.return_value = (
                        metadata_hash,
                        "downloaded",
                        existing_path,
                        {},
                    )
                return mock

            conn.execute.side_effect = execute_side_effect
            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.fetch_ticket_attachment_rows",
                return_value=TicketChildFetchResult(rows=[attachment_row], truncated=False),
            ), patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync._download_attachment_bytes",
                return_value=None,
            ):
                _process_attachments(
                    config,
                    conn,
                    "notable_closed_tickets",
                    ticket_id=TICKET_SYS_ID,
                    source_table="sn_si_incident",
                )
            upsert_sql = [
                call
                for call in conn.execute.call_args_list
                if "INSERT INTO notable_closed_tickets.attachments" in str(call.args[0])
            ]
            self.assertTrue(upsert_sql)
            upsert_args = upsert_sql[0].args[1]
            self.assertEqual(upsert_args[6], existing_path)

    def test_purge_expired_closed_tickets_deletes_rows_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attachment_dir = Path(tmp).resolve()
            config = Config(CLOSED_TICKET_ATTACHMENT_DIR=attachment_dir)
            conn = MagicMock()
            file_path = (
                attachment_dir / TICKET_SYS_ID / f"{ATTACH_SYS_ID}_file.txt"
            ).resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"expired")
            path_mock = MagicMock()
            path_mock.fetchall.return_value = [(str(file_path),)]
            delete_mock = MagicMock()
            delete_mock.rowcount = 2
            conn.execute.side_effect = [path_mock, delete_mock]
            tickets_deleted, pending_paths = purge_expired_closed_tickets_db(
                conn, "notable_closed_tickets"
            )
            self.assertEqual(tickets_deleted, 2)
            self.assertEqual(pending_paths, [str(file_path)])
            self.assertTrue(file_path.exists())
            files_deleted = delete_purged_closed_ticket_files(config, pending_paths)
            self.assertEqual(files_deleted, 1)
            self.assertFalse(file_path.exists())

    def test_purge_db_failure_leaves_files_when_unlink_not_called(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attachment_dir = Path(tmp).resolve()
            config = Config(CLOSED_TICKET_ATTACHMENT_DIR=attachment_dir)
            file_path = (
                attachment_dir / TICKET_SYS_ID / f"{ATTACH_SYS_ID}_keep.txt"
            ).resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"keep")
            conn = MagicMock()
            path_mock = MagicMock()
            path_mock.fetchall.return_value = [(str(file_path),)]
            conn.execute.side_effect = [path_mock, RuntimeError("db delete failed")]
            with self.assertRaises(RuntimeError):
                purge_expired_closed_tickets_db(conn, "notable_closed_tickets")
            self.assertTrue(file_path.exists())
            self.assertEqual(
                delete_purged_closed_ticket_files(config, [str(file_path)]), 1
            )

    def test_retention_expires_one_day_after_29_day_closed_ticket(self) -> None:
        closed_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        synced_at = closed_at + timedelta(days=29)
        expires_at = compute_ticket_retention_expires_at(
            closed_at=closed_at,
            source_updated_at=synced_at,
            retention_days=30,
            synced_at=synced_at,
        )
        self.assertEqual(expires_at, closed_at + timedelta(days=30))
        self.assertEqual(expires_at - synced_at, timedelta(days=1))

    def test_retention_fallback_to_source_updated_at_without_closed_at(self) -> None:
        source_updated = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
        synced_at = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        expires_at = compute_ticket_retention_expires_at(
            closed_at=None,
            source_updated_at=source_updated,
            retention_days=30,
            synced_at=synced_at,
        )
        self.assertEqual(expires_at, source_updated + timedelta(days=30))

    def test_retention_fallback_to_sync_time_when_closure_fields_missing(self) -> None:
        synced_at = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        expires_at = compute_ticket_retention_expires_at(
            closed_at=None,
            source_updated_at=None,
            retention_days=30,
            synced_at=synced_at,
        )
        self.assertEqual(expires_at, synced_at + timedelta(days=30))

    def test_upsert_marks_already_expired_ticket_not_indexed(self) -> None:
        synced_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        row = _ticket_row(
            updated_on="2026-06-01 12:00:00",
            closed_at="2026-01-01 12:00:00",
        )
        ticket = _build_ticket_record(
            row,
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=[],
        )
        conn = MagicMock()
        hash_mock = MagicMock()
        hash_mock.fetchone.return_value = None
        insert_mock = MagicMock()
        conn.execute.side_effect = [hash_mock, insert_mock]
        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.datetime",
        ) as dt_mock:
            dt_mock.now.return_value = synced_at
            dt_mock.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            _upsert_ticket(
                conn,
                "notable_closed_tickets",
                ticket,
                retention_days=30,
            )
        insert_args = conn.execute.call_args_list[-1].args[1]
        self.assertEqual(insert_args[-1], "not_indexed")
        upsert_sql = str(conn.execute.call_args_list[-1].args[0])
        self.assertIn("THEN EXCLUDED.index_status", upsert_sql)

    def test_upsert_update_path_keeps_not_indexed_for_expired_changed_ticket(self) -> None:
        synced_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        row = _ticket_row(
            updated_on="2026-06-01 12:00:00",
            closed_at="2026-01-01 12:00:00",
        )
        ticket = _build_ticket_record(
            row,
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=[],
        )
        changed_ticket = _build_ticket_record(
            {**row, "short_description": "changed payload"},
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=[],
        )
        conn = MagicMock()
        hash_mock = MagicMock()
        hash_mock.fetchone.return_value = ticket.content_hash
        upsert_mock = MagicMock()
        chunk_delete_mock = MagicMock()
        conn.execute.side_effect = [hash_mock, upsert_mock, chunk_delete_mock]
        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.datetime",
        ) as dt_mock:
            dt_mock.now.return_value = synced_at
            dt_mock.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            result = _upsert_ticket(
                conn,
                "notable_closed_tickets",
                changed_ticket,
                retention_days=30,
            )
        self.assertEqual(result, "updated")
        upsert_args = conn.execute.call_args_list[1].args[1]
        self.assertEqual(upsert_args[-1], "not_indexed")
        upsert_sql = str(conn.execute.call_args_list[1].args[0])
        self.assertIn("THEN EXCLUDED.index_status", upsert_sql)
        self.assertNotIn("THEN 'pending'", upsert_sql)
        chunk_sql = str(conn.execute.call_args_list[2].args[0])
        self.assertIn("DELETE FROM notable_closed_tickets.ticket_chunks", chunk_sql)

    def test_upsert_update_path_pending_for_active_changed_ticket(self) -> None:
        synced_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        row = _ticket_row(
            updated_on="2026-06-01 12:00:00",
            closed_at="2026-05-15 12:00:00",
        )
        ticket = _build_ticket_record(
            row,
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=[],
        )
        changed_ticket = _build_ticket_record(
            {**row, "short_description": "still active window"},
            source_table="sn_si_incident",
            base_url="https://example.service-now.com",
            journals_payload=[],
        )
        conn = MagicMock()
        hash_mock = MagicMock()
        hash_mock.fetchone.return_value = ticket.content_hash
        upsert_mock = MagicMock()
        conn.execute.side_effect = [hash_mock, upsert_mock]
        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.datetime",
        ) as dt_mock:
            dt_mock.now.return_value = synced_at
            dt_mock.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            _upsert_ticket(
                conn,
                "notable_closed_tickets",
                changed_ticket,
                retention_days=30,
            )
        upsert_args = conn.execute.call_args_list[1].args[1]
        self.assertEqual(upsert_args[-1], "pending")
        self.assertEqual(len(conn.execute.call_args_list), 2)

    def test_purge_expired_closed_tickets_commits_before_file_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attachment_dir = Path(tmp).resolve()
            config = Config(CLOSED_TICKET_ATTACHMENT_DIR=attachment_dir)
            file_path = (
                attachment_dir / TICKET_SYS_ID / f"{ATTACH_SYS_ID}_purge.txt"
            ).resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"purge")
            conn = MagicMock()
            path_mock = MagicMock()
            path_mock.fetchall.return_value = [(str(file_path),)]
            delete_mock = MagicMock()
            delete_mock.rowcount = 1
            conn.execute.side_effect = [path_mock, delete_mock]
            call_order: list[str] = []
            conn.commit.side_effect = lambda: call_order.append("commit")
            with patch(
                "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync.delete_purged_closed_ticket_files",
                side_effect=lambda *_a, **_k: call_order.append("delete_files"),
            ):
                purge_expired_closed_tickets(config, conn, "notable_closed_tickets")
            self.assertEqual(call_order, ["commit", "delete_files"])
            conn.commit.assert_called_once()

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
