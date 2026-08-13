"""Hybrid BM25 + vector case chunk retrieval for AWS portal Q&A."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .case_embed import embed_text
from .case_index import get_case_metadata
from .config import Config

_MAX_PROMPT_SOURCE_CHARS = 2400
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_BM25_K1 = 1.5
_BM25_B = 0.75


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
    dynamodb_client: Any,
    s3_client: Any,
) -> list[dict[str, Any]]:
    """Load all S3 chunk JSON for a case when retrieval_status is ready."""

    metadata = get_case_metadata(
        config=config,
        dynamodb_client=dynamodb_client,
        case_id=case_id,
    )
    if not metadata:
        raise LookupError("case not found")
    if str(metadata.get("retrieval_status", "")).lower() != "ready":
        return []

    prefix = f"{config.CASE_ARCHIVE_CHUNKS_PREFIX}/{case_id}/"
    chunks: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": config.CASE_ARCHIVE_BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = s3_client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = item.get("Key")
            if not key:
                continue
            chunk = _load_chunk(config.CASE_ARCHIVE_BUCKET, str(key), s3_client)
            if str(chunk.get("case_id", "")) != case_id:
                continue
            chunks.append(chunk)
        if not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")
    return chunks


def tokenize(text: str) -> list[str]:
    """Tokenize text for in-memory BM25 using a simple word regex."""

    return [token.lower() for token in _TOKEN_RE.findall(text or "")]


def bm25_rank(
    question: str,
    chunks: list[dict[str, Any]],
    top_k: int,
) -> list[RankedChunk]:
    """Rank chunks lexically with BM25 over search_text."""

    query_tokens = tokenize(question)
    if not query_tokens or not chunks:
        return []

    doc_tokens: list[list[str]] = []
    ranked_chunks: list[dict[str, Any]] = []
    chunk_ids: list[str] = []
    case_ids: list[str] = []
    for chunk in chunks:
        text = str(chunk.get("search_text") or chunk.get("text") or "")
        tokens = tokenize(text)
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
        doc_len = len(tokens)
        term_freq: dict[str, int] = {}
        for token in tokens:
            term_freq[token] = term_freq.get(token, 0) + 1
        for query_token in query_tokens:
            frequency = term_freq.get(query_token)
            if frequency is None:
                continue
            doc_frequency = doc_freq.get(query_token, 0)
            idf = math.log(1.0 + (doc_count - doc_frequency + 0.5) / (doc_frequency + 0.5))
            numerator = frequency * (_BM25_K1 + 1.0)
            denominator = frequency + _BM25_K1 * (
                1.0 - _BM25_B + _BM25_B * (doc_len / avg_doc_len)
            )
            score += idf * (numerator / denominator)
        scored.append((index, score))

    scored.sort(key=lambda item: (-item[1], chunk_ids[item[0]], case_ids[item[0]]))
    results: list[RankedChunk] = []
    for rank, (index, score) in enumerate(scored[:top_k], start=1):
        chunk = ranked_chunks[index]
        results.append(
            RankedChunk(
                chunk_id=chunk_ids[index],
                case_id=case_ids[index],
                chunk=chunk,
                rank=rank,
                score=score,
            )
        )
    return results


def vector_rank(
    chunks: list[dict[str, Any]],
    query_embedding: list[float],
    top_k: int,
) -> list[RankedChunk]:
    """Rank chunks by cosine similarity against stored embeddings."""

    scored: list[tuple[dict[str, Any], float]] = []
    for chunk in chunks:
        embedding = chunk.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            continue
        try:
            vector = [float(value) for value in embedding]
        except (TypeError, ValueError):
            continue
        if len(vector) != len(query_embedding):
            continue
        score = _cosine_similarity(vector, query_embedding)
        scored.append((chunk, score))

    scored.sort(
        key=lambda item: (
            -item[1],
            str(item[0].get("case_id", "")),
            str(item[0].get("chunk_id", "")),
        )
    )
    results: list[RankedChunk] = []
    for rank, (chunk, score) in enumerate(scored[:top_k], start=1):
        results.append(
            RankedChunk(
                chunk_id=str(chunk.get("chunk_id", "")),
                case_id=str(chunk.get("case_id", "")),
                chunk=chunk,
                rank=rank,
                score=score,
            )
        )
    return results


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
    dynamodb_client: Any,
    s3_client: Any,
    bedrock_client: Any,
    opensearch_client: Any | None = None,
) -> list[dict[str, Any]]:
    """Retrieve ranked case chunks for one analyst question."""

    from .opensearch_retrieval import (
        adapter_for,
        config_value,
        opensearch_enabled,
        retrieve_documents,
    )

    if opensearch_enabled(config, case=True):
        metadata = get_case_metadata(
            config=config,
            dynamodb_client=dynamodb_client,
            case_id=case_id,
        )
        if not metadata or str(metadata.get("retrieval_status", "")).lower() != "ready":
            return []
        tenant_id = str(
            config_value(config, "RAG_TENANT_ID", "") or metadata.get("tenant_id", "")
        ).strip()
        if not tenant_id:
            return []
        query_embedding = embed_text(question, config, bedrock_client)
        documents = retrieve_documents(
            query_text=question,
            query_embedding=query_embedding,
            index=str(config_value(config, "OPENSEARCH_CASE_INDEX", "case-chunks")),
            tenant_id=tenant_id,
            corpus_id="case_chunks",
            case_id=case_id,
            top_k=max(config.CASE_QA_LEXICAL_TOP_K, config.CASE_QA_VECTOR_TOP_K),
            adapter=adapter_for(config, opensearch_client),
            config=config,
            bedrock_client=bedrock_client,
        )
        chunks = []
        for document in documents:
            chunk = dict(document.metadata or {})
            chunk.update(
                {
                    "chunk_id": document.chunk_id or document.document_id,
                    "case_id": document.case_id or case_id,
                    "text": document.text,
                    "search_text": document.text,
                    "score": document.score,
                    "retrieval_provenance": {
                        "tenant_id": document.tenant_id,
                        "corpus_id": document.corpus_id,
                        "case_id": document.case_id or case_id,
                        "chunk_id": document.chunk_id or document.document_id,
                        "source_bucket": document.source_bucket,
                        "source_key": document.source_key,
                        "source_version_id": document.source_version_id,
                        "source_etag": document.source_etag,
                        "source_file": document.source_file,
                        "embedding_model": str(
                            (document.metadata or {}).get("provenance", {}).get(
                                "embedding_model", ""
                            )
                        ),
                    },
                }
            )
            chunks.append(chunk)
        return _trim_chunks(
            [
                RankedChunk(
                    chunk_id=str(chunk.get("chunk_id", "")),
                    case_id=str(chunk.get("case_id", case_id)),
                    chunk=chunk,
                    rank=index,
                    score=float(chunk.get("score", 0.0)),
                )
                for index, chunk in enumerate(chunks, start=1)
            ],
            config,
        )

    chunks = load_all_case_chunks(
        case_id=case_id,
        config=config,
        dynamodb_client=dynamodb_client,
        s3_client=s3_client,
    )
    if not chunks:
        return []

    query_embedding = embed_text(question, config, bedrock_client)
    lexical = bm25_rank(question, chunks, config.CASE_QA_LEXICAL_TOP_K)
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
        text = str(trimmed.get("search_text") or trimmed.get("text") or "")
        text = text[:_MAX_PROMPT_SOURCE_CHARS]
        if not text:
            continue
        next_chars = used_chars + len(text)
        if next_chars > config.CASE_QA_CONTEXT_BUDGET_CHARS:
            break
        trimmed["text"] = text
        trimmed["search_text"] = text
        kept.append(trimmed)
        used_chars = next_chars
    return kept


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _load_chunk(bucket: str, key: str, s3_client: Any) -> dict[str, Any]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    chunk = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(chunk, dict):
        raise ValueError("case chunk must be a JSON object")
    return chunk
