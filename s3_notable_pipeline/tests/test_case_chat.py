"""Tests for selected-case portal Q&A retrieval."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from unittest.mock import patch

from s3_notable_pipeline.case_chat import (
    answer_selected_case_question,
    retrieve_selected_case_chunks,
)
from s3_notable_pipeline.config import Config
from s3_notable_pipeline.portal_chat import PortalAnswer


class FakeDynamoDbClient:
    """Fake CaseIndex client with configurable retrieval status."""

    def __init__(self, retrieval_status: str) -> None:
        self.retrieval_status = retrieval_status

    def get_item(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "Item": {
                "case_id": {"S": "case-1"},
                "retrieval_status": {"S": self.retrieval_status},
            }
        }


class FakeS3Client:
    """Fake S3 chunks client."""

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "Contents": [
                {"Key": f"{kwargs['Prefix']}chunk-1.json"},
            ],
            "IsTruncated": False,
        }

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        body = {
            "case_id": "case-1",
            "chunk_id": "chunk-1",
            "search_text": "alert.summary $ suspicious login",
        }
        return {"Body": io.BytesIO(json.dumps(body).encode("utf-8"))}


def config() -> Config:
    """Return Q&A config."""

    return Config(
        CASE_ARCHIVE_BUCKET="case-bucket",
        CASE_INDEX_TABLE="case-index",
        CASE_ARCHIVE_CHUNKS_PREFIX="case_chunks",
        CASE_QA_MAX_TOTAL_CHUNKS=18,
    )


class CaseChatTests(unittest.TestCase):
    """Selected-case retrieval tests."""

    def test_pending_case_returns_empty_retrieval(self) -> None:
        chunks = retrieve_selected_case_chunks(
            case_id="case-1",
            config=config(),
            dynamodb_client=FakeDynamoDbClient("pending"),
            s3_client=FakeS3Client(),
        )

        self.assertEqual(chunks, [])

    def test_ready_case_returns_selected_case_chunks(self) -> None:
        chunks = retrieve_selected_case_chunks(
            case_id="case-1",
            config=config(),
            dynamodb_client=FakeDynamoDbClient("ready"),
            s3_client=FakeS3Client(),
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_id"], "chunk-1")

    def test_selected_case_chat_passes_case_aware_query_to_kb_retrieval(self) -> None:
        captured: dict[str, str] = {}

        def _fake_kb_sources(*, question: str, config: Config, bedrock_agent_client=None):
            captured["question"] = question
            return []

        case_chunks = [
            {
                "chunk_id": "chunk-1",
                "section": "alert.summary",
                "search_text": "dest_host=db-prod-01.corp.local user=corp\\svc-backup",
                "text": "dest_host=db-prod-01.corp.local user=corp\\svc-backup",
            }
        ]

        with (
            patch(
                "s3_notable_pipeline.case_chat.retrieve_case_chunks_for_question",
                return_value=case_chunks,
            ),
            patch(
                "s3_notable_pipeline.case_chat.build_chat_knowledge_sources",
                side_effect=_fake_kb_sources,
            ),
            patch(
                "s3_notable_pipeline.case_chat.synthesize_case_answer",
                return_value=PortalAnswer(answer="Summary.", answer_status="answered"),
            ),
        ):
            answer_selected_case_question(
                case_id="case-5",
                question="Summarize this case in a few sentences.",
                config=Config(
                    PORTAL_ENABLED=True,
                    PORTAL_AUTH_MODE="iam",
                    CASE_QA_ENABLED=True,
                    CASE_INDEX_TABLE="case-index",
                    CASE_EMBED_LAMBDA_NAME="notable-case-embed",
                    CASE_QA_MAX_QUESTION_CHARS=2000,
                    CASE_QA_MAX_TOTAL_CHUNKS=18,
                    CASE_QA_MAX_CHUNKS_PER_LANE=12,
                    CASE_QA_CONTEXT_BUDGET_CHARS=12000,
                ),
                dynamodb_client=FakeDynamoDbClient("ready"),
                s3_client=FakeS3Client(),
                bedrock_client=object(),
            )

        self.assertIn("Summarize this case in a few sentences.", captured["question"])
        self.assertIn("db-prod-01.corp.local", captured["question"])
        self.assertIn("selected_case_id=case-5", captured["question"])


if __name__ == "__main__":
    unittest.main()
