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
    build_general_knowledge_prompt,
    complete_markdown_answer,
    conversation_history_from_config,
    resolve_portal_chat_bedrock_model_id,
    sanitize_portal_chat_answer,
    should_fallback_to_general_knowledge,
    synthesized_answer_crosses_action_boundary,
    synthesize_case_answer,
)
from s3_notable_pipeline.portal_chat_images import validate_chat_images


class FakeBedrockClient:
    """Fake Bedrock client returning Markdown text."""

    last_kwargs: dict[str, object] | None = None

    def converse(self, **kwargs):
        type(self).last_kwargs = kwargs
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
        self.assertIn("SOURCE_LANE_JSON:", prompt)
        self.assertIn("SECTION_JSON:", prompt)
        self.assertNotIn("chunk_id=", prompt)

    def test_build_prompt_labels_knowledge_base_as_advisory(self) -> None:
        prompt = build_case_grounded_prompt(
            question="Summarize this case.",
            sources=[
                {
                    "source_lane": "knowledge_base",
                    "section": "knowledge_base.hva_registry",
                    "text": "db-prod-01.corp.local is an HVA.",
                }
            ],
        )
        self.assertIn("knowledge_base blocks are advisory", prompt)
        self.assertIn("SOURCE_LANE_JSON: \"knowledge_base\"", prompt)

    def test_build_prompt_uses_adaptive_chatbot_answer_guidance(self) -> None:
        prompt = build_case_grounded_prompt(
            question="What happened?",
            sources=[{"search_text": "suspicious login", "text": "suspicious login"}],
        )

        self.assertIn("Answer like a default helpful chatbot", prompt)
        self.assertIn("offer a brief follow-up", prompt)
        self.assertIn("only when the analyst asks for it", prompt)
        self.assertNotIn("When useful, structure the answer", prompt)
        self.assertNotIn("Draft query/example (unvalidated draft", prompt)

    def test_general_knowledge_prompt_uses_on_demand_query_guidance(self) -> None:
        prompt = build_general_knowledge_prompt("How should I validate this?")

        self.assertIn("Answer like a default helpful chatbot", prompt)
        self.assertIn("If the analyst explicitly asks for Splunk SPL", prompt)
        self.assertIn("offer a brief follow-up", prompt)
        self.assertNotIn("draft queries or examples", prompt)

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
                "This case did not contain enough grounded context to answer."
            )
        )
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

    def test_resolve_portal_chat_bedrock_model_id_uses_vision_override(self) -> None:
        config = Config(
            BEDROCK_MODEL_ID="anthropic.text",
            PORTAL_CHAT_BEDROCK_MODEL_ID="anthropic.chat",
            PORTAL_CHAT_VISION_BEDROCK_MODEL_ID="anthropic.vision",
        )
        self.assertEqual(
            resolve_portal_chat_bedrock_model_id(config, has_images=True),
            "anthropic.vision",
        )
        self.assertEqual(
            resolve_portal_chat_bedrock_model_id(config, has_images=False),
            "anthropic.chat",
        )

    def test_complete_markdown_answer_sends_bedrock_image_blocks(self) -> None:
        import base64
        import io

        from PIL import Image

        config = Config(
            BEDROCK_MODEL_ID="anthropic.test",
            CASE_QA_CHAT_IMAGES_ENABLED=True,
        )
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (0, 255, 0)).save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        images = validate_chat_images(
            [{"media_type": "image/png", "data_base64": encoded}],
            config,
        )
        client = FakeBedrockClient()
        answer = complete_markdown_answer(
            prompt="Describe the image.",
            config=config,
            bedrock_client=client,
            images=images,
        )
        self.assertIn("Grounded answer", answer)
        assert client.last_kwargs is not None
        messages = client.last_kwargs["messages"]
        content = messages[0]["content"]
        self.assertEqual(content[0]["text"], "Describe the image.")
        self.assertEqual(content[1]["image"]["format"], "png")


if __name__ == "__main__":
    unittest.main()
