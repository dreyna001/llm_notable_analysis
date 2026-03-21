"""Config behavior unit tests.

Run this module directly:
  PYTHONPATH=src python -m unittest tests.test_config -v
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from onprem_llm_sdk.config import SDKConfig
from onprem_llm_sdk.errors import ConfigError


class TestSDKConfig(unittest.TestCase):
    def test_loads_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cfg = SDKConfig.from_env()
        self.assertEqual(cfg.llm_api_url, "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(cfg.llm_max_inflight, 2)

    def test_env_overrides_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_MODEL_NAME": "my-model",
                "LLM_MAX_INFLIGHT": "4",
            },
            clear=True,
        ):
            cfg = SDKConfig.from_env()
        self.assertEqual(cfg.llm_model_name, "my-model")
        self.assertEqual(cfg.llm_max_inflight, 4)

    def test_explicit_overrides_take_precedence(self) -> None:
        with patch.dict(os.environ, {"LLM_MAX_INFLIGHT": "2"}, clear=True):
            cfg = SDKConfig.from_env(overrides={"llm_max_inflight": 8})
        self.assertEqual(cfg.llm_max_inflight, 8)

    def test_invalid_numeric_raises(self) -> None:
        with patch.dict(os.environ, {"LLM_MAX_INFLIGHT": "bad"}, clear=True):
            with self.assertRaises(ConfigError):
                SDKConfig.from_env()


if __name__ == "__main__":
    unittest.main()
