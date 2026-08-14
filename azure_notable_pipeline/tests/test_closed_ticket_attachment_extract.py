"""Tests for closed-ticket attachment semantic extraction."""

from __future__ import annotations

from azure_notable_pipeline.closed_ticket_attachment_extract import (
    ClosedTicketAttachmentInput,
    decode_text_attachment,
    extract_attachment_semantic_text,
)
from azure_notable_pipeline.config import Config


def test_decode_text_attachment_plain_text() -> None:
    text, status = decode_text_attachment(
        b"hello analyst note",
        content_type="text/plain",
        config=Config(),
    )
    assert text == "hello analyst note"
    assert status == "text_decoded"


def test_extract_attachment_semantic_text_metadata_only_when_empty() -> None:
    result = extract_attachment_semantic_text(
        ClosedTicketAttachmentInput(
            attachment_id="att-1",
            ticket_id="ticket-1",
            filename="unknown.bin",
            content_type="application/octet-stream",
            metadata={},
            raw_content=None,
        ),
        Config(),
    )
    assert result.extraction_status == "metadata_only"
    assert result.semantic_text is not None
    assert "attachment_metadata_only" in result.semantic_text


def test_extract_attachment_semantic_text_uses_existing_metadata() -> None:
    result = extract_attachment_semantic_text(
        ClosedTicketAttachmentInput(
            attachment_id="att-1",
            ticket_id="ticket-1",
            filename="notes.txt",
            content_type="text/plain",
            metadata={"semantic_description": "previously extracted"},
            raw_content=None,
        ),
        Config(),
    )
    assert result.semantic_text == "previously extracted"
    assert result.extraction_status == "metadata_existing"
