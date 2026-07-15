from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError

from azure_notable_pipeline import blob_store


NOW = datetime(2026, 7, 10, 12, 34, 56, tzinfo=UTC)


class FakeDownloader:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.properties = SimpleNamespace(
            name="incoming/finding.json",
            etag='"etag-1"',
            size=len(body),
            last_modified=NOW,
            content_settings=SimpleNamespace(content_type="application/json"),
        )

    def readall(self) -> bytes:
        return self._body


class FakeBlobClient:
    def __init__(self, body: bytes = b"payload") -> None:
        self.body = body
        self.download_kwargs: dict[str, Any] | None = None
        self.upload_args: tuple[Any, ...] | None = None
        self.upload_kwargs: dict[str, Any] | None = None
        self.delete_kwargs: dict[str, Any] | None = None

    def download_blob(self, **kwargs: Any) -> FakeDownloader:
        self.download_kwargs = kwargs
        return FakeDownloader(self.body)

    def upload_blob(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.upload_args = args
        self.upload_kwargs = kwargs
        return {"etag": '"etag-2"', "last_modified": NOW}

    def delete_blob(self, **kwargs: Any) -> None:
        self.delete_kwargs = kwargs


class FakeContainerClient:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.kwargs: dict[str, Any] | None = None

    def list_blobs(self, **kwargs: Any):
        self.kwargs = kwargs
        return iter(self.items)


class FakeBlobService:
    def __init__(self, *, blob: FakeBlobClient | None = None, items: list[Any] | None = None):
        self.blob = blob or FakeBlobClient()
        self.container = FakeContainerClient(items or [])
        self.blob_calls: list[dict[str, str]] = []

    def get_blob_client(self, **kwargs: str) -> FakeBlobClient:
        self.blob_calls.append(kwargs)
        return self.blob

    def get_container_client(self, _container: str) -> FakeContainerClient:
        return self.container


def test_read_blob_returns_bytes_and_observed_etag() -> None:
    service = FakeBlobService()

    result = blob_store.read_blob_result(
        "input",
        "incoming/finding.json",
        if_match='"etag-1"',
        max_bytes=100,
        store=service,
    )

    assert result.body == b"payload"
    assert result.info.etag == '"etag-1"'
    assert result.info.size_bytes == 7
    assert result.info.content_type == "application/json"
    assert service.blob.download_kwargs == {
        "timeout": 60,
        "etag": '"etag-1"',
        "match_condition": MatchConditions.IfNotModified,
        "length": 101,
        "offset": 0,
    }


def test_read_blob_enforces_application_size_bound() -> None:
    service = FakeBlobService(blob=FakeBlobClient(body=b"too-large"))

    with pytest.raises(blob_store.BlobStoreConfigurationError, match="exceeds"):
        blob_store.read_blob("input", "incoming/x", max_bytes=3, store=service)


def test_write_blob_uses_content_type_etag_and_returns_native_version_metadata() -> None:
    service = FakeBlobService()

    result = blob_store.write_blob(
        "output",
        "reports/finding.json",
        b"{}",
        content_type="application/json",
        if_match='"etag-1"',
        store=service,
    )

    assert result.etag == '"etag-2"'
    assert result.last_modified == NOW
    assert service.blob.upload_args == (b"{}",)
    assert service.blob.upload_kwargs["overwrite"] is True
    assert service.blob.upload_kwargs["etag"] == '"etag-1"'
    assert service.blob.upload_kwargs["match_condition"] == MatchConditions.IfNotModified
    assert service.blob.upload_kwargs["content_settings"].content_type == "application/json"


def test_list_blobs_is_bounded_and_returns_blob_metadata() -> None:
    items = [
        SimpleNamespace(name=f"cases/{index}.json", etag=f'e{index}', size=index, last_modified=NOW)
        for index in range(5)
    ]
    service = FakeBlobService(items=items)

    result = blob_store.list_blobs(
        "output",
        prefix="cases/",
        limit=2,
        store=service,
    )

    assert [item.blob_name for item in result] == ["cases/0.json", "cases/1.json"]
    assert service.container.kwargs == {
        "name_starts_with": "cases/",
        "results_per_page": 2,
        "timeout": 60,
    }


def test_list_and_delete_reject_unbounded_requests() -> None:
    service = FakeBlobService()

    with pytest.raises(blob_store.BlobStoreConfigurationError, match="limit"):
        blob_store.list_blobs("output", prefix="", limit=1001, store=service)
    with pytest.raises(blob_store.BlobStoreConfigurationError, match="at most 256"):
        blob_store.delete_blobs(
            "output",
            [f"cases/{index}" for index in range(257)],
            store=service,
        )


def test_delete_blob_uses_etag_and_can_fail_on_missing() -> None:
    service = FakeBlobService()

    blob_store.delete_blob(
        "output",
        "cases/1.json",
        if_match='"etag-1"',
        store=service,
    )

    assert service.blob.delete_kwargs["etag"] == '"etag-1"'
    assert service.blob.delete_kwargs["match_condition"] == MatchConditions.IfNotModified

    class MissingBlob(FakeBlobClient):
        def delete_blob(self, **_kwargs: Any) -> None:
            raise ResourceNotFoundError("missing")

    with pytest.raises(blob_store.BlobNotFoundError):
        blob_store.delete_blob(
            "output",
            "missing",
            missing_ok=False,
            store=FakeBlobService(blob=MissingBlob()),
        )


def test_default_store_selects_account_by_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeBlobService()
    calls: list[str] = []
    monkeypatch.setenv("INPUT_CONTAINER_NAME", "input")
    monkeypatch.setenv("INPUT_STORAGE_ACCOUNT_URL", "https://input.blob.core.windows.net")
    monkeypatch.setattr(
        blob_store,
        "blob_service_client",
        lambda url: calls.append(url) or service,
    )

    assert blob_store.read_blob("input", "incoming/finding.json") == b"payload"
    assert calls == ["https://input.blob.core.windows.net"]
