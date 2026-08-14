"""Tests for closed-ticket rendering."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from azure_notable_pipeline.closed_ticket_render import (
    ClosedTicketAttachmentRecord,
    ClosedTicketRecord,
    build_closed_ticket_chunk_id,
    build_closed_ticket_chunks,
    closed_ticket_embedding_model,
)
from azure_notable_pipeline.config import Config


def _record(**kwargs):
    defaults = {
        "ticket_id": "ticket-a",
        "ticket_number": "INC001",
        "source_table": "incident",
        "source_url": "https://sn.example/incident/INC001",
        "state": "Closed",
        "is_active": True,
        "closed_at": datetime(2026, 1, 2, tzinfo=UTC),
        "source_updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        "raw_payload": {},
        "journals_payload": [],
        "expires_at": datetime(2027, 1, 1, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return ClosedTicketRecord(**defaults)


class TestClosedTicketRender(unittest.TestCase):
    def test_flattens_display_value_objects(self) -> None:
        record = _record(
            raw_payload={
                "short_description": {
                    "display_value": "False positive login",
                    "value": "False positive login",
                },
                "assignment_group": {"display_value": "SecOps", "value": "secops-id"},
            }
        )
        chunks = build_closed_ticket_chunks(record, Config())
        payload_text = "\n".join(
            chunk.text for chunk in chunks if chunk.section == "ticket.payload"
        )
        self.assertIn("$.raw_payload.short_description.display_value", payload_text)
        self.assertIn("False positive login", payload_text)
        self.assertIn("$.raw_payload.assignment_group.display_value", payload_text)

    def test_chunk_ids_are_stable(self) -> None:
        chunk_id = build_closed_ticket_chunk_id(
            ticket_id="ticket-a",
            section="ticket.core",
            ordinal=0,
        )
        self.assertEqual(
            chunk_id,
            build_closed_ticket_chunk_id(
                ticket_id="ticket-a",
                section="ticket.core",
                ordinal=0,
            ),
        )

    def test_never_mixes_ticket_ids_in_chunks(self) -> None:
        record = _record(
            ticket_id="ticket-a",
            raw_payload={"number": "INC001"},
        )
        chunks = build_closed_ticket_chunks(record, Config())
        self.assertTrue(chunks)
        self.assertTrue(all(chunk.ticket_id == "ticket-a" for chunk in chunks))

    def test_builds_journal_and_attachment_semantic_chunks(self) -> None:
        record = _record(
            journals_payload=[
                {
                    "value": {
                        "display_value": "Closed after validation",
                        "value": "Closed after validation",
                    }
                }
            ]
        )
        attachment = ClosedTicketAttachmentRecord(
            attachment_id="att-1",
            ticket_id="ticket-a",
            filename="notes.txt",
            content_type="text/plain",
            metadata={},
            semantic_text="Analyst note: benign admin activity.",
            extraction_status="text_decoded",
        )
        chunks = build_closed_ticket_chunks(
            record,
            Config(),
            attachments=[attachment],
        )
        sections = {chunk.section for chunk in chunks}
        self.assertIn("ticket.journals", sections)
        self.assertIn("attachment.semantic", sections)

    def test_embedding_model_defaults_to_azure_openai(self) -> None:
        self.assertEqual(
            closed_ticket_embedding_model(Config()),
            "text-embedding-3-large",
        )
