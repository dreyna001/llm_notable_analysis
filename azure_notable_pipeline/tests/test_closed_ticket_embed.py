"""Tests for closed-ticket embed/index handler."""

from __future__ import annotations

from unittest.mock import patch

from azure_notable_pipeline.closed_ticket_embed_handler import handler, invoke_closed_ticket_embed
from azure_notable_pipeline.closed_ticket_index import ClosedTicketPendingIndexResult
from azure_notable_pipeline.config import Config


def test_handler_returns_success_payload() -> None:
    with patch(
        "azure_notable_pipeline.closed_ticket_embed_handler.invoke_closed_ticket_embed",
        return_value={
            "status": "success",
            "selected": 1,
            "ready": 1,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        },
    ):
        response = handler({"max_tickets": 10})
    assert response["statusCode"] == 200
    assert '"ready": 1' in response["body"]


def test_invoke_closed_ticket_embed_reports_errors() -> None:
    with patch(
        "azure_notable_pipeline.closed_ticket_embed_handler.index_pending_closed_tickets",
        return_value=ClosedTicketPendingIndexResult(
            selected=1,
            failed=1,
            errors=["ticket-1: boom"],
        ),
    ):
        with patch(
            "azure_notable_pipeline.closed_ticket_embed_handler.CosmosStore.from_config",
            return_value=object(),
        ):
            result = invoke_closed_ticket_embed(config=Config())
    assert result["status"] == "error"
    assert result["errors"] == ["ticket-1: boom"]
