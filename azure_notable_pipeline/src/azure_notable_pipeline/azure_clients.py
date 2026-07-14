"""Central constructors for keyless Azure platform SDK clients.

The deployed Function Apps use a distinct user-assigned managed identity.  This
module is the only place where SDK credentials are constructed; application
modules receive native clients or call a narrow application boundary.
"""

from __future__ import annotations

import ipaddress
import os
from typing import Any
from urllib.parse import urlparse

from anthropic import AnthropicFoundry
from azure.cosmos import CosmosClient
from azure.identity import ManagedIdentityCredential, get_bearer_token_provider
from azure.keyvault.secrets import SecretClient
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient
from openai import AzureOpenAI

_AI_FOUNDRY_SCOPE = "https://ai.azure.com/.default"
_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
_CONNECT_TIMEOUT_SECONDS = 10
_READ_TIMEOUT_SECONDS = 60
_OPENAI_TIMEOUT_SECONDS = 220
_ANTHROPIC_TIMEOUT_SECONDS = 300
_MAX_RETRIES = 2


class AzureClientConfigurationError(ValueError):
    """A native Azure client cannot be built from the runtime configuration."""


def _local_emulation_enabled() -> bool:
    """Return whether explicitly configured local service emulation is enabled."""

    value = os.getenv("LOCAL_EMULATION", "false").strip().lower()
    if value == "true":
        return True
    if value in {"", "false"}:
        return False
    raise AzureClientConfigurationError(
        "LOCAL_EMULATION must be true or false"
    )


def _require_text(value: str, *, setting_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise AzureClientConfigurationError(f"{setting_name} is required")
    return normalized


def _service_url(
    value: str,
    *,
    setting_name: str,
    required_path: str | None = None,
) -> str:
    url = _require_text(value, setting_name=setting_name).rstrip("/")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise AzureClientConfigurationError(
            f"{setting_name} must be an HTTPS service URL without userinfo, query, or fragment"
        )
    if required_path is not None:
        if parsed.path.rstrip("/") != required_path:
            raise AzureClientConfigurationError(
                f"{setting_name} must end at {required_path}"
            )
    elif parsed.path not in {"", "/"}:
        raise AzureClientConfigurationError(
            f"{setting_name} must identify the service root"
        )
    return url


def _local_service_url(value: str, *, setting_name: str) -> str:
    """Validate an emulator URL without permitting non-local network targets."""

    url = _require_text(value, setting_name=setting_name).rstrip("/")
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise AzureClientConfigurationError(
            f"{setting_name} must be a local HTTP(S) service URL without "
            "userinfo, query, or fragment"
        )

    hostname = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        # Only the repository's Compose service names and Docker Desktop host
        # gateways are accepted; arbitrary single-label names can expand via a
        # DNS search suffix to a remote host.
        is_local = (
            hostname
            in {
                "localhost",
                "host.docker.internal",
                "gateway.docker.internal",
                "azurite",
                "cosmos",
                "cosmos-emulator",
            }
        )
    else:
        is_local = address.is_loopback
    if not is_local:
        raise AzureClientConfigurationError(
            f"{setting_name} must use localhost, a loopback address, or a "
            "local Docker hostname when LOCAL_EMULATION=true"
        )
    return url


def _azurite_connection_string(*, service: str) -> str:
    connection_string = _require_text(
        os.getenv("AZURITE_CONNECTION_STRING", ""),
        setting_name="AZURITE_CONNECTION_STRING",
    )
    fields: dict[str, str] = {}
    for component in connection_string.split(";"):
        if not component:
            continue
        name, separator, value = component.partition("=")
        if not separator:
            raise AzureClientConfigurationError(
                "AZURITE_CONNECTION_STRING must be a valid storage connection string"
            )
        fields[name.strip().lower()] = value.strip()

    for endpoint_name in ("blobendpoint", "queueendpoint"):
        if fields.get(endpoint_name):
            _local_service_url(
                fields[endpoint_name],
                setting_name=(
                    f"AZURITE_CONNECTION_STRING {endpoint_name[:-8].title()}Endpoint"
                ),
            )

    if fields.get("usedevelopmentstorage", "").lower() == "true":
        proxy_uri = fields.get("developmentstorageproxyuri", "")
        if proxy_uri:
            _local_service_url(
                proxy_uri,
                setting_name=(
                    "AZURITE_CONNECTION_STRING DevelopmentStorageProxyUri"
                ),
            )
        return connection_string

    endpoint_name = f"{service.lower()}endpoint"
    _require_text(
        fields.get(endpoint_name, ""),
        setting_name=f"AZURITE_CONNECTION_STRING {service}Endpoint",
    )
    return connection_string


def _credential() -> ManagedIdentityCredential:
    client_id = _require_text(
        os.getenv("AZURE_CLIENT_ID", ""),
        setting_name="AZURE_CLIENT_ID",
    )
    return ManagedIdentityCredential(client_id=client_id)


def blob_service_client(account_url: str) -> BlobServiceClient:
    """Create a managed-identity Blob service client."""

    if _local_emulation_enabled():
        _local_service_url(account_url, setting_name="storage account URL")
        return BlobServiceClient.from_connection_string(
            conn_str=_azurite_connection_string(service="Blob"),
            connection_timeout=_CONNECT_TIMEOUT_SECONDS,
            read_timeout=_READ_TIMEOUT_SECONDS,
            retry_total=_MAX_RETRIES,
        )

    return BlobServiceClient(
        account_url=_service_url(
            account_url,
            setting_name="storage account URL",
        ),
        credential=_credential(),
        connection_timeout=_CONNECT_TIMEOUT_SECONDS,
        read_timeout=_READ_TIMEOUT_SECONDS,
        retry_total=_MAX_RETRIES,
    )


def secret_client(vault_url: str) -> SecretClient:
    """Create a managed-identity Key Vault secret client."""

    return SecretClient(
        vault_url=_service_url(vault_url, setting_name="KEY_VAULT_URI"),
        credential=_credential(),
        connection_timeout=_CONNECT_TIMEOUT_SECONDS,
        read_timeout=_READ_TIMEOUT_SECONDS,
        retry_total=_MAX_RETRIES,
    )


def anthropic_foundry_client(base_url: str) -> AnthropicFoundry:
    """Create the native Anthropic Foundry client with an Entra token provider."""

    token_provider = get_bearer_token_provider(_credential(), _AI_FOUNDRY_SCOPE)
    return AnthropicFoundry(
        base_url=_service_url(
            base_url,
            setting_name="AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL",
            required_path="/anthropic",
        ),
        # AnthropicFoundry otherwise reads ANTHROPIC_FOUNDRY_API_KEY from the
        # ambient environment even when an Entra provider is supplied.
        api_key="",
        azure_ad_token_provider=token_provider,
        timeout=_ANTHROPIC_TIMEOUT_SECONDS,
        max_retries=_MAX_RETRIES,
    )


def azure_openai_client(endpoint: str, api_version: str) -> AzureOpenAI:
    """Create the portal-chat/embedding Azure OpenAI client without an API key."""

    normalized_version = _require_text(
        api_version,
        setting_name="AZURE_OPENAI_API_VERSION",
    )
    token_provider = get_bearer_token_provider(
        _credential(),
        _COGNITIVE_SERVICES_SCOPE,
    )
    return AzureOpenAI(
        azure_endpoint=_service_url(
            endpoint,
            setting_name="AZURE_OPENAI_ENDPOINT",
        ),
        api_version=normalized_version,
        azure_ad_token_provider=token_provider,
        timeout=_OPENAI_TIMEOUT_SECONDS,
        max_retries=_MAX_RETRIES,
    )


def azure_search_client(endpoint: str, index_name: str) -> SearchClient:
    """Create a managed-identity Azure AI Search index client."""

    return SearchClient(
        endpoint=_service_url(endpoint, setting_name="AZURE_SEARCH_ENDPOINT"),
        index_name=_require_text(index_name, setting_name="Azure Search index name"),
        credential=_credential(),
        connection_timeout=_CONNECT_TIMEOUT_SECONDS,
        read_timeout=_READ_TIMEOUT_SECONDS,
        retry_total=_MAX_RETRIES,
    )


def cosmos_client(endpoint: str) -> CosmosClient:
    """Create the strongly-consistent, managed-identity Cosmos client."""

    if _local_emulation_enabled():
        return CosmosClient(
            url=_local_service_url(endpoint, setting_name="COSMOS_ENDPOINT"),
            credential=_require_text(
                os.getenv("COSMOS_EMULATOR_KEY", ""),
                setting_name="COSMOS_EMULATOR_KEY",
            ),
            consistency_level="Strong",
            connection_timeout=_CONNECT_TIMEOUT_SECONDS,
            request_timeout=_READ_TIMEOUT_SECONDS,
        )

    return CosmosClient(
        url=_service_url(endpoint, setting_name="COSMOS_ENDPOINT"),
        credential=_credential(),
        consistency_level="Strong",
        connection_timeout=_CONNECT_TIMEOUT_SECONDS,
        request_timeout=_READ_TIMEOUT_SECONDS,
    )


def queue_client(account_url: str, queue_name: str) -> QueueClient:
    """Create a managed-identity Storage Queue client."""

    normalized_queue_name = _require_text(queue_name, setting_name="queue name")
    if _local_emulation_enabled():
        _local_service_url(account_url, setting_name="storage account URL")
        return QueueClient.from_connection_string(
            conn_str=_azurite_connection_string(service="Queue"),
            queue_name=normalized_queue_name,
            connection_timeout=_CONNECT_TIMEOUT_SECONDS,
            read_timeout=_READ_TIMEOUT_SECONDS,
            retry_total=_MAX_RETRIES,
        )

    return QueueClient(
        account_url=_service_url(
            account_url,
            setting_name="storage account URL",
        ),
        queue_name=normalized_queue_name,
        credential=_credential(),
        connection_timeout=_CONNECT_TIMEOUT_SECONDS,
        read_timeout=_READ_TIMEOUT_SECONDS,
        retry_total=_MAX_RETRIES,
    )


__all__ = [
    "AzureClientConfigurationError",
    "anthropic_foundry_client",
    "azure_openai_client",
    "azure_search_client",
    "blob_service_client",
    "cosmos_client",
    "queue_client",
    "secret_client",
]
