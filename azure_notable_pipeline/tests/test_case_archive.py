"""Native Blob/Cosmos behavior tests for canonical case archives."""

from __future__ import annotations

import json
from types import SimpleNamespace

from azure_notable_pipeline import case_archive
from azure_notable_pipeline.case_archive import SourceContext, archive_case
from azure_notable_pipeline.config import Config


class FakeCosmos:
    def __init__(self, existing=None, conflict=False):
        self.item = existing
        self.conflict = conflict
        self.creates = []

    def get_case(self, _container, _case_id):
        return self.item

    def create_case_if_absent(self, _container, item):
        self.creates.append(item)
        if self.conflict:
            return SimpleNamespace(created=False)
        self.item = item
        return SimpleNamespace(created=True)


class ImmutableFakeCosmos(FakeCosmos):
    def __init__(self):
        super().__init__()
        self.etag = 0

    def get_case(self, container, case_id):
        value = super().get_case(container, case_id)
        return {**value, "_etag": str(self.etag)} if value else None

    def create_case_if_absent(self, container, item):
        self.etag += 1
        self.item = {**item, "_etag": str(self.etag)}
        self.creates.append(item)
        return SimpleNamespace(created=True, item=dict(self.item))

    def replace_if_match(self, _container, item, *, expected_etag):
        if str(expected_etag) != str(self.etag):
            return SimpleNamespace(applied=False, outcome="precondition_failed")
        self.etag += 1
        self.item = {**item, "_etag": str(self.etag)}
        return SimpleNamespace(applied=True, outcome="replaced", item=dict(self.item))

    def publish_case_run_if_latest(self, _container, *, run_id, run_record, **_kwargs):
        self.item["runs"] = {**self.item.get("runs", {}), run_id: dict(run_record)}
        self.item["latest_run_id"] = run_id
        self.item["latest_run_key"] = run_record["envelope_key"]
        self.item["latest_run_at"] = run_record["completed_at"]
        self.item["case_envelope_key"] = run_record["envelope_key"]
        self.etag += 1
        self.item["_etag"] = str(self.etag)
        return SimpleNamespace(applied=True, outcome="replaced", item=dict(self.item))


def _config(**overrides):
    values = {
        "CASE_ARCHIVE_ENABLED": True,
        "CASE_ARCHIVE_CONTAINER": "output",
        "CASE_INDEX_CONTAINER": "case-index",
    }
    values.update(overrides)
    return Config(**values)


def _source():
    return SourceContext("input", "incoming/example.json", "example.json", "json", False)


def _analysis(**overrides):
    value = {
        "markdown": "# not archived",
        "alert_payload": {
            "finding_id": "abc-123",
            "correlation_id": "corr-1",
            "search_name": "Suspicious Login",
            "risk_score": 42,
        },
        "llm_response": {
            "alert_reconciliation": {
                "verdict": "likely_true_positive",
                "confidence": 0.91,
            }
        },
    }
    value.update(overrides)
    return value


def _sink():
    return {
        "status": "success",
        "container": "output",
        "markdown_key": "reports/example.md",
        "json_key": "reports/example.json",
        "html_key": "reports/example.html",
    }


def test_archive_writes_legacy_envelope_and_plain_cosmos_document(monkeypatch):
    writes = []
    monkeypatch.setattr(case_archive, "write_blob", lambda *args, **kwargs: writes.append((args, kwargs)))
    cosmos = FakeCosmos()

    result = archive_case(
        analysis_result=_analysis(), config=_config(CASE_QA_ENABLED=False),
        source=_source(), sink_result=_sink(), cosmos=cosmos,
        processed_at="2026-06-15T10:30:00Z",
    )

    assert result.status == "success"
    assert result.case_id == "abc-123-5942d94f524882e0"
    assert result.case_envelope_key == "cases/2026/06/15/abc-123-5942d94f524882e0.json"
    envelope = json.loads(writes[0][0][2])
    assert writes[0][0][:2] == ("output", result.case_envelope_key)
    assert envelope["source"]["input_bucket"] == "input"
    assert envelope["source"]["input_key"] == "incoming/example.json"
    assert envelope["analysis"]["alert_reconciliation"]["verdict"] == "likely_malicious"
    assert envelope["artifacts"]["report_markdown_key"] == "reports/example.md"
    assert "markdown" not in envelope
    assert cosmos.creates[0]["case_envelope_key"] == result.case_envelope_key
    assert cosmos.creates[0]["expires_at_epoch"] == 1784111400
    assert cosmos.creates[0]["retrieval_status"] == "not_indexed"
    assert "id" not in cosmos.creates[0]


def test_oversized_payload_marks_missing_without_truncation(monkeypatch):
    writes = []
    monkeypatch.setattr(case_archive, "write_blob", lambda *args, **kwargs: writes.append(args))
    result = archive_case(
        analysis_result=_analysis(alert_payload={"finding_id": "abc-123", "large": "x" * 200}),
        config=_config(CASE_ARCHIVE_MAX_ALERT_BYTES=50), source=_source(),
        sink_result=_sink(), cosmos=FakeCosmos(), processed_at="2026-06-15T10:30:00Z",
    )
    envelope = json.loads(writes[0][2])
    assert result.source_completeness == "missing_alert"
    assert envelope["alert_payload"] is None


def test_etag_processing_identity_writes_immutable_run_and_publishes_latest(monkeypatch):
    writes = []
    monkeypatch.setattr(case_archive, "write_blob", lambda *args, **kwargs: writes.append((args, kwargs)))
    cosmos = ImmutableFakeCosmos()
    source = SourceContext(
        "input", "incoming/example.json", "example.json", "json", False,
        source_etag='"etag-1"',
    )

    first = archive_case(
        analysis_result=_analysis(), config=_config(), source=source,
        sink_result=_sink(), cosmos=cosmos, processed_at="2026-06-15T10:30:00Z",
    )
    second = archive_case(
        analysis_result=_analysis(), config=_config(), source=source,
        sink_result=_sink(), cosmos=cosmos, processed_at="2026-06-15T10:30:00Z",
    )

    assert first.status == "success"
    assert "/run-" in first.case_envelope_key
    assert writes[0][1]["overwrite"] is False
    assert cosmos.item["latest_run_id"].startswith("run-")
    assert second.status == "success"
    assert "replay" in second.message
    assert len(writes) == 1


def test_fallback_case_identity_uses_full_source_location(monkeypatch):
    monkeypatch.setattr(case_archive, "write_blob", lambda *_args, **_kwargs: None)
    payload_without_id = {"search_name": "No authoritative identifier"}

    first = archive_case(
        analysis_result=_analysis(alert_payload=payload_without_id),
        config=_config(),
        source=SourceContext(
            "input", "incoming/team-a/alert.json", "alert.json", "json", False
        ),
        sink_result=_sink(),
        cosmos=FakeCosmos(),
        processed_at="2026-06-15T10:30:00Z",
    )
    second = archive_case(
        analysis_result=_analysis(alert_payload=payload_without_id),
        config=_config(),
        source=SourceContext(
            "input", "incoming/team-b/alert.json", "alert.json", "json", False
        ),
        sink_result=_sink(),
        cosmos=FakeCosmos(),
        processed_at="2026-06-15T10:30:00Z",
    )

    assert first.case_id != second.case_id
    assert first.case_id.startswith("alert-")
    assert second.case_id.startswith("alert-")


def test_fallback_case_identity_sanitizes_source_basename(monkeypatch):
    monkeypatch.setattr(case_archive, "write_blob", lambda *_args, **_kwargs: None)

    result = archive_case(
        analysis_result=_analysis(alert_payload={"search_name": "No ID"}),
        config=_config(),
        source=SourceContext(
            "input",
            "incoming/team-a/Alert with spaces (1).json",
            "Alert with spaces (1).json",
            "json",
            False,
        ),
        sink_result=_sink(),
        cosmos=FakeCosmos(),
        processed_at="2026-06-15T10:30:00Z",
    )

    assert result.status == "success"
    assert result.case_id.startswith("Alert_with_spaces_1-")


def test_replay_and_collision_are_resolved_before_blob_write(monkeypatch):
    writes = []
    monkeypatch.setattr(case_archive, "write_blob", lambda *args, **kwargs: writes.append(args))
    matching = {
        "case_id": "abc-123-5942d94f524882e0", "finding_id": "abc-123",
        "source_filename": "example.json", "case_envelope_key": "cases/original.json",
        "retrieval_status": "ready", "source_completeness": "complete",
    }
    replay = archive_case(
        analysis_result=_analysis(), config=_config(), source=_source(), sink_result=_sink(),
        cosmos=FakeCosmos(matching), processed_at="2026-06-15T10:30:00Z",
    )
    collision = archive_case(
        analysis_result=_analysis(), config=_config(), source=_source(), sink_result=_sink(),
        cosmos=FakeCosmos({"finding_id": "other", "source_filename": "other.json"}),
        processed_at="2026-06-15T10:30:00Z",
    )
    assert replay.status == "success" and "replay" in replay.message
    assert replay.case_envelope_key == "cases/original.json"
    assert collision.status == "skipped" and "collision" in collision.message
    assert writes == []


def test_conditional_create_race_reuses_matching_identity(monkeypatch):
    monkeypatch.setattr(case_archive, "write_blob", lambda *_args, **_kwargs: None)
    cosmos = FakeCosmos(conflict=True)
    original_get = cosmos.get_case
    calls = 0
    def get_case(container, case_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return {"finding_id": "abc-123", "source_filename": "example.json", "case_envelope_key": "cases/race.json"}
    cosmos.get_case = get_case
    result = archive_case(
        analysis_result=_analysis(), config=_config(), source=_source(), sink_result=_sink(),
        cosmos=cosmos, processed_at="2026-06-15T10:30:00Z",
    )
    assert result.status == "success"
    assert result.case_envelope_key == "cases/race.json"
