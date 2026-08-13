"""Tests for Bedrock rerank helpers."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.bedrock_rerank import rerank_documents
from s3_notable_pipeline.opensearch_retrieval import RetrievedDocument


def _document(text: str, score: float, document_id: str = "") -> RetrievedDocument:
    return RetrievedDocument(
        document_id=document_id or text,
        text=text,
        score=score,
        tenant_id="tenant-a",
        corpus_id="soc",
        metadata={"provenance": {"manifest_id": "m-1"}},
    )


class FakeRerankClient:
    def __init__(self, responses: dict[str, dict] | None = None, failures: set[str] | None = None):
        self.responses = responses or {}
        self.failures = failures or set()
        self.calls: list[str] = []

    def invoke_model(self, **kwargs):
        model_id = kwargs["modelId"]
        self.calls.append(model_id)
        if model_id in self.failures:
            raise RuntimeError(f"rerank failed for {model_id}")
        payload = self.responses.get(model_id, {"results": []})
        return {"body": io.BytesIO(json.dumps(payload).encode())}


class BedrockRerankTests(unittest.TestCase):
    def test_disabled_rerank_returns_original_order(self) -> None:
        documents = [_document("first", 1.0), _document("second", 2.0)]
        config = SimpleNamespace(
            RAG_RERANK_ENABLED=False,
            RAG_RERANK_MODEL="cohere.rerank-v3-5:0",
            RAG_RERANK_MODEL_FALLBACK="amazon.rerank-v1:0",
        )
        client = FakeRerankClient(
            {
                "cohere.rerank-v3-5:0": {
                    "results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]
                }
            }
        )

        result = rerank_documents("query", documents, config, client)

        self.assertEqual([doc.text for doc in result], ["first", "second"])
        self.assertEqual(client.calls, [])

    def test_single_document_skips_rerank(self) -> None:
        documents = [_document("only", 1.0)]
        config = SimpleNamespace(
            RAG_RERANK_ENABLED=True,
            RAG_RERANK_MODEL="cohere.rerank-v3-5:0",
            RAG_RERANK_MODEL_FALLBACK="amazon.rerank-v1:0",
        )
        client = FakeRerankClient()

        result = rerank_documents("query", documents, config, client)

        self.assertEqual(result[0].text, "only")
        self.assertEqual(client.calls, [])

    def test_successful_rerank_reorders_and_sets_metadata(self) -> None:
        documents = [_document("first", 1.0), _document("second", 2.0)]
        config = SimpleNamespace(
            RAG_RERANK_ENABLED=True,
            RAG_RERANK_MODEL="cohere.rerank-v3-5:0",
            RAG_RERANK_MODEL_FALLBACK="amazon.rerank-v1:0",
        )
        client = FakeRerankClient(
            {
                "cohere.rerank-v3-5:0": {
                    "results": [
                        {"index": 1, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.05},
                    ]
                }
            }
        )

        result = rerank_documents("query", documents, config, client)

        self.assertEqual([doc.text for doc in result], ["second", "first"])
        self.assertEqual(result[0].score, 0.95)
        self.assertEqual(result[0].metadata["rerank_status"], "success")
        self.assertEqual(result[0].metadata["rerank_model"], "cohere.rerank-v3-5:0")
        self.assertEqual(client.calls, ["cohere.rerank-v3-5:0"])

    def test_fallback_model_is_used_when_primary_fails(self) -> None:
        documents = [_document("first", 1.0), _document("second", 2.0)]
        config = SimpleNamespace(
            RAG_RERANK_ENABLED=True,
            RAG_RERANK_MODEL="cohere.rerank-v3-5:0",
            RAG_RERANK_MODEL_FALLBACK="amazon.rerank-v1:0",
        )
        client = FakeRerankClient(
            {
                "amazon.rerank-v1:0": {
                    "results": [
                        {"index": 1, "relevance_score": 0.8},
                        {"index": 0, "relevance_score": 0.2},
                    ]
                }
            },
            failures={"cohere.rerank-v3-5:0"},
        )

        result = rerank_documents("query", documents, config, client)

        self.assertEqual([doc.text for doc in result], ["second", "first"])
        self.assertEqual(client.calls, ["cohere.rerank-v3-5:0", "amazon.rerank-v1:0"])
        self.assertEqual(result[0].metadata["rerank_model"], "amazon.rerank-v1:0")

    def test_fail_soft_returns_original_order_when_all_models_fail(self) -> None:
        documents = [_document("first", 1.0), _document("second", 2.0)]
        config = SimpleNamespace(
            RAG_RERANK_ENABLED=True,
            RAG_RERANK_MODEL="cohere.rerank-v3-5:0",
            RAG_RERANK_MODEL_FALLBACK="amazon.rerank-v1:0",
        )
        client = FakeRerankClient(failures={"cohere.rerank-v3-5:0", "amazon.rerank-v1:0"})

        result = rerank_documents("query", documents, config, client)

        self.assertEqual([doc.text for doc in result], ["first", "second"])
        self.assertEqual(result[0].metadata["rerank_status"], "failed")


if __name__ == "__main__":
    unittest.main()
