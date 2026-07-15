"""Small SigV4 HTTP adapter for a VPC-only OpenSearch Service domain."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import requests
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth

from .aws_clients import aws_credentials

_INDEX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")


class OpenSearchError(RuntimeError):
    """Raised when an OpenSearch request fails or returns bulk errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OpenSearchResponse:
    """Normalized response returned by the adapter."""

    status_code: int
    payload: Any
    headers: Mapping[str, str]


class OpenSearchClient:
    """Transport and REST primitives; query policy lives in retrieval modules."""

    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        service: str = "es",
        timeout_seconds: int = 30,
        credentials: Any | None = None,
        session: Any | None = None,
    ) -> None:
        parsed = urlparse(endpoint.strip())
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("OPENSEARCH_ENDPOINT must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OPENSEARCH_ENDPOINT cannot contain credentials or query data")
        self.endpoint = endpoint.rstrip("/")
        self.region = region.strip()
        self.service = service.strip() or "es"
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.credentials = credentials
        self._session = session or requests.Session()

    @classmethod
    def from_config(cls, config: Any) -> "OpenSearchClient":
        """Build the adapter using optional Config attributes or environment values."""

        import os

        endpoint = str(getattr(config, "OPENSEARCH_ENDPOINT", "") or os.getenv("OPENSEARCH_ENDPOINT", ""))
        region = str(
            getattr(config, "OPENSEARCH_REGION", "")
            or os.getenv("OPENSEARCH_REGION")
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-gov-east-1"
        )
        service = str(
            getattr(config, "OPENSEARCH_SERVICE", "")
            or os.getenv("OPENSEARCH_SERVICE")
            or "es"
        )
        timeout = int(
            getattr(config, "OPENSEARCH_TIMEOUT_SECONDS", 0)
            or os.getenv("OPENSEARCH_TIMEOUT_SECONDS", "30")
        )
        return cls(endpoint=endpoint, region=region, service=service, timeout_seconds=timeout)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> OpenSearchResponse:
        """Send one signed request and normalize its response."""

        if not path.startswith("/") or ".." in path.split("/"):
            raise ValueError("OpenSearch request path must be absolute and normalized")
        url = f"{self.endpoint}{path}"
        payload = body.encode("utf-8") if isinstance(body, str) else body
        request_headers = {"Accept": "application/json", **(headers or {})}
        credentials = self.credentials or aws_credentials()
        if credentials is None:
            raise OpenSearchError("AWS credentials are required for OpenSearch SigV4 requests")
        frozen = credentials.get_frozen_credentials() if hasattr(credentials, "get_frozen_credentials") else credentials
        signed = AWSRequest(
            method=method.upper(),
            url=url,
            data=payload,
            headers=request_headers,
        )
        SigV4Auth(frozen, self.service, self.region).add_auth(signed)
        response = self._session.request(
            method.upper(),
            url,
            data=payload,
            headers=dict(signed.headers),
            timeout=self.timeout_seconds,
        )
        raw = response.text or ""
        try:
            parsed = response.json() if raw else {}
        except (ValueError, json.JSONDecodeError):
            parsed = raw
        normalized = OpenSearchResponse(
            status_code=int(response.status_code),
            payload=parsed,
            headers=dict(response.headers),
        )
        if normalized.status_code >= 400:
            raise OpenSearchError(
                f"OpenSearch request failed with status {normalized.status_code}",
                status_code=normalized.status_code,
            )
        return normalized

    def ensure_vector_index(self, *, index: str, dimensions: int) -> None:
        """Create the bounded k-NN mapping once; tolerate a concurrent creator."""

        _validate_index(index)
        try:
            self.request("HEAD", f"/{index}")
            return
        except OpenSearchError as exc:
            if exc.status_code != 404:
                raise

        mapping = {
            "settings": {"index": {"knn": True}},
            "mappings": {
                "dynamic": True,
                "properties": {
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": max(1, int(dimensions)),
                    },
                    "search_text": {"type": "text"},
                    "text": {"type": "text"},
                    **{
                        field: {
                            "type": "text",
                            "fields": {"keyword": {"type": "keyword", "ignore_above": 1024}},
                        }
                        for field in (
                            "tenant_id",
                            "corpus_id",
                            "case_id",
                            "source_key",
                        )
                    },
                    "active": {"type": "boolean"},
                },
            },
        }
        try:
            self.request(
                "PUT",
                f"/{index}",
                body=json.dumps(mapping, separators=(",", ":")),
                headers={"Content-Type": "application/json"},
            )
        except OpenSearchError as exc:
            if exc.status_code != 400:
                raise
            self.request("HEAD", f"/{index}")

    def search(self, *, index: str, query: dict[str, Any], size: int) -> dict[str, Any]:
        """Execute a bounded search request."""

        _validate_index(index)
        response = self.request(
            "POST",
            f"/{index}/_search",
            body=json.dumps({"size": max(1, int(size)), **query}, separators=(",", ":")),
            headers={"Content-Type": "application/json"},
        )
        if not isinstance(response.payload, dict):
            raise OpenSearchError("OpenSearch search response must be a JSON object")
        return response.payload

    def bulk(self, *, index: str, actions: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """Index or update documents using bounded NDJSON bulk actions."""

        _validate_index(index)
        lines: list[str] = []
        for action in actions:
            operation = str(action.get("operation", "index"))
            document_id = str(action.get("id", "")).strip()
            if not document_id:
                raise ValueError("OpenSearch bulk action requires an id")
            metadata = {operation: {"_index": index, "_id": document_id}}
            lines.append(json.dumps(metadata, separators=(",", ":")))
            if operation in {"index", "create"}:
                document = action.get("document")
                if not isinstance(document, dict):
                    raise ValueError("OpenSearch index action requires a document")
                lines.append(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
            elif operation == "update":
                document = action.get("document")
                if not isinstance(document, dict):
                    raise ValueError("OpenSearch update action requires a document")
                lines.append(json.dumps({"doc": document}, ensure_ascii=False, separators=(",", ":")))
            elif operation != "delete":
                raise ValueError(f"unsupported OpenSearch bulk operation: {operation}")
        if not lines:
            return {"errors": False, "items": []}
        response = self.request(
            "POST",
            "/_bulk",
            body="\n".join(lines) + "\n",
            headers={"Content-Type": "application/x-ndjson"},
        )
        if not isinstance(response.payload, dict):
            raise OpenSearchError("OpenSearch bulk response must be a JSON object")
        if response.payload.get("errors"):
            raise OpenSearchError("OpenSearch bulk request contained item errors")
        return response.payload

    def delete_by_query(self, *, index: str, query: dict[str, Any]) -> dict[str, Any]:
        """Delete documents matching an already-scoped query."""

        _validate_index(index)
        response = self.request(
            "POST",
            f"/{index}/_delete_by_query",
            body=json.dumps({"query": query}, separators=(",", ":")),
            headers={"Content-Type": "application/json"},
        )
        if not isinstance(response.payload, dict):
            raise OpenSearchError("OpenSearch delete response must be a JSON object")
        return response.payload


def _validate_index(index: str) -> None:
    if not _INDEX_RE.fullmatch(index):
        raise ValueError("OpenSearch index name is invalid")
