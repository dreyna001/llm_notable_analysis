"""Request-scoped analyst chat image validation for the portal."""

from __future__ import annotations

import base64
import binascii
import io
import re
from dataclasses import dataclass
from typing import Any, Final

from .config import Config

_ALLOWED_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }
)
_ALLOWED_IMAGE_KEYS: Final[frozenset[str]] = frozenset({"media_type", "data_base64"})
_FORBIDDEN_IMAGE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "url",
        "image_url",
        "href",
        "src",
        "uri",
        "link",
        "path",
        "file",
        "filename",
    }
)
_STRICT_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+(?:={0,2})$")
_PIL_FORMAT_BY_MEDIA_TYPE: Final[dict[str, str]] = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}


@dataclass(frozen=True)
class ValidatedChatImage:
    """Sanitized in-memory chat image for one LLM request."""

    media_type: str
    data_url: str


@dataclass(frozen=True)
class ChatImageSettings:
    enabled: bool
    max_images: int
    max_bytes: int
    max_dimension: int
    max_pixels: int


def chat_image_settings(config: Config) -> ChatImageSettings:
    """Resolve chat image limits from portal config."""
    return ChatImageSettings(
        enabled=bool(config.CASE_QA_CHAT_IMAGES_ENABLED),
        max_images=max(1, int(config.CASE_QA_MAX_CHAT_IMAGES)),
        max_bytes=max(1, int(config.CASE_QA_MAX_CHAT_IMAGE_BYTES)),
        max_dimension=max(1, int(config.CASE_QA_MAX_CHAT_IMAGE_DIMENSION)),
        max_pixels=max(1, int(config.CASE_QA_MAX_CHAT_IMAGE_PIXELS)),
    )


def portal_chat_image_capabilities(config: Config) -> dict[str, int | bool]:
    """Expose chat image capability fields for /api/capabilities."""
    settings = chat_image_settings(config)
    return {
        "chat_images_enabled": settings.enabled,
        "max_chat_images": settings.max_images,
        "max_chat_image_bytes": settings.max_bytes,
    }


def validate_chat_images(
    raw_images: Any,
    config: Config,
) -> tuple[ValidatedChatImage, ...]:
    """Validate optional chat image payloads from a portal chat request."""
    if raw_images is None:
        return ()
    settings = chat_image_settings(config)
    if not isinstance(raw_images, list):
        raise ValueError("images must be an array.")
    if not raw_images:
        return ()
    if not settings.enabled:
        raise ValueError("Chat images are not enabled.")
    if len(raw_images) > settings.max_images:
        raise ValueError(
            f"At most {settings.max_images} chat image(s) are allowed."
        )

    validated: list[ValidatedChatImage] = []
    for index, entry in enumerate(raw_images):
        validated.append(_validate_one_image(entry, settings, index=index))
    return tuple(validated)


def build_multimodal_user_content(
    prompt: str,
    images: tuple[ValidatedChatImage, ...],
) -> list[dict[str, Any]]:
    """Build OpenAI-compatible multimodal user content for one LLM call."""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": image.data_url},
            }
        )
    return content


def _validate_one_image(
    entry: Any,
    settings: ChatImageSettings,
    *,
    index: int,
) -> ValidatedChatImage:
    del index
    if not isinstance(entry, dict):
        raise ValueError("Each chat image must be an object.")

    extra_keys = set(entry.keys()) - _ALLOWED_IMAGE_KEYS
    if extra_keys:
        if extra_keys & _FORBIDDEN_IMAGE_KEYS:
            raise ValueError("Chat image entries must not include URL fields.")
        raise ValueError("Each chat image must include media_type and data_base64 only.")

    media_type = entry.get("media_type")
    if not isinstance(media_type, str) or media_type not in _ALLOWED_MEDIA_TYPES:
        raise ValueError("Only PNG, JPEG, WebP, and GIF images are supported.")

    data_base64 = entry.get("data_base64")
    if not isinstance(data_base64, str) or not data_base64.strip():
        raise ValueError("data_base64 is required.")

    normalized_base64 = data_base64.strip()
    if normalized_base64.startswith("data:"):
        raise ValueError("data_base64 must not include a data URL prefix.")
    if not _STRICT_BASE64_RE.fullmatch(normalized_base64):
        raise ValueError("data_base64 must be valid base64.")
    if len(normalized_base64) % 4 != 0:
        raise ValueError("data_base64 must be valid base64.")

    try:
        raw_bytes = base64.b64decode(normalized_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("data_base64 must be valid base64.") from exc

    if not raw_bytes:
        raise ValueError("Invalid or corrupted image.")
    if len(raw_bytes) > settings.max_bytes:
        raise ValueError(
            f"Image must be {_format_byte_limit(settings.max_bytes)} or smaller."
        )

    detected_mime = _detect_mime(raw_bytes)
    if detected_mime != media_type:
        raise ValueError("Image content does not match the declared media type.")

    sanitized_bytes, width, height = _sanitize_and_measure_image(
        raw_bytes,
        media_type=media_type,
        settings=settings,
    )
    del width, height
    encoded = base64.b64encode(sanitized_bytes).decode("ascii")
    return ValidatedChatImage(
        media_type=media_type,
        data_url=f"data:{media_type};base64,{encoded}",
    )


def _format_byte_limit(max_bytes: int) -> str:
    if max_bytes < 1024:
        return f"{max_bytes} B"
    if max_bytes < 1024 * 1024:
        rounded = max_bytes / 1024
        return f"{rounded:.1f} KB" if max_bytes < 10_240 else f"{int(round(rounded))} KB"
    return f"{max_bytes / (1024 * 1024):.1f} MB"


def _detect_mime(raw_bytes: bytes) -> str | None:
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith(b"GIF87a") or raw_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    return None


def _sanitize_and_measure_image(
    raw_bytes: bytes,
    *,
    media_type: str,
    settings: ChatImageSettings,
) -> tuple[bytes, int, int]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Invalid or corrupted image.") from exc

    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw_bytes)) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError("Invalid or corrupted image.")
            if width > settings.max_dimension or height > settings.max_dimension:
                raise ValueError("Image dimensions exceed the allowed maximum.")
            pixel_count = width * height
            if pixel_count > settings.max_pixels:
                raise ValueError("Image pixel count exceeds the allowed maximum.")

            working = image.copy()
            if media_type == "image/jpeg":
                working = working.convert("RGB")
            elif media_type == "image/png" and working.mode not in {
                "RGB",
                "RGBA",
                "L",
                "LA",
                "P",
            }:
                working = working.convert("RGBA")
            elif media_type == "image/webp" and working.mode not in {
                "RGB",
                "RGBA",
                "L",
            }:
                working = working.convert("RGBA")

            output = io.BytesIO()
            save_format = _PIL_FORMAT_BY_MEDIA_TYPE[media_type]
            save_kwargs: dict[str, object] = {}
            if save_format == "JPEG":
                save_kwargs["quality"] = 95
            working.save(output, format=save_format, **save_kwargs)
            sanitized = output.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid or corrupted image.") from exc

    if not sanitized:
        raise ValueError("Invalid or corrupted image.")
    if len(sanitized) > settings.max_bytes:
        raise ValueError(
            f"Image must be {_format_byte_limit(settings.max_bytes)} or smaller."
        )
    detected_mime = _detect_mime(sanitized)
    if detected_mime != media_type:
        raise ValueError("Image content does not match the declared media type.")
    return sanitized, width, height
