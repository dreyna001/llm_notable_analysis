"""Bedrock rerank helpers for OpenSearch hybrid retrieval."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Sequence

from .aws_clients import bedrock_agent_runtime_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RerankOutcome:
    """Bounded rerank result for retrieval callers."""

    documents: list[Any]
    status: str
    model_id: str = ""
    message: str = ""


def rerank_model_arn(model_id: str, *, region: str | None = None) -> str:
    """Build a foundation-model ARN for Bedrock rerank calls."""

    resolved_region = (
        region
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    ).strip()
    partition = (os.getenv("AWS_PARTITION") or "aws").strip() or "aws"
    normalized_model_id = model_id.strip()
    if not normalized_model_id:
        raise ValueError("model_id is required for rerank")
    return f"arn:{partition}:bedrock:{resolved_region}::foundation-model/{normalized_model_id}"


def rerank_documents(
    *,
    query_text: str,
    documents: Sequence[Any],
    config: Any,
    top_k: int | None = None,
    bedrock_client: Any | None = None,
) -> RerankOutcome:
    """Rerank retrieved documents with Bedrock models; fail-soft on errors."""

    rerank_enabled = bool(getattr(config, "RAG_RERANK_ENABLED", False))
    doc_list = list(documents)
    if not rerank_enabled:
        logger.info("rerank_status=skipped reason=disabled")
        return RerankOutcome(documents=doc_list, status="skipped")
    if len(doc_list) <= 1:
        logger.info("rerank_status=skipped reason=insufficient_documents")
        return RerankOutcome(documents=doc_list, status="skipped")
    if not query_text.strip():
        logger.info("rerank_status=skipped reason=empty_query")
        return RerankOutcome(documents=doc_list, status="skipped")

    primary_model = str(getattr(config, "RAG_RERANK_MODEL", "cohere.rerank-v3-5:0")).strip()
    fallback_model = str(
        getattr(config, "RAG_RERANK_MODEL_FALLBACK", "amazon.rerank-v1:0")
    ).strip()
    model_ids = [primary_model]
    if fallback_model and fallback_model not in model_ids:
        model_ids.append(fallback_model)

    sources: list[dict[str, Any]] = []
    source_doc_indices: list[int] = []
    for index, document in enumerate(doc_list):
        text = str(getattr(document, "text", "") or "").strip()
        if not text:
            continue
        source_doc_indices.append(index)
        sources.append(
            {
                "type": "INLINE",
                "inlineDocumentSource": {
                    "type": "TEXT",
                    "textDocument": {"text": text},
                },
            }
        )
    if len(sources) <= 1:
        logger.info("rerank_status=skipped reason=insufficient_text_documents")
        return RerankOutcome(documents=doc_list, status="skipped")

    client = bedrock_client or bedrock_agent_runtime_client()
    number_of_results = min(len(sources), top_k if top_k is not None else len(sources))
    last_error: Exception | None = None
    for model_id in model_ids:
        try:
            response = client.rerank(
                queries=[{"type": "TEXT", "textQuery": {"text": query_text}}],
                sources=sources,
                rerankingConfiguration={
                    "type": "BEDROCK_RERANKING_MODEL",
                    "bedrockRerankingConfiguration": {
                        "modelConfiguration": {
                            "modelArn": rerank_model_arn(model_id),
                        },
                        "numberOfResults": number_of_results,
                    },
                },
            )
            results = response.get("results", []) if isinstance(response, dict) else []
            reranked = _apply_rerank_results(
                doc_list,
                results,
                source_doc_indices=source_doc_indices,
                model_id=model_id,
            )
            logger.info(
                "rerank_status=success model_id=%s document_count=%s",
                model_id,
                len(reranked),
            )
            return RerankOutcome(
                documents=reranked,
                status="success",
                model_id=model_id,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            last_error = exc
            logger.warning("Bedrock rerank failed for model %s: %s", model_id, exc)

    message = str(last_error) if last_error else "rerank failed"
    logger.warning("rerank_status=failed error=%s", message)
    return RerankOutcome(documents=doc_list, status="failed", message=message)


def _apply_rerank_results(
    documents: Sequence[Any],
    results: Sequence[Any],
    *,
    source_doc_indices: Sequence[int],
    model_id: str,
) -> list[Any]:
    """Reorder documents using Bedrock rerank indices and attach rerank metadata."""

    from .opensearch_retrieval import RetrievedDocument

    doc_list = list(documents)
    reranked: list[RetrievedDocument] = []
    seen: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        source_index = int(item.get("index", -1))
        if source_index < 0 or source_index >= len(source_doc_indices):
            continue
        original_index = source_doc_indices[source_index]
        if original_index in seen:
            continue
        seen.add(original_index)
        document = doc_list[original_index]
        metadata = dict(document.metadata or {})
        metadata.update(
            {
                "rerank_status": "success",
                "rerank_model_id": model_id,
                "rerank_score": float(item.get("relevanceScore", 0.0) or 0.0),
                "hybrid_score": document.score,
            }
        )
        reranked.append(
            RetrievedDocument(
                document_id=document.document_id,
                text=document.text,
                score=float(item.get("relevanceScore", 0.0) or 0.0),
                tenant_id=document.tenant_id,
                corpus_id=document.corpus_id,
                case_id=document.case_id,
                chunk_id=document.chunk_id,
                source_bucket=document.source_bucket,
                source_key=document.source_key,
                source_version_id=document.source_version_id,
                source_etag=document.source_etag,
                source_file=document.source_file,
                section=document.section,
                metadata=metadata,
            )
        )

    for index, document in enumerate(doc_list):
        if index in seen:
            continue
        metadata = dict(document.metadata or {})
        metadata["rerank_status"] = "skipped"
        reranked.append(
            RetrievedDocument(
                document_id=document.document_id,
                text=document.text,
                score=document.score,
                tenant_id=document.tenant_id,
                corpus_id=document.corpus_id,
                case_id=document.case_id,
                chunk_id=document.chunk_id,
                source_bucket=document.source_bucket,
                source_key=document.source_key,
                source_version_id=document.source_version_id,
                source_etag=document.source_etag,
                source_file=document.source_file,
                section=document.section,
                metadata=metadata,
            )
        )
    return reranked
