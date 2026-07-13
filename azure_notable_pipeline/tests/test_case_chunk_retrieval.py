"""Native-fake tests for hybrid case-chunk retrieval."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from azure_notable_pipeline.case_chunk_retrieval import (
    RankedChunk,
    bm25_rank,
    merge_rrf,
    retrieve_case_chunks_for_question,
)
from azure_notable_pipeline.config import Config


class FakeCaseStore:
    def get_case(self, case_id: str) -> dict[str, Any] | None:
        return {"case_id": case_id, "retrieval_status": "ready"}


class FakeChunkSource:
    def __init__(self) -> None:
        vector_a = [1.0] + [0.0] * 1023
        vector_b = [0.0] * 1023 + [1.0]
        self.chunks = [
            {
                "case_id": "case-1",
                "chunk_id": "chunk-a",
                "search_text": "generic timeline notes",
                "embedding": vector_a,
                "source_lane": "current_case",
            },
            {
                "case_id": "case-1",
                "chunk_id": "chunk-b",
                "search_text": "hypothesis 3 encoded command details",
                "embedding": vector_b,
                "source_lane": "current_case",
            },
        ]
        self.limits: list[int] = []

    def load_chunks(self, case_id: str, *, limit: int) -> list[dict[str, Any]]:
        self.limits.append(limit)
        return [chunk for chunk in self.chunks if chunk["case_id"] == case_id][:limit]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        vector = [0.0] * 1023 + [1.0]
        return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=vector)])


def test_bm25_prefers_matching_hypothesis_chunk() -> None:
    chunks = FakeChunkSource().chunks
    ranked = bm25_rank("hypothesis 3", chunks, top_k=2)
    assert ranked[0].chunk_id == "chunk-b"


def test_merge_rrf_combines_lexical_and_vector_ranks() -> None:
    lexical = [
        RankedChunk("chunk-a", "case-1", {"chunk_id": "chunk-a"}, 2),
        RankedChunk("chunk-b", "case-1", {"chunk_id": "chunk-b"}, 1),
    ]
    vector = [
        RankedChunk("chunk-b", "case-1", {"chunk_id": "chunk-b"}, 1),
        RankedChunk("chunk-a", "case-1", {"chunk_id": "chunk-a"}, 3),
    ]
    assert merge_rrf(lexical, vector, rrf_k=60)[0].chunk_id == "chunk-b"


def test_question_uses_azure_openai_embedding_and_bounded_chunk_source() -> None:
    source = FakeChunkSource()
    embeddings = FakeEmbeddings()
    gateway = SimpleNamespace(embeddings=embeddings)
    config = Config(
        AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT="embeddings-1024",
        CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=200,
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
        case_store=FakeCaseStore(),
        chunk_source=source,
        embedding_gateway=gateway,
    )

    assert source.limits == [200]
    assert chunks[0]["chunk_id"] == "chunk-b"
    assert embeddings.calls == [
        {
            "model": "embeddings-1024",
            "input": ["hypothesis 3"],
            "dimensions": 1024,
            "timeout": 60,
        }
    ]
