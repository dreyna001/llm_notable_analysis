"""Runtime validation helpers for external integration boundaries."""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlparse

from .secret_provider import read_secret


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
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError(f"{setting_name} must not target a private or local IP")
    return url


def resolve_secret_string(
    *,
    secret_name: str,
    setting_name: str,
    secret_field: str = "token",
    fallback_fields: tuple[str, ...] = (),
    provider: Any | None = None,
) -> str:
    """Resolve a plain-string or JSON field from a Key Vault secret."""

    clean_name = str(secret_name or "").strip()
    if not clean_name:
        return ""
    secret_value = read_secret(clean_name, provider=provider)
    if not secret_value:
        raise ValueError(f"{setting_name} secret has no content")
    try:
        parsed = json.loads(secret_value)
    except json.JSONDecodeError:
        return secret_value
    if not isinstance(parsed, dict):
        raise ValueError(f"{setting_name} secret JSON must be an object or plain string")
    for field in (secret_field, *fallback_fields):
        token_value = parsed.get(field)
        if isinstance(token_value, str) and token_value.strip():
            return token_value
    raise ValueError(f"{setting_name} secret JSON missing required field")
