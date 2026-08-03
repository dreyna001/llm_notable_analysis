"""Lambda handler for post-archive case chunk embedding."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from .aws_clients import (
    bedrock_runtime_client,
    dynamodb_client,
    s3_client,
)
from .case_embed import EmbedResult, embed_case_envelope
from .config import Config, load_config

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Embed archived case envelope(s) from direct invoke or SQS batch events."""

    config = load_config()
    records = event.get("Records") if isinstance(event, dict) else None
    if isinstance(records, list) and records:
        return _handle_sqs_batch(records, config)
    return _handle_direct(event, config)


def _handle_direct(event: dict[str, Any], config: Config) -> dict[str, Any]:
    bucket, key = _embed_pointers(event, config)
    result = _embed_one(bucket=bucket, key=key, config=config)
    if result.status == "failed":
        logger.error("Case embedding failed for %s: %s", key, result.message)
    else:
        logger.info("Embedded %d chunk(s) for case %s", result.chunk_count, result.case_id)
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "status": result.status,
                "case_id": result.case_id,
                "chunk_count": result.chunk_count,
                "message": result.message,
            }
        ),
    }


def _handle_sqs_batch(records: list[Any], config: Config) -> dict[str, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    for record in records:
        identifier = _record_identifier(record)
        try:
            bucket, key = _embed_pointers_from_record(record, config)
            result = _embed_one(bucket=bucket, key=key, config=config)
            if result.status == "failed":
                logger.error("Case embedding failed for %s: %s", key, result.message)
                failures.append({"itemIdentifier": identifier})
        except Exception as exc:
            logger.error("Case embed SQS record failed: %s", exc)
            failures.append({"itemIdentifier": identifier})
    return {"batchItemFailures": failures}


def _embed_one(*, bucket: str, key: str, config: Config) -> EmbedResult:
    return embed_case_envelope(
        bucket=bucket,
        key=key,
        config=config,
        s3_client=s3_client(),
        bedrock_client=bedrock_runtime_client(),
        dynamodb_client=dynamodb_client(),
    )


def _embed_pointers(payload: dict[str, Any], config: Config) -> tuple[str, str]:
    bucket = str(payload.get("case_envelope_bucket") or config.CASE_ARCHIVE_BUCKET).strip()
    key = str(payload.get("case_envelope_key") or "").strip()
    if not bucket:
        raise ValueError("case_envelope_bucket or CASE_ARCHIVE_BUCKET is required")
    if not key:
        raise ValueError("case_envelope_key is required")
    return bucket, key


def _embed_pointers_from_record(record: Any, config: Config) -> tuple[str, str]:
    if not isinstance(record, dict):
        raise ValueError("SQS record must be an object")
    body = record.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("SQS record body must be a non-empty JSON string")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("case embed SQS body must be a JSON object")
    return _embed_pointers(payload, config)


def _record_identifier(record: Any) -> str:
    if isinstance(record, dict):
        message_id = str(record.get("messageId", "")).strip()
        if message_id:
            return message_id
        body = record.get("body")
        if isinstance(body, str):
            return hashlib.sha256(body.encode("utf-8")).hexdigest()
    return hashlib.sha256(repr(record).encode("utf-8")).hexdigest()
