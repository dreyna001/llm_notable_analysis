"""Lambda handler for closed ticket render, embed, and OpenSearch indexing."""

from __future__ import annotations

import json
import logging
from typing import Any

from .aws_clients import bedrock_runtime_client, dynamodb_client, s3_client
from .closed_ticket_embed import embed_closed_ticket, index_pending_closed_tickets
from .config import load_config

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Index pending closed tickets or one ticket_id from direct invoke."""

    config = load_config()
    if not config.CLOSED_TICKET_EMBED_ENABLED:
        logger.info("Closed ticket embed skipped: disabled")
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "skipped", "enabled": False}),
        }

    ticket_id = str(event.get("ticket_id") or "").strip()
    if ticket_id:
        result = embed_closed_ticket(
            ticket_id=ticket_id,
            config=config,
            s3_client=s3_client(),
            bedrock_client=bedrock_runtime_client(),
            dynamodb_client=dynamodb_client(),
        )
        if result.status == "failed":
            logger.error("Closed ticket embed failed for %s: %s", ticket_id, result.message)
        else:
            logger.info(
                "Closed ticket embed %s for %s (%d chunks)",
                result.status,
                ticket_id,
                result.chunk_count,
            )
        return {
            "statusCode": 200 if result.status != "failed" else 500,
            "body": json.dumps(
                {
                    "status": result.status,
                    "ticket_id": result.ticket_id,
                    "chunk_count": result.chunk_count,
                    "message": result.message,
                }
            ),
        }

    summary = index_pending_closed_tickets(
        config=config,
        s3_client=s3_client(),
        bedrock_client=bedrock_runtime_client(),
        dynamodb_client=dynamodb_client(),
        batch_size=event.get("batch_size"),
        max_tickets=event.get("max_tickets"),
    )
    if summary.get("failed"):
        logger.warning("Closed ticket pending embed finished with failures: %s", summary)
    else:
        logger.info("Closed ticket pending embed finished: %s", summary)
    return {
        "statusCode": 200 if summary.get("status") != "error" else 500,
        "body": json.dumps(summary),
    }
