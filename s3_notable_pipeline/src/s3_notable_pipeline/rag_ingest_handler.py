"""SQS partial-batch handler for application-managed RAG ingestion."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import unquote_plus

from .aws_clients import bedrock_runtime_client, s3_client
from .config import Config, load_config
from .opensearch_retrieval import adapter_for
from .rag_ingestion import ingest_manifest


def handler(
    event: dict[str, Any],
    _context: Any = None,
    *,
    config: Config | Any | None = None,
    s3: Any | None = None,
    bedrock: Any | None = None,
    opensearch: Any | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Process SQS records and return only failed message identifiers."""

    runtime_config = config or load_config()
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not isinstance(records, list):
        raise ValueError("SQS event Records must be a list")
    failures: list[dict[str, str]] = []
    for record in records:
        identifier = _record_identifier(record)
        try:
            for payload in _message_payloads(record):
                ingest_manifest(
                    manifest_bucket=payload["manifest_bucket"],
                    manifest_key=payload["manifest_key"],
                    manifest_version_id=payload.get("manifest_version_id", ""),
                    manifest_etag=payload.get("manifest_etag", ""),
                    config=runtime_config,
                    s3_client=s3 or s3_client(),
                    bedrock_client=bedrock or bedrock_runtime_client(),
                    adapter=opensearch or adapter_for(runtime_config),
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Returning a failed identifier lets SQS retry only this message.
            _ = exc
            failures.append({"itemIdentifier": identifier})
    return {"batchItemFailures": failures}


def _message_payloads(record: Any) -> list[dict[str, str]]:
    if not isinstance(record, dict):
        raise ValueError("SQS record must be an object")
    body = record.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("SQS record body must be a non-empty JSON string")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("RAG ingest SQS body must be a JSON object")
    s3_records = payload.get("Records")
    if isinstance(s3_records, list):
        if not s3_records:
            raise ValueError("S3 notification Records must not be empty")
        return [_s3_notification_payload(item) for item in s3_records]

    manifest_bucket = str(payload.get("manifest_bucket", "")).strip()
    manifest_key = str(payload.get("manifest_key", "")).strip()
    version_id = str(payload.get("manifest_version_id", "") or "").strip()
    etag = str(payload.get("manifest_etag", "") or "").strip().strip('"')
    if not manifest_bucket or not manifest_key:
        raise ValueError("manifest_bucket and manifest_key are required")
    if not version_id and not etag:
        raise ValueError("manifest_version_id or manifest_etag is required")
    return [{
        "manifest_bucket": manifest_bucket,
        "manifest_key": manifest_key,
        "manifest_version_id": version_id,
        "manifest_etag": etag,
    }]


def _s3_notification_payload(record: Any) -> dict[str, str]:
    if not isinstance(record, dict) or record.get("eventSource") != "aws:s3":
        raise ValueError("RAG queue contains a non-S3 notification record")
    s3 = record.get("s3")
    if not isinstance(s3, dict):
        raise ValueError("S3 notification is missing s3 data")
    bucket = s3.get("bucket")
    obj = s3.get("object")
    if not isinstance(bucket, dict) or not isinstance(obj, dict):
        raise ValueError("S3 notification is missing bucket or object data")
    bucket_name = str(bucket.get("name", "")).strip()
    key = unquote_plus(str(obj.get("key", "")).strip())
    version_id = str(obj.get("versionId", "") or "").strip()
    etag = str(obj.get("eTag", "") or "").strip().strip('"')
    if not bucket_name or not key or (not version_id and not etag):
        raise ValueError("S3 manifest notification requires bucket, key, and version or ETag")
    return {
        "manifest_bucket": bucket_name,
        "manifest_key": key,
        "manifest_version_id": version_id,
        "manifest_etag": etag,
    }


def _record_identifier(record: Any) -> str:
    if isinstance(record, dict):
        message_id = str(record.get("messageId", "")).strip()
        if message_id:
            return message_id
        body = record.get("body")
        if isinstance(body, str):
            return hashlib.sha256(body.encode("utf-8")).hexdigest()
    return hashlib.sha256(repr(record).encode("utf-8")).hexdigest()
