"""Unit tests for native Anthropic Foundry Messages analysis."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import httpx
import pytest
from anthropic.types import TextBlock, ToolUseBlock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.azure_anthropic_gateway import (
    AnthropicGatewayAuthenticationError,
    AnthropicGatewayRateLimitError,
    AnthropicGatewayRefusalError,
    AnthropicGatewayResponseError,
    AnthropicGatewayTimeoutError,
    analyze_notable,
    generate_text,
    parse_analyze_notable_response,
    parse_text_response,
)


def _tool_block(payload: dict) -> ToolUseBlock:
    return ToolUseBlock(
        id="toolu_123",
        input=payload,
        name="analyze_notable",
        type="tool_use",
    )


def _response(*blocks, stop_reason: str = "tool_use") -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        stop_details=None,
        usage=SimpleNamespace(input_tokens=42, output_tokens=21),
    )


def test_analyze_notable_uses_forced_single_tool_without_thinking_or_effort() -> None:
    client = Mock()
    client.messages.create.return_value = _response(_tool_block({"answer": "ok"}))

    result = analyze_notable(
        messages=[{"role": "user", "content": "analyze"}],
        deployment="claude-sonnet-4-6",
        tool={
            "name": "analyze_notable",
            "description": "Analyze",
            "input_schema": {"type": "object"},
        },
        gateway=client,
    )

    assert result.payload == {"answer": "ok"}
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["tool_choice"] == {
        "type": "tool",
        "name": "analyze_notable",
        "disable_parallel_tool_use": True,
    }
    assert kwargs["temperature"] == 0.1
    assert "thinking" not in kwargs
    assert "effort" not in kwargs


def test_parser_requires_exactly_one_native_tool_use_block() -> None:
    with pytest.raises(AnthropicGatewayResponseError, match="exactly one"):
        parse_analyze_notable_response(
            _response(
                TextBlock(text="extra", type="text"),
                _tool_block({"answer": "ok"}),
            )
        )

    with pytest.raises(AnthropicGatewayResponseError, match="exactly one"):
        parse_analyze_notable_response(
            _response(_tool_block({}), _tool_block({"second": True}))
        )


def test_parser_rejects_wrong_tool_name_and_refusal() -> None:
    wrong = ToolUseBlock(
        id="toolu_wrong", input={}, name="other_tool", type="tool_use"
    )
    with pytest.raises(AnthropicGatewayResponseError, match="unexpected tool"):
        parse_analyze_notable_response(_response(wrong))

    with pytest.raises(AnthropicGatewayRefusalError):
        parse_analyze_notable_response(
            _response(TextBlock(text="refused", type="text"), stop_reason="refusal")
        )


def test_parser_rejects_truncated_response_with_bounded_diagnostic_text() -> None:
    with pytest.raises(AnthropicGatewayResponseError) as exc_info:
        parse_analyze_notable_response(
            _response(TextBlock(text="partial", type="text"), stop_reason="max_tokens")
        )

    assert exc_info.value.raw_output == "partial"


def test_optional_synthesis_uses_native_text_without_tool_contract() -> None:
    client = Mock()
    client.messages.create.return_value = _response(
        TextBlock(text='{"answer":"ok"}', type="text"),
        stop_reason="end_turn",
    )

    result = generate_text(
        messages=[{"role": "user", "content": "generate bounded JSON"}],
        deployment="claude-sonnet-4-6",
        max_tokens=768,
        gateway=client,
    )

    assert result.text == '{"answer":"ok"}'
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 768
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs
    assert parse_text_response(client.messages.create.return_value) == result


@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (
            anthropic.APITimeoutError(httpx.Request("POST", "https://foundry.test")),
            AnthropicGatewayTimeoutError,
        ),
        (
            anthropic.RateLimitError(
                "limited",
                response=httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://foundry.test"),
                ),
                body=None,
            ),
            AnthropicGatewayRateLimitError,
        ),
        (
            anthropic.AuthenticationError(
                "denied",
                response=httpx.Response(
                    401,
                    request=httpx.Request("POST", "https://foundry.test"),
                ),
                body=None,
            ),
            AnthropicGatewayAuthenticationError,
        ),
    ],
)
def test_sdk_failures_are_translated_to_typed_gateway_errors(
    sdk_error: anthropic.APIError,
    expected_error: type[Exception],
) -> None:
    client = Mock()
    client.messages.create.side_effect = sdk_error

    with pytest.raises(expected_error):
        analyze_notable(
            messages=[{"role": "user", "content": "analyze"}],
            deployment="claude-sonnet-4-6",
            tool={"name": "analyze_notable", "input_schema": {"type": "object"}},
            gateway=client,
        )

    assert client.messages.create.call_count == 1
