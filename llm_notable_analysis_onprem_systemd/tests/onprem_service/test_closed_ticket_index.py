import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index import (
    ClosedTicketChunkWriteError,
    ClosedTicketIndexResult,
    build_delete_ticket_chunks_sql,
    build_insert_ticket_chunks_sql,
    build_select_attachments_for_ticket_sql,
    build_select_pending_tickets_for_index_sql,
    fetch_attachment_records_for_ticket,
    index_closed_ticket,
    index_pending_closed_tickets,
    read_bounded_attachment_bytes,
    resolve_safe_attachment_path,
    store_closed_ticket_chunks_once,
)
from llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_render import (
    ClosedTicketRecord,
    build_closed_ticket_chunks,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config


class _FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, attachment_rows=None):
        self.executed = []
        self.executemany_calls = []
        self.attachment_rows = attachment_rows or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "attachments" in sql and "SELECT" in sql:
            return _FakeResult(self.attachment_rows)
        return _FakeResult([])

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, list(rows)))


class _FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        return [[1.0] + [0.0] * 1023 for _ in texts]


def _config() -> Config:
    config = Config()
    object.__setattr__(config, "CASE_POSTGRES_DSN", "postgresql://example")
    object.__setattr__(config, "CLOSED_TICKET_POSTGRES_SCHEMA", "notable_closed_tickets")
    object.__setattr__(config, "CLOSED_TICKET_POSTGRES_CHUNKS_TABLE", "ticket_chunks")
    return config


def _active_record() -> ClosedTicketRecord:
    return ClosedTicketRecord(
        ticket_id="ticket-1",
        ticket_number="INC100",
        source_table="incident",
        source_url="https://sn.example/INC100",
        state="Closed",
        is_active=True,
        closed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw_payload={"short_description": "Benign login"},
        journals_payload=[],
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )


class TestClosedTicketIndex(unittest.TestCase):
    def test_sql_builders_quote_schema_and_table(self) -> None:
        delete_sql = build_delete_ticket_chunks_sql("notable_closed_tickets", "ticket_chunks")
        insert_sql = build_insert_ticket_chunks_sql("notable_closed_tickets", "ticket_chunks")
        self.assertIn('"notable_closed_tickets"."ticket_chunks"', delete_sql)
        self.assertIn("ON CONFLICT (chunk_id)", insert_sql)
        self.assertNotIn("search_vector", insert_sql)
        self.assertNotIn("created_at", insert_sql)

    def test_pending_ticket_sql_filters_active_unexpired_status(self) -> None:
        sql = build_select_pending_tickets_for_index_sql("notable_closed_tickets")
        self.assertIn("is_active = true", sql)
        self.assertIn("expires_at > now()", sql)
        self.assertIn("index_status IN ('pending', 'failed')", sql)

    def test_index_pending_processes_bounded_batch(self) -> None:
        config = _config()
        object.__setattr__(config, "CLOSED_TICKET_RAG_ENABLED", True)
        record = _active_record()
        conn = _FakeConnection()

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index.fetch_pending_ticket_records",
            return_value=[record],
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index.fetch_attachment_records_for_ticket",
            return_value=[],
        ), patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index.index_closed_ticket",
            return_value=ClosedTicketIndexResult(
                ticket_id=record.ticket_id,
                chunk_count=2,
                status="ready",
            ),
        ):
            result = index_pending_closed_tickets(
                config=config,
                max_tickets=1,
                connect=lambda _dsn: conn,
                embedding_model=_FakeEmbeddingModel(),
            )
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.ready, 1)

    def test_store_chunks_deletes_then_upserts_and_sets_status(self) -> None:
        config = _config()
        conn = _FakeConnection()
        chunks = build_closed_ticket_chunks(_active_record(), config)
        rows = [
            (
                chunk.chunk_id,
                chunk.ticket_id,
                chunk.ordinal,
                chunk.section,
                chunk.field_path,
                chunk.text,
                "[1.0]",
                "{}",
                chunk.chunk_schema_version,
                chunk.embedding_model,
            )
            for chunk in chunks[:1]
        ]
        count = store_closed_ticket_chunks_once(
            ticket_id="ticket-1",
            config=config,
            rows=rows,
            index_status="ready",
            index_error=None,
            connect=lambda _dsn: conn,
        )
        self.assertEqual(count, 1)
        delete_calls = [sql for sql, _ in conn.executed if str(sql).startswith("DELETE FROM")]
        self.assertEqual(len(delete_calls), 1)
        self.assertEqual(len(conn.executemany_calls), 1)
        self.assertIn("index_status", conn.executed[-1][0])

    def test_index_skips_inactive_ticket_and_deletes_chunks(self) -> None:
        config = _config()
        conn = _FakeConnection()
        record = _active_record()
        inactive = ClosedTicketRecord(
            ticket_id=record.ticket_id,
            ticket_number=record.ticket_number,
            source_table=record.source_table,
            source_url=record.source_url,
            state=record.state,
            is_active=False,
            closed_at=record.closed_at,
            source_updated_at=record.source_updated_at,
            raw_payload=record.raw_payload,
            journals_payload=record.journals_payload,
            expires_at=record.expires_at,
        )
        result = index_closed_ticket(
            record=inactive,
            config=config,
            connect=lambda _dsn: conn,
            embedding_model=_FakeEmbeddingModel(),
        )
        self.assertTrue(result.skipped)
        self.assertEqual(result.status, "not_indexed")
        delete_calls = [sql for sql, _ in conn.executed if str(sql).startswith("DELETE FROM")]
        self.assertEqual(len(delete_calls), 1)
        self.assertEqual(conn.executemany_calls, [])

    def test_index_marks_failed_on_embedding_error(self) -> None:
        config = _config()
        conn = _FakeConnection()

        class _BadModel:
            def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
                del show_progress_bar, convert_to_numpy, texts
                raise RuntimeError("embed failed")

        with self.assertRaises(ClosedTicketChunkWriteError):
            index_closed_ticket(
                record=_active_record(),
                config=config,
                connect=lambda _dsn: conn,
                embedding_model=_BadModel(),
            )
        status_update = conn.executed[-1]
        self.assertEqual(status_update[1][0], "failed")

    def test_index_skips_expired_ticket(self) -> None:
        config = _config()
        conn = _FakeConnection()
        record = _active_record()
        expired = ClosedTicketRecord(
            ticket_id=record.ticket_id,
            ticket_number=record.ticket_number,
            source_table=record.source_table,
            source_url=record.source_url,
            state=record.state,
            is_active=True,
            closed_at=record.closed_at,
            source_updated_at=record.source_updated_at,
            raw_payload=record.raw_payload,
            journals_payload=record.journals_payload,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        result = index_closed_ticket(
            record=expired,
            config=config,
            connect=lambda _dsn: conn,
            embedding_model=_FakeEmbeddingModel(),
        )
        self.assertTrue(result.skipped)

    def test_attachment_select_sql_matches_ddl_columns(self) -> None:
        sql = build_select_attachments_for_ticket_sql("notable_closed_tickets")
        self.assertIn("file_name", sql)
        self.assertIn("storage_path", sql)
        self.assertIn("download_status", sql)
        self.assertNotIn("raw_content", sql)
        self.assertNotIn("filename", sql)

    def test_resolve_safe_attachment_path_rejects_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "attachments"
            root.mkdir()
            outside = Path(tmpdir) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            config = _config()
            object.__setattr__(config, "CLOSED_TICKET_ATTACHMENT_DIR", root)
            resolved = resolve_safe_attachment_path(config, str(outside))
            self.assertIsNone(resolved)

    def test_fetch_attachment_reads_storage_path_and_persists_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ticket_dir = root / "ticket-1"
            ticket_dir.mkdir()
            file_path = ticket_dir / "att-1_note.txt"
            file_path.write_text("Known admin script activity.", encoding="utf-8")
            config = _config()
            object.__setattr__(config, "CLOSED_TICKET_ATTACHMENT_DIR", root)
            attachment_rows = [
                (
                    "att-1",
                    "ticket-1",
                    "note.txt",
                    "text/plain",
                    str(file_path),
                    json.dumps({}),
                    "downloaded",
                )
            ]
            conn = _FakeConnection(attachment_rows=attachment_rows)
            records = fetch_attachment_records_for_ticket(
                config=config,
                ticket_id="ticket-1",
                connect=lambda _dsn: conn,
            )
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].semantic_text, "Known admin script activity.")
            update_calls = [
                (sql, params)
                for sql, params in conn.executed
                if "UPDATE" in sql and "metadata" in sql
            ]
            self.assertEqual(len(update_calls), 1)
            persisted = json.loads(update_calls[0][1][0])
            self.assertEqual(
                persisted["semantic_description"],
                "Known admin script activity.",
            )
            self.assertEqual(persisted["semantic_extraction_status"], "text_decoded")

    def test_read_bounded_attachment_bytes_limits_reads(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"abcdefghij")
            path = Path(handle.name)
        try:
            payload = read_bounded_attachment_bytes(path, max_bytes=4)
            self.assertEqual(payload, b"abcd")
        finally:
            path.unlink(missing_ok=True)
