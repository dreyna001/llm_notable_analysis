from __future__ import annotations

from typing import Any

import pytest

from azure_notable_pipeline import azure_clients


class Capture:
    def __init__(self) -> None:
        self.args: tuple[Any, ...] = ()
        self.kwargs: dict[str, Any] = {}

    def __call__(self, *args: Any, **kwargs: Any) -> object:
        self.args = args
        self.kwargs = kwargs
        return object()


class CaptureConnectionString:
    calls: list[dict[str, Any]] = []

    @classmethod
    def from_connection_string(cls, **kwargs: Any) -> object:
        cls.calls.append(kwargs)
        return object()


def test_blob_client_uses_explicit_user_assigned_identity_and_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential_factory = Capture()
    blob_factory = Capture()
    monkeypatch.setenv("AZURE_CLIENT_ID", "uami-client-id")
    monkeypatch.setattr(azure_clients, "ManagedIdentityCredential", credential_factory)
    monkeypatch.setattr(azure_clients, "BlobServiceClient", blob_factory)

    result = azure_clients.blob_service_client("https://input.blob.core.usgovcloudapi.net/")

    assert result is not None
    assert credential_factory.kwargs == {"client_id": "uami-client-id"}
    assert blob_factory.kwargs["account_url"] == "https://input.blob.core.usgovcloudapi.net"
    assert blob_factory.kwargs["credential"] is not None
    assert blob_factory.kwargs["connection_timeout"] == 10
    assert blob_factory.kwargs["read_timeout"] == 60
    assert "account_key" not in blob_factory.kwargs


def test_clients_fail_closed_without_user_assigned_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)

    with pytest.raises(
        azure_clients.AzureClientConfigurationError,
        match="AZURE_CLIENT_ID is required",
    ):
        azure_clients.blob_service_client("https://input.blob.core.usgovcloudapi.net")


def test_blob_client_uses_azurite_connection_string_only_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_string = (
        "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
        "AccountKey=local-only;BlobEndpoint=http://azurite:10000/devstoreaccount1;"
        "QueueEndpoint=http://azurite:10001/devstoreaccount1"
    )
    CaptureConnectionString.calls = []
    monkeypatch.setenv("LOCAL_EMULATION", "true")
    monkeypatch.setenv("AZURITE_CONNECTION_STRING", connection_string)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.setattr(azure_clients, "BlobServiceClient", CaptureConnectionString)

    azure_clients.blob_service_client("http://azurite:10000/devstoreaccount1")

    assert CaptureConnectionString.calls == [
        {
            "conn_str": connection_string,
            "connection_timeout": 10,
            "read_timeout": 60,
            "retry_total": 2,
        }
    ]


def test_queue_client_uses_named_queue_from_azurite_connection_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_string = (
        "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
        "AccountKey=local-only;BlobEndpoint=http://azurite:10000/devstoreaccount1;"
        "QueueEndpoint=http://azurite:10001/devstoreaccount1"
    )
    CaptureConnectionString.calls = []
    monkeypatch.setenv("LOCAL_EMULATION", "true")
    monkeypatch.setenv("AZURITE_CONNECTION_STRING", connection_string)
    monkeypatch.setattr(azure_clients, "QueueClient", CaptureConnectionString)

    azure_clients.queue_client(
        "http://azurite:10001/devstoreaccount1",
        "notable-analysis-jobs",
    )

    assert CaptureConnectionString.calls[0]["conn_str"] == connection_string
    assert CaptureConnectionString.calls[0]["queue_name"] == "notable-analysis-jobs"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://192.0.2.10:10000/devstoreaccount1",
        "http://storage:10000/devstoreaccount1",
        "https://storage.example.com/devstoreaccount1",
        "http://user:password@localhost:10000/devstoreaccount1",
    ],
)
def test_local_storage_rejects_nonlocal_or_credentialed_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    monkeypatch.setenv("LOCAL_EMULATION", "true")
    monkeypatch.setenv("AZURITE_CONNECTION_STRING", "UseDevelopmentStorage=true")

    with pytest.raises(
        azure_clients.AzureClientConfigurationError,
        match="local HTTP|local Docker",
    ):
        azure_clients.blob_service_client(endpoint)


@pytest.mark.parametrize(
    "connection_string",
    [
        (
            "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
            "AccountKey=local-only;BlobEndpoint=https://storage.example.com/account"
        ),
        (
            "UseDevelopmentStorage=true;"
            "DevelopmentStorageProxyUri=https://proxy.example.com"
        ),
    ],
)
def test_azurite_connection_string_rejects_remote_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    connection_string: str,
) -> None:
    monkeypatch.setenv("LOCAL_EMULATION", "true")
    monkeypatch.setenv("AZURITE_CONNECTION_STRING", connection_string)

    with pytest.raises(
        azure_clients.AzureClientConfigurationError,
        match="local Docker hostname",
    ):
        azure_clients.blob_service_client("http://azurite:10000/devstoreaccount1")


def test_invalid_local_emulation_flag_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_EMULATION", "1")

    with pytest.raises(
        azure_clients.AzureClientConfigurationError,
        match="must be true or false",
    ):
        azure_clients.blob_service_client("https://input.blob.core.usgovcloudapi.net")


def test_azure_openai_uses_cognitive_services_entra_scope_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = object()
    provider = object()
    openai_factory = Capture()
    token_calls: list[tuple[object, str]] = []
    monkeypatch.setattr(azure_clients, "_credential", lambda: credential)
    monkeypatch.setattr(
        azure_clients,
        "get_bearer_token_provider",
        lambda value, scope: token_calls.append((value, scope)) or provider,
    )
    monkeypatch.setattr(azure_clients, "AzureOpenAI", openai_factory)

    azure_clients.azure_openai_client(
        "https://qualified.openai.azure.us",
        "2024-10-21",
    )

    assert token_calls == [
        (credential, "https://cognitiveservices.azure.us/.default")
    ]
    assert openai_factory.kwargs["azure_ad_token_provider"] is provider
    assert openai_factory.kwargs["timeout"] == 220
    assert "api_key" not in openai_factory.kwargs


def test_commercial_openai_endpoint_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_CLIENT_ID", "uami-client-id")
    with pytest.raises(
        azure_clients.AzureClientConfigurationError,
        match="Azure Government endpoint",
    ):
        azure_clients.azure_openai_client(
            "https://qualified.openai.azure.com",
            "2024-10-21",
        )


def test_cosmos_client_requests_strong_consistency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cosmos_factory = Capture()
    credential = object()
    monkeypatch.setattr(azure_clients, "_credential", lambda: credential)
    monkeypatch.setattr(azure_clients, "CosmosClient", cosmos_factory)

    azure_clients.cosmos_client("https://qualified.documents.azure.us")

    assert cosmos_factory.kwargs["credential"] is credential
    assert cosmos_factory.kwargs["consistency_level"] == "Strong"
    assert cosmos_factory.kwargs["connection_timeout"] == 10
    assert cosmos_factory.kwargs["request_timeout"] == 60


def test_cosmos_emulator_uses_local_endpoint_and_explicit_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cosmos_factory = Capture()
    monkeypatch.setenv("LOCAL_EMULATION", "true")
    monkeypatch.setenv("COSMOS_EMULATOR_KEY", "local-emulator-key")
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.setattr(azure_clients, "CosmosClient", cosmos_factory)

    azure_clients.cosmos_client("https://localhost:8081")

    assert cosmos_factory.kwargs["url"] == "https://localhost:8081"
    assert cosmos_factory.kwargs["credential"] == "local-emulator-key"
    assert cosmos_factory.kwargs["consistency_level"] == "Strong"


def test_cosmos_emulator_rejects_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_EMULATION", "true")
    monkeypatch.setenv("COSMOS_EMULATOR_KEY", "local-emulator-key")

    with pytest.raises(
        azure_clients.AzureClientConfigurationError,
        match="local Docker hostname",
    ):
        azure_clients.cosmos_client("https://qualified.documents.azure.us")


def test_cosmos_emulator_requires_explicit_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_EMULATION", "true")
    monkeypatch.delenv("COSMOS_EMULATOR_KEY", raising=False)

    with pytest.raises(
        azure_clients.AzureClientConfigurationError,
        match="COSMOS_EMULATOR_KEY is required",
    ):
        azure_clients.cosmos_client("https://localhost:8081")


def test_queue_and_search_names_must_be_nonblank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(azure_clients, "_credential", lambda: object())

    with pytest.raises(azure_clients.AzureClientConfigurationError):
        azure_clients.queue_client("https://output.queue.core.usgovcloudapi.net", "")
    with pytest.raises(azure_clients.AzureClientConfigurationError):
        azure_clients.azure_search_client("https://qualified.search.azure.us", "")
