"""Private polling Blob-trigger and analyzer queue contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from azure_notable_pipeline.analyzer_job import (
    ANALYZER_JOB_KEYS,
    AnalyzerQueueJob,
)
from azure_notable_pipeline.blob_handler import normalize_analyzer_queue_message
from azure_notable_pipeline.queue_publisher import enqueue_analyzer_job


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _job_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "container_name": "input",
        "blob_name": "incoming/finding-123.json.gz",
        "etag": '"0x8DCABC123"',
        "size_bytes": 1234,
        "last_modified": "2026-07-10T12:34:56Z",
    }


def test_analyzer_job_has_exact_strict_v1_schema() -> None:
    job = AnalyzerQueueJob.from_mapping(_job_payload())

    assert set(job.to_dict()) == ANALYZER_JOB_KEYS
    assert job.to_dict() == _job_payload()
    assert json.loads(job.to_json()) == _job_payload()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.pop("etag"), "missing fields: etag"),
        (lambda value: value.update({"url": "https://example.test"}), "extra fields: url"),
        (lambda value: value.update({"schema_version": 2}), "schema_version"),
        (lambda value: value.update({"schema_version": 1.0}), "schema_version"),
        (lambda value: value.update({"size_bytes": True}), "size_bytes"),
        (lambda value: value.update({"size_bytes": -1}), "size_bytes"),
        (
            lambda value: value.update({"last_modified": "2026-07-10T12:34:56-04:00"}),
            "last_modified",
        ),
    ],
)
def test_analyzer_job_rejects_non_contract_values(mutation, message: str) -> None:
    payload = _job_payload()
    mutation(payload)

    with pytest.raises(ValueError, match=message):
        AnalyzerQueueJob.from_mapping(payload)


def test_queue_wrapper_normalizes_only_after_strict_validation() -> None:
    intake = normalize_analyzer_queue_message(json.dumps(_job_payload()))

    assert intake.container_name == "input"
    assert intake.blob_name == "incoming/finding-123.json.gz"
    assert intake.etag == '"0x8DCABC123"'
    assert intake.size_bytes == 1234
    assert intake.last_modified == "2026-07-10T12:34:56Z"


def test_queue_publisher_authors_the_versioned_job() -> None:
    class Publisher:
        messages: list[str] = []

        def send_message(self, payload: str) -> None:
            self.messages.append(payload)

    publisher = Publisher()
    enqueue_analyzer_job(
        container_name="input",
        blob_name="incoming/finding-123.json.gz",
        etag='"0x8DCABC123"',
        size_bytes=1234,
        last_modified="2026-07-10T12:34:56Z",
        publisher=publisher,
    )

    assert len(publisher.messages) == 1
    assert json.loads(publisher.messages[0]) == _job_payload()


def test_function_wrappers_use_polling_blob_and_output_queue_bindings() -> None:
    source = (
        PROJECT_ROOT / "src" / "azure_notable_pipeline" / "function_app.py"
    ).read_text(encoding="utf-8")

    assert '@app.function_name(name="intake_blob")' in source
    assert "@app.blob_trigger(" in source
    assert 'path="%INPUT_CONTAINER_NAME%/incoming/{name}"' in source
    assert 'connection="InputStorage"' in source
    assert '@app.function_name(name="analyzer_queue")' in source
    assert "@app.queue_trigger(" in source
    assert 'queue_name="%ANALYZER_QUEUE_NAME%"' in source
    assert 'connection="OutputStorage"' in source


def test_bicep_shell_locks_private_storage_and_queue_ownership() -> None:
    storage = (
        PROJECT_ROOT / "deploy" / "azure" / "modules" / "storage.bicep"
    ).read_text(encoding="utf-8")
    network = (
        PROJECT_ROOT / "deploy" / "azure" / "modules" / "network.bicep"
    ).read_text(encoding="utf-8")
    analyzer = (
        PROJECT_ROOT / "deploy" / "azure" / "modules" / "functions-analyzer.bicep"
    ).read_text(encoding="utf-8")

    assert "publicNetworkAccess: 'Disabled'" in storage
    assert "allowSharedKeyAccess: false" in storage
    assert "'notable-analysis-jobs'" in storage
    assert "analyzerQueueAccountName string = outputStorageAccountName" in storage
    assert "accountName: inputStorageAccountName\n    subresource: 'queue'" in network
    assert "InputStorage__queueServiceUri" in analyzer
    assert "Storage Queue Data Contributor" in analyzer
    assert "scope: 'output-notable-analysis-jobs'" in analyzer
