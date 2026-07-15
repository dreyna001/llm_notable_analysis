"""Application-oriented Azure Storage Queue publication boundary."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse

from azure.core.exceptions import (
    AzureError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)

from .analyzer_job import AnalyzerQueueJob
from .azure_clients import AzureClientConfigurationError, queue_client
from .rag_ingest_handler import RagIngestQueueJob


EMBED_JOB_SCHEMA_VERSION = 1
EMBED_JOB_KEYS = frozenset(
    {
        "schema_version",
        "case_envelope_container",
        "case_envelope_blob_name",
    }
)


class QueuePublisherError(RuntimeError):
    """A Storage Queue publication failed through the stable boundary."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class QueuePublisherConfigurationError(QueuePublisherError):
    """Queue publication configuration or input is invalid."""


class QueuePublisherUnavailableError(QueuePublisherError):
    """Storage Queue was unavailable and the trigger should retry."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


def _required_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QueuePublisherConfigurationError(
            f"{field_name} must be a non-empty string"
        )
    return value.strip()


@dataclass(frozen=True)
class EmbedQueueJob:
    """Strict v1 case-embedding queue message."""

    schema_version: int
    case_envelope_container: str
    case_envelope_blob_name: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != EMBED_JOB_SCHEMA_VERSION
        ):
            raise QueuePublisherConfigurationError("schema_version must be integer 1")
        _required_string(
            self.case_envelope_container,
            field_name="case_envelope_container",
        )
        _required_string(
            self.case_envelope_blob_name,
            field_name="case_envelope_blob_name",
        )

    @classmethod
    def create(
        cls,
        *,
        case_envelope_container: str,
        case_envelope_blob_name: str,
    ) -> EmbedQueueJob:
        return cls(
            schema_version=EMBED_JOB_SCHEMA_VERSION,
            case_envelope_container=case_envelope_container,
            case_envelope_blob_name=case_envelope_blob_name,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EmbedQueueJob:
        if not isinstance(value, Mapping):
            raise QueuePublisherConfigurationError("embed job must be a JSON object")
        actual_keys = frozenset(value.keys())
        if actual_keys != EMBED_JOB_KEYS:
            missing = sorted(str(key) for key in EMBED_JOB_KEYS - actual_keys)
            extra = sorted(str(key) for key in actual_keys - EMBED_JOB_KEYS)
            details = []
            if missing:
                details.append(f"missing fields: {', '.join(missing)}")
            if extra:
                details.append(f"extra fields: {', '.join(extra)}")
            raise QueuePublisherConfigurationError(
                "invalid embed job fields (" + "; ".join(details) + ")"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(cls, payload: str | bytes) -> EmbedQueueJob:
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise QueuePublisherConfigurationError(
                "embed job must be valid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise QueuePublisherConfigurationError("embed job must be a JSON object")
        return cls.from_mapping(decoded)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


def _queue_account_url() -> str:
    binding_url = os.getenv("OutputStorage__queueServiceUri", "").strip()
    if binding_url:
        return binding_url

    blob_url = os.getenv("OUTPUT_STORAGE_ACCOUNT_URL", "").strip()
    if not blob_url:
        raise QueuePublisherConfigurationError(
            "OutputStorage__queueServiceUri is required"
        )
    parsed = urlparse(blob_url)
    host = parsed.hostname or ""
    if ".blob." not in host:
        raise QueuePublisherConfigurationError(
            "OUTPUT_STORAGE_ACCOUNT_URL must be an Azure Blob service URL"
        )
    queue_host = host.replace(".blob.", ".queue.", 1)
    if parsed.port:
        queue_host = f"{queue_host}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=queue_host))


def _publisher(queue_name: str, publisher: Any | None) -> Any:
    if publisher is not None:
        return publisher
    try:
        return queue_client(_queue_account_url(), queue_name)
    except AzureClientConfigurationError as exc:
        raise QueuePublisherConfigurationError(str(exc)) from exc


def _send_message(*, queue_name: str, payload: str, publisher: Any | None) -> None:
    try:
        _publisher(queue_name, publisher).send_message(payload)
    except QueuePublisherError:
        raise
    except (ServiceRequestError, ServiceResponseError) as exc:
        raise QueuePublisherUnavailableError(
            f"Storage Queue publication failed for {queue_name}"
        ) from exc
    except HttpResponseError as exc:
        if exc.status_code in {408, 429, 500, 502, 503, 504}:
            raise QueuePublisherUnavailableError(
                f"Storage Queue publication failed for {queue_name}"
            ) from exc
        raise QueuePublisherError(
            f"Storage Queue publication failed for {queue_name}"
        ) from exc
    except AzureError as exc:
        raise QueuePublisherError(
            f"Storage Queue publication failed for {queue_name}"
        ) from exc


def enqueue_analyzer_job(
    *,
    container_name: str,
    blob_name: str,
    etag: str,
    size_bytes: int,
    last_modified: str,
    publisher: Any | None = None,
) -> None:
    """Publish the application-authored strict v1 analyzer job."""

    job = AnalyzerQueueJob.create(
        container_name=container_name,
        blob_name=blob_name,
        etag=etag,
        size_bytes=size_bytes,
        last_modified=last_modified,
    )
    queue_name = _required_string(
        os.getenv("ANALYZER_QUEUE_NAME", "notable-analysis-jobs"),
        field_name="ANALYZER_QUEUE_NAME",
    )
    _send_message(
        queue_name=queue_name,
        payload=job.to_json(),
        publisher=publisher,
    )


def enqueue_case_embed(
    case_envelope_container: str,
    case_envelope_blob_name: str,
    *,
    publisher: Any | None = None,
) -> None:
    """Publish one strict v1 case-envelope embedding job."""

    job = EmbedQueueJob.create(
        case_envelope_container=case_envelope_container,
        case_envelope_blob_name=case_envelope_blob_name,
    )
    queue_name = _required_string(
        os.getenv("CASE_EMBED_QUEUE_NAME", "case-embed-invocations"),
        field_name="CASE_EMBED_QUEUE_NAME",
    )
    _send_message(
        queue_name=queue_name,
        payload=job.to_json(),
        publisher=publisher,
    )


def enqueue_rag_ingest(
    *,
    manifest_container: str,
    manifest_blob_name: str,
    manifest_version_id: str = "",
    manifest_etag: str = "",
    publisher: Any | None = None,
) -> None:
    """Publish one strict manifest ingestion job to the dedicated queue."""

    job = RagIngestQueueJob(
        schema_version=1,
        manifest_container=manifest_container,
        manifest_blob_name=manifest_blob_name,
        manifest_version_id=manifest_version_id,
        manifest_etag=manifest_etag,
    )
    queue_name = _required_string(
        os.getenv("RAG_INGEST_QUEUE_NAME", "rag-ingest-invocations"),
        field_name="RAG_INGEST_QUEUE_NAME",
    )
    _send_message(
        queue_name=queue_name,
        payload=json.dumps(
            {
                "schema_version": job.schema_version,
                "manifest_container": job.manifest_container,
                "manifest_blob_name": job.manifest_blob_name,
                "manifest_version_id": job.manifest_version_id,
                "manifest_etag": job.manifest_etag,
            },
            separators=(",", ":"),
        ),
        publisher=publisher,
    )


__all__ = [
    "EMBED_JOB_SCHEMA_VERSION",
    "EMBED_JOB_KEYS",
    "EmbedQueueJob",
    "QueuePublisherConfigurationError",
    "QueuePublisherError",
    "QueuePublisherUnavailableError",
    "enqueue_analyzer_job",
    "enqueue_case_embed",
    "enqueue_rag_ingest",
]
