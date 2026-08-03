"""Tests for hybrid case-chunk retrieval."""

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

from s3_notable_pipeline.case_chunk_retrieval import (
    bm25_rank,
    merge_rrf,
    retrieve_case_chunks_for_question,
)
from s3_notable_pipeline.config import Config


class CaseChunkRetrievalTests(unittest.TestCase):
    """Hybrid rank behavior tests."""

    def test_bm25_prefers_matching_hypothesis_chunk(self) -> None:
        chunks = [
            {
                "chunk_id": "chunk-a",
                "case_id": "case-1",
                "search_text": "unrelated alert summary only",
            },
            {
                "chunk_id": "chunk-b",
                "case_id": "case-1",
                "search_text": "competing hypothesis 3 lateral movement details",
            },
        ]

        ranked = bm25_rank("hypothesis 3", chunks, top_k=2)

        self.assertEqual(ranked[0].chunk_id, "chunk-b")

    def test_merge_rrf_combines_lexical_and_vector_ranks(self) -> None:
        from s3_notable_pipeline.case_chunk_retrieval import RankedChunk

        lexical = [
            RankedChunk(
                chunk_id="chunk-a",
                case_id="case-1",
                chunk={"chunk_id": "chunk-a"},
                rank=2,
            ),
            RankedChunk(
                chunk_id="chunk-b",
                case_id="case-1",
                chunk={"chunk_id": "chunk-b"},
                rank=1,
            ),
        ]
        vector = [
            RankedChunk(
                chunk_id="chunk-b",
                case_id="case-1",
                chunk={"chunk_id": "chunk-b"},
                rank=1,
            ),
            RankedChunk(
                chunk_id="chunk-a",
                case_id="case-1",
                chunk={"chunk_id": "chunk-a"},
                rank=3,
            ),
        ]

        merged = merge_rrf(lexical, vector, rrf_k=60)

        self.assertEqual(merged[0].chunk_id, "chunk-b")


class FakeDynamoDbClient:
    def get_item(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "Item": {
                "case_id": {"S": "case-1"},
                "retrieval_status": {"S": "ready"},
            }
        }


class FakeS3Client:
    def __init__(self) -> None:
        self.embedding_b = [0.0] * 1023 + [1.0]
        self.embedding_a = [1.0] + [0.0] * 1023
        self.objects = {
            "case_chunks/case-1/chunk-a.json": {
                "case_id": "case-1",
                "chunk_id": "chunk-a",
                "search_text": "generic timeline notes",
                "embedding": self.embedding_a,
            },
            "case_chunks/case-1/chunk-b.json": {
                "case_id": "case-1",
                "chunk_id": "chunk-b",
                "search_text": "hypothesis 3 encoded command details",
                "embedding": self.embedding_b,
            },
        }

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        prefix = kwargs["Prefix"]
        keys = [key for key in self.objects if key.startswith(prefix)]
        return {
            "Contents": [{"Key": key} for key in keys],
            "IsTruncated": False,
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        return {
            "Body": io.BytesIO(json.dumps(self.objects[Key]).encode("utf-8")),
        }


class FakeBedrockClient:
    def invoke_model(self, **_kwargs: Any) -> dict[str, Any]:
        embedding = [0.0] * 1023 + [1.0]
        return {
            "body": io.BytesIO(
                json.dumps({"embedding": embedding}).encode("utf-8")
            )
        }


class CaseChatHybridRetrievalTests(unittest.TestCase):
    """End-to-end question-aware retrieval over fixture chunks."""

    def test_question_ranks_matching_hypothesis_chunk_first(self) -> None:
        config = Config(
            CASE_ARCHIVE_BUCKET="case-bucket",
            CASE_INDEX_TABLE="case-index",
            CASE_ARCHIVE_CHUNKS_PREFIX="case_chunks",
            CASE_QA_MAX_TOTAL_CHUNKS=18,
            CASE_QA_CONTEXT_BUDGET_CHARS=12_000,
            CASE_QA_LEXICAL_TOP_K=30,
            CASE_QA_VECTOR_TOP_K=30,
            CASE_QA_RRF_K=60,
        )
        chunks = retrieve_case_chunks_for_question(
            case_id="case-1",
            question="hypothesis 3",
            config=config,
            dynamodb_client=FakeDynamoDbClient(),
            s3_client=FakeS3Client(),
            bedrock_client=FakeBedrockClient(),
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["chunk_id"], "chunk-b")


if __name__ == "__main__":
    unittest.main()
