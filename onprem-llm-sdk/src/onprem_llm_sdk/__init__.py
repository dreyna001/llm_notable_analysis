"""Public SDK interface."""

from .client import VLLMClient
from .config import SDKConfig
from .contracts import CompletionResult
from .errors import (
    ClientRequestError,
    ConfigError,
    RateLimitError,
    RequestTimeoutError,
    ResponseFormatError,
    SDKError,
    ServerError,
    TransportError,
)

__all__ = [
    "VLLMClient",
    "SDKConfig",
    "CompletionResult",
    "SDKError",
    "ConfigError",
    "TransportError",
    "RequestTimeoutError",
    "ResponseFormatError",
    "ClientRequestError",
    "RateLimitError",
    "ServerError",
]

__version__ = "0.1.0"

