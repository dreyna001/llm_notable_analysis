"""Request/response contract helpers for OpenAI-compatible chat APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .errors import ResponseFormatError


@dataclass(frozen=True)
class CompletionRequest:
    """Normalized request contract for chat-completions endpoint.

    Attributes:
        model: Model name to target on the endpoint.
        prompt: Prompt text submitted to the model.
        max_tokens: Maximum number of response tokens to generate.
        temperature: Sampling temperature.
    """

    model: str
    prompt: str
    max_tokens: int
    temperature: float = 0.0

    def to_payload(self) -> Dict[str, Any]:
        """Serialize request fields into chat-completions payload format.

        Returns:
            JSON-serializable payload dictionary.
        """
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": self.prompt,
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }


@dataclass(frozen=True)
class CompletionResult:
    """Normalized SDK return payload for callers.

    Attributes:
        text: Extracted completion text.
        raw_response: Parsed response payload from the endpoint.
        latency_seconds: End-to-end request latency in seconds.
        attempts: Number of attempts used.
        correlation_id: Correlation identifier applied to the request.
        status_code: Final HTTP status code.
    """

    text: str
    raw_response: Dict[str, Any]
    latency_seconds: float
    attempts: int
    correlation_id: str
    status_code: int


def parse_completion_text(response_json: Dict[str, Any]) -> str:
    """Extract completion text from OpenAI-compatible response shape.

    Args:
        response_json: Parsed JSON response from completion API.

    Returns:
        Extracted completion text.

    Raises:
        ResponseFormatError: If expected completion fields are missing or invalid.
    """
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


def parse_retry_after_seconds(headers: Optional[Dict[str, str]]) -> Optional[float]:
    """Parse Retry-After header when present.

    Args:
        headers: Optional response headers dictionary.

    Returns:
        Parsed retry delay in seconds, or `None` when missing/invalid.
    """
    if not headers:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed
