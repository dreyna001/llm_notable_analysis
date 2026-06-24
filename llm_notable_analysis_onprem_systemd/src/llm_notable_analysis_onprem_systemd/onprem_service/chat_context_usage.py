"""Deterministic portal chat context usage estimates for analyst UI."""

from __future__ import annotations

import json
from typing import Any, Literal, Sequence

from .config import Config

CHARS_PER_TOKEN_ESTIMATE = 4.38
EstimateMethod = Literal["chars_per_token", "tiktoken"]

ContextKind = Literal["case_grounded", "general_knowledge"]


def estimate_tokens_from_chars(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, round(char_count / CHARS_PER_TOKEN_ESTIMATE))


def _tiktoken_encoding(model_name: str | None) -> Any | None:
    try:
        import tiktoken
    except ImportError:
        return None
    model = str(model_name or "").strip()
    if model:
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            pass
    return tiktoken.get_encoding("cl100k_base")


def estimate_tokens_from_text(
    text: str,
    *,
    model_name: str | None = None,
) -> tuple[int, EstimateMethod]:
    """Estimate token count for a prompt string."""
    if not text:
        return 0, "chars_per_token"
    encoding = _tiktoken_encoding(model_name)
    if encoding is not None:
        return len(encoding.encode(text)), "tiktoken"
    return estimate_tokens_from_chars(len(text)), "chars_per_token"


def _segment(segment_id: str, label: str, char_count: int) -> dict[str, Any]:
    return {
        "id": segment_id,
        "label": label,
        "chars": char_count,
        "tokens": 0,
    }


def _allocate_segment_tokens(
    segments: list[dict[str, Any]],
    *,
    prompt_tokens: int,
) -> None:
    content_chars = sum(int(item["chars"]) for item in segments)
    if prompt_tokens <= 0 or content_chars <= 0:
        for item in segments:
            item["tokens"] = 0
        return
    allocated = 0
    for index, item in enumerate(segments):
        if index == len(segments) - 1:
            item["tokens"] = max(0, prompt_tokens - allocated)
            continue
        tokens = round(prompt_tokens * int(item["chars"]) / content_chars)
        item["tokens"] = tokens
        allocated += tokens


def _question_block_chars(question: str, *, kind: ContextKind) -> int:
    block = "QUESTION_JSON:\n" + json.dumps(question.strip(), ensure_ascii=True)
    if kind == "case_grounded":
        return len(block) + 2
    return len(block)


def _conversation_segment_chars(
    question: str,
    conversation_history: Sequence[Any] | None,
    *,
    kind: ContextKind,
) -> tuple[int, int]:
    """Return (conversation segment chars, current question block chars)."""
    history_chars = _conversation_chars(conversation_history)
    question_chars = _question_block_chars(question, kind=kind)
    return history_chars + question_chars, question_chars


def _conversation_chars(conversation_history: Sequence[Any] | None) -> int:
    if not conversation_history:
        return 0
    from .case_chat import _render_conversation_history

    return len(_render_conversation_history(conversation_history))


def _lane_block_chars(sources: Sequence[Any] | None, lane: str) -> int:
    if not sources:
        return 0
    from .case_chat import _format_context_block

    total = 0
    for source in sources:
        if str(getattr(source, "source_lane", "") or "") != lane:
            continue
        total += len(_format_context_block(source))
    return total


def build_context_usage(
    config: Config,
    *,
    kind: ContextKind,
    question: str,
    system_prompt_chars: int,
    sources: Sequence[Any] | None = None,
    conversation_history: Sequence[Any] | None = None,
    prompt_text: str | None = None,
) -> dict[str, Any]:
    """Build a bounded context usage snapshot for one synthesis request."""
    conversation_chars, current_question_chars = _conversation_segment_chars(
        question,
        conversation_history,
        kind=kind,
    )

    segments: list[dict[str, Any]] = []
    segments.append(_segment("system_prompt", "System prompt", system_prompt_chars))

    if kind == "case_grounded":
        for lane_id, label in (
            ("current_case", "Case context"),
            ("knowledge_base", "Knowledge base"),
            ("prior_case", "Prior cases"),
        ):
            lane_chars = _lane_block_chars(sources, lane_id)
            if lane_chars:
                segments.append(_segment(lane_id, label, lane_chars))

    segments.append(_segment("conversation", "Conversation", conversation_chars))

    model_name = str(getattr(config, "LLM_MODEL_NAME", "") or "").strip() or None
    if prompt_text is not None:
        prompt_chars = len(prompt_text)
        prompt_tokens, estimate_method = estimate_tokens_from_text(
            prompt_text,
            model_name=model_name,
        )
    else:
        source_count = len(sources or [])
        prompt_chars = sum(int(item["chars"]) for item in segments) + _prompt_wrapper_overhead(
            kind,
            source_count=source_count,
        )
        prompt_tokens = estimate_tokens_from_chars(prompt_chars)
        estimate_method = "chars_per_token"

    _allocate_segment_tokens(segments, prompt_tokens=prompt_tokens)

    limit_tokens = int(getattr(config, "CASE_QA_MODEL_CONTEXT_TOKENS", 128_000))
    limit_tokens = max(limit_tokens, 1)
    utilization_pct = min(100, round(prompt_tokens / limit_tokens * 100))

    return {
        "kind": kind,
        "prompt_chars": prompt_chars,
        "prompt_tokens": prompt_tokens,
        "context_limit_tokens": limit_tokens,
        "utilization_pct": utilization_pct,
        "segments": segments,
        "estimate_method": estimate_method,
        "chars_per_token_estimate": CHARS_PER_TOKEN_ESTIMATE,
        "current_question_chars": current_question_chars,
    }


def _prompt_wrapper_overhead(kind: ContextKind, *, source_count: int) -> int:
    if kind == "case_grounded":
        overhead = 0
        if source_count:
            overhead += len("RETRIEVED CONTEXT:\n\n")
            if source_count > 1:
                overhead += (source_count - 1) * 2
        overhead += len(
            "\n\nAnswer like a default helpful chatbot: start with a direct answer, "
            "keep it concise, and add structure only when it helps. Do not use default "
            "sections such as Grounded answer, Unknowns, Suggested next steps, or "
            "Draft query/example unless the analyst's question makes that structure useful."
        )
        return overhead
    return 0


def merge_gateway_usage(
    usage: dict[str, Any],
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> dict[str, Any]:
    """Attach gateway token counts when the LLM transport returns usage fields."""
    merged = dict(usage)
    if prompt_tokens is not None:
        merged["gateway_prompt_tokens"] = prompt_tokens
        merged["prompt_tokens"] = prompt_tokens
        limit_tokens = int(merged.get("context_limit_tokens", 1))
        merged["utilization_pct"] = min(
            100, round(prompt_tokens / max(limit_tokens, 1) * 100)
        )
    if completion_tokens is not None:
        merged["gateway_completion_tokens"] = completion_tokens
    return merged
