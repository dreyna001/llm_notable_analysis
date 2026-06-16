"""Lambda handler for post-archive case chunk embedding."""

from __future__ import annotations

import json
import logging
from typing import Any

from .aws_clients import (
    bedrock_runtime_client,
    dynamodb_client,
    s3_client,
)
from .case_embed import embed_case_envelope
from .config import load_config

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Embed one archived case envelope into S3 chunk objects."""

    config = load_config()
    bucket = str(event.get("case_envelope_bucket") or config.CASE_ARCHIVE_BUCKET).strip()
    key = str(event.get("case_envelope_key") or "").strip()
    if not bucket:
        raise ValueError("case_envelope_bucket or CASE_ARCHIVE_BUCKET is required")
    if not key:
        raise ValueError("case_envelope_key is required")

    result = embed_case_envelope(
        bucket=bucket,
        key=key,
        config=config,
        s3_client=s3_client(),
        bedrock_client=bedrock_runtime_client(),
        dynamodb_client=dynamodb_client(),
    )
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
