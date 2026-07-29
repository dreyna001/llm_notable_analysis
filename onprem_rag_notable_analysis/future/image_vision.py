"""Optional loopback-only OpenAI-compatible vision descriptions."""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

STATUS_VISION_DESCRIBED = "vision_described"
STATUS_VISION_DISABLED = "vision_disabled"
STATUS_VISION_NOT_CONFIGURED = "vision_not_configured"
STATUS_VISION_EMPTY_RESPONSE = "vision_empty_response"
STATUS_VISION_FAILED = "vision_failed"
STATUS_VISION_PARTIAL = "vision_partial"
STATUS_VISION_ENDPOINT_NOT_LOOPBACK = "vision_endpoint_not_loopback"

HttpClient = Callable[[str, bytes, dict[str, str], float], bytes]
_RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    urllib_error.URLError,
    ConnectionError,
    OSError,
)


@dataclass(frozen=True)
class ImageVisionConfig:
    """Loopback vision gateway settings constructed by callers."""

    enabled: bool = False
    api_base: str = ""
    model: str = ""
    api_key: str = ""
    timeout_seconds: float = 30.0
    max_tokens: int = 400
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")


@dataclass(frozen=True)
class ImageVisionResult:
    """Structured output from ``describe_image_with_vision``."""

    status: str
    description: str | None
    error_message: str | None = None


def _collapse_ws(text: str) -> str:
    return " ".join((text or "").split())


def _is_loopback_host(hostname: str) -> bool:
    normalized = (hostname or "").strip().lower().strip("[]")
    if not normalized:
        return False
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    if normalized.startswith("127."):
        return True
    return False


def _validate_loopback_api_base(api_base: str) -> bool:
    parsed = urllib_parse.urlparse(api_base.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    return _is_loopback_host(parsed.hostname or "")


def _build_data_url(content_type: str, image_bytes: bytes) -> str:
    normalized_type = (content_type or "application/octet-stream").split(";", 1)[0].strip()
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{normalized_type};base64,{encoded}"


def _default_http_client(url: str, payload: bytes, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib_request.Request(url, data=payload, headers=headers, method="POST")
    with urllib_request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _parse_description(response_bytes: bytes) -> tuple[str | None, str]:
    try:
        parsed = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, STATUS_VISION_FAILED

    choices = parsed.get("choices") or []
    if not choices:
        return None, STATUS_VISION_EMPTY_RESPONSE
    message = choices[0].get("message") or {}
    content = _collapse_ws(str(message.get("content") or ""))
    if not content:
        return None, STATUS_VISION_EMPTY_RESPONSE
    return content, STATUS_VISION_DESCRIBED


def describe_image_with_vision(
    *,
    image_bytes: bytes,
    content_type: str,
    config: ImageVisionConfig,
    http_client: HttpClient | None = None,
) -> ImageVisionResult:
    """Describe sanitized image bytes via a loopback OpenAI-compatible endpoint."""
    if not config.enabled:
        return ImageVisionResult(status=STATUS_VISION_DISABLED, description=None)

    api_base = (config.api_base or "").strip().rstrip("/")
    model = (config.model or "").strip()
    if not api_base or not model:
        return ImageVisionResult(status=STATUS_VISION_NOT_CONFIGURED, description=None)

    if not _validate_loopback_api_base(api_base):
        return ImageVisionResult(
            status=STATUS_VISION_ENDPOINT_NOT_LOOPBACK,
            description=None,
            error_message="api_base must resolve to localhost or loopback",
        )

    if not image_bytes:
        return ImageVisionResult(
            status=STATUS_VISION_FAILED,
            description=None,
            error_message="image_bytes must not be empty",
        )

    data_url = _build_data_url(content_type, image_bytes)
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Describe this image for a security operations analyst. "
                            "State only what is visible. Do not infer intent or malware."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": int(config.max_tokens),
    }
    payload = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = (config.api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{api_base}/chat/completions"
    client = http_client or _default_http_client
    attempts = config.max_retries + 1
    last_error: str | None = None

    for attempt in range(attempts):
        try:
            response_bytes = client(url, payload, headers, config.timeout_seconds)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_error = exc.__class__.__name__
            if attempt >= attempts - 1:
                logger.warning("Vision request failed after retries: %s", last_error)
                return ImageVisionResult(
                    status=STATUS_VISION_FAILED,
                    description=None,
                    error_message=last_error,
                )
            time.sleep(config.retry_backoff_seconds * (attempt + 1))
            continue
        except Exception as exc:
            logger.warning("Vision request failed: %s", exc.__class__.__name__)
            return ImageVisionResult(
                status=STATUS_VISION_FAILED,
                description=None,
                error_message=exc.__class__.__name__,
            )

        description, status = _parse_description(response_bytes)
        if status == STATUS_VISION_DESCRIBED and description:
            return ImageVisionResult(status=status, description=description)
        return ImageVisionResult(status=status, description=None)

    return ImageVisionResult(
        status=STATUS_VISION_FAILED,
        description=None,
        error_message=last_error,
    )
