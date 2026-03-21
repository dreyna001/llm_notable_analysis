"""Contract parser compatibility unit tests.

Run this module directly:
  PYTHONPATH=src python -m unittest tests.test_contract_compat -v
"""

from __future__ import annotations

import unittest

from onprem_llm_sdk.contracts import parse_completion_text, parse_retry_after_seconds
from onprem_llm_sdk.errors import ResponseFormatError


class TestContractCompatibility(unittest.TestCase):
    def test_parse_text_choice(self) -> None:
        payload = {"choices": [{"text": "plain"}]}
        self.assertEqual(parse_completion_text(payload), "plain")

    def test_parse_message_content_choice(self) -> None:
        payload = {"choices": [{"message": {"content": "chat-format"}}]}
        self.assertEqual(parse_completion_text(payload), "chat-format")

    def test_invalid_shape_raises(self) -> None:
        with self.assertRaises(ResponseFormatError):
            parse_completion_text({"choices": [{}]})

    def test_retry_after_parser(self) -> None:
        self.assertEqual(parse_retry_after_seconds({"Retry-After": "2"}), 2.0)
        self.assertIsNone(parse_retry_after_seconds({"Retry-After": "bad"}))
        self.assertIsNone(parse_retry_after_seconds(None))


if __name__ == "__main__":
    unittest.main()
