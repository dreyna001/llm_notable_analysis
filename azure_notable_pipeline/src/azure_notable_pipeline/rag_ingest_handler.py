"""Strict Azure Storage Queue handler for manifest-driven RAG ingestion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .config import load_config
from .rag_ingestion import IngestionResult, ingest_manifest

RAG_INGEST_SCHEMA_VERSION = 1
_RAG_INGEST_KEYS = frozenset(
    {
        "schema_version",
        "manifest_container",
        "manifest_blob_name",
        "manifest_version_id",
        "manifest_etag",
    }
)


class RagIngestMessageError(ValueError):
    """The queue message is invalid and should be retried into poison handling."""


@dataclass(frozen=True)
class RagIngestQueueJob:
    schema_version: int
    manifest_container: str
    manifest_blob_name: str
    manifest_version_id: str = ""
    manifest_etag: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != RAG_INGEST_SCHEMA_VERSION:
            raise RagIngestMessageError("schema_version must be integer 1")
        for name in ("manifest_container", "manifest_blob_name"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise RagIngestMessageError(f"{name} must be a non-empty string")
        for name in ("manifest_version_id", "manifest_etag"):
            if not isinstance(getattr(self, name), str):
                raise RagIngestMessageError(f"{name} must be a string")
        if not str(self.manifest_version_id or "").strip() and not str(self.manifest_etag or "").strip():
            raise RagIngestMessageError("manifest_version_id or manifest_etag is required")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RagIngestQueueJob":
        if not isinstance(value, Mapping):
            raise RagIngestMessageError("RAG ingest job must be a JSON object")
        actual = frozenset(value.keys())
        if actual != _RAG_INGEST_KEYS:
            missing = sorted(str(key) for key in _RAG_INGEST_KEYS - actual)
            extra = sorted(str(key) for key in actual - _RAG_INGEST_KEYS)
            details = []
            if missing:
                details.append(f"missing fields: {', '.join(missing)}")
            if extra:
                details.append(f"extra fields: {', '.join(extra)}")
            raise RagIngestMessageError("invalid RAG ingest job fields (" + "; ".join(details) + ")")
        return cls(**dict(value))

    @classmethod
    def from_json(cls, payload: str | bytes) -> "RagIngestQueueJob":
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise RagIngestMessageError("RAG ingest job must be valid JSON") from exc
        return cls.from_mapping(value)


def normalize_queue_message(payload: str | bytes) -> RagIngestQueueJob:
    return RagIngestQueueJob.from_json(payload)


def dispatch_queue_message(
    payload: str | bytes,
    *,
    config: Any | None = None,
    workflow: Callable[..., IngestionResult] | None = None,
    blob_store: Any | None = None,
    embedding_gateway: Any | None = None,
    adapter: Any | None = None,
) -> IngestionResult:
    """Validate before dispatch; exceptions intentionally escape for poison safety."""

    job = normalize_queue_message(payload)
    selected = workflow or ingest_manifest
    return selected(
        manifest_container=job.manifest_container,
        manifest_blob_name=job.manifest_blob_name,
        manifest_version_id=job.manifest_version_id,
        manifest_etag=job.manifest_etag,
        config=config or load_config(),
        blob_store=blob_store,
        embedding_gateway=embedding_gateway,
        adapter=adapter,
    )


def handler(
    event: Mapping[str, Any] | str | bytes,
    *,
    config: Any | None = None,
    workflow: Callable[..., IngestionResult] | None = None,
    blob_store: Any | None = None,
    embedding_gateway: Any | None = None,
    adapter: Any | None = None,
) -> dict[str, Any]:
    """Process one native Queue trigger or a test event with one record."""

    if isinstance(event, Mapping) and "Records" in event:
        records = event.get("Records")
        if not isinstance(records, list) or len(records) != 1:
            raise RagIngestMessageError("RAG ingest event must contain exactly one record")
        record = records[0]
        if not isinstance(record, Mapping) or not isinstance(record.get("body"), (str, bytes)):
            raise RagIngestMessageError("RAG ingest record body must be text")
        payload = record["body"]
    else:
        payload = event
    result = dispatch_queue_message(
        payload,
        config=config,
        workflow=workflow,
        blob_store=blob_store,
        embedding_gateway=embedding_gateway,
        adapter=adapter,
    )
    return {"status": "success", "manifest_id": result.manifest_id, "indexed_count": result.indexed_count}


def message_identifier(payload: str | bytes) -> str:
    """Return a non-sensitive stable identifier for logs and poison diagnostics."""

    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(raw).hexdigest()[:16]


__all__ = [
    "RAG_INGEST_SCHEMA_VERSION",
    "RagIngestMessageError",
    "RagIngestQueueJob",
    "dispatch_queue_message",
    "handler",
    "message_identifier",
    "normalize_queue_message",
]
