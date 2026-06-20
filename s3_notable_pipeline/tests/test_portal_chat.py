"""Tests for portal answer synthesis and guards."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.portal_chat import (
    ChatTurn,
    bounded_conversation_history,
    build_case_grounded_prompt,
    conversation_history_from_config,
    sanitize_portal_chat_answer,
    should_fallback_to_general_knowledge,
    synthesized_answer_crosses_action_boundary,
    synthesize_case_answer,
)


class FakeBedrockClient:
    """Fake Bedrock client returning Markdown text."""

    def converse(self, **_kwargs):
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": (
                                "## Grounded answer\n\nThe login was suspicious based "
                                "on archived context."
                            )
                        }
                    ]
                }
            }
        }


class PortalChatTests(unittest.TestCase):
    """Portal chat prompt and guard tests."""

    def test_build_prompt_uses_context_block_packaging(self) -> None:
        prompt = build_case_grounded_prompt(
            question="What happened?",
            sources=[
                {
                    "search_text": "alert.summary suspicious login",
                    "text": "alert.summary suspicious login",
                }
            ],
        )

        self.assertIn("<CONTEXT_BLOCK>", prompt)
        self.assertIn("UNTRUSTED_TEXT_JSON:", prompt)
        self.assertNotIn("chunk_id=", prompt)

    def test_sanitize_removes_source_markers(self) -> None:
        cleaned = sanitize_portal_chat_answer("Answer text. Source #1")

        self.assertNotIn("Source #1", cleaned)
        self.assertIn("Answer text.", cleaned)

    def test_action_boundary_detection(self) -> None:
        self.assertTrue(
            synthesized_answer_crosses_action_boundary(
                "I ran a Splunk search and created ticket INC123."
            )
        )
        self.assertFalse(
            synthesized_answer_crosses_action_boundary(
                "Draft SPL for a human analyst to review."
            )
        )

    def test_insufficient_archive_phrase_triggers_fallback(self) -> None:
        self.assertTrue(
            should_fallback_to_general_knowledge(
                "The archive did not contain enough grounded context to answer."
            )
        )

    def test_synthesize_returns_answered_markdown(self) -> None:
        config = Config(
            BEDROCK_MODEL_ID="anthropic.test",
            CASE_QA_MAX_TOTAL_CHUNKS=18,
            CASE_QA_MAX_CHUNKS_PER_LANE=6,
            CASE_QA_CONTEXT_BUDGET_CHARS=12_000,
            CASE_QA_MAX_ANSWER_TOKENS=800,
            CASE_QA_GENERAL_KNOWLEDGE_ENABLED=False,
        )
        result = synthesize_case_answer(
            question="What happened?",
            sources=[{"search_text": "suspicious login", "text": "suspicious login"}],
            config=config,
            bedrock_client=FakeBedrockClient(),
        )

        self.assertEqual(result.answer_status, "answered")
        self.assertIn("Grounded answer", result.answer)

    def test_build_prompt_includes_bounded_conversation_history(self) -> None:
        prompt = build_case_grounded_prompt(
            question="Expand on that.",
            sources=[{"search_text": "suspicious login", "text": "suspicious login"}],
            conversation_history=[
                ChatTurn(role="user", content="What happened?"),
                ChatTurn(role="assistant", content="A suspicious login occurred."),
            ],
        )

        self.assertIn("CONVERSATION HISTORY:", prompt)
        self.assertIn("What happened?", prompt)
        self.assertIn("suspicious login occurred", prompt.lower())

    def test_bounded_conversation_history_keeps_recent_turns_within_budget(self) -> None:
        turns = bounded_conversation_history(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
                {"role": "user", "content": "third"},
            ],
            max_turns=2,
            max_chars=20,
        )

        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].content, "second")
        self.assertEqual(turns[1].content, "third")

    def test_conversation_history_from_config_is_empty_when_history_disabled(self) -> None:
        config = Config(CASE_QA_CHAT_HISTORY_ENABLED=False)
        self.assertEqual(
            conversation_history_from_config(
                config,
                [{"role": "user", "content": "prior question"}],
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
