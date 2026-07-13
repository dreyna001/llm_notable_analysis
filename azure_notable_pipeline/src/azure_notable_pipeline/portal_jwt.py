"""Validate portal JWT bearer tokens for Function URL and direct browser calls."""

from __future__ import annotations

from typing import Any

import jwt
import requests
from jwt import PyJWKClient

from .config import Config
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


def jwt_claims_valid(claims: dict[str, Any], *, issuer: str, audience: str) -> bool:
    """Return True when JWT claims match the configured issuer and audience."""

    audience_value = claims.get("aud")
    if isinstance(audience_value, list):
        audience_valid = audience in audience_value
    else:
        audience_valid = str(audience_value or "") == audience
    return str(claims.get("iss") or "") == issuer and audience_valid


def resolve_portal_jwt_claims(
    event: dict[str, Any],
    config: Config,
) -> dict[str, Any] | None:
    """Return validated JWT claims from the authorizer context or bearer token."""

    if config.PORTAL_AUTH_MODE != "jwt":
        return None
    authorizer = ((event.get("requestContext") or {}).get("authorizer") or {})
    claims = (authorizer.get("jwt") or {}).get("claims")
    if isinstance(claims, dict) and jwt_claims_valid(
        claims,
        issuer=config.PORTAL_JWT_ISSUER,
        audience=config.PORTAL_JWT_AUDIENCE,
    ):
        return claims
    token = bearer_token_from_headers(event.get("headers"))
    if not token:
        return None
    return validate_portal_jwt(
        token,
        issuer=config.PORTAL_JWT_ISSUER,
        audience=config.PORTAL_JWT_AUDIENCE,
    )


def resolve_portal_user_id(event: dict[str, Any], config: Config) -> str | None:
    """Return the authenticated portal user id from JWT sub or IAM caller identity."""

    if config.PORTAL_AUTH_MODE == "jwt":
        claims = resolve_portal_jwt_claims(event, config)
        if not isinstance(claims, dict):
            return None
        user_id = str(claims.get("sub") or "").strip()
        return user_id or None
    if config.PORTAL_AUTH_MODE == "iam":
        authorizer = ((event.get("requestContext") or {}).get("authorizer") or {})
        iam = authorizer.get("iam")
        if isinstance(iam, dict):
            user_id = str(iam.get("userId") or iam.get("userArn") or "").strip()
            return user_id or None
    return None


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
