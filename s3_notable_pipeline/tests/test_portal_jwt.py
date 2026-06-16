"""Tests for portal JWT bearer-token validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline import portal_jwt


class FakeDiscoveryResponse:
    """Minimal OIDC discovery response used by JWT tests."""

    def __init__(self, body: dict[str, str]) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return self.body


class FakeSigningKey:
    """Minimal signing key returned by the mocked JWKS client."""

    key = "public-key"


class PortalJwtTests(unittest.TestCase):
    """Portal JWT validation behavior."""

    def setUp(self) -> None:
        portal_jwt._jwk_clients.clear()  # pylint: disable=protected-access
        portal_jwt._jwks_urls.clear()  # pylint: disable=protected-access

    def test_bearer_token_from_headers_is_case_insensitive(self) -> None:
        token = portal_jwt.bearer_token_from_headers(
            {"authorization": "Bearer token-value"}
        )

        self.assertEqual(token, "token-value")

    def test_validate_jwt_uses_oidc_discovered_jwks_uri(self) -> None:
        with (
            patch.object(
                portal_jwt.requests,
                "get",
                return_value=FakeDiscoveryResponse(
                    {"jwks_uri": "https://issuer.example.test/keys"}
                ),
            ),
            patch.object(portal_jwt, "PyJWKClient") as jwk_client_cls,
            patch.object(
                portal_jwt.jwt,
                "decode",
                return_value={"iss": "https://issuer.example.test", "aud": "portal"},
            ),
        ):
            jwk_client_cls.return_value.get_signing_key_from_jwt.return_value = (
                FakeSigningKey()
            )

            claims = portal_jwt.validate_portal_jwt(
                "jwt-token",
                issuer="https://issuer.example.test",
                audience="portal",
            )

        self.assertEqual(claims["aud"], "portal")
        jwk_client_cls.assert_called_once_with(
            "https://issuer.example.test/keys",
            cache_keys=True,
            timeout=5,
        )

    def test_validate_jwt_falls_back_to_standard_jwks_path(self) -> None:
        with (
            patch.object(
                portal_jwt.requests,
                "get",
                side_effect=requests.RequestException("discovery unavailable"),
            ),
            patch.object(portal_jwt, "PyJWKClient") as jwk_client_cls,
            patch.object(portal_jwt.jwt, "decode", return_value={"aud": "portal"}),
        ):
            jwk_client_cls.return_value.get_signing_key_from_jwt.return_value = (
                FakeSigningKey()
            )

            portal_jwt.validate_portal_jwt(
                "jwt-token",
                issuer="https://issuer.example.test/",
                audience="portal",
            )

        jwk_client_cls.assert_called_once_with(
            "https://issuer.example.test/.well-known/jwks.json",
            cache_keys=True,
            timeout=5,
        )

    def test_validate_jwt_fails_closed_for_invalid_issuer_url(self) -> None:
        claims = portal_jwt.validate_portal_jwt(
            "jwt-token",
            issuer="http://issuer.example.test",
            audience="portal",
        )

        self.assertIsNone(claims)


if __name__ == "__main__":
    unittest.main()
