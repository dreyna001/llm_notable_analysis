"""Native Anthropic Messages boundary for Sonnet analysis in Azure AI Foundry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import anthropic
from anthropic.types import ToolUseBlock

from .azure_clients import anthropic_foundry_client


class AnthropicGatewayError(RuntimeError):
    """Base class for failures at the Foundry Messages boundary."""


class AnthropicGatewayTimeoutError(AnthropicGatewayError):
    """The model request exceeded its configured timeout."""


class AnthropicGatewayRateLimitError(AnthropicGatewayError):
    """The model endpoint rejected the request due to rate limiting."""


class AnthropicGatewayAuthenticationError(AnthropicGatewayError):
    """Managed-identity authentication or authorization failed."""


class AnthropicGatewayRequestError(AnthropicGatewayError):
    """The model endpoint rejected an invalid request."""


class AnthropicGatewayServiceError(AnthropicGatewayError):
    """The model endpoint or its network path failed."""


class AnthropicGatewayRefusalError(AnthropicGatewayError):
    """The model or its content controls refused the request."""


class AnthropicGatewayResponseError(AnthropicGatewayError):
    """The model returned content outside the forced-tool contract."""

    def __init__(self, message: str, *, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


@dataclass(frozen=True)
class AnthropicAnalysis:
    """Parsed native Messages response with bounded diagnostic metadata."""

    payload: dict[str, Any]
    raw_output: str
    stop_reason: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def _looks_like_refusal(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("content filter", "content_filter", "refusal", "safety")
    )


def _translate_sdk_error(exc: BaseException) -> AnthropicGatewayError:
    """Translate SDK exceptions without exposing provider response bodies."""

    if isinstance(exc, anthropic.APITimeoutError):
        return AnthropicGatewayTimeoutError("Anthropic Foundry request timed out")
    if isinstance(exc, anthropic.RateLimitError):
        return AnthropicGatewayRateLimitError("Anthropic Foundry rate limit exceeded")
    if isinstance(
        exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)
    ):
        return AnthropicGatewayAuthenticationError(
            "Anthropic Foundry managed-identity access was rejected"
        )
    if isinstance(exc, anthropic.BadRequestError):
        if _looks_like_refusal(exc):
            return AnthropicGatewayRefusalError(
                "Anthropic Foundry content controls refused the request"
            )
        return AnthropicGatewayRequestError("Anthropic Foundry rejected the request")
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APIStatusError)):
        return AnthropicGatewayServiceError("Anthropic Foundry service request failed")
    return AnthropicGatewayServiceError("Anthropic Foundry request failed")


def _usage_value(usage: Any, name: str) -> int | None:
    value = getattr(usage, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_analyze_notable_response(response: Any) -> AnthropicAnalysis:
    """Require exactly one native ``ToolUseBlock`` for ``analyze_notable``."""

    stop_reason = str(getattr(response, "stop_reason", "") or "")
    stop_details = getattr(response, "stop_details", None)
    content = getattr(response, "content", None)
    diagnostic_text = "\n".join(
        str(getattr(block, "text", ""))
        for block in content
        if getattr(block, "type", None) == "text"
    ) if isinstance(content, list) else ""

    if stop_reason == "refusal" or stop_details is not None:
        raise AnthropicGatewayRefusalError(
            "Anthropic Foundry refused the analysis request"
        )
    if stop_reason == "max_tokens":
        raise AnthropicGatewayResponseError(
            "Anthropic Foundry response stopped at the output-token limit",
            raw_output=diagnostic_text,
        )

    if not isinstance(content, list):
        raise AnthropicGatewayResponseError(
            "Anthropic Foundry response content must be a list"
        )

    tool_blocks = [block for block in content if isinstance(block, ToolUseBlock)]
    if len(tool_blocks) != 1 or len(content) != 1:
        raise AnthropicGatewayResponseError(
            "Anthropic Foundry response must contain exactly one ToolUseBlock",
            raw_output=diagnostic_text,
        )

    tool_block = tool_blocks[0]
    if tool_block.name != "analyze_notable":
        raise AnthropicGatewayResponseError(
            "Anthropic Foundry returned an unexpected tool name"
        )
    if not isinstance(tool_block.input, dict):
        raise AnthropicGatewayResponseError(
            "analyze_notable tool input must be an object"
        )

    payload = dict(tool_block.input)
    raw_output = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    usage = getattr(response, "usage", None)
    return AnthropicAnalysis(
        payload=payload,
        raw_output=raw_output,
        stop_reason=stop_reason,
        input_tokens=_usage_value(usage, "input_tokens"),
        output_tokens=_usage_value(usage, "output_tokens"),
    )


def analyze_notable(
    *,
    messages: Sequence[Mapping[str, Any]],
    deployment: str,
    tool: Mapping[str, Any],
    base_url: str = "",
    max_tokens: int = 8192,
    temperature: float = 0.1,
    gateway: Any | None = None,
) -> AnthropicAnalysis:
    """Run one forced native Messages tool call through Azure AI Foundry.

    Transport retries belong to the configured Anthropic SDK client. This operation
    performs no retry and has no API-key, Azure OpenAI, or raw-text fallback path.
    """

    if not deployment.strip():
        raise ValueError("deployment cannot be blank")
    if not 256 <= max_tokens <= 8192:
        raise ValueError("max_tokens must be between 256 and 8192")
    if not messages:
        raise ValueError("messages cannot be empty")

    client = gateway or anthropic_foundry_client(base_url)
    try:
        response = client.messages.create(
            model=deployment,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=list(messages),
            tools=[dict(tool)],
            tool_choice={
                "type": "tool",
                "name": "analyze_notable",
                "disable_parallel_tool_use": True,
            },
        )
    except anthropic.APIError as exc:
        raise _translate_sdk_error(exc) from exc
    except (OSError, TimeoutError) as exc:
        raise AnthropicGatewayServiceError(
            "Anthropic Foundry client request failed"
        ) from exc

    return parse_analyze_notable_response(response)
