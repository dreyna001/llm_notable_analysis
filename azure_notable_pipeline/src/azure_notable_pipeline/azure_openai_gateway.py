"""Native Azure Government OpenAI operations for analysis, chat, and embeddings."""

from __future__ import annotations

import math
import os
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)

from .azure_clients import AzureClientConfigurationError, azure_openai_client

EMBEDDING_DIMENSIONS = 1024
_EMBEDDING_TIMEOUT_SECONDS = 60
_CHAT_TIMEOUT_SECONDS = 220
_MAX_CHAT_TIMEOUT_SECONDS = 225


class AzureOpenAIGatewayError(RuntimeError):
    """A stable Azure OpenAI boundary failure."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AzureOpenAIConfigurationError(AzureOpenAIGatewayError):
    """Required Azure OpenAI runtime configuration is invalid or absent."""


class AzureOpenAIRequestError(AzureOpenAIGatewayError):
    """The application supplied a request Azure OpenAI cannot accept."""


class AzureOpenAIAuthenticationError(AzureOpenAIGatewayError):
    """The managed identity is unauthenticated or unauthorized."""


class AzureOpenAIRateLimitError(AzureOpenAIGatewayError):
    """The deployment quota is temporarily exhausted."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class AzureOpenAIUnavailableError(AzureOpenAIGatewayError):
    """Azure OpenAI timed out or returned a retryable service failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class AzureOpenAIResponseError(AzureOpenAIGatewayError):
    """Azure OpenAI returned a malformed or contract-incompatible response."""

    def __init__(self, message: str, *, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


class AzureOpenAIRefusalError(AzureOpenAIGatewayError):
    """Azure OpenAI refused the request and must not be repaired automatically."""


@dataclass(frozen=True)
class AzureOpenAIAnalysis:
    """Parsed forced-tool response for the analyzer contract."""

    payload: dict[str, Any]
    raw_output: str
    stop_reason: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise AzureOpenAIConfigurationError(f"{name} is required")
    return value


def _native_client(gateway: Any | None) -> Any:
    if gateway is not None:
        return gateway
    try:
        return azure_openai_client(
            _required_env("AZURE_OPENAI_ENDPOINT"),
            os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
            or "2024-10-21",
        )
    except AzureClientConfigurationError as exc:
        raise AzureOpenAIConfigurationError(str(exc)) from exc


def _raise_openai_error(exc: Exception, *, operation: str) -> None:
    message = f"Azure OpenAI {operation} failed"
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        raise AzureOpenAIAuthenticationError(message) from exc
    if isinstance(exc, RateLimitError):
        raise AzureOpenAIRateLimitError(message) from exc
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        raise AzureOpenAIUnavailableError(message) from exc
    if isinstance(exc, BadRequestError):
        raise AzureOpenAIRequestError(message) from exc
    if isinstance(exc, APIStatusError) and exc.status_code in {408, 429, 500, 502, 503, 504}:
        raise AzureOpenAIUnavailableError(message) from exc
    if isinstance(exc, (APIError, OpenAIError)):
        raise AzureOpenAIGatewayError(message) from exc
    raise exc


def _embedding_vector(item: Any) -> list[float]:
    raw_vector = _value(item, "embedding")
    if not isinstance(raw_vector, Sequence) or isinstance(raw_vector, (str, bytes)):
        raise AzureOpenAIResponseError("Azure OpenAI embedding is not a numeric vector")
    if len(raw_vector) != EMBEDDING_DIMENSIONS:
        raise AzureOpenAIResponseError(
            "Azure OpenAI embedding dimension mismatch: "
            f"expected {EMBEDDING_DIMENSIONS}, received {len(raw_vector)}"
        )
    vector: list[float] = []
    for component in raw_vector:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise AzureOpenAIResponseError(
                "Azure OpenAI embedding contains a non-numeric component"
            )
        number = float(component)
        if not math.isfinite(number):
            raise AzureOpenAIResponseError(
                "Azure OpenAI embedding contains a non-finite component"
            )
        vector.append(number)
    return vector


def embed_texts(
    texts: Sequence[str],
    *,
    gateway: Any | None = None,
    deployment: str | None = None,
) -> list[list[float]]:
    """Embed text with the configured Azure OpenAI deployment at exactly 1024 dims."""

    if isinstance(texts, (str, bytes)):
        raise AzureOpenAIRequestError("texts must be a sequence of strings")
    normalized = list(texts)
    if any(not isinstance(text, str) or not text.strip() for text in normalized):
        raise AzureOpenAIRequestError("each embedding input must be non-empty text")
    if not normalized:
        return []
    model = str(deployment or "").strip() or _required_env(
        "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"
    )
    try:
        response = _native_client(gateway).embeddings.create(
            model=model,
            input=normalized,
            dimensions=EMBEDDING_DIMENSIONS,
            timeout=_EMBEDDING_TIMEOUT_SECONDS,
        )
    except AzureOpenAIGatewayError:
        raise
    except Exception as exc:
        _raise_openai_error(exc, operation="embeddings request")
        raise AssertionError("unreachable")

    data = _value(response, "data")
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        raise AzureOpenAIResponseError("Azure OpenAI embeddings response has no data list")
    if len(data) != len(normalized):
        raise AzureOpenAIResponseError(
            "Azure OpenAI embeddings response count does not match the request"
        )
    try:
        ordered = sorted(data, key=lambda item: int(_value(item, "index")))
    except (TypeError, ValueError) as exc:
        raise AzureOpenAIResponseError(
            "Azure OpenAI embeddings response has an invalid index"
        ) from exc
    indexes = [int(_value(item, "index")) for item in ordered]
    if indexes != list(range(len(normalized))):
        raise AzureOpenAIResponseError(
            "Azure OpenAI embeddings response indexes are incomplete or duplicated"
        )
    return [_embedding_vector(item) for item in ordered]


def _chat_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        raise AzureOpenAIResponseError("Azure OpenAI chat content has an invalid shape")
    parts: list[str] = []
    for part in content:
        text = _value(part, "text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _tool_calls(message: Any) -> list[dict[str, Any]]:
    raw_calls = _value(message, "tool_calls", []) or []
    if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes)):
        raise AzureOpenAIResponseError("Azure OpenAI tool_calls has an invalid shape")
    calls: list[dict[str, Any]] = []
    for call in raw_calls:
        function = _value(call, "function")
        name = _value(function, "name")
        arguments = _value(function, "arguments")
        if not isinstance(name, str) or not isinstance(arguments, str):
            raise AzureOpenAIResponseError(
                "Azure OpenAI tool call is missing function name or arguments"
            )
        calls.append(
            {
                "id": str(_value(call, "id", "") or ""),
                "type": str(_value(call, "type", "function") or "function"),
                "function": {"name": name, "arguments": arguments},
            }
        )
    return calls


def _usage(response: Any) -> dict[str, int]:
    usage = _value(response, "usage")
    if usage is None:
        return {}
    output: dict[str, int] = {}
    for source, target in (
        ("prompt_tokens", "prompt_tokens"),
        ("completion_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = _value(usage, source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            output[target] = value
    return output


def _tool_schema(tool: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the shared tool contract to the OpenAI function shape."""

    name = str(tool.get("name") or "").strip()
    parameters = tool.get("input_schema")
    if not name or not isinstance(parameters, Mapping):
        raise AzureOpenAIRequestError("tool must define a name and input_schema")
    description = str(tool.get("description") or "").strip()
    function: dict[str, Any] = {
        "name": name,
        "parameters": dict(parameters),
    }
    if description:
        function["description"] = description
    return {"type": "function", "function": function}


def _usage_value(usage: Mapping[str, Any], name: str) -> int | None:
    value = usage.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def analyze_notable(
    *,
    messages: Sequence[Mapping[str, Any]],
    deployment: str,
    tool: Mapping[str, Any],
    max_tokens: int = 8192,
    temperature: float = 0.1,
    gateway: Any | None = None,
) -> AzureOpenAIAnalysis:
    """Run exactly one forced function call using a customer OpenAI deployment."""

    if not deployment.strip():
        raise AzureOpenAIConfigurationError("analysis deployment cannot be blank")
    if not 256 <= max_tokens <= 8192:
        raise AzureOpenAIRequestError("max_tokens must be between 256 and 8192")
    if not messages:
        raise AzureOpenAIRequestError("messages cannot be empty")

    result = create_chat_completion(
        messages=messages,
        gateway=gateway,
        deployment=deployment,
        max_tokens=max_tokens,
        temperature=temperature,
        tools=[_tool_schema(tool)],
        tool_choice={
            "type": "function",
            "function": {"name": str(tool.get("name") or "")},
        },
        timeout_seconds=_MAX_CHAT_TIMEOUT_SECONDS,
    )
    if result.get("refusal"):
        raise AzureOpenAIRefusalError("Azure OpenAI refused the analysis request")
    calls = result["tool_calls"]
    if len(calls) != 1 or calls[0]["function"]["name"] != tool.get("name"):
        raise AzureOpenAIResponseError(
            "Azure OpenAI analysis response must contain exactly one analyze_notable function call"
        )
    raw_arguments = calls[0]["function"]["arguments"]
    try:
        payload = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise AzureOpenAIResponseError(
            "Azure OpenAI analysis function arguments were not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise AzureOpenAIResponseError(
            "Azure OpenAI analysis function arguments must be an object"
        )
    usage = result.get("usage", {})
    return AzureOpenAIAnalysis(
        payload=payload,
        raw_output=raw_arguments,
        stop_reason=str(result.get("finish_reason") or ""),
        input_tokens=_usage_value(usage, "prompt_tokens"),
        output_tokens=_usage_value(usage, "completion_tokens"),
    )


def generate_text(
    *,
    messages: Sequence[Mapping[str, Any]],
    deployment: str,
    max_tokens: int = 8192,
    temperature: float = 0.1,
    gateway: Any | None = None,
    json_object: bool = False,
) -> str:
    """Run one bounded text call for optional synthesis and repair workflows."""

    if not deployment.strip():
        raise AzureOpenAIConfigurationError("analysis deployment cannot be blank")
    if not 256 <= max_tokens <= 8192:
        raise AzureOpenAIRequestError("max_tokens must be between 256 and 8192")
    response_format = {"type": "json_object"} if json_object else None
    result = create_chat_completion(
        messages=messages,
        gateway=gateway,
        deployment=deployment,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_seconds=_MAX_CHAT_TIMEOUT_SECONDS,
        response_format=response_format,
    )
    if result.get("refusal"):
        raise AzureOpenAIResponseError("Azure OpenAI refused the text request")
    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        raise AzureOpenAIResponseError("Azure OpenAI text response was empty")
    if result.get("finish_reason") == "length":
        raise AzureOpenAIResponseError(
            "Azure OpenAI response stopped at the output-token limit"
        )
    return text


def create_chat_completion(
    *,
    messages: Sequence[Mapping[str, Any]],
    gateway: Any | None = None,
    deployment: str | None = None,
    max_tokens: int = 800,
    temperature: float = 0.0,
    tools: Sequence[Mapping[str, Any]] | None = None,
    tool_choice: str | Mapping[str, Any] | None = None,
    response_format: Mapping[str, Any] | None = None,
    timeout_seconds: int = _CHAT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Create one portal chat completion and return a stable normalized result."""

    if isinstance(messages, (str, bytes)) or not messages:
        raise AzureOpenAIRequestError("messages must be a non-empty sequence")
    normalized_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            raise AzureOpenAIRequestError("each chat message must be an object")
        role = str(message.get("role") or "").strip()
        if role not in {"system", "developer", "user", "assistant", "tool"}:
            raise AzureOpenAIRequestError(f"unsupported chat message role: {role or '(blank)'}")
        if "content" not in message:
            raise AzureOpenAIRequestError("each chat message must include content")
        normalized_messages.append(dict(message))
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise AzureOpenAIRequestError("max_tokens must be a positive integer")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise AzureOpenAIRequestError("temperature must be numeric")
    if not 0 <= float(temperature) <= 2:
        raise AzureOpenAIRequestError("temperature must be between 0 and 2")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= _MAX_CHAT_TIMEOUT_SECONDS
    ):
        raise AzureOpenAIRequestError(
            f"timeout_seconds must be between 1 and {_MAX_CHAT_TIMEOUT_SECONDS}"
        )
    model = str(deployment or "").strip() or _required_env(
        "AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT"
    )
    request: dict[str, Any] = {
        "model": model,
        "messages": normalized_messages,
        "max_tokens": max_tokens,
        "temperature": float(temperature),
        "timeout": timeout_seconds,
    }
    if tools is not None:
        if isinstance(tools, (str, bytes)):
            raise AzureOpenAIRequestError("tools must be a sequence of objects")
        normalized_tools = list(tools)
        if any(not isinstance(tool, Mapping) for tool in normalized_tools):
            raise AzureOpenAIRequestError("each tool must be an object")
        request["tools"] = [dict(tool) for tool in normalized_tools]
    if tool_choice is not None:
        request["tool_choice"] = tool_choice
    if response_format is not None:
        if not isinstance(response_format, Mapping):
            raise AzureOpenAIRequestError("response_format must be an object")
        request["response_format"] = dict(response_format)
    try:
        response = _native_client(gateway).chat.completions.create(**request)
    except AzureOpenAIGatewayError:
        raise
    except Exception as exc:
        _raise_openai_error(exc, operation="chat request")
        raise AssertionError("unreachable")

    choices = _value(response, "choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise AzureOpenAIResponseError("Azure OpenAI chat response has no choices")
    choice = choices[0]
    message = _value(choice, "message")
    if message is None:
        raise AzureOpenAIResponseError("Azure OpenAI chat response has no message")
    refusal = _value(message, "refusal")
    if refusal is not None and not isinstance(refusal, str):
        refusal = str(refusal)
    return {
        "id": str(_value(response, "id", "") or ""),
        "text": _chat_text(_value(message, "content")),
        "finish_reason": str(_value(choice, "finish_reason", "") or ""),
        "refusal": refusal,
        "tool_calls": _tool_calls(message),
        "usage": _usage(response),
    }


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "AzureOpenAIAuthenticationError",
    "AzureOpenAIConfigurationError",
    "AzureOpenAIGatewayError",
    "AzureOpenAIRateLimitError",
    "AzureOpenAIRequestError",
    "AzureOpenAIRefusalError",
    "AzureOpenAIResponseError",
    "AzureOpenAIUnavailableError",
    "AzureOpenAIAnalysis",
    "analyze_notable",
    "create_chat_completion",
    "embed_texts",
    "generate_text",
]
