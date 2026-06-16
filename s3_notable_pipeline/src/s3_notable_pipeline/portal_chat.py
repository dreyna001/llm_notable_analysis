"""Bedrock answer synthesis for AWS portal Case Q&A."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import Config


@dataclass(frozen=True)
class PortalAnswer:
    """Validated portal chat answer."""

    answer: str
    answer_status: str
    citations: list[str]


def synthesize_case_answer(
    *,
    question: str,
    sources: list[dict[str, Any]],
    config: Config,
    bedrock_client: Any,
) -> PortalAnswer:
    """Ask Bedrock for a cited answer grounded only in retrieved case chunks."""

    if not sources:
        return PortalAnswer(
            answer="The case archive did not contain enough grounded context to answer.",
            answer_status="insufficient_context",
            citations=[],
        )
    prompt = _build_prompt(question=question, sources=sources)
    response = bedrock_client.invoke_model(
        modelId=config.PORTAL_CHAT_BEDROCK_MODEL_ID or config.BEDROCK_MODEL_ID,
        body=json.dumps(
            {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": config.CASE_QA_MAX_ANSWER_TOKENS,
            }
        ),
        accept="application/json",
        contentType="application/json",
    )
    allowed_citations = {
        str(source.get("chunk_id", "")).strip()
        for source in sources
        if str(source.get("chunk_id", "")).strip()
    }
    return validate_answer_payload(_read_bedrock_json(response), allowed_citations=allowed_citations)


def validate_answer_payload(
    payload: Any,
    *,
    allowed_citations: set[str] | None = None,
) -> PortalAnswer:
    """Validate answer JSON and fail soft when citations are missing."""

    if not isinstance(payload, dict):
        return _insufficient()
    if "content" in payload and isinstance(payload["content"], list):
        text = "".join(
            str(item.get("text", ""))
            for item in payload["content"]
            if isinstance(item, dict)
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return _insufficient()
    answer = str(payload.get("answer", "")).strip()
    status = str(payload.get("answer_status", "")).strip() or "insufficient_context"
    raw_citations = payload.get("citations", [])
    citations = (
        [str(item).strip() for item in raw_citations if str(item).strip()]
        if isinstance(raw_citations, list)
        else []
    )
    if status == "answered" and not citations:
        return _insufficient()
    if allowed_citations is not None and any(item not in allowed_citations for item in citations):
        return _insufficient()
    if status not in {"answered", "insufficient_context"}:
        return _insufficient()
    return PortalAnswer(answer=answer or _insufficient().answer, answer_status=status, citations=citations)


def _build_prompt(question: str, sources: list[dict[str, Any]]) -> str:
    rendered_sources = []
    for index, source in enumerate(sources, 1):
        rendered_sources.append(
            f"[{index}] chunk_id={source.get('chunk_id')}\n{source.get('search_text') or source.get('text')}"
        )
    return (
        "Answer the analyst question using only the provided selected-case sources. "
        "Do not mutate case fields, call tools, run queries, or claim external actions. "
        "Return strict JSON with answer, answer_status, and citations. "
        "Use answer_status=insufficient_context when the sources do not answer.\n\n"
        f"QUESTION:\n{question}\n\nSOURCES:\n" + "\n\n".join(rendered_sources)
    )


def _read_bedrock_json(response: dict[str, Any]) -> Any:
    body = response.get("body")
    payload = body.read() if hasattr(body, "read") else body
    return json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)


def _insufficient() -> PortalAnswer:
    return PortalAnswer(
        answer="The case archive did not contain enough grounded context to answer.",
        answer_status="insufficient_context",
        citations=[],
    )
