"""Validate portal JWT bearer tokens for Function URL and direct browser calls."""

from __future__ import annotations

from typing import Any

import jwt
import requests
from jwt import PyJWKClient

from .runtime_security import validate_https_url

_jwk_clients: dict[str, PyJWKClient] = {}
_jwks_urls: dict[str, str] = {}


def bearer_token_from_headers(headers: dict[str, Any] | None) -> str:
    """Extract a Bearer token from API Gateway or Function URL headers."""

    for key, value in (headers or {}).items():
        if str(key).lower() != "authorization":
            continue
        parts = str(value or "").split()
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
    return ""


def validate_portal_jwt(token: str, *, issuer: str, audience: str) -> dict[str, Any] | None:
    """Return JWT claims when the bearer token matches issuer and audience."""

    normalized_issuer = issuer.strip()
    normalized_audience = audience.strip()
    if not token or not normalized_issuer or not normalized_audience:
        return None

    try:
        jwk_client = _jwk_clients.get(normalized_issuer)
        if jwk_client is None:
            jwks_url = _jwks_url_for_issuer(normalized_issuer)
            jwk_client = PyJWKClient(jwks_url, cache_keys=True, timeout=5)
            _jwk_clients[normalized_issuer] = jwk_client
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "RS384", "ES384", "RS512", "ES512"],
            audience=normalized_audience,
            issuer=normalized_issuer,
            options={"require": ["exp", "iss", "aud"]},
        )
    except (jwt.PyJWTError, OSError, ValueError):
        return None


def _jwks_url_for_issuer(issuer: str) -> str:
    cached = _jwks_urls.get(issuer)
    if cached:
        return cached

    validate_https_url(issuer, setting_name="PortalJwtIssuer")
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        response = requests.get(discovery_url, timeout=5)
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict):
            jwks_uri = body.get("jwks_uri")
            if isinstance(jwks_uri, str) and jwks_uri.strip():
                jwks_url = validate_https_url(
                    jwks_uri,
                    setting_name="PortalJwtIssuer jwks_uri",
                )
                _jwks_urls[issuer] = jwks_url
                return jwks_url
    except (requests.RequestException, ValueError):
        pass

    jwks_url = validate_https_url(
        f"{issuer.rstrip('/')}/.well-known/jwks.json",
        setting_name="PortalJwtIssuer jwks_uri",
    )
    _jwks_urls[issuer] = jwks_url
    return jwks_url
