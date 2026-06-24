"""Tests for deterministic portal chat context usage estimates."""

from __future__ import annotations

import unittest

from llm_notable_analysis_onprem_systemd.onprem_service.case_chat import (
    ChatTurn,
    RetrievedSource,
    _context_usage_for_request,
)
from llm_notable_analysis_onprem_systemd.onprem_service.chat_context_usage import (
    build_context_usage,
    estimate_tokens_from_chars,
    estimate_tokens_from_text,
    merge_gateway_usage,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config


class ChatContextUsageTests(unittest.TestCase):
    def test_estimate_tokens_from_chars(self) -> None:
        self.assertEqual(estimate_tokens_from_chars(0), 0)
        self.assertEqual(estimate_tokens_from_chars(1), 1)
        self.assertEqual(estimate_tokens_from_chars(9), 2)

    def test_build_context_usage_includes_segments(self) -> None:
        config = Config(CASE_QA_MODEL_CONTEXT_TOKENS=1000)
        usage = build_context_usage(
            config,
            kind="case_grounded",
            question="What happened?",
            system_prompt_chars=500,
            sources=[
                RetrievedSource(
                    source_lane="current_case",
                    section="summary",
                    text="Case summary text",
                )
            ],
            conversation_history=[
                ChatTurn(role="user", content="Earlier question"),
            ],
        )
        self.assertEqual(usage["kind"], "case_grounded")
        self.assertGreater(usage["prompt_tokens"], 0)
        segment_ids = {segment["id"] for segment in usage["segments"]}
        self.assertIn("system_prompt", segment_ids)
        self.assertIn("current_case", segment_ids)
        self.assertIn("conversation", segment_ids)
        self.assertNotIn("question", segment_ids)
        self.assertGreater(usage["current_question_chars"], 0)
        self.assertLessEqual(usage["utilization_pct"], 100)

    def test_merge_gateway_usage_overrides_estimate(self) -> None:
        usage = {
            "prompt_tokens": 100,
            "context_limit_tokens": 1000,
            "utilization_pct": 10,
        }
        merged = merge_gateway_usage(usage, prompt_tokens=250, completion_tokens=50)
        self.assertEqual(merged["prompt_tokens"], 250)
        self.assertEqual(merged["gateway_completion_tokens"], 50)
        self.assertEqual(merged["utilization_pct"], 25)

    def test_estimate_tokens_from_text_uses_tiktoken_when_available(self) -> None:
        try:
            import tiktoken  # noqa: F401
        except ImportError:
            self.skipTest("tiktoken not installed")
        tokens, method = estimate_tokens_from_text(
            "summarize this case",
            model_name="gpt-4.1-mini",
        )
        self.assertEqual(method, "tiktoken")
        self.assertGreater(tokens, 0)

    def test_build_context_usage_from_prompt_text(self) -> None:
        config = Config(
            CASE_QA_MODEL_CONTEXT_TOKENS=1000,
            LLM_MODEL_NAME="gpt-4.1-mini",
        )
        prompt = "SYSTEM INSTRUCTIONS:\n" + ("x" * 400) + "\nQUESTION_JSON:\n\"hi\""
        usage = build_context_usage(
            config,
            kind="general_knowledge",
            question="hi",
            system_prompt_chars=100,
            prompt_text=prompt,
        )
        self.assertEqual(usage["prompt_chars"], len(prompt))
        self.assertEqual(
            sum(segment["tokens"] for segment in usage["segments"]),
            usage["prompt_tokens"],
        )

    def test_context_usage_for_request_matches_general_kind(self) -> None:
        config = Config(CASE_QA_MODEL_CONTEXT_TOKENS=128000)
        usage = _context_usage_for_request(
            config,
            kind="general_knowledge",
            question="Explain TLS 1.3",
            sources=None,
            conversation_history=None,
        )
        self.assertEqual(usage["kind"], "general_knowledge")
        labels = [segment["label"] for segment in usage["segments"]]
        self.assertIn("System prompt", labels)
        self.assertNotIn("Case context", labels)


if __name__ == "__main__":
    unittest.main()
