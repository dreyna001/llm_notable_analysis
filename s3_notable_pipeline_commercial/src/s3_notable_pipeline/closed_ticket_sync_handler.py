"""Lambda handler for scheduled ServiceNow closed ticket sync."""

from __future__ import annotations

import json
import logging
from typing import Any

from .aws_clients import dynamodb_client, s3_client
from .config import load_config
from .servicenow_closed_ticket_sync import run_closed_ticket_sync

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Run one ServiceNow closed ticket sync pass."""

    config = load_config()
    result = run_closed_ticket_sync(
        config=config,
        s3_client=s3_client(),
        dynamodb_client=dynamodb_client(),
    )
    if result.get("status") == "error":
        logger.error("ServiceNow closed ticket sync failed: %s", result.get("errors"))
    return {
        "statusCode": 200 if result.get("status") != "error" else 500,
        "body": json.dumps(result),
    }
