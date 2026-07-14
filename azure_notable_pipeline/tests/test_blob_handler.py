"""Azure-native core analyzer handler behavior tests."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from azure_notable_pipeline import blob_handler
from azure_notable_pipeline.blob_store import (
    BlobConditionFailedError,
    BlobInfo,
    BlobReadResult,
)
from azure_notable_pipeline.config import Config
from azure_notable_pipeline.queue_publisher import (
    EmbedQueueJob,
    QueuePublisherConfigurationError,
    enqueue_case_embed,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 10, 12, 34, 56, tzinfo=UTC)


def _intake(**overrides):
    values = {
        "container_name": "input",
        "blob_name": "incoming/finding-123.json",
        "etag": '"etag-1"',
        "size_bytes": 28,
        "last_modified": "2026-07-10T12:34:56Z",
    }
    values.update(overrides)
    return blob_handler.BlobCreatedInput(**values)


def _read_result(body: bytes, *, etag: str = '"etag-1"') -> BlobReadResult:
    return BlobReadResult(
        body=body,
        info=BlobInfo(
            blob_name="incoming/finding-123.json",
            etag=etag,
            size_bytes=len(body),
            last_modified=NOW,
            content_type="application/json",
        ),
    )


class FakeAnalyzer:
    def __init__(self) -> None:
        self.last_llm_response = {
            "ttp_analysis": [],
            "alert_reconciliation": {
                "verdict": "unknown",
                "confidence": 0.5,
                "one_sentence_summary": "One alert was received.",
                "decision_drivers": [],
                "recommended_actions": [],
            },
            "ioc_extraction": {},
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "competing_hypotheses": [],
        }
        self.formatted_payload = None

    def format_alert_input(self, payload, **_kwargs) -> str:
        self.formatted_payload = payload
        return json.dumps(payload, separators=(",", ":"))

    def analyze_ttp(self, _alert_text: str, advisory_context: str = ""):
        return []


def test_native_trigger_fixture_authors_exact_strict_job() -> None:
    observation = json.loads(
        (PROJECT_ROOT / "events" / "blob-trigger-observation.json").read_text()
    )
    expected = json.loads(
        (PROJECT_ROOT / "events" / "analyzer-job.v1.json").read_text()
    )
    calls = []

    def enqueue(**kwargs):
        calls.append(kwargs)

    result = blob_handler.publish_blob_trigger_input(
        SimpleNamespace(**observation),
        config=Config(),
        publisher=object(),
        enqueue=enqueue,
    )

    assert result == expected
    assert calls[0] == {
        **{key: value for key, value in expected.items() if key != "schema_version"},
        "publisher": calls[0]["publisher"],
    }


def test_bounded_gzip_and_json_normalization_preserve_notable_behavior() -> None:
    decoded = blob_handler.decode_blob_notable(
        "incoming/finding-123.json.gz",
        gzip.compress(b'{"finding_id":"finding-123"}'),
        config=Config(MAX_DECOMPRESSED_INPUT_BYTES=64),
    )

    assert decoded.was_compressed is True
    assert decoded.content_type == "json"
    assert blob_handler.normalize_notable(decoded.content, decoded.content_type) == {
        "finding_id": "finding-123"
    }

    with pytest.raises(ValueError, match="Decompressed input exceeds"):
        blob_handler.decode_blob_notable(
            "incoming/large.json.gz",
            gzip.compress(b"x" * 65),
            config=Config(MAX_DECOMPRESSED_INPUT_BYTES=64),
        )
    with pytest.raises(ValueError, match="Invalid gzip content"):
        blob_handler.decode_blob_notable(
            "incoming/broken.json.gz",
            b"not-gzip",
            config=Config(),
        )


def test_report_writer_uses_deterministic_paths_and_optional_html(monkeypatch) -> None:
    writes = []
    monkeypatch.setattr(
        blob_handler,
        "write_text_blob",
        lambda container, name, text, **kwargs: writes.append(
            (container, name, text, kwargs["content_type"], kwargs["overwrite"])
        ),
    )

    result = blob_handler.write_to_blob_sink(
        "incoming/finding-123.json.gz",
        "# Report",
        {
            "alert_payload": {"finding_id": "finding-123"},
            "llm_response": {"answer": "ok"},
            "html": "<html></html>",
        },
        config=Config(HTML_REPORT_ENABLED=True),
    )

    assert result == {
        "status": "success",
        "container": "output",
        "markdown_key": "reports/finding-123.md",
        "json_key": "reports/finding-123.json",
        "html_key": "reports/finding-123.html",
    }
    assert [(item[1], item[3]) for item in writes] == [
        ("reports/finding-123.md", "text/markdown"),
        ("reports/finding-123.json", "application/json"),
        ("reports/finding-123.html", "text/html"),
    ]
    assert all(item[4] is True for item in writes)


def test_report_fallback_identity_distinguishes_same_basename_in_other_prefixes(
    monkeypatch,
) -> None:
    writes = []
    monkeypatch.setattr(
        blob_handler,
        "write_text_blob",
        lambda _container, name, _text, **_kwargs: writes.append(name),
    )
    analysis_result = {"llm_response": {"answer": "ok"}}

    first = blob_handler.write_to_blob_sink(
        "incoming/team-a/alert.json", "# A", analysis_result, config=Config()
    )
    second = blob_handler.write_to_blob_sink(
        "incoming/team-b/alert.json", "# B", analysis_result, config=Config()
    )

    assert first["markdown_key"] != second["markdown_key"]
    assert first["markdown_key"].startswith("reports/alert-")
    assert second["markdown_key"].startswith("reports/alert-")
    assert len(set(writes)) == 4

    other_container = blob_handler.write_to_blob_sink(
        "incoming/team-a/alert.json",
        "# Other",
        {
            "llm_response": {"answer": "ok"},
            "meta": {"source_container": "other-input"},
        },
        config=Config(),
    )
    assert other_container["markdown_key"] != first["markdown_key"]


def test_report_fallback_identity_sanitizes_valid_blob_name_punctuation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(blob_handler, "write_text_blob", lambda *_a, **_k: None)

    result = blob_handler.write_to_blob_sink(
        "incoming/team-a/Alert with spaces (1).json",
        "# Report",
        {"llm_response": {"answer": "ok"}},
        config=Config(),
    )

    assert result["markdown_key"].startswith("reports/Alert_with_spaces_1-")
    assert result["markdown_key"].endswith(".md")


def test_gzip_download_is_bounded_before_readall(monkeypatch) -> None:
    body = gzip.compress(b'{"finding_id":"finding-123"}')
    reads = []

    def read(container, name, **kwargs):
        reads.append((container, name, kwargs))
        return _read_result(body)

    monkeypatch.setattr(blob_handler, "read_blob_result", read)
    monkeypatch.setattr(blob_handler, "write_text_blob", lambda *_a, **_k: None)

    blob_handler.process_blob_created(
        _intake(blob_name="incoming/finding-123.json.gz", size_bytes=len(body)),
        config=Config(MAX_COMPRESSED_INPUT_BYTES=128),
        analyzer=FakeAnalyzer(),
    )

    assert reads[0][2]["max_bytes"] == 128

    with pytest.raises(ValueError, match="MAX_COMPRESSED_INPUT_BYTES"):
        blob_handler.process_blob_created(
            _intake(blob_name="incoming/finding-123.json.gz", size_bytes=129),
            config=Config(MAX_COMPRESSED_INPUT_BYTES=128),
            analyzer=FakeAnalyzer(),
        )


def test_core_handler_reads_exact_etag_analyzes_and_writes_reports(monkeypatch) -> None:
    body = b'{"finding_id":"finding-123"}'
    reads = []
    writes = []
    analyzer = FakeAnalyzer()

    def read(container, name, **kwargs):
        reads.append((container, name, kwargs))
        return _read_result(body)

    monkeypatch.setattr(blob_handler, "read_blob_result", read)
    monkeypatch.setattr(
        blob_handler,
        "write_text_blob",
        lambda container, name, text, **kwargs: writes.append((container, name, text)),
    )

    result = blob_handler.process_blob_created(
        _intake(size_bytes=len(body)),
        config=Config(),
        analyzer=analyzer,
    )

    assert result["status"] == "success"
    assert analyzer.formatted_payload == {"finding_id": "finding-123"}
    assert reads == [
        (
            "input",
            "incoming/finding-123.json",
            {"if_match": '"etag-1"', "max_bytes": 1_048_576, "store": None},
        )
    ]
    assert [name for _container, name, _text in writes] == [
        "reports/finding-123.md",
        "reports/finding-123.json",
    ]


def test_stale_etag_is_terminal_superseded(monkeypatch) -> None:
    def stale(*_args, **_kwargs):
        raise BlobConditionFailedError("stale")

    monkeypatch.setattr(blob_handler, "read_blob_result", stale)

    assert blob_handler.process_blob_created(
        _intake(),
        config=Config(),
        analyzer=FakeAnalyzer(),
    ) == {
        "blob_name": "incoming/finding-123.json",
        "status": "superseded",
        "reason": "stale_etag",
    }


def test_retryable_read_failures_propagate(monkeypatch) -> None:
    class RetryableFailure(RuntimeError):
        retryable = True

    monkeypatch.setattr(
        blob_handler,
        "read_blob_result",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RetryableFailure("unavailable")),
    )

    with pytest.raises(RetryableFailure, match="unavailable"):
        blob_handler.process_blob_created(
            _intake(),
            config=Config(),
            analyzer=FakeAnalyzer(),
        )


def test_embed_publication_uses_strict_versioned_schema() -> None:
    publisher = SimpleNamespace(messages=[])
    publisher.send_message = publisher.messages.append

    enqueue_case_embed(
        "output",
        "cases/2026/07/10/case-123.json",
        publisher=publisher,
    )

    assert json.loads(publisher.messages[0]) == {
        "schema_version": 1,
        "case_envelope_container": "output",
        "case_envelope_blob_name": "cases/2026/07/10/case-123.json",
    }

    with pytest.raises(QueuePublisherConfigurationError, match="extra fields: case_id"):
        EmbedQueueJob.from_mapping(
            {
                "schema_version": 1,
                "case_envelope_container": "output",
                "case_envelope_blob_name": "cases/2026/07/10/case-123.json",
                "case_id": "case-123",
            }
        )


def test_analyzer_enqueues_produced_case_envelope_when_case_qa_enabled(
    monkeypatch,
) -> None:
    body = b'{"finding_id":"finding-123"}'
    operations = []

    monkeypatch.setattr(
        blob_handler,
        "read_blob_result",
        lambda *_args, **_kwargs: _read_result(body),
    )
    monkeypatch.setattr(
        blob_handler,
        "write_text_blob",
        lambda _container, name, _text, **_kwargs: operations.append(("write", name)),
    )

    result = blob_handler.process_blob_created(
        _intake(size_bytes=len(body)),
        config=Config(
            PORTAL_ENABLED=True,
            PORTAL_AUTH_MODE="iam",
            PORTAL_ENTRA_REQUIRED_APP_ROLE="Case.Reader",
            CASE_QA_ENABLED=True,
            CASE_ARCHIVE_ENABLED=True,
            CASE_INDEX_CONTAINER="notable-case-index",
        ),
        analyzer=FakeAnalyzer(),
        case_archive_workflow=lambda **_kwargs: operations.append(("archive",))
        or blob_handler.CaseEnvelopeReference(
            container_name="output",
            blob_name="cases/2026/07/10/case-123.json",
        ),
        embed_publisher=object(),
        enqueue_embed=lambda container, name, **kwargs: operations.append(
            ("enqueue", container, name, kwargs["publisher"])
        ),
    )

    assert result["case_embed_queued"] is True
    assert [operation[0] for operation in operations] == [
        "write",
        "write",
        "archive",
        "enqueue",
    ]
    assert operations[-1][1:3] == (
        "output",
        "cases/2026/07/10/case-123.json",
    )


def test_analyzer_default_archive_seam_builds_native_source_context(monkeypatch) -> None:
    body = b'{"finding_id":"finding-123"}'
    archived = []
    monkeypatch.setattr(
        blob_handler,
        "read_blob_result",
        lambda *_args, **_kwargs: _read_result(body),
    )
    monkeypatch.setattr(blob_handler, "write_text_blob", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        blob_handler,
        "archive_case",
        lambda **kwargs: archived.append(kwargs)
        or SimpleNamespace(
            status="success",
            case_envelope_key="cases/2026/07/10/case-123.json",
        ),
    )

    result = blob_handler.process_blob_created(
        _intake(size_bytes=len(body)),
        config=Config(
            CASE_ARCHIVE_ENABLED=True,
            CASE_INDEX_CONTAINER="notable-case-index",
        ),
        analyzer=FakeAnalyzer(),
    )

    assert result["status"] == "success"
    assert result["case_embed_queued"] is False
    source = archived[0]["source"]
    assert source.input_bucket == "input"
    assert source.input_key == "incoming/finding-123.json"
    assert source.source_filename == "finding-123.json"
    assert source.content_type == "json"


def test_analyzer_does_not_invent_case_envelope_or_enqueue_when_qa_disabled(
    monkeypatch,
) -> None:
    body = b'{"finding_id":"finding-123"}'
    enqueues = []
    monkeypatch.setattr(
        blob_handler,
        "read_blob_result",
        lambda *_args, **_kwargs: _read_result(body),
    )
    monkeypatch.setattr(blob_handler, "write_text_blob", lambda *_args, **_kwargs: None)

    missing_reference = blob_handler.process_blob_created(
        _intake(size_bytes=len(body)),
        config=Config(
            PORTAL_ENABLED=True,
            PORTAL_AUTH_MODE="iam",
            PORTAL_ENTRA_REQUIRED_APP_ROLE="Case.Reader",
            CASE_QA_ENABLED=True,
            CASE_INDEX_CONTAINER="notable-case-index",
        ),
        analyzer=FakeAnalyzer(),
        enqueue_embed=lambda *_args, **_kwargs: enqueues.append("unexpected"),
    )
    disabled = blob_handler.process_blob_created(
        _intake(size_bytes=len(body)),
        config=Config(),
        analyzer=FakeAnalyzer(),
        enqueue_embed=lambda *_args, **_kwargs: enqueues.append("unexpected"),
    )

    assert missing_reference["case_embed_queued"] is False
    assert disabled["case_embed_queued"] is False
    assert enqueues == []


def test_analyzer_fails_closed_when_archive_workflow_fails(monkeypatch) -> None:
    body = b'{"finding_id":"finding-123"}'
    monkeypatch.setattr(
        blob_handler,
        "read_blob_result",
        lambda *_args, **_kwargs: _read_result(body),
    )
    monkeypatch.setattr(blob_handler, "write_text_blob", lambda *_args, **_kwargs: None)

    def fail_archive(**_kwargs):
        raise RuntimeError("Cosmos unavailable")

    with pytest.raises(RuntimeError, match="Cosmos unavailable"):
        blob_handler.process_blob_created(
            _intake(size_bytes=len(body)),
            config=Config(
                PORTAL_ENABLED=True,
                PORTAL_AUTH_MODE="iam",
                PORTAL_ENTRA_REQUIRED_APP_ROLE="Case.Reader",
                CASE_QA_ENABLED=True,
                CASE_ARCHIVE_ENABLED=True,
                CASE_ARCHIVE_FAILURE_MODE="fail_closed",
                CASE_INDEX_CONTAINER="notable-case-index",
            ),
            analyzer=FakeAnalyzer(),
            case_archive_workflow=fail_archive,
        )


def test_analyzer_propagates_embed_queue_publication_failure(monkeypatch) -> None:
    body = b'{"finding_id":"finding-123"}'
    monkeypatch.setattr(
        blob_handler,
        "read_blob_result",
        lambda *_args, **_kwargs: _read_result(body),
    )
    monkeypatch.setattr(blob_handler, "write_text_blob", lambda *_args, **_kwargs: None)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("embed queue unavailable")

    with pytest.raises(RuntimeError, match="embed queue unavailable"):
        blob_handler.process_blob_created(
            _intake(size_bytes=len(body)),
            config=Config(
                PORTAL_ENABLED=True,
                PORTAL_AUTH_MODE="iam",
                PORTAL_ENTRA_REQUIRED_APP_ROLE="Case.Reader",
                CASE_QA_ENABLED=True,
                CASE_ARCHIVE_ENABLED=True,
                CASE_INDEX_CONTAINER="notable-case-index",
            ),
            analyzer=FakeAnalyzer(),
            case_archive_workflow=lambda **_kwargs: blob_handler.CaseEnvelopeReference(
                container_name="output",
                blob_name="cases/2026/07/10/case-123.json",
            ),
            enqueue_embed=unavailable,
        )
