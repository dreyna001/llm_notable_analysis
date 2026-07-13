"""Strict internal contract between Blob intake and analyzer queue wrappers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


ANALYZER_JOB_SCHEMA_VERSION = 1
ANALYZER_JOB_KEYS = frozenset(
    {
        "schema_version",
        "container_name",
        "blob_name",
        "etag",
        "size_bytes",
        "last_modified",
    }
)
_RFC3339_UTC_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)


def _required_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _validate_utc_timestamp(value: object) -> str:
    timestamp = _required_string(value, field_name="last_modified")
    if not _RFC3339_UTC_PATTERN.fullmatch(timestamp):
        raise ValueError("last_modified must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("last_modified must be an RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("last_modified must be an RFC 3339 UTC timestamp")
    return timestamp


@dataclass(frozen=True)
class AnalyzerQueueJob:
    """Versioned analyzer queue job authored by the application."""

    schema_version: int
    container_name: str
    blob_name: str
    etag: str
    size_bytes: int
    last_modified: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise ValueError("schema_version must be integer 1")
        _required_string(self.container_name, field_name="container_name")
        _required_string(self.blob_name, field_name="blob_name")
        _required_string(self.etag, field_name="etag")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ValueError("size_bytes must be a non-negative integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        _validate_utc_timestamp(self.last_modified)

    @classmethod
    def create(
        cls,
        *,
        container_name: str,
        blob_name: str,
        etag: str,
        size_bytes: int,
        last_modified: str,
    ) -> AnalyzerQueueJob:
        return cls(
            schema_version=ANALYZER_JOB_SCHEMA_VERSION,
            container_name=container_name,
            blob_name=blob_name,
            etag=etag,
            size_bytes=size_bytes,
            last_modified=last_modified,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AnalyzerQueueJob:
        if not isinstance(value, Mapping):
            raise ValueError("analyzer job must be a JSON object")
        actual_keys = frozenset(value.keys())
        if actual_keys != ANALYZER_JOB_KEYS:
            missing = sorted(str(key) for key in ANALYZER_JOB_KEYS - actual_keys)
            extra = sorted(str(key) for key in actual_keys - ANALYZER_JOB_KEYS)
            details = []
            if missing:
                details.append(f"missing fields: {', '.join(missing)}")
            if extra:
                details.append(f"extra fields: {', '.join(extra)}")
            raise ValueError("invalid analyzer job fields (" + "; ".join(details) + ")")
        return cls(**dict(value))

    @classmethod
    def from_json(cls, payload: str | bytes) -> AnalyzerQueueJob:
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("analyzer job must be valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("analyzer job must be a JSON object")
        return cls.from_mapping(decoded)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))
