"""Deterministic portal chat context-usage behavior."""

from azure_notable_pipeline.chat_context_usage import (
    build_context_usage,
    estimate_tokens_from_chars,
    estimate_tokens_from_text,
    merge_gateway_usage,
)
from azure_notable_pipeline.config import Config
from azure_notable_pipeline.portal_chat import ChatTurn, _context_usage_for_request


def test_token_estimates_are_deterministic() -> None:
    assert estimate_tokens_from_chars(0) == 0
    assert estimate_tokens_from_chars(1) == 1
    tokens, method = estimate_tokens_from_text("summarize this case")
    assert tokens > 0
    assert method == "chars_per_token"


def test_context_usage_keeps_evidence_lanes_separate() -> None:
    usage = build_context_usage(
        Config(CASE_QA_MODEL_CONTEXT_TOKENS=1_000),
        kind="case_grounded",
        question="What happened?",
        system_prompt_chars=500,
        sources=[
            {"source_lane": "current_case", "section": "summary", "text": "case fact"},
            {
                "source_lane": "knowledge_base",
                "section": "knowledge_base.sop",
                "text": "advisory procedure",
            },
        ],
        conversation_history=[ChatTurn(role="user", content="Earlier question")],
    )
    segment_ids = {segment["id"] for segment in usage["segments"]}
    assert {"system_prompt", "current_case", "knowledge_base", "conversation"} <= segment_ids
    assert usage["current_question_chars"] > 0
    assert usage["utilization_pct"] <= 100


def test_gateway_usage_overrides_estimated_prompt_count() -> None:
    merged = merge_gateway_usage(
        {"prompt_tokens": 100, "context_limit_tokens": 1_000, "utilization_pct": 10},
        prompt_tokens=250,
        completion_tokens=50,
    )
    assert merged["prompt_tokens"] == 250
    assert merged["gateway_completion_tokens"] == 50
    assert merged["utilization_pct"] == 25


def test_general_context_usage_has_no_case_lane() -> None:
    usage = _context_usage_for_request(
        Config(CASE_QA_MODEL_CONTEXT_TOKENS=128_000),
        kind="general_knowledge",
        question="Explain TLS 1.3",
        sources=None,
        conversation_history=None,
    )
    assert usage["kind"] == "general_knowledge"
    assert "Case context" not in [segment["label"] for segment in usage["segments"]]
