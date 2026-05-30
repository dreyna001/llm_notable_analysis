"""Bedrock Knowledge Base retrieval helpers for advisory SOC context."""
# pylint: disable=broad-exception-caught

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .aws_clients import bedrock_agent_runtime_client
from .config import Config


@dataclass(frozen=True)
class RetrievalResult:
    """Bounded retrieval output for prompt assembly and metadata."""

    status: str
    context: str = ""
    snippet_count: int = 0
    message: str = ""


def _source_label(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    for key in ("source_file", "source", "uri", "title"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    location = result.get("location")
    if isinstance(location, dict):
        return str(location.get("type") or "bedrock_kb").strip()
    return "bedrock_kb"


def _content_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def render_soc_context(results: list[dict[str, Any]], *, budget_chars: int) -> str:
    """Render retrieved snippets as advisory context with source labels."""

    rendered: list[str] = []
    remaining = max(budget_chars, 0)
    for index, result in enumerate(results, 1):
        text = _content_text(result)
        if not text or remaining <= 0:
            continue
        source = _source_label(result)
        prefix = f"[{index}] Source: {source}\n"
        available = max(remaining - len(prefix), 0)
        snippet = text[:available].strip()
        if not snippet:
            continue
        block = f"{prefix}{snippet}"
        rendered.append(block)
        remaining -= len(block) + 2
    return "\n\n".join(rendered)


def retrieve_soc_context(
    alert_text: str,
    config: Config,
    *,
    client: Any | None = None,
) -> RetrievalResult:
    """Retrieve advisory SOC context from a Bedrock Knowledge Base."""

    if not config.RAG_ENABLED:
        return RetrievalResult(status="skipped", message="RAG disabled")
    if not config.RAG_BEDROCK_KB_ID.strip():
        message = "RAG_BEDROCK_KB_ID is required when RAG is enabled"
        if config.RAG_FAILURE_MODE == "fail_closed":
            raise ValueError(message)
        return RetrievalResult(status="failed", message=message)

    kb_client = client or bedrock_agent_runtime_client()
    try:
        response = kb_client.retrieve(
            knowledgeBaseId=config.RAG_BEDROCK_KB_ID,
            retrievalQuery={"text": alert_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": config.RAG_MAX_SNIPPETS,
                }
            },
        )
    except Exception as exc:
        message = f"Bedrock Knowledge Base retrieval failed: {exc}"
        if config.RAG_FAILURE_MODE == "fail_closed":
            raise RuntimeError(message) from exc
        return RetrievalResult(status="failed", message=message)

    raw_results = response.get("retrievalResults", [])
    results = [item for item in raw_results if isinstance(item, dict)]
    context = render_soc_context(
        results[: config.RAG_MAX_SNIPPETS],
        budget_chars=config.RAG_CONTEXT_BUDGET_CHARS,
    )
    if not context:
        return RetrievalResult(status="no_match", snippet_count=0, message="No RAG snippets returned")
    return RetrievalResult(
        status="success",
        context=context,
        snippet_count=len(results[: config.RAG_MAX_SNIPPETS]),
    )
