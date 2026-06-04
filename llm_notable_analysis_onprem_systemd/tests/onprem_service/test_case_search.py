from datetime import datetime, timezone
import json
import unittest

from llm_notable_analysis_onprem_systemd.onprem_service.case_search import (
    CaseChunkWriteError,
    build_case_chunks,
    build_chunk_id,
    build_insert_case_chunks_sql,
    build_select_case_records_sql,
    dry_run_case_chunk_rebuild,
    fetch_case_records,
    mark_case_retrieval_status,
    rebuild_case_chunks,
    store_case_chunks,
)
from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config


class _FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, rows=None, row_pages=None, fail_once_on_execute=False):
        self.executed = []
        self.executemany_calls = []
        self.rows = rows or []
        self.row_pages = list(row_pages or [])
        self.fail_once_on_execute = fail_once_on_execute

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        if self.fail_once_on_execute:
            self.fail_once_on_execute = False
            raise OSError("temporary database failure")
        self.executed.append((sql, params))
        if "FROM" in sql and ".cases" in sql and "SELECT" in sql:
            if self.row_pages:
                return _FakeResult(self.row_pages.pop(0))
            return _FakeResult(self.rows)
        return _FakeResult([])

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, list(rows)))


class _FakeEmbeddingModel:
    def __init__(self):
        self.encoded_texts = []

    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        self.encoded_texts.extend(texts)
        return [[1.0] + [0.0] * 767 for _text in texts]


class _BadDimensionEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        return [[1.0, 0.0] for _text in texts]


def _analysis() -> dict:
    return {
        "alert_reconciliation": {
            "verdict": "likely malicious",
            "confidence": "0.82",
            "one_sentence_summary": "Suspicious PowerShell from admin host.",
        },
        "competing_hypotheses": [
            {
                "hypothesis_type": "benign",
                "summary": "Admin script.",
                "supporting_evidence": ["known admin host"],
            },
            {
                "hypothesis_type": "adversary",
                "summary": "Credentialed execution.",
                "supporting_evidence": ["encoded command"],
            },
        ],
        "evidence_vs_inference": {"evidence": ["user=admin"], "inferences": []},
        "ioc_extraction": {"ips": ["10.0.0.1"], "domains": ["example.test"]},
        "ttp_analysis": [{"ttp_id": "T1059.001", "confidence_score": 0.8}],
        "query_result_section": {"status": "not_run", "results": []},
        "servicenow_section": {"draft": {"status": "skipped"}},
    }


def _record(config: Config):
    return build_case_archive_record(
        config=config,
        case_id="case-1",
        finding_id="case-1",
        source_filename="case-1.json",
        alert_payload={
            "notable_id": "abc-123",
            "search_name": "Suspicious PowerShell",
            "riskScore": "42",
            "user": "admin",
            "host": "workstation-1",
            "command_line": "powershell -enc AAAA",
        },
        analysis=_analysis(),
        report_md_path="/reports/case-1.md",
        report_html_path=None,
        processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )


def _row_from_record(record):
    return (
        record.case_id,
        record.finding_id,
        record.source_filename,
        record.processed_at,
        record.expires_at,
        record.correlation_id,
        json.dumps(record.capability_snapshot),
        json.dumps(record.archive_metadata),
        json.dumps(record.alert_payload),
        json.dumps(record.analysis),
        record.case_schema_version,
        record.analysis_schema_version,
        record.verdict,
        record.confidence,
        record.search_name,
        record.risk_score,
        record.report_md_path,
        record.report_html_path,
        record.retrieval_status,
        record.backfill_status,
        record.source_completeness,
    )


class TestCaseSearch(unittest.TestCase):
    def test_build_case_chunks_covers_initial_sections_and_citations(self) -> None:
        config = Config()
        chunks = build_case_chunks(_record(config), config)

        sections = {chunk.section for chunk in chunks}
        self.assertIn("alert.summary", sections)
        self.assertIn("alert.key_fields", sections)
        self.assertIn("analysis.alert_reconciliation", sections)
        self.assertIn("analysis.competing_hypotheses", sections)
        self.assertIn("analysis.evidence_vs_inference", sections)
        self.assertIn("analysis.ioc_extraction", sections)
        self.assertIn("analysis.ttp_analysis", sections)
        self.assertIn("analysis.query_result_section", sections)
        self.assertIn("analysis.servicenow_section", sections)
        self.assertEqual(
            {chunk.source_lane for chunk in chunks},
            {"alert_payload", "case_analysis"},
        )
        for chunk in chunks:
            self.assertEqual(chunk.case_id, "case-1")
            self.assertTrue(chunk.chunk_id.startswith("case-1:"))
            self.assertEqual(chunk.metadata["chunk_id"], chunk.chunk_id)
            self.assertEqual(chunk.metadata["stored_source_lane"], chunk.source_lane)
            self.assertEqual(chunk.metadata["field_path"], chunk.field_path)

    def test_build_insert_sql_targets_case_chunks(self) -> None:
        sql = build_insert_case_chunks_sql("notable_cases")

        self.assertIn('INSERT INTO "notable_cases".case_chunks', sql)
        self.assertIn("%s::vector", sql)
        self.assertIn("%s::jsonb", sql)
        self.assertIn("ON CONFLICT (chunk_id) DO UPDATE", sql)

    def test_store_case_chunks_replaces_rows_and_marks_ready(self) -> None:
        config = Config()
        connection = _FakeConnection()
        model = _FakeEmbeddingModel()

        count = store_case_chunks(
            record=_record(config),
            config=config,
            connect=lambda _dsn: connection,
            embedding_model=model,
        )

        self.assertGreater(count, 0)
        self.assertEqual(len(model.encoded_texts), count)
        self.assertTrue(
            any("DELETE FROM" in sql for sql, _params in connection.executed)
        )
        self.assertEqual(len(connection.executemany_calls), 1)
        insert_sql, rows = connection.executemany_calls[0]
        self.assertIn('INSERT INTO "notable_cases".case_chunks', insert_sql)
        self.assertTrue(rows[0][6].startswith("[1.00000000,0.00000000"))
        self.assertEqual(rows[0][6].count(","), 767)
        self.assertIn(
            (
                'UPDATE "notable_cases".cases SET retrieval_status = %s WHERE case_id = %s',
                ("ready", "case-1"),
            ),
            connection.executed,
        )

    def test_store_case_chunks_embeds_before_opening_database_connection(self) -> None:
        config = Config()
        model = _FakeEmbeddingModel()
        connection = _FakeConnection()

        def connect(_dsn):
            self.assertGreater(len(model.encoded_texts), 0)
            return connection

        count = store_case_chunks(
            record=_record(config),
            config=config,
            connect=connect,
            embedding_model=model,
        )

        self.assertGreater(count, 0)

    def test_store_case_chunks_retries_transient_database_failures(self) -> None:
        config = Config(
            CASE_ARCHIVE_WRITE_MAX_ATTEMPTS=2,
            CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS=1,
        )
        first = _FakeConnection(fail_once_on_execute=True)
        second = _FakeConnection()
        connections = [first, second]
        sleeps = []
        model = _FakeEmbeddingModel()

        count = store_case_chunks(
            record=_record(config),
            config=config,
            connect=lambda _dsn: connections.pop(0),
            embedding_model=model,
            sleep=sleeps.append,
        )

        self.assertGreater(count, 0)
        self.assertEqual(sleeps, [1.0])
        self.assertEqual(len(model.encoded_texts), count)

    def test_store_case_chunks_rejects_embedding_dimension_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimension mismatch"):
            store_case_chunks(
                record=_record(Config()),
                config=Config(),
                connect=lambda _dsn: _FakeConnection(),
                embedding_model=_BadDimensionEmbeddingModel(),
            )

    def test_store_case_chunks_marks_not_indexed_when_no_chunks_exist(self) -> None:
        config = Config()
        connection = _FakeConnection()
        record = build_case_archive_record(
            config=config,
            case_id="raw-case",
            finding_id="raw-case",
            source_filename="raw-case.txt",
            alert_payload={},
            analysis={"poc_unstructured_output": True},
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        count = store_case_chunks(
            record=record,
            config=config,
            connect=lambda _dsn: connection,
            embedding_model=_FakeEmbeddingModel(),
        )

        self.assertEqual(count, 0)
        self.assertFalse(connection.executemany_calls)
        self.assertIn(
            (
                'UPDATE "notable_cases".cases SET retrieval_status = %s WHERE case_id = %s',
                ("not_indexed", "raw-case"),
            ),
            connection.executed,
        )

    def test_plain_text_alert_payload_is_chunked(self) -> None:
        config = Config()
        record = build_case_archive_record(
            config=config,
            case_id="text-case",
            finding_id="text-case",
            source_filename="text-case.txt",
            alert_payload="plain text alert body",
            analysis=_analysis(),
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        chunks = build_case_chunks(record, config)

        self.assertTrue(
            any(
                chunk.section == "alert.summary"
                and "plain text alert body" in chunk.text
                for chunk in chunks
            )
        )

    def test_large_scalar_analysis_fields_are_split(self) -> None:
        config = Config()
        analysis = _analysis()
        analysis["alert_reconciliation"]["one_sentence_summary"] = "a" * 6000
        record = build_case_archive_record(
            config=config,
            case_id="large-case",
            finding_id="large-case",
            source_filename="large-case.json",
            alert_payload={"summary": "alert"},
            analysis=analysis,
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        chunks = [
            chunk
            for chunk in build_case_chunks(record, config)
            if chunk.field_path == "$.alert_reconciliation.one_sentence_summary"
        ]

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text) <= 2600 for chunk in chunks))

    def test_deep_json_alert_does_not_recurse_unbounded(self) -> None:
        payload = {"user": "admin"}
        for _ in range(80):
            payload = {"nested": payload}
        record = build_case_archive_record(
            config=Config(),
            case_id="deep-case",
            finding_id="deep-case",
            source_filename="deep-case.json",
            alert_payload=payload,
            analysis=_analysis(),
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )

        chunks = build_case_chunks(record, Config())

        self.assertGreater(len(chunks), 0)

    def test_chunk_id_adds_hash_when_sanitized_component_changes(self) -> None:
        chunk_id = build_chunk_id(
            case_id="case:one",
            source_lane="case_analysis",
            section="analysis.alert_reconciliation",
            ordinal=0,
        )

        self.assertRegex(chunk_id, r"case_one_[0-9a-f]{12}:")

    def test_fetch_and_dry_run_rebuild_use_stored_case_rows(self) -> None:
        config = Config()
        record = _record(config)
        connection = _FakeConnection(rows=[_row_from_record(record)])

        records = fetch_case_records(
            config=config,
            case_id="case-1",
            limit=25,
            connect=lambda _dsn: connection,
        )
        result = dry_run_case_chunk_rebuild(
            config=config,
            case_id="case-1",
            batch_size=25,
            connect=lambda _dsn: connection,
        )

        self.assertEqual(records[0].case_id, "case-1")
        self.assertIn(
            "WHERE case_id = %s",
            build_select_case_records_sql("notable_cases", case_id="case-1"),
        )
        self.assertIn("LIMIT %s", build_select_case_records_sql("notable_cases"))
        self.assertEqual(result["cases"], 1)
        self.assertGreater(result["chunks"], 0)

    def test_dry_run_rebuild_pages_all_cases(self) -> None:
        config = Config()
        record_1 = _record(config)
        record_2 = build_case_archive_record(
            config=config,
            case_id="case-2",
            finding_id="case-2",
            source_filename="case-2.json",
            alert_payload={"summary": "second"},
            analysis=_analysis(),
            report_md_path=None,
            report_html_path=None,
            processed_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
        )
        connection = _FakeConnection(
            row_pages=[
                [_row_from_record(record_1)],
                [_row_from_record(record_2)],
                [],
            ]
        )

        result = dry_run_case_chunk_rebuild(
            config=config,
            batch_size=1,
            connect=lambda _dsn: connection,
        )

        self.assertEqual(result["cases"], 2)
        self.assertGreater(result["chunks"], 0)
        self.assertEqual(
            connection.executed[3][1],
            (record_1.processed_at, record_1.processed_at, record_1.case_id, 1),
        )

    def test_rebuild_case_chunks_fetches_then_stores(self) -> None:
        config = Config()
        record = _record(config)
        connection = _FakeConnection(rows=[_row_from_record(record)])
        model = _FakeEmbeddingModel()

        result = rebuild_case_chunks(
            config=config,
            batch_size=10,
            connect=lambda _dsn: connection,
            embedding_model=model,
        )

        self.assertEqual(result["cases"], 1)
        self.assertGreater(result["chunks"], 0)
        self.assertEqual(len(connection.executemany_calls), 1)

    def test_mark_case_retrieval_status_rejects_unknown_status(self) -> None:
        with self.assertRaises(ValueError):
            mark_case_retrieval_status(
                config=Config(),
                case_id="case-1",
                status="done",
                connect=lambda _dsn: _FakeConnection(),
            )

    def test_mark_case_retrieval_status_retries_transient_failures(self) -> None:
        config = Config(
            CASE_ARCHIVE_WRITE_MAX_ATTEMPTS=2,
            CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS=1,
        )
        connections = [_FakeConnection(fail_once_on_execute=True), _FakeConnection()]
        sleeps = []

        mark_case_retrieval_status(
            config=config,
            case_id="case-1",
            status="failed",
            connect=lambda _dsn: connections.pop(0),
            sleep=sleeps.append,
        )

        self.assertEqual(sleeps, [1.0])

    def test_mark_case_retrieval_status_wraps_non_retryable_failures(self) -> None:
        class BadConnection(_FakeConnection):
            def execute(self, sql, params=None):
                raise ValueError("bad schema")

        with self.assertRaises(CaseChunkWriteError):
            mark_case_retrieval_status(
                config=Config(),
                case_id="case-1",
                status="failed",
                connect=lambda _dsn: BadConnection(),
            )


if __name__ == "__main__":
    unittest.main()
