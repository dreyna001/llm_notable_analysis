"""Request/response contract helpers for OpenAI-compatible completion APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .errors import ResponseFormatError


@dataclass(frozen=True)
class CompletionRequest:
    """Normalized request contract for completions endpoint."""

    model: str
    prompt: str
    max_tokens: int
    temperature: float = 0.0

    def to_payload(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "prompt": self.prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }


@dataclass(frozen=True)
class CompletionResult:
    """Normalized SDK return payload for callers."""

    text: str
    raw_response: Dict[str, Any]
    latency_seconds: float
    attempts: int
    correlation_id: str
    status_code: int


def parse_completion_text(response_json: Dict[str, Any]) -> str:
    """Extract completion text from OpenAI-compatible response shape."""
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
    """Parse Retry-After header when present."""
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

