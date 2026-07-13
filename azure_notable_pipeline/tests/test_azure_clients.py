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


def test_blob_client_uses_explicit_user_assigned_identity_and_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential_factory = Capture()
    blob_factory = Capture()
    monkeypatch.setenv("AZURE_CLIENT_ID", "uami-client-id")
    monkeypatch.setattr(azure_clients, "ManagedIdentityCredential", credential_factory)
    monkeypatch.setattr(azure_clients, "BlobServiceClient", blob_factory)

    result = azure_clients.blob_service_client("https://input.blob.core.windows.net/")

    assert result is not None
    assert credential_factory.kwargs == {"client_id": "uami-client-id"}
    assert blob_factory.kwargs["account_url"] == "https://input.blob.core.windows.net"
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
        azure_clients.blob_service_client("https://input.blob.core.windows.net")


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
        "https://qualified.openai.azure.com",
        "2024-10-21",
    )

    assert token_calls == [
        (credential, "https://cognitiveservices.azure.com/.default")
    ]
    assert openai_factory.kwargs["azure_ad_token_provider"] is provider
    assert openai_factory.kwargs["timeout"] == 220
    assert "api_key" not in openai_factory.kwargs


def test_anthropic_foundry_uses_ai_entra_scope_and_native_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = object()
    provider = object()
    foundry_factory = Capture()
    token_calls: list[tuple[object, str]] = []
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "ambient-key-must-not-be-used")
    monkeypatch.setattr(azure_clients, "_credential", lambda: credential)
    monkeypatch.setattr(
        azure_clients,
        "get_bearer_token_provider",
        lambda value, scope: token_calls.append((value, scope)) or provider,
    )
    monkeypatch.setattr(azure_clients, "AnthropicFoundry", foundry_factory)

    azure_clients.anthropic_foundry_client(
        "https://qualified.services.ai.azure.com/anthropic/"
    )

    assert token_calls == [(credential, "https://ai.azure.com/.default")]
    assert foundry_factory.kwargs["base_url"].endswith("/anthropic")
    assert foundry_factory.kwargs["azure_ad_token_provider"] is provider
    assert foundry_factory.kwargs["api_key"] == ""


def test_anthropic_foundry_rejects_operation_url() -> None:
    with pytest.raises(
        azure_clients.AzureClientConfigurationError,
        match="must end at /anthropic",
    ):
        azure_clients._service_url(
            "https://qualified.services.ai.azure.com/anthropic/v1/messages",
            setting_name="AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL",
            required_path="/anthropic",
        )


def test_cosmos_client_requests_strong_consistency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cosmos_factory = Capture()
    credential = object()
    monkeypatch.setattr(azure_clients, "_credential", lambda: credential)
    monkeypatch.setattr(azure_clients, "CosmosClient", cosmos_factory)

    azure_clients.cosmos_client("https://qualified.documents.azure.com")

    assert cosmos_factory.kwargs["credential"] is credential
    assert cosmos_factory.kwargs["consistency_level"] == "Strong"
    assert cosmos_factory.kwargs["connection_timeout"] == 10
    assert cosmos_factory.kwargs["request_timeout"] == 60


def test_queue_and_search_names_must_be_nonblank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(azure_clients, "_credential", lambda: object())

    with pytest.raises(azure_clients.AzureClientConfigurationError):
        azure_clients.queue_client("https://output.queue.core.windows.net", "")
    with pytest.raises(azure_clients.AzureClientConfigurationError):
        azure_clients.azure_search_client("https://qualified.search.windows.net", "")
