"""Application-oriented Azure Blob Storage operations.

Only container/blob names and stable application values cross this boundary.
Azure SDK paging, match conditions, responses, and exceptions remain internal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from typing import Any, Iterable, Mapping

from azure.core import MatchConditions
from azure.core.exceptions import (
    AzureError,
    HttpResponseError,
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.storage.blob import ContentSettings

from .azure_clients import AzureClientConfigurationError, blob_service_client

_OPERATION_TIMEOUT_SECONDS = 60
_MAX_LIST_RESULTS = 1_000
_MAX_DELETE_BATCH = 256


class BlobStoreError(RuntimeError):
    """A Blob operation failed through the stable application boundary."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class BlobStoreConfigurationError(BlobStoreError):
    """Blob operation input or runtime configuration is invalid."""


class BlobNotFoundError(BlobStoreError):
    """The requested container or blob does not exist."""


class BlobConflictError(BlobStoreError):
    """A create-only Blob write conflicts with an existing object."""


class BlobConditionFailedError(BlobStoreError):
    """An ETag precondition did not match the current Blob version."""


class BlobStoreUnavailableError(BlobStoreError):
    """Blob Storage could not be reached or returned a retryable failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


@dataclass(frozen=True)
class BlobInfo:
    """Stable metadata for one Blob."""

    blob_name: str
    etag: str
    size_bytes: int
    last_modified: datetime | None
    content_type: str | None = None


@dataclass(frozen=True)
class BlobReadResult:
    """Blob bytes plus the version metadata observed by the download."""

    body: bytes
    info: BlobInfo


@dataclass(frozen=True)
class BlobWriteResult:
    """Version metadata returned by a successful Blob write."""

    etag: str
    last_modified: datetime | None


def _required(value: str, *, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise BlobStoreConfigurationError(f"{name} is required")
    return normalized


def _mapping_or_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _content_type(properties: Any) -> str | None:
    settings = _mapping_or_attr(properties, "content_settings")
    content_type = _mapping_or_attr(settings, "content_type")
    return str(content_type) if content_type else None


def _blob_info(properties: Any, *, fallback_name: str, body_size: int = 0) -> BlobInfo:
    raw_size = _mapping_or_attr(properties, "size", body_size)
    try:
        size_bytes = int(raw_size)
    except (TypeError, ValueError):
        size_bytes = body_size
    last_modified = _mapping_or_attr(properties, "last_modified")
    if not isinstance(last_modified, datetime):
        last_modified = None
    return BlobInfo(
        blob_name=str(_mapping_or_attr(properties, "name", fallback_name)),
        etag=str(_mapping_or_attr(properties, "etag", "") or ""),
        size_bytes=max(0, size_bytes),
        last_modified=last_modified,
        content_type=_content_type(properties),
    )


def _account_url_for(container_name: str, explicit_url: str | None) -> str:
    if explicit_url:
        return explicit_url.strip()

    input_container = os.getenv("INPUT_CONTAINER_NAME", "input").strip()
    output_container = os.getenv("OUTPUT_CONTAINER_NAME", "output").strip()
    archive_container = os.getenv("CASE_ARCHIVE_CONTAINER", output_container).strip()
    if container_name == input_container:
        setting_name = "INPUT_STORAGE_ACCOUNT_URL"
    elif container_name in {output_container, archive_container}:
        setting_name = "OUTPUT_STORAGE_ACCOUNT_URL"
    else:
        raise BlobStoreConfigurationError(
            "account_url is required for a container outside the configured input/output containers"
        )
    value = os.getenv(setting_name, "").strip()
    if not value:
        raise BlobStoreConfigurationError(f"{setting_name} is required")
    return value


def _service(
    container_name: str,
    *,
    store: Any | None,
    account_url: str | None,
) -> Any:
    if store is not None:
        return store
    try:
        return blob_service_client(_account_url_for(container_name, account_url))
    except AzureClientConfigurationError as exc:
        raise BlobStoreConfigurationError(str(exc)) from exc


def _raise_blob_error(
    exc: Exception,
    *,
    operation: str,
    container_name: str,
    blob_name: str | None = None,
) -> None:
    target = f"{container_name}/{blob_name}" if blob_name else container_name
    message = f"Blob {operation} failed for {target}"
    if isinstance(exc, ResourceNotFoundError):
        raise BlobNotFoundError(message) from exc
    if isinstance(exc, ResourceExistsError):
        raise BlobConflictError(message) from exc
    if isinstance(exc, ResourceModifiedError) or (
        isinstance(exc, HttpResponseError) and exc.status_code == 412
    ):
        raise BlobConditionFailedError(message) from exc
    if isinstance(exc, (ServiceRequestError, ServiceResponseError)):
        raise BlobStoreUnavailableError(message) from exc
    if isinstance(exc, HttpResponseError) and exc.status_code in {408, 429, 500, 502, 503, 504}:
        raise BlobStoreUnavailableError(message) from exc
    if isinstance(exc, AzureError):
        raise BlobStoreError(message) from exc
    raise exc


def read_blob_result(
    container_name: str,
    blob_name: str,
    *,
    if_match: str | None = None,
    max_bytes: int | None = None,
    store: Any | None = None,
    account_url: str | None = None,
) -> BlobReadResult:
    """Read one Blob and return bytes with its observed ETag metadata."""

    container = _required(container_name, name="container_name")
    blob = _required(blob_name, name="blob_name")
    if max_bytes is not None and (isinstance(max_bytes, bool) or max_bytes <= 0):
        raise BlobStoreConfigurationError("max_bytes must be a positive integer")
    match = str(if_match or "").strip()
    sdk_client = _service(container, store=store, account_url=account_url).get_blob_client(
        container=container,
        blob=blob,
    )
    download_kwargs: dict[str, Any] = {"timeout": _OPERATION_TIMEOUT_SECONDS}
    if match:
        download_kwargs.update(
            {
                "etag": match,
                "match_condition": MatchConditions.IfNotModified,
            }
        )
    if max_bytes is not None:
        download_kwargs["length"] = max_bytes + 1
    try:
        downloader = sdk_client.download_blob(**download_kwargs)
        body = downloader.readall()
        if not isinstance(body, bytes):
            body = bytes(body)
        if max_bytes is not None and len(body) > max_bytes:
            raise BlobStoreConfigurationError(
                f"Blob body exceeds the configured {max_bytes}-byte limit"
            )
        properties = getattr(downloader, "properties", None)
        if properties is None:
            properties = sdk_client.get_blob_properties(timeout=_OPERATION_TIMEOUT_SECONDS)
        return BlobReadResult(
            body=body,
            info=_blob_info(properties, fallback_name=blob, body_size=len(body)),
        )
    except BlobStoreError:
        raise
    except Exception as exc:
        _raise_blob_error(
            exc,
            operation="read",
            container_name=container,
            blob_name=blob,
        )
        raise AssertionError("unreachable")


def read_blob(
    container_name: str,
    blob_name: str,
    *,
    if_match: str | None = None,
    max_bytes: int | None = None,
    store: Any | None = None,
    account_url: str | None = None,
) -> bytes:
    """Read one Blob as bytes, optionally requiring an exact ETag."""

    return read_blob_result(
        container_name,
        blob_name,
        if_match=if_match,
        max_bytes=max_bytes,
        store=store,
        account_url=account_url,
    ).body


def write_blob(
    container_name: str,
    blob_name: str,
    body: bytes,
    *,
    content_type: str = "application/octet-stream",
    overwrite: bool = True,
    if_match: str | None = None,
    store: Any | None = None,
    account_url: str | None = None,
) -> BlobWriteResult:
    """Write bytes to one Blob with optional optimistic ETag concurrency."""

    container = _required(container_name, name="container_name")
    blob = _required(blob_name, name="blob_name")
    if not isinstance(body, bytes):
        raise BlobStoreConfigurationError("body must be bytes")
    normalized_content_type = _required(content_type, name="content_type")
    match = str(if_match or "").strip()
    if match and not overwrite:
        raise BlobStoreConfigurationError("if_match requires overwrite=True")
    sdk_client = _service(container, store=store, account_url=account_url).get_blob_client(
        container=container,
        blob=blob,
    )
    upload_kwargs: dict[str, Any] = {
        "overwrite": overwrite,
        "content_settings": ContentSettings(content_type=normalized_content_type),
        "timeout": _OPERATION_TIMEOUT_SECONDS,
    }
    if match:
        upload_kwargs.update(
            {
                "etag": match,
                "match_condition": MatchConditions.IfNotModified,
            }
        )
    try:
        response = sdk_client.upload_blob(body, **upload_kwargs)
        last_modified = _mapping_or_attr(response, "last_modified")
        if not isinstance(last_modified, datetime):
            last_modified = None
        return BlobWriteResult(
            etag=str(_mapping_or_attr(response, "etag", "") or ""),
            last_modified=last_modified,
        )
    except Exception as exc:
        _raise_blob_error(
            exc,
            operation="write",
            container_name=container,
            blob_name=blob,
        )
        raise AssertionError("unreachable")


def write_text_blob(
    container_name: str,
    blob_name: str,
    text: str,
    *,
    content_type: str = "text/plain; charset=utf-8",
    overwrite: bool = True,
    if_match: str | None = None,
    store: Any | None = None,
    account_url: str | None = None,
) -> BlobWriteResult:
    """Encode and write one UTF-8 text Blob."""

    if not isinstance(text, str):
        raise BlobStoreConfigurationError("text must be a string")
    return write_blob(
        container_name,
        blob_name,
        text.encode("utf-8"),
        content_type=content_type,
        overwrite=overwrite,
        if_match=if_match,
        store=store,
        account_url=account_url,
    )


def delete_blob(
    container_name: str,
    blob_name: str,
    *,
    if_match: str | None = None,
    missing_ok: bool = True,
    store: Any | None = None,
    account_url: str | None = None,
) -> None:
    """Delete one Blob, optionally requiring the caller's ETag."""

    container = _required(container_name, name="container_name")
    blob = _required(blob_name, name="blob_name")
    sdk_client = _service(container, store=store, account_url=account_url).get_blob_client(
        container=container,
        blob=blob,
    )
    kwargs: dict[str, Any] = {
        "delete_snapshots": "include",
        "timeout": _OPERATION_TIMEOUT_SECONDS,
    }
    match = str(if_match or "").strip()
    if match:
        kwargs.update(
            {
                "etag": match,
                "match_condition": MatchConditions.IfNotModified,
            }
        )
    try:
        sdk_client.delete_blob(**kwargs)
    except ResourceNotFoundError as exc:
        if not missing_ok:
            _raise_blob_error(
                exc,
                operation="delete",
                container_name=container,
                blob_name=blob,
            )
    except Exception as exc:
        _raise_blob_error(
            exc,
            operation="delete",
            container_name=container,
            blob_name=blob,
        )


def delete_blobs(
    container_name: str,
    blob_names: Iterable[str],
    *,
    missing_ok: bool = True,
    store: Any | None = None,
    account_url: str | None = None,
) -> None:
    """Delete a bounded batch of Blob names through the single-delete contract."""

    names = list(blob_names)
    if len(names) > _MAX_DELETE_BATCH:
        raise BlobStoreConfigurationError(
            f"delete_blobs accepts at most {_MAX_DELETE_BATCH} names"
        )
    service = _service(
        _required(container_name, name="container_name"),
        store=store,
        account_url=account_url,
    )
    for blob_name in names:
        delete_blob(
            container_name,
            blob_name,
            missing_ok=missing_ok,
            store=service,
        )


def list_blobs(
    container_name: str,
    *,
    prefix: str,
    limit: int,
    store: Any | None = None,
    account_url: str | None = None,
) -> list[BlobInfo]:
    """Return at most ``limit`` Blob metadata records for one prefix."""

    container = _required(container_name, name="container_name")
    normalized_prefix = str(prefix or "").strip()
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIST_RESULTS:
        raise BlobStoreConfigurationError(
            f"limit must be an integer from 1 to {_MAX_LIST_RESULTS}"
        )
    sdk_client = _service(container, store=store, account_url=account_url)
    try:
        pager = sdk_client.get_container_client(container).list_blobs(
            name_starts_with=normalized_prefix or None,
            results_per_page=limit,
            timeout=_OPERATION_TIMEOUT_SECONDS,
        )
        return [
            _blob_info(item, fallback_name="")
            for item in islice(pager, limit)
        ]
    except Exception as exc:
        _raise_blob_error(
            exc,
            operation="list",
            container_name=container,
        )
        raise AssertionError("unreachable")


__all__ = [
    "BlobConditionFailedError",
    "BlobConflictError",
    "BlobInfo",
    "BlobNotFoundError",
    "BlobReadResult",
    "BlobStoreConfigurationError",
    "BlobStoreError",
    "BlobStoreUnavailableError",
    "BlobWriteResult",
    "delete_blob",
    "delete_blobs",
    "list_blobs",
    "read_blob",
    "read_blob_result",
    "write_blob",
    "write_text_blob",
]
