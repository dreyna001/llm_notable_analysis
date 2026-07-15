"""Tests for portal UI preview OpenAI configuration helpers."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from preview_portal_ui import (  # noqa: E402
    load_optional_preview_env,
    preview_chat_mode_label,
    resolve_openai_preview_llm,
)


class PreviewPortalUiOpenAiConfigTests(unittest.TestCase):
    def test_resolve_openai_preview_llm_returns_none_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_openai_preview_llm())

    def test_resolve_openai_preview_llm_reads_openai_api_key(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test", "PORTAL_PREVIEW_OPENAI_MODEL": "gpt-4.1-mini"},
            clear=True,
        ):
            settings = resolve_openai_preview_llm()
        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertEqual(settings["LLM_API_TOKEN"], "sk-test")
        self.assertEqual(settings["LLM_MODEL_NAME"], "gpt-4.1-mini")
        self.assertEqual(
            settings["LLM_API_URL"],
            "https://api.openai.com/v1/chat/completions",
        )

    def test_load_optional_preview_env_does_not_override_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "config.portal-preview.env"
            env_path.write_text(
                "PORTAL_PREVIEW_OPENAI_API_KEY=from-file\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "PORTAL_PREVIEW_ENV": str(env_path),
                    "PORTAL_PREVIEW_OPENAI_API_KEY": "from-shell",
                },
                clear=True,
            ):
                loaded = load_optional_preview_env()
                self.assertEqual(loaded, env_path)
                self.assertEqual(
                    os.environ["PORTAL_PREVIEW_OPENAI_API_KEY"],
                    "from-shell",
                )

    def test_preview_chat_mode_label_reflects_openai_config(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test", "PORTAL_PREVIEW_OPENAI_MODEL": "gpt-4.1-mini"},
            clear=True,
        ):
            self.assertIn("OpenAI", preview_chat_mode_label())
        with patch.dict(os.environ, {}, clear=True):
            self.assertIn("stub", preview_chat_mode_label())


if __name__ == "__main__":
    unittest.main()
