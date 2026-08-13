"""Tests for portal chat closed-ticket retrieval lane."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.case_chat import answer_selected_case_question
from s3_notable_pipeline.closed_ticket_retrieval import (
    CLOSED_TICKET_CORPUS_ID,
    ClosedTicketRetrievalHit,
    ClosedTicketRetrievalOutcome,
    build_closed_ticket_retrieval_query,
    closed_ticket_lane_enabled,
    retrieve_closed_tickets_fail_soft,
)
from s3_notable_pipeline.config import Config
from s3_notable_pipeline.opensearch_retrieval import build_scoped_hybrid_query
from s3_notable_pipeline.portal_chat import (
    build_case_grounded_prompt,
    synthesize_case_answer,
)
from s3_notable_pipeline.portal_chat_kb import build_chat_closed_ticket_sources


class FakeDynamoDbClient:
    """Fake CaseIndex client."""

    def get_item(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "Item": {
                "case_id": {"S": "case-1"},
                "retrieval_status": {"S": "ready"},
            }
        }


class FakeS3Client:
    """Fake S3 chunks client."""

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "Contents": [{"Key": f"{kwargs['Prefix']}chunk-1.json"}],
            "IsTruncated": False,
        }

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        body = {
            "case_id": "case-1",
            "chunk_id": "chunk-1",
            "search_text": "alert.summary suspicious admin PowerShell login",
        }
        return {"Body": io.BytesIO(json.dumps(body).encode("utf-8"))}


class FakeBedrockClient:
    """Fake Bedrock client for embedding and synthesis."""

    def invoke_model(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "body": io.BytesIO(
                json.dumps({"embedding": [0.01] * 1024}).encode("utf-8")
            )
        }

    def converse(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "output": {
                "message": {
                    "content": [{"text": "Grounded answer from closed ticket precedent."}]
                }
            }
        }


def _portal_config(**overrides: Any) -> Config:
    values = {
        "CASE_ARCHIVE_BUCKET": "case-bucket",
        "CASE_INDEX_TABLE": "case-index",
        "CASE_ARCHIVE_CHUNKS_PREFIX": "case_chunks",
        "PORTAL_ENABLED": True,
        "PORTAL_AUTH_MODE": "iam",
        "CASE_QA_ENABLED": True,
        "CASE_EMBED_LAMBDA_NAME": "notable-case-embed",
        "CASE_QA_MAX_TOTAL_CHUNKS": 18,
        "CASE_QA_MAX_CHUNKS_PER_LANE": 6,
        "CASE_QA_CONTEXT_BUDGET_CHARS": 12_000,
        "CASE_QA_MAX_ANSWER_TOKENS": 800,
        "CASE_QA_GENERAL_KNOWLEDGE_ENABLED": False,
        "BEDROCK_MODEL_ID": "anthropic.test",
        "OPENSEARCH_ENDPOINT": "https://search.example.local",
        "RAG_TENANT_ID": "tenant-a",
        "RAG_RETRIEVAL_BACKEND": "opensearch",
    }
    values.update(overrides)
    return Config(**values)


class ClosedTicketRetrievalTests(unittest.TestCase):
    """Unit tests for closed-ticket retrieval helpers."""

    def test_lane_requires_both_flags(self) -> None:
        self.assertFalse(
            closed_ticket_lane_enabled(
                Config(
                    CASE_QA_CLOSED_TICKET_ENABLED=True,
                    CLOSED_TICKET_RAG_ENABLED=False,
                )
            )
        )
        self.assertFalse(
            closed_ticket_lane_enabled(
                Config(
                    CASE_QA_CLOSED_TICKET_ENABLED=False,
                    CLOSED_TICKET_RAG_ENABLED=True,
                )
            )
        )
        self.assertTrue(
            closed_ticket_lane_enabled(
                Config(
                    CASE_QA_CLOSED_TICKET_ENABLED=True,
                    CLOSED_TICKET_RAG_ENABLED=True,
                )
            )
        )

    def test_build_query_combines_question_and_case_snippets(self) -> None:
        query = build_closed_ticket_retrieval_query(
            question="Summarize disposition options.",
            current_case_snippets=["admin PowerShell from host-a"],
        )
        self.assertIn("Summarize disposition options.", query)
        self.assertIn("admin PowerShell from host-a", query)

    def test_hybrid_query_scopes_tenant_and_corpus(self) -> None:
        query = build_scoped_hybrid_query(
            query_text="credential reset precedent",
            query_embedding=[0.1, 0.2],
            tenant_id="tenant-a",
            corpus_id=CLOSED_TICKET_CORPUS_ID,
            top_k=6,
        )
        filters = query["query"]["bool"]["filter"]
        self.assertEqual(
            filters,
            [
                {"term": {"tenant_id.keyword": "tenant-a"}},
                {"term": {"corpus_id.keyword": CLOSED_TICKET_CORPUS_ID}},
                {"term": {"active": True}},
            ],
        )

    def test_fail_soft_returns_error_without_raising(self) -> None:
        config = _portal_config(
            CASE_QA_CLOSED_TICKET_ENABLED=True,
            CLOSED_TICKET_RAG_ENABLED=True,
        )
        with patch(
            "s3_notable_pipeline.closed_ticket_retrieval.retrieve_closed_ticket_hits",
            side_effect=RuntimeError("opensearch unavailable"),
        ):
            outcome = retrieve_closed_tickets_fail_soft(
                config=config,
                question="What happened?",
                bedrock_client=FakeBedrockClient(),
            )
        self.assertEqual(outcome.hits, [])
        self.assertEqual(outcome.context, "")
        self.assertEqual(outcome.error, "opensearch unavailable")


class PortalChatClosedTicketIntegrationTests(unittest.TestCase):
    """Portal chat wiring tests for the closed-ticket lane."""

    def test_build_chat_closed_ticket_sources_disabled_without_flags(self) -> None:
        sources = build_chat_closed_ticket_sources(
            question="Compare disposition.",
            case_sources=[{"source_lane": "current_case", "text": "case text"}],
            config=_portal_config(),
            bedrock_client=FakeBedrockClient(),
        )
        self.assertEqual(sources, [])

    def test_build_prompt_includes_closed_ticket_provenance(self) -> None:
        prompt = build_case_grounded_prompt(
            question="Compare disposition.",
            sources=[
                {
                    "source_lane": "closed_ticket",
                    "section": "resolution",
                    "text": "Reset credentials and closed.",
                    "search_text": "Reset credentials and closed.",
                    "ticket_id": "ticket-abc",
                    "ticket_number": "INC4242",
                    "provenance": "closed_ticket_rag:hybrid",
                }
            ],
        )
        self.assertIn("SOURCE_LANE_JSON: \"closed_ticket\"", prompt)
        self.assertIn("TICKET_ID_JSON: \"ticket-abc\"", prompt)
        self.assertIn("TICKET_NUMBER_JSON: \"INC4242\"", prompt)
        self.assertIn("PROVENANCE_JSON:", prompt)

    def test_synthesis_context_usage_includes_closed_ticket_segment(self) -> None:
        config = _portal_config()
        result = synthesize_case_answer(
            question="Compare disposition.",
            sources=[
                {
                    "source_lane": "current_case",
                    "text": "Current case evidence.",
                    "search_text": "Current case evidence.",
                },
                {
                    "source_lane": "closed_ticket",
                    "section": "resolution",
                    "text": "Historical precedent text.",
                    "search_text": "Historical precedent text.",
                    "ticket_id": "ticket-1",
                },
            ],
            config=config,
            bedrock_client=FakeBedrockClient(),
        )
        usage = result.context_usage
        self.assertIsInstance(usage, dict)
        segment_ids = {segment["id"] for segment in usage["segments"]}
        self.assertIn("closed_ticket", segment_ids)

    @patch("s3_notable_pipeline.case_chat.retrieve_case_chunks_for_question")
    @patch("s3_notable_pipeline.case_chat.build_chat_knowledge_sources")
    @patch("s3_notable_pipeline.case_chat.build_chat_closed_ticket_sources")
    def test_answer_selected_case_merges_closed_ticket_lane(
        self,
        mock_closed_ticket_sources: Any,
        mock_kb_sources: Any,
        mock_case_chunks: Any,
    ) -> None:
        mock_case_chunks.return_value = [
            {
                "section": "alert.summary",
                "chunk_id": "chunk-1",
                "search_text": "admin PowerShell login",
                "text": "admin PowerShell login",
            }
        ]
        mock_kb_sources.return_value = [
            {
                "source_lane": "knowledge_base",
                "section": "knowledge_base.rag",
                "text": "Escalate credentialed PowerShell.",
                "search_text": "Escalate credentialed PowerShell.",
            }
        ]
        mock_closed_ticket_sources.return_value = [
            {
                "source_lane": "closed_ticket",
                "section": "resolution",
                "text": "Reset credentials and closed ticket.",
                "search_text": "Reset credentials and closed ticket.",
                "ticket_id": "ticket-1",
                "ticket_number": "INC0001",
                "provenance": "closed_ticket_rag:hybrid",
            }
        ]
        captured_prompts: list[str] = []

        class PromptCapturingBedrock(FakeBedrockClient):
            def converse(self, **kwargs: Any) -> dict[str, Any]:
                captured_prompts.append(
                    kwargs["messages"][0]["content"][0]["text"]
                )
                return super().converse(**kwargs)

        answer = answer_selected_case_question(
            case_id="case-1",
            question="Summarize disposition options.",
            config=_portal_config(
                CASE_QA_CLOSED_TICKET_ENABLED=True,
                CLOSED_TICKET_RAG_ENABLED=True,
            ),
            dynamodb_client=FakeDynamoDbClient(),
            s3_client=FakeS3Client(),
            bedrock_client=PromptCapturingBedrock(),
        )
        mock_closed_ticket_sources.assert_called_once()
        call_kwargs = mock_closed_ticket_sources.call_args.kwargs
        self.assertEqual(call_kwargs["question"], "Summarize disposition options.")
        self.assertEqual(answer.answer_status, "answered")
        usage = answer.context_usage
        self.assertIsNotNone(usage)
        segment_ids = {segment["id"] for segment in usage["segments"]}
        self.assertIn("closed_ticket", segment_ids)
        self.assertTrue(captured_prompts)
        prompt = captured_prompts[0]
        self.assertIn("SOURCE_LANE_JSON: \"closed_ticket\"", prompt)
        self.assertIn("SOURCE_LANE_JSON: \"current_case\"", prompt)
        self.assertIn("SOURCE_LANE_JSON: \"knowledge_base\"", prompt)

    @patch("s3_notable_pipeline.case_chat.retrieve_case_chunks_for_question")
    @patch("s3_notable_pipeline.case_chat.build_chat_closed_ticket_sources")
    def test_closed_ticket_retrieval_failure_is_fail_soft(
        self,
        mock_closed_ticket_sources: Any,
        mock_case_chunks: Any,
    ) -> None:
        mock_case_chunks.return_value = [
            {
                "section": "alert.summary",
                "chunk_id": "chunk-1",
                "search_text": "suspicious login",
                "text": "suspicious login",
            }
        ]
        mock_closed_ticket_sources.return_value = []
        answer = answer_selected_case_question(
            case_id="case-1",
            question="What evidence supports this?",
            config=_portal_config(
                CASE_QA_CLOSED_TICKET_ENABLED=True,
                CLOSED_TICKET_RAG_ENABLED=True,
            ),
            dynamodb_client=FakeDynamoDbClient(),
            s3_client=FakeS3Client(),
            bedrock_client=FakeBedrockClient(),
        )
        mock_closed_ticket_sources.assert_called_once()
        self.assertEqual(answer.answer_status, "answered")
        usage = answer.context_usage
        self.assertIsNotNone(usage)
        segment_ids = {segment["id"] for segment in usage["segments"]}
        self.assertNotIn("closed_ticket", segment_ids)


if __name__ == "__main__":
    unittest.main()
