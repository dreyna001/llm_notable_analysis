"""Tests for loopback-only vision helper."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from onprem_rag_notable_analysis.future.image_vision import (
    STATUS_VISION_DESCRIBED,
    STATUS_VISION_DISABLED,
    STATUS_VISION_EMPTY_RESPONSE,
    STATUS_VISION_ENDPOINT_NOT_LOOPBACK,
    STATUS_VISION_FAILED,
    STATUS_VISION_NOT_CONFIGURED,
    ImageVisionConfig,
    describe_image_with_vision,
)


class _FakeHttpClient:
    def __init__(
        self,
        *,
        responses: list[bytes] | None = None,
        errors: list[Exception] | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.errors = list(errors or [])
        self.calls: list[tuple[str, dict, float]] = []

    def __call__(self, url: str, payload: bytes, headers: dict[str, str], timeout: float) -> bytes:
        body = json.loads(payload.decode("utf-8"))
        self.calls.append((url, body, timeout))
        if self.errors:
            raise self.errors.pop(0)
        if not self.responses:
            raise RuntimeError("no fake response configured")
        return self.responses.pop(0)


class TestImageVision(unittest.TestCase):
    def test_disabled_and_not_configured(self) -> None:
        disabled = describe_image_with_vision(
            image_bytes=b"abc",
            content_type="image/png",
            config=ImageVisionConfig(enabled=False),
        )
        self.assertEqual(disabled.status, STATUS_VISION_DISABLED)

        not_configured = describe_image_with_vision(
            image_bytes=b"abc",
            content_type="image/png",
            config=ImageVisionConfig(enabled=True, api_base="", model=""),
        )
        self.assertEqual(not_configured.status, STATUS_VISION_NOT_CONFIGURED)

    def test_loopback_restriction(self) -> None:
        result = describe_image_with_vision(
            image_bytes=b"abc",
            content_type="image/png",
            config=ImageVisionConfig(
                enabled=True,
                api_base="https://vision.example/v1",
                model="gemma",
            ),
            http_client=_FakeHttpClient(
                responses=[json.dumps({"choices": [{"message": {"content": "x"}}]}).encode()]
            ),
        )
        self.assertEqual(result.status, STATUS_VISION_ENDPOINT_NOT_LOOPBACK)
        self.assertIsNone(result.description)

    def test_multimodal_payload_uses_internal_data_url(self) -> None:
        client = _FakeHttpClient(
            responses=[
                json.dumps(
                    {"choices": [{"message": {"content": "Login form visible."}}]}
                ).encode()
            ]
        )
        result = describe_image_with_vision(
            image_bytes=b"\x89PNG",
            content_type="image/png",
            config=ImageVisionConfig(
                enabled=True,
                api_base="http://127.0.0.1:4000/v1",
                model="gemma-vision",
                api_key="secret-token",
            ),
            http_client=client,
        )
        self.assertEqual(result.status, STATUS_VISION_DESCRIBED)
        self.assertEqual(result.description, "Login form visible.")
        self.assertEqual(len(client.calls), 1)
        url, body, _timeout = client.calls[0]
        self.assertTrue(url.endswith("/chat/completions"))
        content = body["messages"][0]["content"]
        image_part = next(item for item in content if item["type"] == "image_url")
        image_url = image_part["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertFalse(image_url.startswith("http"))

    def test_retryable_transport_error_retries_then_fails(self) -> None:
        client = _FakeHttpClient(errors=[TimeoutError("slow"), TimeoutError("slow again")])
        config = ImageVisionConfig(
            enabled=True,
            api_base="http://localhost:4000/v1",
            model="gemma-vision",
            max_retries=1,
            retry_backoff_seconds=0,
        )
        with mock.patch("onprem_rag_notable_analysis.future.image_vision.time.sleep"):
            result = describe_image_with_vision(
                image_bytes=b"img",
                content_type="image/png",
                config=config,
                http_client=client,
            )
        self.assertEqual(result.status, STATUS_VISION_FAILED)
        self.assertEqual(len(client.calls), 2)

    def test_non_retryable_error_does_not_retry(self) -> None:
        client = _FakeHttpClient(errors=[ValueError("bad payload")])
        config = ImageVisionConfig(
            enabled=True,
            api_base="http://127.0.0.1:4000/v1",
            model="gemma-vision",
            max_retries=3,
            retry_backoff_seconds=0,
        )
        result = describe_image_with_vision(
            image_bytes=b"img",
            content_type="image/png",
            config=config,
            http_client=client,
        )
        self.assertEqual(result.status, STATUS_VISION_FAILED)
        self.assertEqual(len(client.calls), 1)

    def test_empty_model_response(self) -> None:
        client = _FakeHttpClient(responses=[json.dumps({"choices": []}).encode()])
        result = describe_image_with_vision(
            image_bytes=b"img",
            content_type="image/png",
            config=ImageVisionConfig(
                enabled=True,
                api_base="http://127.0.0.1:4000/v1",
                model="gemma-vision",
            ),
            http_client=client,
        )
        self.assertEqual(result.status, STATUS_VISION_EMPTY_RESPONSE)

    def test_localhost_and_ipv6_loopback_allowed(self) -> None:
        for api_base in (
            "http://localhost:4000/v1",
            "http://[::1]:4000/v1",
        ):
            client = _FakeHttpClient(
                responses=[
                    json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
                ]
            )
            result = describe_image_with_vision(
                image_bytes=b"img",
                content_type="image/png",
                config=ImageVisionConfig(
                    enabled=True,
                    api_base=api_base,
                    model="gemma-vision",
                ),
                http_client=client,
            )
            self.assertEqual(result.status, STATUS_VISION_DESCRIBED, msg=api_base)


if __name__ == "__main__":
    unittest.main()
