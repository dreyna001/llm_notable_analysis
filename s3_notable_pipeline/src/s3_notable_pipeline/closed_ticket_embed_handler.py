"""Lambda handler for closed-ticket chunk embedding and OpenSearch indexing."""

from __future__ import annotations

import json
import logging
from typing import Any

from .aws_clients import bedrock_runtime_client, dynamodb_client, s3_client, textract_client
from .closed_ticket_index import index_pending_closed_tickets
from .config import load_config
from .opensearch_client import OpenSearchClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Index pending/failed closed tickets from DynamoDB + S3 archive."""

    config = load_config()
    max_tickets = int(event.get("max_tickets", 500)) if isinstance(event, dict) else 500
    result = index_pending_closed_tickets(
        config=config,
        dynamodb_client=dynamodb_client(),
        s3_client=s3_client(),
        bedrock_client=bedrock_runtime_client(),
        adapter=OpenSearchClient.from_config(config),
        textract_client=textract_client(),
        max_tickets=max_tickets,
    )
    if result.errors:
        logger.error("Closed-ticket indexing errors: %s", result.errors)
    return {
        "statusCode": 200 if not result.errors else 500,
        "body": json.dumps(
            {
                "selected": result.selected,
                "ready": result.ready,
                "failed": result.failed,
                "skipped": result.skipped,
                "errors": result.errors,
            }
        ),
    }
