"""Tests for OpenAI-compatible chat transport helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.openai_transport_nonsdk import (
    openai_chat_complete,
)


class TestOpenAiTransportNonsdk(unittest.TestCase):
    def test_openai_chat_complete_preserves_text_only_payload(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "Answer text"}}]
        }
        session.post.return_value = response
        config = Config(
            LLM_API_URL="http://127.0.0.1:4000/v1/chat/completions",
            LLM_MODEL_NAME="test-model",
        )

        answer, _latency = openai_chat_complete(
            session,
            config,
            prompt="Question text",
            max_tokens=32,
            temperature=0.0,
            connect_timeout_sec=1.0,
            read_timeout_sec=1.0,
        )

        self.assertEqual(answer, "Answer text")
        body = session.post.call_args.kwargs["json"]
        self.assertEqual(
            body["messages"],
            [{"role": "user", "content": "Question text"}],
        )

    def test_openai_chat_complete_accepts_multimodal_user_content(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "Seen the screenshot."}}]
        }
        session.post.return_value = response
        config = Config(
            LLM_API_URL="http://127.0.0.1:4000/v1/chat/completions",
            LLM_MODEL_NAME="test-model",
        )
        user_content = [
            {"type": "text", "text": "Question text"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,abcd"},
            },
        ]

        answer, _latency = openai_chat_complete(
            session,
            config,
            prompt="Question text",
            user_content=user_content,
            max_tokens=32,
            temperature=0.0,
            connect_timeout_sec=1.0,
            read_timeout_sec=1.0,
        )

        self.assertEqual(answer, "Seen the screenshot.")
        body = session.post.call_args.kwargs["json"]
        self.assertEqual(body["messages"][0]["content"], user_content)

    def test_openai_chat_complete_rejects_remote_image_urls(self) -> None:
        session = MagicMock()
        config = Config(
            LLM_API_URL="http://127.0.0.1:4000/v1/chat/completions",
            LLM_MODEL_NAME="test-model",
        )
        with self.assertRaisesRegex(ValueError, "internal data URL"):
            openai_chat_complete(
                session,
                config,
                prompt="Question text",
                user_content=[
                    {"type": "text", "text": "Question text"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.test/image.png"},
                    },
                ],
                max_tokens=32,
                temperature=0.0,
                connect_timeout_sec=1.0,
                read_timeout_sec=1.0,
            )
