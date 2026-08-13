"""Tests for closed-ticket advisory grounding in the analyzer lane."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.closed_ticket_retrieval import (  # noqa: E402
    ClosedTicketRetrievalHit,
    ClosedTicketRetrievalOutcome,
    render_historical_closed_tickets_context,
    retrieve_closed_tickets_fail_soft,
)
from s3_notable_pipeline.config import Config  # noqa: E402
from s3_notable_pipeline.historical_closed_ticket_grounding import (  # noqa: E402
    HISTORICAL_CLOSED_TICKET_RULES,
    build_closed_ticket_rag_metadata,
    format_historical_closed_tickets_prompt_block,
    retrieve_historical_closed_tickets_for_first_pass,
)
from s3_notable_pipeline.ttp_analyzer import BedrockAnalyzer  # noqa: E402


def _sample_hit(ticket_id: str = "t1") -> ClosedTicketRetrievalHit:
    return ClosedTicketRetrievalHit(
        ticket_id=ticket_id,
        ticket_number="INC-100",
        section="summary",
        field_path="verdict",
        text="Prior benign closure after validation.",
        score=0.91,
        source_url="https://example.test/inc100",
    )


def _sample_historical_context() -> str:
    return render_historical_closed_tickets_context([_sample_hit()])


class TestHistoricalClosedTicketGrounding(unittest.TestCase):
    def test_format_block_none_when_empty(self) -> None:
        block = format_historical_closed_tickets_prompt_block("")
        self.assertEqual(block, "HISTORICAL_CLOSED_TICKETS\n(none)\n")

    def test_rules_cover_advisory_and_evidence_boundaries(self) -> None:
        self.assertIn("advisory precedent", HISTORICAL_CLOSED_TICKET_RULES)
        self.assertIn(
            "Never treat HISTORICAL_CLOSED_TICKETS as direct evidence",
            HISTORICAL_CLOSED_TICKET_RULES,
        )
        self.assertIn("Do not add IOCs", HISTORICAL_CLOSED_TICKET_RULES)

    def test_metadata_disabled_is_skipped(self) -> None:
        meta = build_closed_ticket_rag_metadata(enabled=False)
        self.assertEqual(meta["closed_ticket_rag_status"], "skipped")
        self.assertFalse(meta["closed_ticket_rag_included"])

    def test_metadata_success_without_payload_text(self) -> None:
        context = _sample_historical_context()
        meta = build_closed_ticket_rag_metadata(
            enabled=True,
            hits=[_sample_hit(), _sample_hit("t2")],
            context=context,
        )
        self.assertEqual(meta["closed_ticket_rag_status"], "success")
        self.assertTrue(meta["closed_ticket_rag_included"])
        self.assertEqual(meta["closed_ticket_rag_hit_count"], 2)
        self.assertEqual(meta["closed_ticket_rag_snippet_count"], 2)
        self.assertEqual(meta["closed_ticket_rag_context_chars"], len(context))

    def test_metadata_degraded_on_unavailable(self) -> None:
        meta = build_closed_ticket_rag_metadata(
            enabled=True,
            unavailable_reason="opensearch unavailable",
        )
        self.assertEqual(meta["closed_ticket_rag_status"], "degraded")
        self.assertTrue(meta["closed_ticket_rag_unavailable"])

    def test_metadata_no_match_when_enabled_without_hits(self) -> None:
        meta = build_closed_ticket_rag_metadata(enabled=True)
        self.assertEqual(meta["closed_ticket_rag_status"], "no_match")

    @patch(
        "s3_notable_pipeline.historical_closed_ticket_grounding.retrieve_closed_tickets_fail_soft"
    )
    def test_retrieve_skipped_when_disabled(self, mock_retrieve) -> None:
        config = Config(CLOSED_TICKET_RAG_ENABLED=False)
        result = retrieve_historical_closed_tickets_for_first_pass(config, "alert")
        self.assertEqual(result.status, "skipped")
        mock_retrieve.assert_not_called()

    @patch(
        "s3_notable_pipeline.historical_closed_ticket_grounding.retrieve_closed_tickets_fail_soft"
    )
    def test_retrieve_success_when_hits_present(self, mock_retrieve) -> None:
        context = _sample_historical_context()
        mock_retrieve.return_value = ClosedTicketRetrievalOutcome(
            hits=[_sample_hit()],
            context=context,
        )
        config = Config(CLOSED_TICKET_RAG_ENABLED=True)
        result = retrieve_historical_closed_tickets_for_first_pass(config, "alert")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.snippet_count, 1)
        self.assertEqual(result.context, context)
        self.assertEqual(result.metadata["closed_ticket_rag_status"], "success")

    @patch(
        "s3_notable_pipeline.historical_closed_ticket_grounding.retrieve_closed_tickets_fail_soft"
    )
    def test_retrieve_degraded_on_fail_soft_error(self, mock_retrieve) -> None:
        mock_retrieve.return_value = ClosedTicketRetrievalOutcome(
            hits=[],
            context="",
            error="opensearch unavailable",
        )
        config = Config(CLOSED_TICKET_RAG_ENABLED=True)
        result = retrieve_historical_closed_tickets_for_first_pass(config, "alert")
        self.assertEqual(result.status, "degraded")
        self.assertIn("opensearch unavailable", result.message)

    @patch(
        "s3_notable_pipeline.closed_ticket_retrieval.retrieve_closed_ticket_hits",
        side_effect=RuntimeError("boom"),
    )
    def test_fail_soft_retrieval_returns_error(self, _mock_hits) -> None:
        config = Config(CLOSED_TICKET_RAG_ENABLED=True)
        outcome = retrieve_closed_tickets_fail_soft(config=config, alert_text="alert")
        self.assertEqual(outcome.error, "boom")
        self.assertEqual(outcome.context, "")

    @patch("s3_notable_pipeline.opensearch_retrieval.retrieve_documents")
    @patch("s3_notable_pipeline.case_embed.embed_text")
    @patch("s3_notable_pipeline.opensearch_retrieval.opensearch_enabled", return_value=True)
    @patch("s3_notable_pipeline.opensearch_retrieval.tenant_id_for", return_value="tenant-a")
    def test_retrieval_maps_opensearch_documents_to_hits(
        self,
        _tenant,
        _enabled,
        mock_embed,
        mock_retrieve_documents,
    ) -> None:
        mock_embed.return_value = [0.1, 0.2]
        mock_retrieve_documents.return_value = [
            SimpleNamespace(
                document_id="chunk-1",
                chunk_id="chunk-1",
                case_id="",
                section="resolution",
                text="Closed as benign after host validation.",
                score=1.5,
                metadata={
                    "ticket_id": "sys-1",
                    "ticket_number": "INC-200",
                    "field_path": "close_notes",
                    "source_url": "https://example.test/inc200",
                },
            )
        ]
        config = Config(
            CLOSED_TICKET_RAG_ENABLED=True,
            OPENSEARCH_ENDPOINT="https://search.example.test",
            RAG_TENANT_ID="tenant-a",
            RAG_RETRIEVAL_BACKEND="opensearch",
        )
        outcome = retrieve_closed_tickets_fail_soft(
            config=config,
            alert_text="suspicious login",
            opensearch_client=object(),
            bedrock_client=object(),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(len(outcome.hits), 1)
        self.assertEqual(outcome.hits[0].ticket_id, "sys-1")
        self.assertIn("HISTORICAL_CLOSED_TICKETS", outcome.context)
        self.assertIn("<HISTORICAL_CLOSED_TICKET_BLOCK>", outcome.context)

    def test_prompt_includes_historical_lane_after_soc_rules(self) -> None:
        with patch("s3_notable_pipeline.ttp_analyzer.boto3.client"):
            analyzer = BedrockAnalyzer(model_id="test-model")
        prompt = analyzer._build_prompt(
            "user=alice",
            None,
            use_tool=True,
            advisory_context="Use index main for pivots.",
            historical_closed_tickets_context=_sample_historical_context(),
        )
        soc_rules_idx = prompt.index("SOC CONTEXT RULES:")
        historical_idx = prompt.index("HISTORICAL_CLOSED_TICKETS", soc_rules_idx)
        rules_idx = prompt.index("HISTORICAL CLOSED-TICKET RULES:", historical_idx)
        self.assertLess(soc_rules_idx, historical_idx)
        self.assertLess(historical_idx, rules_idx)
        self.assertIn("Never treat HISTORICAL_CLOSED_TICKETS as direct evidence", prompt)


if __name__ == "__main__":
    unittest.main()
