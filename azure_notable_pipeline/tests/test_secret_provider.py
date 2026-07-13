from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from azure.core.exceptions import ResourceNotFoundError

from azure_notable_pipeline import secret_provider


class FakeProvider:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_secret(self, name: str, **kwargs: Any) -> SimpleNamespace:
        self.calls.append((name, kwargs))
        return SimpleNamespace(value=self.value)


def test_read_secret_returns_native_value_without_secret_string_wrapper() -> None:
    provider = FakeProvider("plain-token")

    value = secret_provider.read_secret("splunk-api-token", provider=provider)

    assert value == "plain-token"
    assert provider.calls == [
        ("splunk-api-token", {"version": None, "timeout": 30})
    ]


def test_read_secret_json_validates_object_and_required_fields() -> None:
    provider = FakeProvider('{"token":"abc","tenant":"soc"}')

    value = secret_provider.read_secret_json(
        "splunk-api-token",
        required_fields=("token", "tenant"),
        provider=provider,
    )

    assert value == {"token": "abc", "tenant": "soc"}

    with pytest.raises(secret_provider.SecretValueError, match="missing required"):
        secret_provider.read_secret_json(
            "splunk-api-token",
            required_fields=("username",),
            provider=provider,
        )


def test_read_secret_field_requires_nonempty_string_semantics() -> None:
    assert (
        secret_provider.read_secret_field(
            "splunk-api-token",
            field="token",
            fallback_fields=("api_token",),
            provider=FakeProvider('{"token":" abc "}'),
        )
        == "abc"
    )
    with pytest.raises(secret_provider.SecretValueError, match="non-empty string"):
        secret_provider.read_secret_field(
            "splunk-api-token",
            field="token",
            provider=FakeProvider('{"token":42}'),
        )


def test_read_secret_field_supports_explicit_plain_text_contract() -> None:
    provider = FakeProvider("plain-token")

    assert secret_provider.read_secret_field(
        "splunk-api-token",
        field="token",
        provider=provider,
    ) == "plain-token"
    with pytest.raises(secret_provider.SecretValueError, match="JSON object"):
        secret_provider.read_secret_field(
            "splunk-api-token",
            field="token",
            allow_plain_text=False,
            provider=provider,
        )


def test_secret_name_and_empty_values_fail_closed() -> None:
    with pytest.raises(secret_provider.SecretConfigurationError):
        secret_provider.read_secret("invalid_name", provider=FakeProvider("x"))
    with pytest.raises(secret_provider.SecretValueError, match="non-empty"):
        secret_provider.read_secret("valid-name", provider=FakeProvider("  "))


def test_missing_secret_is_translated_to_stable_error() -> None:
    class MissingProvider:
        def get_secret(self, *_args: Any, **_kwargs: Any) -> None:
            raise ResourceNotFoundError("missing")

    with pytest.raises(secret_provider.SecretNotFoundError):
        secret_provider.read_secret("missing-secret", provider=MissingProvider())
