#!/usr/bin/env python3
"""Upload one Splunk SOAR/Phantom payload to private Azure Government Blob input."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MAX_PAYLOAD_BYTES = 1_048_576
_CONTAINER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
_GOV_BLOB_SUFFIX = ".blob.core.usgovcloudapi.net"


class ConfigurationError(ValueError):
    """The helper was given an unsafe or incomplete customer setting."""


class BlobNameCollisionError(RuntimeError):
    """A deterministic Blob name already contains different content."""


def validate_storage_account_url(value: str) -> str:
    """Require an HTTPS Azure Government Blob endpoint without URL extras."""

    url = str(value or "").strip().rstrip("/")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.hostname.casefold().endswith(_GOV_BLOB_SUFFIX)
    ):
        raise ConfigurationError(
            "storage account URL must be an HTTPS Azure Government Blob endpoint"
        )
    return url


def validate_container_name(value: str) -> str:
    """Validate a customer-provisioned Blob container name."""

    container = str(value or "").strip().lower()
    if not _CONTAINER_RE.fullmatch(container):
        raise ConfigurationError("container must be a valid Azure Blob container name")
    return container


def validate_prefix(value: str) -> str:
    """Normalize a Blob prefix and reject traversal-like path segments."""

    prefix = str(value or "").strip().strip("/")
    parts = prefix.split("/") if prefix else []
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise ConfigurationError("prefix must contain normalized Blob path segments")
    if any(_SAFE_ID_RE.search(part) for part in parts):
        raise ConfigurationError("prefix contains unsupported Blob path characters")
    return "/".join(parts)


def _candidate_finding_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("finding_id", "notable_id", "sid", "id"):
            value = str(payload.get(key, "")).strip()
            if value:
                return value
    return ""


def derive_finding_id(payload: Any, supplied: str = "") -> str:
    """Return a bounded stable identifier without trusting it as a path."""

    raw = str(supplied or "").strip() or _candidate_finding_id(payload)
    if raw:
        safe = _SAFE_ID_RE.sub("_", raw).strip("._:-")[:128]
        if safe:
            return safe
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"payload-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:32]}"


def read_payload(path: str, *, max_bytes: int = MAX_PAYLOAD_BYTES) -> Any:
    """Read and parse a bounded JSON payload from a file or standard input."""

    if max_bytes <= 0 or max_bytes > MAX_PAYLOAD_BYTES:
        raise ConfigurationError(f"max bytes must be between 1 and {MAX_PAYLOAD_BYTES}")
    if path == "-":
        raw = sys.stdin.buffer.read(max_bytes + 1)
    else:
        with Path(path).open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ConfigurationError("payload exceeds the configured compressed input limit")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("input must be valid JSON") from exc


def serialize_payload(payload: Any, *, compress: bool) -> tuple[bytes, str, str]:
    """Serialize a stable JSON document and return bytes, suffix, and encoding."""

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    if compress:
        return gzip.compress(raw, mtime=0), ".json.gz", "gzip"
    return raw, ".json", ""


def build_blob_name(*, prefix: str, finding_id: str, suffix: str) -> str:
    """Build the only destination path used by this producer."""

    safe_id = derive_finding_id({}, finding_id)
    if suffix not in {".json", ".json.gz"}:
        raise ConfigurationError("suffix must be .json or .json.gz")
    return f"{validate_prefix(prefix)}/{safe_id}{suffix}"


def credential_for_mode(mode: str, *, managed_identity_client_id: str = "") -> Any:
    """Create a Government credential using only customer runtime settings."""

    normalized = str(mode or "").strip().lower()
    if normalized == "managed-identity":
        from azure.identity import ManagedIdentityCredential

        client_id = str(managed_identity_client_id or "").strip() or None
        return ManagedIdentityCredential(client_id=client_id)
    if normalized != "service-principal":
        raise ConfigurationError("auth mode must be managed-identity or service-principal")

    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip()
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
    if not tenant_id or not client_id or not client_secret:
        raise ConfigurationError(
            "service-principal mode requires AZURE_TENANT_ID, AZURE_CLIENT_ID, "
            "and runtime-injected AZURE_CLIENT_SECRET"
        )
    from azure.identity import AzureAuthorityHosts, ClientSecretCredential

    return ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        authority=AzureAuthorityHosts.AZURE_GOVERNMENT,
    )


def upload_payload(
    *,
    storage_account_url: str,
    container: str,
    prefix: str,
    payload: Any,
    auth_mode: str = "managed-identity",
    managed_identity_client_id: str = "",
    finding_id: str = "",
    compress: bool = True,
) -> dict[str, str]:
    """Upload one complete payload and return a secret-free operation summary."""

    data, suffix, content_encoding = serialize_payload(payload, compress=compress)
    if len(data) > MAX_PAYLOAD_BYTES:
        raise ConfigurationError("serialized payload exceeds the configured input limit")
    account_url = validate_storage_account_url(storage_account_url)
    container_name = validate_container_name(container)
    stable_id = derive_finding_id(payload, finding_id)
    blob_name = build_blob_name(prefix=prefix, finding_id=stable_id, suffix=suffix)

    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobClient, ContentSettings

    content_md5 = hashlib.md5(data).digest()
    blob = BlobClient(
        account_url=account_url,
        container_name=container_name,
        blob_name=blob_name,
        credential=credential_for_mode(
            auth_mode,
            managed_identity_client_id=managed_identity_client_id,
        ),
    )
    settings = ContentSettings(
        content_type="application/json",
        content_encoding=content_encoding or None,
        content_md5=content_md5,
    )
    try:
        blob.upload_blob(data, overwrite=False, content_settings=settings)
    except ResourceExistsError:
        existing = blob.get_blob_properties()
        existing_md5 = getattr(existing.content_settings, "content_md5", None)
        if existing_md5 != content_md5:
            raise BlobNameCollisionError(
                "destination Blob exists with different content; choose a new finding ID"
            )
        return {"status": "already_exists", "container": container_name, "blob": blob_name}
    return {"status": "uploaded", "container": container_name, "blob": blob_name}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", default="-", help="JSON file path, or '-' for stdin")
    parser.add_argument("--storage-account-url", default=os.getenv("AZURE_STORAGE_ACCOUNT_URL", ""))
    parser.add_argument("--container", default=os.getenv("AZURE_STORAGE_CONTAINER", "input"))
    parser.add_argument("--prefix", default=os.getenv("AZURE_STORAGE_PREFIX", "incoming"))
    parser.add_argument(
        "--auth-mode",
        choices=("managed-identity", "service-principal"),
        default=os.getenv("AZURE_STORAGE_AUTH_MODE", "managed-identity"),
    )
    parser.add_argument(
        "--managed-identity-client-id",
        default=os.getenv("AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID", ""),
        help="Optional user-assigned identity client ID; no secret is accepted here",
    )
    parser.add_argument("--finding-id", default="")
    parser.add_argument("--max-bytes", type=int, default=MAX_PAYLOAD_BYTES)
    parser.add_argument("--no-gzip", action="store_true", help="Upload JSON instead of gzip JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.storage_account_url:
            raise ConfigurationError("--storage-account-url or AZURE_STORAGE_ACCOUNT_URL is required")
        payload = read_payload(args.input_file, max_bytes=args.max_bytes)
        result = upload_payload(
            storage_account_url=args.storage_account_url,
            container=args.container,
            prefix=args.prefix,
            payload=payload,
            auth_mode=args.auth_mode,
            managed_identity_client_id=args.managed_identity_client_id,
            finding_id=args.finding_id,
            compress=not args.no_gzip,
        )
    except (ConfigurationError, BlobNameCollisionError, OSError, ValueError) as exc:
        print(f"soar_to_blob_error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
