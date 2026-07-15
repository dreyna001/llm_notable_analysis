"""Hybrid BM25 + vector case-chunk retrieval for Azure portal Q&A."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .azure_openai_gateway import embed_texts
from .azure_search_adapter import AzureSearchAdapter, build_filter
from .azure_search_retrieval import application_managed_search_enabled, config_value, tenant_id_for
from .blob_store import list_blobs, read_blob
from .config import Config

_MAX_PROMPT_SOURCE_CHARS = 2_400
_MAX_CHUNK_BLOB_BYTES = 1_048_576
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_BM25_K1 = 1.5
_BM25_B = 0.75


class CaseChunkSource(Protocol):
    """Application-facing source of bounded case chunk objects."""

    def load_chunks(self, case_id: str, *, limit: int) -> list[dict[str, Any]]:
        """Load at most ``limit`` chunks for one case."""


class BlobCaseChunkSource:
    """Read case chunks through the native application Blob boundary."""

    def __init__(
        self,
        *,
        container_name: str,
        chunks_prefix: str,
        store: Any | None = None,
        account_url: str | None = None,
    ) -> None:
        self.container_name = str(container_name or "").strip()
        self.chunks_prefix = str(chunks_prefix or "").strip().strip("/")
        self.store = store
        self.account_url = account_url

    def load_chunks(self, case_id: str, *, limit: int) -> list[dict[str, Any]]:
        normalized_case_id = str(case_id or "").strip()
        prefix = f"{self.chunks_prefix}/{normalized_case_id}/"
        blobs = list_blobs(
            self.container_name,
            prefix=prefix,
            limit=limit,
            store=self.store,
            account_url=self.account_url,
        )
        chunks: list[dict[str, Any]] = []
        for blob in blobs:
            body = read_blob(
                self.container_name,
                blob.blob_name,
                max_bytes=_MAX_CHUNK_BLOB_BYTES,
                store=self.store,
                account_url=self.account_url,
            )
            try:
                chunk = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"case chunk {blob.blob_name!r} must contain a UTF-8 JSON object"
                ) from exc
            if not isinstance(chunk, dict):
                raise ValueError(f"case chunk {blob.blob_name!r} must be a JSON object")
            if str(chunk.get("case_id", "")) == normalized_case_id:
                chunks.append(chunk)
        return chunks


class AzureSearchCaseChunkSource:
    """Dedicated Search case index source; it never lists or reads chunk Blobs."""

    def __init__(
        self,
        *,
        index_name: str,
        tenant_id: str,
        adapter: Any | None = None,
        run_id: str = "",
    ) -> None:
        self.index_name = str(index_name or "").strip()
        self.tenant_id = str(tenant_id or "").strip()
        self.adapter = adapter
        self.run_id = str(run_id or "").strip()
        if not self.index_name:
            raise ValueError("CASE_QA_AZURE_SEARCH_INDEX is required")
        if not self.tenant_id:
            raise ValueError("RAG_TENANT_ID is required for case Search retrieval")

    def _adapter(self) -> Any:
        return self.adapter or AzureSearchAdapter.from_config(
            SimpleConfig(index=self.index_name),
            index_name=self.index_name,
        )

    def load_chunks(self, case_id: str, *, limit: int) -> list[dict[str, Any]]:
        documents = self._adapter().search(
            index=self.index_name,
            filter=build_filter(
                tenant_id=self.tenant_id,
                corpus_id="case_chunks",
                case_id=str(case_id).strip(),
                run_id=self.run_id,
                active_only=True,
            ),
            select=False,
            top=min(max(1, int(limit)), 1000),
        )
        return [_case_document(document) for document in documents]

    def retrieve(
        self,
        *,
        case_id: str,
        question: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        documents = self._adapter().hybrid_search(
            index=self.index_name,
            query_text=question,
            query_embedding=query_embedding,
            tenant_id=self.tenant_id,
            corpus_id="case_chunks",
            case_id=str(case_id).strip(),
            run_id=self.run_id,
            top_k=min(max(1, int(top_k)), 1000),
        )
        return [_case_document(document) for document in documents]


class SimpleConfig:
    """Minimal adapter config used when callers inject no full Config object."""

    def __init__(self, *, index: str) -> None:
        self.AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "")
        self.RAG_AZURE_SEARCH_INDEX = index


def _case_document(document: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(document)
    normalized.setdefault("chunk_id", normalized.get("id", ""))
    normalized.setdefault("text", normalized.get("search_text", ""))
    normalized.setdefault("search_text", normalized.get("text", ""))
    return normalized


@dataclass
class RankedChunk:
    """One chunk candidate with retrieval rank metadata."""

    chunk_id: str
    case_id: str
    chunk: dict[str, Any]
    rank: int
    score: float = 0.0
    fusion_score: float = 0.0


def load_all_case_chunks(
    *,
    case_id: str,
    config: Config,
    case_store: Any,
    chunk_source: CaseChunkSource | None = None,
    case_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Load bounded Blob chunk JSON only when case retrieval is ready."""

    normalized_case_id = str(case_id or "").strip()
    if not normalized_case_id:
        raise ValueError("case_id is required")
    metadata = case_metadata or case_store.get_case(
        config.CASE_INDEX_CONTAINER, normalized_case_id
    )
    if not metadata:
        raise LookupError("case not found")
    if str(metadata.get("retrieval_status", "")).lower() != "ready":
        return []

    if application_managed_search_enabled(config, case=True):
        index_name = str(
            config_value(
                config,
                "CASE_QA_AZURE_SEARCH_INDEX",
                config_value(config, "CASE_AZURE_SEARCH_INDEX", ""),
            )
            or ""
        ).strip()
        run_id = str(
            metadata.get("retrieval_run_id")
            or metadata.get("active_run_id")
            or metadata.get("run_id")
            or metadata.get("latest_run_id")
            or ""
        ).strip()
        source = chunk_source
        if source is None or isinstance(source, BlobCaseChunkSource):
            source = AzureSearchCaseChunkSource(
                index_name=index_name,
                tenant_id=tenant_id_for(config, required=True),
                run_id=run_id,
            )
        return source.load_chunks(
            normalized_case_id,
            limit=config.CASE_QA_MAX_INDEX_CHUNKS_PER_CASE,
        )

    source = chunk_source or BlobCaseChunkSource(
        container_name=config.CASE_ARCHIVE_CONTAINER,
        chunks_prefix=config.CASE_ARCHIVE_CHUNKS_PREFIX,
        account_url=config.OUTPUT_STORAGE_ACCOUNT_URL,
    )
    return source.load_chunks(
        normalized_case_id,
        limit=config.CASE_QA_MAX_INDEX_CHUNKS_PER_CASE,
    )


def tokenize(text: str) -> list[str]:
    """Tokenize text for deterministic in-memory BM25."""

    return [token.lower() for token in _TOKEN_RE.findall(text or "")]


def bm25_rank(
    question: str,
    chunks: list[dict[str, Any]],
    top_k: int,
) -> list[RankedChunk]:
    """Rank chunks lexically with BM25 over ``search_text``."""

    query_tokens = tokenize(question)
    if not query_tokens or not chunks or top_k <= 0:
        return []

    doc_tokens: list[list[str]] = []
    ranked_chunks: list[dict[str, Any]] = []
    chunk_ids: list[str] = []
    case_ids: list[str] = []
    for chunk in chunks:
        tokens = tokenize(str(chunk.get("search_text") or chunk.get("text") or ""))
        if not tokens:
            continue
        doc_tokens.append(tokens)
        ranked_chunks.append(chunk)
        chunk_ids.append(str(chunk.get("chunk_id", "")))
        case_ids.append(str(chunk.get("case_id", "")))
    if not doc_tokens:
        return []

    doc_count = len(doc_tokens)
    avg_doc_len = sum(len(tokens) for tokens in doc_tokens) / doc_count
    doc_freq: dict[str, int] = {}
    for tokens in doc_tokens:
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    scored: list[tuple[int, float]] = []
    for index, tokens in enumerate(doc_tokens):
        score = 0.0
        term_freq: dict[str, int] = {}
        for token in tokens:
            term_freq[token] = term_freq.get(token, 0) + 1
        for query_token in query_tokens:
            frequency = term_freq.get(query_token)
            if frequency is None:
                continue
            doc_frequency = doc_freq.get(query_token, 0)
            idf = math.log(
                1.0 + (doc_count - doc_frequency + 0.5) / (doc_frequency + 0.5)
            )
            numerator = frequency * (_BM25_K1 + 1.0)
            denominator = frequency + _BM25_K1 * (
                1.0 - _BM25_B + _BM25_B * (len(tokens) / avg_doc_len)
            )
            score += idf * (numerator / denominator)
        scored.append((index, score))

    scored.sort(key=lambda item: (-item[1], chunk_ids[item[0]], case_ids[item[0]]))
    return [
        RankedChunk(
            chunk_id=chunk_ids[index],
            case_id=case_ids[index],
            chunk=ranked_chunks[index],
            rank=rank,
            score=score,
        )
        for rank, (index, score) in enumerate(scored[:top_k], start=1)
    ]


def vector_rank(
    chunks: list[dict[str, Any]],
    query_embedding: list[float],
    top_k: int,
) -> list[RankedChunk]:
    """Rank chunks by cosine similarity against stored 1024-d vectors."""

    scored: list[tuple[dict[str, Any], float]] = []
    for chunk in chunks:
        embedding = chunk.get("embedding")
        if (
            not isinstance(embedding, Sequence)
            or isinstance(embedding, (str, bytes))
            or not embedding
        ):
            continue
        try:
            vector = [float(value) for value in embedding]
        except (TypeError, ValueError):
            continue
        if (
            len(vector) != len(query_embedding)
            or any(not math.isfinite(value) for value in vector)
        ):
            continue
        scored.append((chunk, _cosine_similarity(vector, query_embedding)))

    scored.sort(
        key=lambda item: (
            -item[1],
            str(item[0].get("case_id", "")),
            str(item[0].get("chunk_id", "")),
        )
    )
    return [
        RankedChunk(
            chunk_id=str(chunk.get("chunk_id", "")),
            case_id=str(chunk.get("case_id", "")),
            chunk=chunk,
            rank=rank,
            score=score,
        )
        for rank, (chunk, score) in enumerate(scored[:top_k], start=1)
    ]


def merge_rrf(
    lexical: list[RankedChunk],
    vector: list[RankedChunk],
    *,
    rrf_k: int,
) -> list[RankedChunk]:
    """Merge lexical and vector candidates with reciprocal-rank fusion."""

    by_chunk: dict[str, RankedChunk] = {}
    for candidates in (lexical, vector):
        for candidate in candidates:
            score = 1.0 / (float(rrf_k) + float(candidate.rank))
            existing = by_chunk.get(candidate.chunk_id)
            if existing is None:
                candidate.fusion_score = score
                by_chunk[candidate.chunk_id] = candidate
            else:
                existing.fusion_score += score
    return sorted(
        by_chunk.values(),
        key=lambda item: (-item.fusion_score, item.case_id, item.chunk_id),
    )


def retrieve_case_chunks_for_question(
    *,
    case_id: str,
    question: str,
    config: Config,
    case_store: Any,
    chunk_source: CaseChunkSource | None = None,
    embedding_gateway: Any | None = None,
    search_adapter: Any | None = None,
) -> list[dict[str, Any]]:
    """Retrieve ranked chunks using native Azure OpenAI query embeddings."""

    normalized_question = str(question or "").strip()
    if not normalized_question:
        raise ValueError("question is required")
    metadata = case_store.get_case(config.CASE_INDEX_CONTAINER, str(case_id).strip())
    if not metadata:
        raise LookupError("case not found")
    if str(metadata.get("retrieval_status", "")).lower() != "ready":
        return []
    if application_managed_search_enabled(config, case=True):
        index_name = str(
            config_value(
                config,
                "CASE_QA_AZURE_SEARCH_INDEX",
                config_value(config, "CASE_AZURE_SEARCH_INDEX", ""),
            )
            or ""
        ).strip()
        run_id = str(
            metadata.get("retrieval_run_id")
            or metadata.get("active_run_id")
            or metadata.get("run_id")
            or metadata.get("latest_run_id")
            or ""
        ).strip()
        source = chunk_source
        if source is None or isinstance(source, BlobCaseChunkSource):
            source = AzureSearchCaseChunkSource(
                index_name=index_name,
                tenant_id=tenant_id_for(config, required=True),
                adapter=search_adapter,
                run_id=run_id,
            )
        query_embedding = embed_texts(
            [normalized_question],
            gateway=embedding_gateway,
            deployment=getattr(config, "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "") or None,
        )[0]
        if not hasattr(source, "retrieve"):
            raise TypeError("Azure Search case source must implement retrieve")
        return _trim_chunks(
            [
                RankedChunk(
                    chunk_id=str(chunk.get("chunk_id", "")),
                    case_id=str(chunk.get("case_id", case_id)),
                    chunk=chunk,
                    rank=index + 1,
                    score=float(chunk.get("@search.score", chunk.get("score", 0.0)) or 0.0),
                )
                for index, chunk in enumerate(
                    source.retrieve(
                        case_id=str(case_id).strip(),
                        question=normalized_question,
                        query_embedding=query_embedding,
                        top_k=int(getattr(config, "CASE_QA_VECTOR_TOP_K", 30)),
                    )
                )
            ],
            config,
        )

    chunks = load_all_case_chunks(
        case_id=case_id,
        config=config,
        case_store=case_store,
        chunk_source=chunk_source,
        case_metadata=metadata,
    )
    if not chunks:
        return []

    query_embedding = embed_texts(
        [normalized_question],
        gateway=embedding_gateway,
        deployment=config.AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT or None,
    )[0]
    lexical = bm25_rank(normalized_question, chunks, config.CASE_QA_LEXICAL_TOP_K)
    vector = vector_rank(chunks, query_embedding, config.CASE_QA_VECTOR_TOP_K)
    merged = merge_rrf(lexical, vector, rrf_k=config.CASE_QA_RRF_K)
    return _trim_chunks(merged, config)


def trim_chunks_list_order(
    chunks: list[dict[str, Any]],
    config: Config,
) -> list[dict[str, Any]]:
    """Trim chunks in storage order for deprecated list-order retrieval."""

    ranked = [
        RankedChunk(
            chunk_id=str(chunk.get("chunk_id", "")),
            case_id=str(chunk.get("case_id", "")),
            chunk=chunk,
            rank=index + 1,
        )
        for index, chunk in enumerate(chunks)
    ]
    return _trim_chunks(ranked, config)


def _trim_chunks(ranked: list[RankedChunk], config: Config) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    used_chars = 0
    for item in ranked:
        if len(kept) >= config.CASE_QA_MAX_TOTAL_CHUNKS:
            break
        trimmed = dict(item.chunk)
        text = str(trimmed.get("search_text") or trimmed.get("text") or "")[
            :_MAX_PROMPT_SOURCE_CHARS
        ]
        if not text:
            continue
        if used_chars + len(text) > config.CASE_QA_CONTEXT_BUDGET_CHARS:
            break
        trimmed["text"] = text
        trimmed["search_text"] = text
        kept.append(trimmed)
        used_chars += len(text)
    return kept


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


__all__ = [
    "BlobCaseChunkSource",
    "AzureSearchCaseChunkSource",
    "CaseChunkSource",
    "RankedChunk",
    "bm25_rank",
    "load_all_case_chunks",
    "merge_rrf",
    "retrieve_case_chunks_for_question",
    "tokenize",
    "trim_chunks_list_order",
    "vector_rank",
]
