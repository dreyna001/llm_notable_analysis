"""Azure timer handler for closed-ticket chunk embedding and Search indexing."""

from __future__ import annotations

import json
import logging
from typing import Any

from .azure_clients import blob_service_client
from .azure_search_adapter import AzureSearchAdapter
from .closed_ticket_index import index_pending_closed_tickets
from .config import load_config
from .cosmos_store import CosmosStore

logger = logging.getLogger(__name__)


class ClosedTicketEmbedInvocationError(RuntimeError):
    """An embed/index pass failed and the Azure invocation must be marked failed."""


def invoke_closed_ticket_embed(
    *,
    config: Any | None = None,
    cosmos_store: CosmosStore | None = None,
    blob_service: Any | None = None,
    adapter: AzureSearchAdapter | None = None,
    document_intelligence_client: Any | None = None,
    max_tickets: int = 500,
) -> dict[str, Any]:
    """Index pending/failed closed tickets from Cosmos + Blob archive."""

    runtime_config = config or load_config()
    persistence = cosmos_store or CosmosStore.from_config(runtime_config)
    archive_blob_service = blob_service
    if archive_blob_service is None and runtime_config.OUTPUT_STORAGE_ACCOUNT_URL.strip():
        archive_blob_service = blob_service_client(runtime_config.OUTPUT_STORAGE_ACCOUNT_URL)

    result = index_pending_closed_tickets(
        config=runtime_config,
        cosmos_store=persistence,
        blob_service=archive_blob_service,
        adapter=adapter,
        document_intelligence_client=document_intelligence_client,
        max_tickets=max_tickets,
    )
    body = {
        "status": "error" if result.errors else "success",
        "selected": result.selected,
        "ready": result.ready,
        "failed": result.failed,
        "skipped": result.skipped,
        "errors": result.errors,
    }
    if result.errors:
        logger.error("Closed-ticket indexing errors: %s", result.errors)
    return body


def handle_timer(timer: Any, *, max_tickets: int = 500) -> dict[str, Any]:
    """Handle one native timer invocation for closed-ticket indexing."""

    if bool(getattr(timer, "past_due", False)):
        logger.warning("Closed ticket embed timer invocation is past due")
    result = invoke_closed_ticket_embed(max_tickets=max_tickets)
    if result.get("status") == "error":
        message = str(result.get("errors") or "closed ticket indexing failed")
        raise ClosedTicketEmbedInvocationError(message)
    logger.info("Closed ticket embed invocation completed: %s", result)
    return result


def handler(event: dict[str, Any] | None = None, _context: Any = None) -> dict[str, Any]:
    """Legacy handler shape for tests and direct invocation."""

    max_tickets = 500
    if isinstance(event, dict) and event.get("max_tickets") is not None:
        max_tickets = int(event["max_tickets"])
    result = invoke_closed_ticket_embed(max_tickets=max_tickets)
    return {
        "statusCode": 200 if result.get("status") != "error" else 500,
        "body": json.dumps(result),
    }


__all__ = [
    "ClosedTicketEmbedInvocationError",
    "handle_timer",
    "handler",
    "invoke_closed_ticket_embed",
]
