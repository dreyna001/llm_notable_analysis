"""OpenAI-compatible chat HTTP transport without onprem-llm-sdk.

Used by local_llm_client_nonsdk.LocalLLMClient. Mirrors the SDK request/response
shape enough for the notable analyzer retry and error-handling paths.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import requests

from .config import Config


class ClientRequestError(Exception):
    """Non-retryable 4xx (except 429)."""


class RateLimitError(Exception):
    """HTTP 429."""


class RequestTimeoutError(Exception):
    """Request timed out."""


class ResponseFormatError(Exception):
    """Invalid JSON or missing completion fields."""


class ServerError(Exception):
    """HTTP 5xx."""


class TransportError(Exception):
    """Network / transport failure."""


def _parse_completion_text(response_json: Dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ResponseFormatError("Expected non-empty choices[] in completion response")

    first = choices[0]
    if not isinstance(first, dict):
        raise ResponseFormatError("Expected choices[0] to be an object")

    text = first.get("text")
    if isinstance(text, str):
        return text

    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content

    raise ResponseFormatError("Expected choices[0].text or choices[0].message.content")


def _parse_tool_call_arguments(
    response_json: Dict[str, Any], *, tool_name: str
) -> str:
    """Extract function arguments JSON text from OpenAI tool-call response."""
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ResponseFormatError("Expected non-empty choices[] in completion response")

    first = choices[0]
    if not isinstance(first, dict):
        raise ResponseFormatError("Expected choices[0] to be an object")

    message = first.get("message")
    if not isinstance(message, dict):
        raise ResponseFormatError("Expected choices[0].message to be an object")

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        selected: Optional[Dict[str, Any]] = None
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            func = call.get("function")
            if isinstance(func, dict) and str(func.get("name", "")).strip() == tool_name:
                selected = call
                break
        if selected is None:
            selected = tool_calls[0] if isinstance(tool_calls[0], dict) else None
        if selected is None:
            raise ResponseFormatError("Expected tool call object in message.tool_calls")
        function_obj = selected.get("function")
        if not isinstance(function_obj, dict):
            raise ResponseFormatError("Expected tool call function object")
        arguments = function_obj.get("arguments")
        if isinstance(arguments, str):
            return arguments
        if isinstance(arguments, dict):
            return json.dumps(arguments, ensure_ascii=True)
        raise ResponseFormatError("Expected string/dict function.arguments in tool call")

    function_call = message.get("function_call")
    if isinstance(function_call, dict):
        arguments = function_call.get("arguments")
        if isinstance(arguments, str):
            return arguments
        if isinstance(arguments, dict):
            return json.dumps(arguments, ensure_ascii=True)
        raise ResponseFormatError(
            "Expected string/dict function_call.arguments in completion response"
        )

    raise ResponseFormatError("Expected message.tool_calls or message.function_call")


def _headers(config: Config, correlation_id: str) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "X-Correlation-ID": correlation_id,
        "X-LLM-App": "notable-analyzer",
        "User-Agent": "notable-analyzer/openai-transport-nonsdk",
    }
    token = (config.LLM_API_TOKEN or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _payload(
    config: Config,
    *,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> Dict[str, Any]:
    return {
        "model": config.LLM_MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


def openai_chat_complete(
    session: Any,
    config: Config,
    *,
    prompt: str,
    max_tokens: int,
    temperature: float,
    connect_timeout_sec: float,
    read_timeout_sec: float,
    correlation_id: Optional[str] = None,
) -> Tuple[str, float]:
    """POST chat completion; return (text, latency_seconds).

    Raises the same exception types LocalLLMClient.analyze_alert catches.
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt must not be empty")

    corr = correlation_id or str(uuid.uuid4())
    timeout = (float(connect_timeout_sec), float(read_timeout_sec))
    verify = config.LLM_API_URL.lower().startswith("https://")
    body = _payload(
        config, prompt=prompt, max_tokens=max_tokens, temperature=temperature
    )

    overall_start = time.perf_counter()
    try:
        response = session.post(
            config.LLM_API_URL,
            json=body,
            headers=_headers(config, corr),
            timeout=timeout,
            verify=verify,
        )
    except requests.exceptions.Timeout as exc:
        raise RequestTimeoutError(
            "LLM request timed out"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise TransportError(f"LLM transport error: {exc}") from exc

    latency = time.perf_counter() - overall_start
    code = response.status_code

    if code == 429:
        raise RateLimitError("LLM API rate limited (429)")
    if 500 <= code < 600:
        detail = (getattr(response, "text", None) or "").strip()
        if len(detail) > 800:
            detail = detail[:800] + "..."
        raise ServerError(
            f"LLM server error: HTTP {code}"
            + (f" — {detail}" if detail else "")
        )
    if 400 <= code < 500:
        detail = (getattr(response, "text", None) or "").strip()
        if len(detail) > 800:
            detail = detail[:800] + "..."
        raise ClientRequestError(
            f"LLM client error: HTTP {code}"
            + (f" — {detail}" if detail else "")
        )

    if not (200 <= code < 300):
        raise ClientRequestError(f"LLM unexpected status: HTTP {code}")

    try:
        response_json = response.json()
    except ValueError as exc:
        raise ResponseFormatError("Response is not valid JSON") from exc

    try:
        text = _parse_completion_text(response_json)
    except ResponseFormatError:
        raise
    except Exception as exc:
        raise ResponseFormatError(str(exc)) from exc

    return text, latency


def openai_chat_complete_tool_call(
    session: Any,
    config: Config,
    *,
    prompt: str,
    max_tokens: int,
    temperature: float,
    tool_spec: Dict[str, Any],
    tool_name: str,
    connect_timeout_sec: float,
    read_timeout_sec: float,
    correlation_id: Optional[str] = None,
) -> Tuple[str, float]:
    """POST chat completion with tool-calling; return (arguments_json_text, latency_seconds)."""
    if not prompt or not prompt.strip():
        raise ValueError("prompt must not be empty")

    corr = correlation_id or str(uuid.uuid4())
    timeout = (float(connect_timeout_sec), float(read_timeout_sec))
    verify = config.LLM_API_URL.lower().startswith("https://")
    body = _payload(
        config, prompt=prompt, max_tokens=max_tokens, temperature=temperature
    )
    body["tools"] = [tool_spec]
    body["tool_choice"] = {"type": "function", "function": {"name": tool_name}}

    overall_start = time.perf_counter()
    try:
        response = session.post(
            config.LLM_API_URL,
            json=body,
            headers=_headers(config, corr),
            timeout=timeout,
            verify=verify,
        )
    except requests.exceptions.Timeout as exc:
        raise RequestTimeoutError(
            "LLM request timed out"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise TransportError(f"LLM transport error: {exc}") from exc

    latency = time.perf_counter() - overall_start
    code = response.status_code

    if code == 429:
        raise RateLimitError("LLM API rate limited (429)")
    if 500 <= code < 600:
        detail = (getattr(response, "text", None) or "").strip()
        if len(detail) > 800:
            detail = detail[:800] + "..."
        raise ServerError(
            f"LLM server error: HTTP {code}"
            + (f" — {detail}" if detail else "")
        )
    if 400 <= code < 500:
        detail = (getattr(response, "text", None) or "").strip()
        if len(detail) > 800:
            detail = detail[:800] + "..."
        raise ClientRequestError(
            f"LLM client error: HTTP {code}"
            + (f" — {detail}" if detail else "")
        )

    if not (200 <= code < 300):
        raise ClientRequestError(f"LLM unexpected status: HTTP {code}")

    try:
        response_json = response.json()
    except ValueError as exc:
        raise ResponseFormatError("Response is not valid JSON") from exc

    try:
        arguments_text = _parse_tool_call_arguments(
            response_json,
            tool_name=tool_name,
        )
    except ResponseFormatError:
        raise
    except Exception as exc:
        raise ResponseFormatError(str(exc)) from exc

    return arguments_text, latency
