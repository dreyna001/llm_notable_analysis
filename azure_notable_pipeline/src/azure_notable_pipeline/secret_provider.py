"""Application-oriented Azure Key Vault secret access."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable, Mapping

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)

from .azure_clients import AzureClientConfigurationError, secret_client

_SECRET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,127}$")
_OPERATION_TIMEOUT_SECONDS = 30


class SecretProviderError(RuntimeError):
    """A stable Key Vault boundary failure."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class SecretConfigurationError(SecretProviderError):
    """The secret name or Key Vault runtime configuration is invalid."""


class SecretNotFoundError(SecretProviderError):
    """The requested Key Vault secret does not exist."""


class SecretAccessDeniedError(SecretProviderError):
    """The Function App identity cannot read the requested secret."""


class SecretValueError(SecretProviderError):
    """A secret value violates its application-level contract."""


class SecretProviderUnavailableError(SecretProviderError):
    """Key Vault could not be reached or returned a retryable response."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


def _secret_name(name: str) -> str:
    clean_name = str(name or "").strip()
    if not _SECRET_NAME_PATTERN.fullmatch(clean_name):
        raise SecretConfigurationError(
            "Key Vault secret name must contain 1-127 letters, numbers, or hyphens"
        )
    return clean_name


def _provider(provider: Any | None) -> Any:
    if provider is not None:
        return provider
    vault_url = os.getenv("KEY_VAULT_URI", "").strip()
    if not vault_url:
        raise SecretConfigurationError("KEY_VAULT_URI is required")
    try:
        return secret_client(vault_url)
    except AzureClientConfigurationError as exc:
        raise SecretConfigurationError(str(exc)) from exc


def _raise_secret_error(exc: Exception, *, name: str) -> None:
    message = f"Key Vault secret lookup failed for {name}"
    if isinstance(exc, ResourceNotFoundError):
        raise SecretNotFoundError(message) from exc
    if isinstance(exc, ClientAuthenticationError) or (
        isinstance(exc, HttpResponseError) and exc.status_code in {401, 403}
    ):
        raise SecretAccessDeniedError(message) from exc
    if isinstance(exc, (ServiceRequestError, ServiceResponseError)):
        raise SecretProviderUnavailableError(message) from exc
    if isinstance(exc, HttpResponseError) and exc.status_code in {408, 429, 500, 502, 503, 504}:
        raise SecretProviderUnavailableError(message) from exc
    if isinstance(exc, AzureError):
        raise SecretProviderError(message) from exc
    raise exc


def read_secret(
    name: str,
    *,
    version: str | None = None,
    provider: Any | None = None,
) -> str:
    """Return one non-empty Key Vault secret value as application text."""

    clean_name = _secret_name(name)
    clean_version = str(version or "").strip() or None
    try:
        result = _provider(provider).get_secret(
            clean_name,
            version=clean_version,
            timeout=_OPERATION_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        _raise_secret_error(exc, name=clean_name)
        raise AssertionError("unreachable")
    value = getattr(result, "value", result)
    if not isinstance(value, str) or not value.strip():
        raise SecretValueError(f"Key Vault secret {clean_name} must contain non-empty text")
    return value


def read_secret_json(
    name: str,
    *,
    required_fields: Iterable[str] = (),
    provider: Any | None = None,
) -> dict[str, Any]:
    """Decode one secret as a JSON object and validate required fields."""

    value = read_secret(name, provider=provider)
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SecretValueError(f"Key Vault secret {name} must contain valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SecretValueError(f"Key Vault secret {name} JSON must be an object")
    fields = tuple(str(field or "").strip() for field in required_fields)
    if any(not field for field in fields):
        raise SecretConfigurationError("required_fields cannot contain blank names")
    missing = [field for field in fields if field not in decoded]
    if missing:
        raise SecretValueError(
            f"Key Vault secret {name} JSON missing required field(s): {', '.join(missing)}"
        )
    return decoded


def read_secret_field(
    name: str,
    *,
    field: str,
    fallback_fields: Iterable[str] = (),
    allow_plain_text: bool = True,
    provider: Any | None = None,
) -> str:
    """Return one non-empty string field from a JSON or plain-text secret."""

    requested = str(field or "").strip()
    fallback = tuple(str(item or "").strip() for item in fallback_fields)
    if not requested or any(not item for item in fallback):
        raise SecretConfigurationError("secret field names cannot be blank")
    value = read_secret(name, provider=provider)
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        if allow_plain_text:
            return value
        raise SecretValueError(f"Key Vault secret {name} must contain a JSON object")
    if not isinstance(decoded, Mapping):
        raise SecretValueError(
            f"Key Vault secret {name} must be a JSON object"
            + (" or plain text" if allow_plain_text else "")
        )
    for candidate in (requested, *fallback):
        selected = decoded.get(candidate)
        if isinstance(selected, str) and selected.strip():
            return selected.strip()
    raise SecretValueError(
        f"Key Vault secret {name} JSON missing a non-empty string field: "
        + ", ".join((requested, *fallback))
    )


__all__ = [
    "SecretAccessDeniedError",
    "SecretConfigurationError",
    "SecretNotFoundError",
    "SecretProviderError",
    "SecretProviderUnavailableError",
    "SecretValueError",
    "read_secret",
    "read_secret_field",
    "read_secret_json",
]
