"""Elasticsearch-dedicated Bedrock Knowledge Base grounding helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .aws_clients import bedrock_agent_runtime_client, bedrock_runtime_client
from .config import Config

ELASTICSEARCH_GROUNDING_CONTEXT_HEADER = "ELASTICSEARCH_GROUNDING_CONTEXT"
ELASTICSEARCH_GROUNDING_FAILURE_MODES = {"suppress", "fallback_to_ungrounded"}


@dataclass(frozen=True)
class ElasticsearchGroundingResult:
    """Rendered Elastic KB context plus status metadata."""

    status: str
    context: str = ""
    snippet_count: int = 0
    message: str = ""
    provenance: tuple[dict[str, Any], ...] = ()


def elasticsearch_grounding_failure_mode(config: Config) -> str:
    """Return a supported failure mode for Elasticsearch query grounding."""

    mode = str(config.ELASTICSEARCH_GROUNDING_FAILURE_MODE or "suppress").strip().lower()
    if mode not in ELASTICSEARCH_GROUNDING_FAILURE_MODES:
        return "suppress"
    return mode


def build_elasticsearch_grounding_query(
    *,
    alert_text: str,
    hypotheses: list[dict[str, Any]],
) -> str:
    """Build retrieval query text for the Elasticsearch-focused KB."""

    normalized_hypotheses = []
    for item in hypotheses:
        if not isinstance(item, dict):
            continue
        normalized_hypotheses.append(
            {
                "hypothesis_type": str(item.get("hypothesis_type", "")).strip(),
                "hypothesis": str(item.get("hypothesis", "")).strip(),
                "best_pivots": item.get("best_pivots", []),
            }
        )
    return "\n\n".join(
        part
        for part in (
            "SECURITY ALERT INPUT:",
            alert_text,
            "COMPETING HYPOTHESES:",
            json.dumps(normalized_hypotheses, ensure_ascii=True),
        )
        if str(part).strip()
    )


def _source_and_section(result: dict[str, Any]) -> tuple[str, str]:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    source = (
        metadata.get("source_file")
        or metadata.get("source")
        or metadata.get("uri")
        or metadata.get("title")
        or "bedrock_kb"
    )
    section = metadata.get("section_path") or metadata.get("section") or "root"
    return str(source).strip() or "bedrock_kb", str(section).strip() or "root"


def _content_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"].strip()
    return ""


def render_elasticsearch_grounding_context(
    results: list[dict[str, Any]],
    *,
    budget_chars: int,
) -> str:
    """Render KB snippets in the on-prem-compatible provenance line format."""

    rendered = [ELASTICSEARCH_GROUNDING_CONTEXT_HEADER]
    remaining = max(budget_chars - len(ELASTICSEARCH_GROUNDING_CONTEXT_HEADER) - 1, 0)
    for index, result in enumerate(results, 1):
        text = _content_text(result)
        if not text or remaining <= 0:
            continue
        source, section = _source_and_section(result)
        prefix = f"[{index}] [{source} :: {section}] "
        available = max(remaining - len(prefix), 0)
        snippet = text[:available].strip()
        if not snippet:
            continue
        line = f"{prefix}{snippet}"
        rendered.append(line)
        remaining -= len(line) + 1
    if len(rendered) == 1:
        return ""
    return "\n".join(rendered)


def retrieve_elasticsearch_grounding(
    *,
    alert_text: str,
    hypotheses: list[dict[str, Any]],
    config: Config,
    client: Any | None = None,
    opensearch_client: Any | None = None,
    bedrock_client: Any | None = None,
) -> ElasticsearchGroundingResult:
    """Retrieve Elasticsearch query grounding from a Bedrock Knowledge Base."""

    if not config.ELASTICSEARCH_GROUNDING_ENABLED:
        return ElasticsearchGroundingResult(status="skipped", message="Elasticsearch grounding disabled")
    from .case_embed import embed_text
    from .opensearch_retrieval import (
        adapter_for,
        config_value,
        opensearch_enabled,
        render_documents,
        retrieve_documents,
        tenant_id_for,
    )

    query_text = build_elasticsearch_grounding_query(alert_text=alert_text, hypotheses=hypotheses)
    if opensearch_enabled(config):
        try:
            documents = retrieve_documents(
                query_text=query_text,
                query_embedding=embed_text(
                    query_text,
                    config,
                    bedrock_client or bedrock_runtime_client(),
                ),
                index=str(
                    config_value(
                        config,
                        "OPENSEARCH_ELASTICSEARCH_INDEX",
                        config_value(config, "OPENSEARCH_ELASTIC_INDEX", "notable-elastic-dictionary"),
                    )
                ),
                tenant_id=tenant_id_for(config, required=True),
                corpus_id="elastic",
                top_k=config.ELASTICSEARCH_GROUNDING_MAX_SNIPPETS,
                adapter=adapter_for(
                    config,
                    opensearch_client or (client if hasattr(client, "search") else None),
                ),
                config=config,
            )
            context = render_documents(
                documents,
                budget_chars=config.ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS,
                header=ELASTICSEARCH_GROUNDING_CONTEXT_HEADER,
            )
            if not context:
                return ElasticsearchGroundingResult(
                    status="no_match",
                    message="No Elasticsearch grounding snippets returned",
                )
            return ElasticsearchGroundingResult(
                status="success",
                context=context,
                snippet_count=len(documents),
                provenance=tuple(
                    dict(document.metadata or {}).get("provenance", {}) for document in documents
                ),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return ElasticsearchGroundingResult(
                status="failed",
                message=f"OpenSearch Elasticsearch grounding failed: {exc}",
            )
    if not config.ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID.strip():
        return ElasticsearchGroundingResult(
            status="failed",
            message="ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID is required when grounding is enabled",
        )

    kb_client = client or bedrock_agent_runtime_client()
    try:
        response = kb_client.retrieve(
            knowledgeBaseId=config.ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID,
            retrievalQuery={"text": query_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": config.ELASTICSEARCH_GROUNDING_MAX_SNIPPETS,
                }
            },
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return ElasticsearchGroundingResult(
            status="failed",
            message=f"Elasticsearch Bedrock Knowledge Base retrieval failed: {exc}",
        )

    raw_results = response.get("retrievalResults", [])
    results = [item for item in raw_results if isinstance(item, dict)]
    context = render_elasticsearch_grounding_context(
        results[: config.ELASTICSEARCH_GROUNDING_MAX_SNIPPETS],
        budget_chars=config.ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS,
    )
    if not context:
        return ElasticsearchGroundingResult(
            status="no_match",
            snippet_count=0,
            message="No Elasticsearch grounding snippets returned",
        )
    return ElasticsearchGroundingResult(
        status="success",
        context=context,
        snippet_count=len(results[: config.ELASTICSEARCH_GROUNDING_MAX_SNIPPETS]),
    )
