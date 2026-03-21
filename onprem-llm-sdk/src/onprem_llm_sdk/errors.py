"""Custom exception types for SDK consumers."""

from __future__ import annotations


class SDKError(Exception):
    """Base exception for SDK errors."""


class ConfigError(SDKError):
    """Raised when SDK configuration is invalid."""


class ConcurrencyLimitError(SDKError):
    """Raised when inflight request guard cannot be acquired."""


class TransportError(SDKError):
    """Raised for network/transport failures to the LLM endpoint."""


class RequestTimeoutError(TransportError):
    """Raised when a request times out."""


class ResponseFormatError(SDKError):
    """Raised when endpoint response shape is incompatible with the contract."""


class ClientRequestError(SDKError):
    """Raised for non-retryable 4xx responses from the endpoint."""

    def __init__(self, message: str, *, status_code: int, response_body: str = "") -> None:
        """Initialize client request error details.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code.
            response_body: Optional truncated response body.
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class RateLimitError(SDKError):
    """Raised for retryable 429 responses from the endpoint."""

    def __init__(self, message: str, *, status_code: int = 429, response_body: str = "") -> None:
        """Initialize rate-limit error details.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code (defaults to 429).
            response_body: Optional truncated response body.
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class ServerError(SDKError):
    """Raised for retryable/non-retryable 5xx responses from the endpoint."""

    def __init__(self, message: str, *, status_code: int, response_body: str = "") -> None:
        """Initialize server error details.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code.
            response_body: Optional truncated response body.
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
