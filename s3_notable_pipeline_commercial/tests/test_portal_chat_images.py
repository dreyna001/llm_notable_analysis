"""Tests for request-scoped portal chat image validation."""

from __future__ import annotations

import base64
import io
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.portal_chat_images import (
    build_bedrock_converse_user_content,
    chat_image_settings,
    portal_chat_image_capabilities,
    validate_chat_images,
)


def _make_png_bytes(*, width: int = 32, height: int = 32) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), (255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _png_payload(
    *,
    width: int = 32,
    height: int = 32,
    media_type: str = "image/png",
) -> dict[str, str]:
    encoded = base64.b64encode(_make_png_bytes(width=width, height=height)).decode("ascii")
    return {"media_type": media_type, "data_base64": encoded}


def _chat_image_config(**enabled: bool) -> Config:
    config = Config(BEDROCK_MODEL_ID="anthropic.test")
    if enabled.get("enabled", True):
        config.CASE_QA_CHAT_IMAGES_ENABLED = True
    return config


class TestPortalChatImages(unittest.TestCase):
    def test_defaults_disable_chat_images(self) -> None:
        config = _chat_image_config(enabled=False)
        settings = chat_image_settings(config)
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.max_images, 1)
        self.assertEqual(settings.max_bytes, 750_000)
        self.assertEqual(
            portal_chat_image_capabilities(config),
            {
                "chat_images_enabled": False,
                "max_chat_images": 1,
                "max_chat_image_bytes": 750_000,
            },
        )

    def test_validate_accepts_one_png_when_enabled(self) -> None:
        config = _chat_image_config()
        validated = validate_chat_images([_png_payload()], config)
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0].media_type, "image/png")
        self.assertTrue(validated[0].data_url.startswith("data:image/png;base64,"))

    def test_validate_rejects_when_feature_disabled(self) -> None:
        config = _chat_image_config(enabled=False)
        with self.assertRaisesRegex(ValueError, "Chat images are not enabled."):
            validate_chat_images([_png_payload()], config)

    def test_validate_rejects_non_object_entries(self) -> None:
        config = _chat_image_config()
        with self.assertRaisesRegex(ValueError, "Each chat image must be an object."):
            validate_chat_images(["not-an-object"], config)

    def test_validate_rejects_url_fields(self) -> None:
        config = _chat_image_config()
        payload = _png_payload()
        payload["url"] = "https://example.test/image.png"
        with self.assertRaisesRegex(ValueError, "must not include URL fields"):
            validate_chat_images([payload], config)

    def test_validate_rejects_unknown_fields(self) -> None:
        config = _chat_image_config()
        payload = _png_payload()
        payload["caption"] = "screenshot"
        with self.assertRaisesRegex(
            ValueError,
            "must include media_type and data_base64 only",
        ):
            validate_chat_images([payload], config)

    def test_validate_rejects_invalid_base64(self) -> None:
        config = _chat_image_config()
        with self.assertRaisesRegex(ValueError, "data_base64 must be valid base64."):
            validate_chat_images(
                [{"media_type": "image/png", "data_base64": "%%%"}],
                config,
            )

    def test_validate_rejects_oversized_decoded_bytes(self) -> None:
        config = _chat_image_config()
        config.CASE_QA_MAX_CHAT_IMAGE_BYTES = 100
        with self.assertRaisesRegex(ValueError, "100 B or smaller"):
            validate_chat_images([_png_payload()], config)

    def test_validate_rejects_dimension_and_pixel_limits(self) -> None:
        config = _chat_image_config()
        config.CASE_QA_MAX_CHAT_IMAGE_DIMENSION = 16
        config.CASE_QA_MAX_CHAT_IMAGE_PIXELS = 256
        with self.assertRaisesRegex(ValueError, "dimensions exceed"):
            validate_chat_images([_png_payload(width=32, height=32)], config)

    def test_build_bedrock_converse_user_content_uses_image_blocks(self) -> None:
        config = _chat_image_config()
        validated = validate_chat_images([_png_payload()], config)
        content = build_bedrock_converse_user_content("Question text", validated)
        self.assertEqual(content[0], {"text": "Question text"})
        image_block = content[1]["image"]
        self.assertEqual(image_block["format"], "png")
        self.assertIsInstance(image_block["source"]["bytes"], bytes)
        self.assertTrue(image_block["source"]["bytes"].startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
