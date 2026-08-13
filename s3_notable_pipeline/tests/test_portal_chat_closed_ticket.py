"""Tests for portal closed-ticket chat lane integration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.closed_ticket_retrieval import (
    ClosedTicketRetrievalHit,
    ClosedTicketRetrievalOutcome,
    build_closed_ticket_retrieval_query,
    closed_ticket_hits_to_chat_sources,
    render_historical_closed_tickets_context,
    retrieve_closed_tickets_fail_soft,
)
from s3_notable_pipeline.config import Config
from s3_notable_pipeline.portal_chat import build_case_grounded_prompt, trim_sources
from s3_notable_pipeline.portal_chat_kb import build_closed_ticket_chat_sources


def _config(*, lane_enabled: bool = True, rag_enabled: bool = True) -> Config:
    return Config(
        CASE_QA_ENABLED=True,
        PORTAL_ENABLED=True,
        PORTAL_AUTH_MODE="jwt",
        PORTAL_JWT_ISSUER="https://issuer.example.test",
        PORTAL_JWT_AUDIENCE="portal",
        PORTAL_REQUIRED_ANALYST_ROLE="Case.Reader",
        CASE_EMBED_QUEUE_URL="https://sqs.example.test/queue",
        CASE_INDEX_TABLE="case-index",
        CASE_ARCHIVE_BUCKET="case-bucket",
        RAG_RETRIEVAL_BACKEND="opensearch",
        OPENSEARCH_ENDPOINT="https://search.example.test",
        RAG_TENANT_ID="tenant-a",
        CASE_QA_CLOSED_TICKET_ENABLED=lane_enabled,
        CLOSED_TICKET_RAG_ENABLED=rag_enabled,
    )


class TestClosedTicketRetrieval(unittest.TestCase):
    def test_build_query_combines_question_and_case_snippets(self) -> None:
        query = build_closed_ticket_retrieval_query(
            alert_text="Suspicious PowerShell",
            question="Was this closed before?",
            current_case_snippets=["host=workstation-1"],
        )
        self.assertIn("Suspicious PowerShell", query)
        self.assertIn("Was this closed before?", query)
        self.assertIn("host=workstation-1", query)

    def test_render_context_uses_historical_header(self) -> None:
        hits = [
            ClosedTicketRetrievalHit(
                ticket_id="t1",
                ticket_number="INC1",
                section="ticket.payload",
                field_path="$",
                text="Benign login precedent",
                score=1.2,
                source_url="https://sn.example/INC1",
            )
        ]
        context = render_historical_closed_tickets_context(hits, budget_chars=500)
        self.assertTrue(context.startswith("HISTORICAL_CLOSED_TICKETS"))
        self.assertIn("UNTRUSTED_EXCERPT_JSON", context)
        self.assertIn("Benign login precedent", context)

    def test_chat_source_adapter_shape(self) -> None:
        hit = ClosedTicketRetrievalHit(
            ticket_id="t1",
            ticket_number="INC1",
            section="ticket.core",
            field_path="$",
            text="ticket summary",
            score=0.5,
            source_url="https://sn.example/INC1",
            chunk_id="c1",
        )
        sources = closed_ticket_hits_to_chat_sources([hit])
        self.assertEqual(sources[0]["source_lane"], "closed_ticket")
        self.assertEqual(sources[0]["ticket_id"], "t1")

    def test_fail_soft_returns_outcome_with_error(self) -> None:
        config = _config()

        with patch(
            "s3_notable_pipeline.closed_ticket_retrieval.retrieve_closed_ticket_hits",
            side_effect=RuntimeError("opensearch unavailable"),
        ):
            outcome = retrieve_closed_tickets_fail_soft(
                config=config,
                question="login false positive",
                bedrock_client=object(),
            )
        self.assertEqual(outcome.hits, [])
        self.assertEqual(outcome.context, "")
        self.assertIn("opensearch unavailable", outcome.error or "")

    def test_disabled_lane_returns_empty_outcome(self) -> None:
        config = _config(lane_enabled=False)
        outcome = retrieve_closed_tickets_fail_soft(
            config=config,
            question="anything",
            bedrock_client=object(),
        )
        self.assertEqual(outcome, ClosedTicketRetrievalOutcome(hits=[], context=""))


class TestPortalClosedTicketIntegration(unittest.TestCase):
    def test_build_closed_ticket_sources_disabled_returns_empty(self) -> None:
        config = _config(lane_enabled=False)
        sources = build_closed_ticket_chat_sources(
            question="Was this benign before?",
            config=config,
            case_sources=[{"source_lane": "current_case", "text": "login alert"}],
            bedrock_client=object(),
        )
        self.assertEqual(sources, [])

    def test_build_closed_ticket_sources_maps_hits(self) -> None:
        config = _config()
        outcome = ClosedTicketRetrievalOutcome(
            hits=[
                ClosedTicketRetrievalHit(
                    ticket_id="t1",
                    ticket_number="INC1",
                    section="ticket.payload",
                    field_path="$",
                    text="Prior benign login",
                    score=0.9,
                    source_url="https://sn.example/INC1",
                )
            ],
            context="HISTORICAL_CLOSED_TICKETS",
        )
        with patch(
            "s3_notable_pipeline.portal_chat_kb.retrieve_closed_tickets_fail_soft",
            return_value=outcome,
        ):
            sources = build_closed_ticket_chat_sources(
                question="Was this benign before?",
                config=config,
                case_sources=[{"source_lane": "current_case", "text": "login alert"}],
                bedrock_client=object(),
            )
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_lane"], "closed_ticket")
        self.assertEqual(sources[0]["ticket_number"], "INC1")

    def test_prompt_labels_closed_ticket_lane(self) -> None:
        prompt = build_case_grounded_prompt(
            question="Compare to prior tickets",
            sources=[
                {
                    "source_lane": "closed_ticket",
                    "section": "ticket.payload",
                    "ticket_id": "t1",
                    "ticket_number": "INC1",
                    "provenance": "closed_ticket_rag:opensearch",
                    "text": "Prior benign login",
                }
            ],
        )
        self.assertIn("closed_ticket", prompt)
        self.assertIn("TICKET_NUMBER_JSON", prompt)
        self.assertIn("INC1", prompt)

    def test_trim_sources_applies_closed_ticket_lane_budget(self) -> None:
        config = _config()
        config.CLOSED_TICKET_RAG_CONTEXT_BUDGET_CHARS = 40
        config.CASE_QA_CONTEXT_BUDGET_CHARS = 10_000
        sources = trim_sources(
            [
                {
                    "source_lane": "closed_ticket",
                    "text": "x" * 30,
                },
                {
                    "source_lane": "closed_ticket",
                    "text": "y" * 30,
                },
            ],
            config,
        )
        self.assertEqual(len(sources), 1)
