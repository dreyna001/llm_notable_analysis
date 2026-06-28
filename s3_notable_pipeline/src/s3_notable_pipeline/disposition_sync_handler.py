"""Lambda handler for scheduled ServiceNow closed disposition sync."""

from __future__ import annotations

import json
import logging
from typing import Any

from .aws_clients import dynamodb_client, s3_client
from .config import load_config
from .servicenow_disposition_sync import run_disposition_sync

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Run one ServiceNow disposition sync pass."""

    config = load_config()
    result = run_disposition_sync(
        config=config,
        dynamodb_client=dynamodb_client(),
        s3_client=s3_client(),
    )
    if result.get("status") == "error":
        logger.error("ServiceNow disposition sync failed: %s", result.get("message", ""))
    return {
        "statusCode": 200 if result.get("status") != "error" else 500,
        "body": json.dumps(result),
    }
