"""Native embed-queue schema and deferred dispatcher tests."""

from __future__ import annotations

import json

import pytest

from azure_notable_pipeline.embed_handler import (
    DeferredCaseEmbeddingWorkflowError,
    dispatch_embed_queue_message,
    normalize_embed_queue_message,
)
from azure_notable_pipeline.queue_publisher import QueuePublisherConfigurationError


def _payload(**overrides) -> bytes:
    value = {
        "schema_version": 1,
        "case_envelope_container": "output",
        "case_envelope_blob_name": "cases/2026/07/10/case-123.json",
    }
    value.update(overrides)
    return json.dumps(value).encode("utf-8")


def test_dispatcher_normalizes_native_v1_job_before_injected_workflow() -> None:
    observed = []

    result = dispatch_embed_queue_message(
        _payload(),
        workflow=lambda job: observed.append(job) or {"status": "embedded"},
    )

    assert result == {"status": "embedded"}
    assert observed[0].schema_version == 1
    assert observed[0].case_envelope_container == "output"
    assert observed[0].case_envelope_blob_name == (
        "cases/2026/07/10/case-123.json"
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_payload(schema_version=2), "schema_version must be integer 1"),
        (_payload(schema_version=True), "schema_version must be integer 1"),
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "case_envelope_container": "output",
                }
            ).encode(),
            "missing fields: case_envelope_blob_name",
        ),
        (_payload(case_id="case-123"), "extra fields: case_id"),
        (_payload(case_envelope_container=" "), "must be a non-empty string"),
        (b"not-json", "must be valid JSON"),
    ],
)
def test_embed_job_schema_rejects_non_contract_payloads(payload, message) -> None:
    with pytest.raises(QueuePublisherConfigurationError, match=message):
        normalize_embed_queue_message(payload)


def test_default_dispatcher_fails_closed_until_native_workflow_lands() -> None:
    with pytest.raises(
        DeferredCaseEmbeddingWorkflowError,
        match="deferred Blob/Cosmos workflow",
    ):
        dispatch_embed_queue_message(_payload())
