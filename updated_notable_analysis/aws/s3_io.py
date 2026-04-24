"""S3 JSON transport seam for the AWS deployment wrapper."""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol

from updated_notable_analysis.core.validators import require_non_empty_string


class S3JsonTransport(Protocol):
    """Protocol for AWS wrapper JSON reads and writes to S3."""

    def get_json_object(self, *, bucket: str, key: str) -> Mapping[str, Any]:
        """Load and return one JSON object from S3."""

    def put_json_object(self, *, bucket: str, key: str, payload: Mapping[str, Any]) -> None:
        """Write one JSON object to S3."""


class Boto3S3JsonTransport:
    """Boto3-backed S3 JSON transport implementation."""

    def __init__(self, s3_client: Any | None = None) -> None:
        """Initialize a transport with an optional injected boto3 client."""
        if s3_client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    "boto3 is required for AWS S3 transport but is not installed."
                ) from exc
            s3_client = boto3.client("s3")
        self._s3_client = s3_client

    def get_json_object(self, *, bucket: str, key: str) -> Mapping[str, Any]:
        """Load and validate one JSON object from S3."""
        bucket = require_non_empty_string(bucket, "bucket")
        key = require_non_empty_string(key, "key")
        response = self._s3_client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read()
        try:
            decoded_body = body.decode("utf-8")
            payload = json.loads(decoded_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"S3 object s3://{bucket}/{key} did not contain valid UTF-8 JSON."
            ) from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"S3 object s3://{bucket}/{key} must contain a JSON object.")
        return dict(payload)

    def put_json_object(self, *, bucket: str, key: str, payload: Mapping[str, Any]) -> None:
        """Serialize and write one JSON object to S3."""
        bucket = require_non_empty_string(bucket, "bucket")
        key = require_non_empty_string(key, "key")
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self._s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=encoded,
            ContentType="application/json",
        )
