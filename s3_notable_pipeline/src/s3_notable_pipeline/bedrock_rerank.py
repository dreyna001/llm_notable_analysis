"""Bedrock rerank for application-managed OpenSearch RAG retrieval."""

from __future__ import annotations

import json
import logging
from typing import Any

from .opensearch_retrieval import RetrievedDocument

logger = logging.getLogger(__name__)


def rerank_documents(
    query: str,
    documents: list[RetrievedDocument],
    config: Any,
    bedrock_client: Any,
) -> list[RetrievedDocument]:
    """Rerank retrieved documents with Bedrock; fail-soft and preserve order on error."""

    if not bool(getattr(config, "RAG_RERANK_ENABLED", False)):
        return documents
    if len(documents) <= 1:
        return documents

    primary_model = str(getattr(config, "RAG_RERANK_MODEL", "")).strip()
    fallback_model = str(getattr(config, "RAG_RERANK_MODEL_FALLBACK", "")).strip()
    models = [model for model in (primary_model, fallback_model) if model]
    if not models:
        logger.warning("rerank_status=skipped reason=missing_model_configuration")
        return documents

    query_text = str(query or "").strip()
    if not query_text:
        logger.warning("rerank_status=skipped reason=empty_query")
        return documents

    doc_texts = [document.text for document in documents]
    top_n = len(documents)

    for model_id in models:
        try:
            response = bedrock_client.invoke_model(
                modelId=model_id,
                body=json.dumps(
                    {
                        "query": query_text,
                        "documents": doc_texts,
                        "top_n": top_n,
                        "api_version": 2,
                    }
                ),
                accept="application/json",
                contentType="application/json",
            )
            body = response.get("body")
            payload = body.read() if hasattr(body, "read") else body
            parsed = json.loads(
                payload.decode("utf-8") if isinstance(payload, bytes) else payload
            )
            reranked = _apply_rerank_results(documents, parsed.get("results", []))
            if not reranked:
                raise ValueError("Bedrock rerank returned no usable results")
            logger.info(
                "rerank_status=success model=%s document_count=%d",
                model_id,
                len(reranked),
            )
            return _with_rerank_metadata(
                reranked,
                rerank_status="success",
                rerank_model=model_id,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Bedrock rerank failed for model %s; rerank_status=failed error=%s",
                model_id,
                exc,
            )

    logger.warning("rerank_status=failed; returning original retrieval order")
    return _with_rerank_metadata(documents, rerank_status="failed")


def _apply_rerank_results(
    documents: list[RetrievedDocument],
    results: list[Any],
) -> list[RetrievedDocument]:
    ordered: list[RetrievedDocument] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if index is None:
            continue
        index_value = int(index)
        if index_value < 0 or index_value >= len(documents):
            continue
        score = item.get("relevance_score", item.get("relevanceScore"))
        score_value = float(score) if score is not None else documents[index_value].score
        source = documents[index_value]
        metadata = dict(source.metadata or {})
        metadata["rerank_score"] = score_value
        ordered.append(
            RetrievedDocument(
                document_id=source.document_id,
                text=source.text,
                score=score_value,
                tenant_id=source.tenant_id,
                corpus_id=source.corpus_id,
                case_id=source.case_id,
                chunk_id=source.chunk_id,
                source_bucket=source.source_bucket,
                source_key=source.source_key,
                source_version_id=source.source_version_id,
                source_etag=source.source_etag,
                source_file=source.source_file,
                section=source.section,
                metadata=metadata,
            )
        )
    return ordered


def _with_rerank_metadata(
    documents: list[RetrievedDocument],
    *,
    rerank_status: str,
    rerank_model: str = "",
) -> list[RetrievedDocument]:
    marked: list[RetrievedDocument] = []
    for document in documents:
        metadata = dict(document.metadata or {})
        metadata["rerank_status"] = rerank_status
        if rerank_model:
            metadata["rerank_model"] = rerank_model
        marked.append(
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
    return marked
