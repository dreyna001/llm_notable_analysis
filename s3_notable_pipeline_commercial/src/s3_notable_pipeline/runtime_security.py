"""Runtime validation helpers for external integration boundaries."""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlparse

from .aws_clients import secretsmanager_client


def read_bounded_bytes(body: Any, *, max_bytes: int, setting_name: str) -> bytes:
    """Read a streaming or in-memory body without accepting more than the limit."""

    if max_bytes < 1:
        raise ValueError(f"{setting_name} must be greater than 0")
    if isinstance(body, str):
        data = body.encode("utf-8")
    elif isinstance(body, (bytes, bytearray)):
        data = bytes(body)
    elif hasattr(body, "read"):
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            try:
                chunk = body.read(min(64 * 1024, remaining))
            except TypeError as exc:
                raise ValueError("body stream must support bounded reads") from exc
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            if not isinstance(chunk, (bytes, bytearray)):
                raise ValueError("body stream must return bytes or text")
            value = bytes(chunk)
            chunks.append(value)
            remaining -= len(value)
        data = b"".join(chunks)
    else:
        raise ValueError("body must be bytes, text, or a readable stream")
    if len(data) > max_bytes:
        raise ValueError(f"body exceeds {setting_name} ({max_bytes})")
    return data


def validate_https_url(
    value: str,
    *,
    setting_name: str,
    allow_private: bool = False,
) -> str:
    """Validate an outbound HTTPS URL before sending secrets or payloads."""

    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{setting_name} must be an HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{setting_name} must not include userinfo")
    hostname = (parsed.hostname or "").strip()
    if not hostname:
        raise ValueError(f"{setting_name} must include a host")
    if hostname.lower() == "localhost" or hostname.lower().endswith(".localhost"):
        if not allow_private:
            raise ValueError(f"{setting_name} must not target localhost")
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    if ip and not allow_private:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"{setting_name} must not target a private or local IP")
    return url


def resolve_secret_string(
    *,
    secret_arn: str,
    setting_name: str,
    secret_field: str = "token",
    fallback_fields: tuple[str, ...] = (),
    client: Any | None = None,
) -> str:
    """Resolve a plain-string or JSON field secret from Secrets Manager."""

    clean_arn = str(secret_arn or "").strip()
    if not clean_arn or clean_arn == "*":
        return ""
    sm_client = client or secretsmanager_client()
    secret_response = sm_client.get_secret_value(SecretId=clean_arn)
    secret_string = secret_response.get("SecretString") or ""
    if not secret_string:
        raise ValueError(f"{setting_name} secret has no SecretString content")
    try:
        parsed = json.loads(secret_string)
    except json.JSONDecodeError:
        return secret_string
    if not isinstance(parsed, dict):
        raise ValueError(f"{setting_name} secret JSON must be an object or plain string")
    fields = (secret_field, *fallback_fields)
    for field in fields:
        token_value = parsed.get(field)
        if isinstance(token_value, str) and token_value.strip():
            return token_value
    raise ValueError(f"{setting_name} secret JSON missing required field")
