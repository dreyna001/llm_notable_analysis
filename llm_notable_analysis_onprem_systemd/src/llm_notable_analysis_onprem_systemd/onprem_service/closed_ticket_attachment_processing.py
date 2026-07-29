"""Attachment semantic extraction helpers for closed-ticket indexing."""

# Vision calls use stdlib HTTP only and fail soft when disabled or unavailable.
# pylint: disable=broad-exception-caught,import-error

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from onprem_rag_notable_analysis.future.image_extraction import (
    STATUS_BYTE_LIMIT_EXCEEDED,
    STATUS_EMBEDDED_IMAGE_LIMIT_EXCEEDED,
    STATUS_EMPTY_CONTENT,
    STATUS_EXTRACTED,
    STATUS_INVALID_IMAGE,
    STATUS_MIME_MISMATCH,
    STATUS_OCR_EMPTY,
    STATUS_OCR_FAILED,
    STATUS_OCR_TIMEOUT,
    STATUS_OUTPUT_TRUNCATED,
    STATUS_PAGE_LIMIT_EXCEEDED,
    STATUS_PIXEL_LIMIT_EXCEEDED,
    STATUS_PREREQUISITE_MISSING,
    STATUS_UNSUPPORTED_CONTENT_TYPE,
    ImageExtractionResult,
    VisionDescriber,
    extract_image_content,
)
from onprem_rag_notable_analysis.future.image_extraction_config import (
    ImageExtractionConfig,
)
from onprem_rag_notable_analysis.future.image_vision import (
    ImageVisionConfig,
    ImageVisionResult,
    describe_image_with_vision,
)

from .config import Config

logger = logging.getLogger(__name__)

_TEXT_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "application/csv",
    "text/csv",
    "text/html",
    "text/plain",
    "text/xml",
}
_IMAGE_CONTENT_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}
_PDF_CONTENT_TYPES = {"application/pdf"}
_DOCX_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_BINARY_EXTRACTION_CONTENT_TYPES = _IMAGE_CONTENT_TYPES | _PDF_CONTENT_TYPES | _DOCX_CONTENT_TYPES
_WHITESPACE_RE = re.compile(r"\s+")

# Conservative bounds when no closed-ticket-specific env knobs exist yet.
_DEFAULT_MAX_PIXELS = 25_000_000
_DEFAULT_MAX_WIDTH = 8192
_DEFAULT_MAX_HEIGHT = 8192
_DEFAULT_MAX_PDF_PAGES = 50
_DEFAULT_MAX_EMBEDDED_IMAGES = 20
_DEFAULT_TESSERACT_BINARY = "tesseract"
_DEFAULT_TESSERACT_LANG = "eng"
_DEFAULT_TESSERACT_TIMEOUT_SECONDS = 60.0

_SHARED_STATUS_SUFFIX = {
    STATUS_EXTRACTED: "ocr_extracted",
    STATUS_OUTPUT_TRUNCATED: "ocr_truncated",
    STATUS_OCR_EMPTY: "ocr_empty",
    STATUS_OCR_FAILED: "ocr_failed",
    STATUS_OCR_TIMEOUT: "ocr_timeout",
    STATUS_PREREQUISITE_MISSING: "prerequisite_missing",
    STATUS_INVALID_IMAGE: "invalid_content",
    STATUS_MIME_MISMATCH: "mime_mismatch",
    STATUS_BYTE_LIMIT_EXCEEDED: "byte_limit_exceeded",
    STATUS_PIXEL_LIMIT_EXCEEDED: "pixel_limit_exceeded",
    STATUS_PAGE_LIMIT_EXCEEDED: "page_limit_exceeded",
    STATUS_EMBEDDED_IMAGE_LIMIT_EXCEEDED: "embedded_image_limit_exceeded",
    STATUS_EMPTY_CONTENT: "empty_content",
    STATUS_UNSUPPORTED_CONTENT_TYPE: "unsupported_content_type",
}

_NON_AUTHORITATIVE_VISION_STATUSES = frozenset(
    {
        "vision_disabled",
        "vision_not_configured",
    }
)


@dataclass(frozen=True)
class ClosedTicketAttachmentInput:
    """Raw attachment row values used for semantic extraction."""

    attachment_id: str
    ticket_id: str
    filename: str | None
    content_type: str | None
    metadata: dict[str, Any]
    storage_path: str | None = None
    raw_content: Any = None


@dataclass(frozen=True)
class ClosedTicketAttachmentSemanticResult:
    """Semantic extraction output for one attachment."""

    attachment_id: str
    ticket_id: str
    filename: str | None
    content_type: str | None
    metadata: dict[str, Any]
    semantic_text: str | None
    extraction_status: str


def _config_bool(config: Config, name: str, default: bool = False) -> bool:
    value = getattr(config, name, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _max_text_chars(config: Config) -> int:
    return max(256, int(getattr(config, "CLOSED_TICKET_ATTACHMENT_MAX_TEXT_CHARS", 12000)))


def _max_attachment_bytes(config: Config) -> int:
    return max(1, int(getattr(config, "CLOSED_TICKET_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)))


def _positive_config_int(config: Config, name: str, default: int) -> int:
    raw = getattr(config, name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _positive_config_float(config: Config, name: str, default: float) -> float:
    raw = getattr(config, name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _config_str(config: Config, name: str, default: str) -> str:
    value = getattr(config, name, default)
    text = str(value or "").strip()
    return text or default


def _image_extraction_config(config: Config) -> ImageExtractionConfig:
    return ImageExtractionConfig(
        max_bytes=_max_attachment_bytes(config),
        max_output_chars=_max_text_chars(config),
        max_pixels=_positive_config_int(config, "IMAGE_INGEST_MAX_PIXELS", _DEFAULT_MAX_PIXELS),
        max_width=_positive_config_int(config, "IMAGE_INGEST_MAX_WIDTH", _DEFAULT_MAX_WIDTH),
        max_height=_positive_config_int(config, "IMAGE_INGEST_MAX_HEIGHT", _DEFAULT_MAX_HEIGHT),
        max_pdf_pages=_positive_config_int(config, "IMAGE_INGEST_MAX_PDF_PAGES", _DEFAULT_MAX_PDF_PAGES),
        max_embedded_images=_positive_config_int(
            config,
            "IMAGE_INGEST_MAX_EMBEDDED_IMAGES",
            _DEFAULT_MAX_EMBEDDED_IMAGES,
        ),
        tesseract_binary=_config_str(
            config,
            "IMAGE_INGEST_TESSERACT_BINARY",
            _DEFAULT_TESSERACT_BINARY,
        ),
        tesseract_lang=_config_str(config, "IMAGE_INGEST_TESSERACT_LANG", _DEFAULT_TESSERACT_LANG),
        tesseract_timeout_seconds=_positive_config_float(
            config,
            "IMAGE_INGEST_TESSERACT_TIMEOUT_SECONDS",
            _DEFAULT_TESSERACT_TIMEOUT_SECONDS,
        ),
    )


def _image_vision_config(config: Config) -> ImageVisionConfig:
    return ImageVisionConfig(
        enabled=_config_bool(config, "CLOSED_TICKET_VISION_ENABLED", False),
        api_base=str(getattr(config, "CLOSED_TICKET_VISION_API_BASE", "") or "").strip(),
        model=str(getattr(config, "CLOSED_TICKET_VISION_MODEL", "") or "").strip(),
        api_key=str(getattr(config, "CLOSED_TICKET_VISION_API_KEY", "") or "").strip(),
        timeout_seconds=float(getattr(config, "CLOSED_TICKET_VISION_TIMEOUT_SECONDS", 30.0)),
        max_tokens=int(getattr(config, "CLOSED_TICKET_VISION_MAX_TOKENS", 400)),
    )


def _collapse_ws(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", (text or "").strip())


def _normalize_content_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _metadata_only_message(
    *,
    filename: str | None,
    content_type: str | None,
    reason: str,
) -> str:
    parts = ["attachment_metadata_only"]
    if filename:
        parts.append(f"filename={filename}")
    if content_type:
        parts.append(f"content_type={content_type}")
    parts.append(f"reason={reason}")
    return " ".join(parts)


def _map_shared_extraction_status(*, prefix: str, shared_status: str) -> str:
    suffix = _SHARED_STATUS_SUFFIX.get(shared_status)
    if suffix:
        return f"{prefix}_{suffix}"
    return f"{prefix}_{shared_status}"


def _authoritative_vision_status(vision_status: str | None) -> str | None:
    if not vision_status or vision_status in _NON_AUTHORITATIVE_VISION_STATUSES:
        return None
    return vision_status


def decode_text_attachment(
    raw_content: Any,
    *,
    content_type: str | None,
    config: Config,
) -> tuple[str | None, str]:
    """Decode a text-like attachment with bounded UTF-8 handling."""
    normalized_type = _normalize_content_type(content_type)
    if raw_content is None:
        return None, "missing_content"
    if isinstance(raw_content, str):
        text = raw_content
    elif isinstance(raw_content, (bytes, bytearray, memoryview)):
        text = bytes(raw_content).decode("utf-8", errors="replace")
    else:
        return None, "unsupported_content_encoding"
    limit = _max_text_chars(config)
    collapsed = _collapse_ws(text)
    if not collapsed:
        return None, "empty_text"
    if len(collapsed) > limit:
        collapsed = collapsed[:limit].rstrip() + " [truncated]"
    if normalized_type in _TEXT_CONTENT_TYPES or normalized_type.startswith("text/"):
        return collapsed, "text_decoded"
    if normalized_type in ("application/octet-stream", ""):
        return collapsed, "text_decoded_best_effort"
    return collapsed, "text_decoded_best_effort"


def _bytes_from_raw(raw_content: Any) -> bytes | None:
    if raw_content is None:
        return None
    if isinstance(raw_content, (bytes, bytearray, memoryview)):
        return bytes(raw_content)
    if isinstance(raw_content, str):
        try:
            return base64.b64decode(raw_content, validate=True)
        except Exception:
            return raw_content.encode("utf-8", errors="replace")
    return None


def _read_storage_bytes(storage_path: str | None, *, max_bytes: int) -> bytes | None:
    if not str(storage_path or "").strip():
        return None
    path = Path(storage_path)
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
        if size > int(max_bytes):
            return None
        return path.read_bytes()
    except OSError as exc:
        logger.warning("Failed to read attachment file %s: %s", storage_path, exc)
        return None


def _attachment_payload_bytes(
    attachment: ClosedTicketAttachmentInput,
    config: Config,
) -> bytes | None:
    raw_bytes = _bytes_from_raw(attachment.raw_content)
    if raw_bytes is not None:
        return raw_bytes
    return _read_storage_bytes(
        attachment.storage_path,
        max_bytes=_max_attachment_bytes(config),
    )


def describe_image_with_vision_model(
    *,
    image_bytes: bytes,
    content_type: str,
    config: Config,
    http_client: Any = None,
) -> tuple[str | None, str]:
    """Call an optional OpenAI-compatible vision endpoint; fails soft when disabled."""
    result = describe_image_with_vision(
        image_bytes=image_bytes,
        content_type=content_type,
        config=_image_vision_config(config),
        http_client=http_client,
    )
    return result.description, result.status


def _build_vision_describer(
    config: Config,
    *,
    http_client: Any = None,
) -> VisionDescriber | None:
    vision_config = _image_vision_config(config)
    if not vision_config.enabled:
        return None

    def _describe(image_bytes: bytes, content_type: str) -> ImageVisionResult:
        return describe_image_with_vision(
            image_bytes=image_bytes,
            content_type=content_type,
            config=vision_config,
            http_client=http_client,
        )

    return _describe


def _semantic_text_from_extraction(extraction: ImageExtractionResult) -> str | None:
    text = (extraction.text or "").strip()
    return text or None


def _resolve_binary_extraction_status(
    *,
    content_type: str,
    extraction: ImageExtractionResult,
) -> str:
    prefix = "image"
    if content_type in _PDF_CONTENT_TYPES:
        prefix = "pdf"
    elif content_type in _DOCX_CONTENT_TYPES:
        prefix = "docx"

    if content_type in _IMAGE_CONTENT_TYPES:
        authoritative_vision = _authoritative_vision_status(extraction.vision_status)
        if authoritative_vision == "vision_described":
            return "vision_described"
        if extraction.status in {STATUS_EXTRACTED, STATUS_OUTPUT_TRUNCATED}:
            return _map_shared_extraction_status(prefix="image", shared_status=extraction.status)
        if authoritative_vision:
            return authoritative_vision
        return _map_shared_extraction_status(prefix="image", shared_status=extraction.status)

    if extraction.text:
        return _map_shared_extraction_status(prefix=prefix, shared_status=extraction.status)
    return _map_shared_extraction_status(prefix=prefix, shared_status=extraction.status)


def _extract_binary_attachment_semantic_text(
    *,
    attachment: ClosedTicketAttachmentInput,
    content_type: str,
    raw_bytes: bytes,
    config: Config,
    http_client: Any = None,
) -> ClosedTicketAttachmentSemanticResult | None:
    extraction_config = _image_extraction_config(config)
    vision_describer = _build_vision_describer(config, http_client=http_client)

    extraction = extract_image_content(
        raw_bytes,
        content_type=content_type,
        config=extraction_config,
        vision_describer=vision_describer,
    )

    semantic_text = _semantic_text_from_extraction(extraction)
    if semantic_text:
        status = _resolve_binary_extraction_status(
            content_type=content_type,
            extraction=extraction,
        )
        return ClosedTicketAttachmentSemanticResult(
            attachment_id=attachment.attachment_id,
            ticket_id=attachment.ticket_id,
            filename=attachment.filename,
            content_type=content_type,
            metadata=dict(attachment.metadata or {}),
            semantic_text=semantic_text,
            extraction_status=status,
        )

    if content_type in _IMAGE_CONTENT_TYPES:
        reason = (
            _authoritative_vision_status(extraction.vision_status)
            or _map_shared_extraction_status(prefix="image", shared_status=extraction.status)
        )
        return ClosedTicketAttachmentSemanticResult(
            attachment_id=attachment.attachment_id,
            ticket_id=attachment.ticket_id,
            filename=attachment.filename,
            content_type=content_type,
            metadata=dict(attachment.metadata or {}),
            semantic_text=_metadata_only_message(
                filename=attachment.filename,
                content_type=content_type,
                reason=reason,
            ),
            extraction_status=reason,
        )

    prefix = "pdf" if content_type in _PDF_CONTENT_TYPES else "docx"
    status = _map_shared_extraction_status(prefix=prefix, shared_status=extraction.status)
    return ClosedTicketAttachmentSemanticResult(
        attachment_id=attachment.attachment_id,
        ticket_id=attachment.ticket_id,
        filename=attachment.filename,
        content_type=content_type,
        metadata=dict(attachment.metadata or {}),
        semantic_text=_metadata_only_message(
            filename=attachment.filename,
            content_type=content_type,
            reason=status,
        ),
        extraction_status=status,
    )


def extract_attachment_semantic_text(
    attachment: ClosedTicketAttachmentInput,
    config: Config,
    *,
    http_client: Any = None,
) -> ClosedTicketAttachmentSemanticResult:
    """Extract semantic attachment text without mutating authoritative raw content."""
    metadata = dict(attachment.metadata or {})
    content_type = _normalize_content_type(attachment.content_type)
    filename = attachment.filename

    existing = metadata.get("semantic_description")
    if isinstance(existing, str) and existing.strip():
        return ClosedTicketAttachmentSemanticResult(
            attachment_id=attachment.attachment_id,
            ticket_id=attachment.ticket_id,
            filename=filename,
            content_type=content_type or None,
            metadata=metadata,
            semantic_text=existing.strip(),
            extraction_status=str(metadata.get("semantic_extraction_status") or "metadata_existing"),
        )

    raw_bytes = _attachment_payload_bytes(attachment, config)
    if content_type in _BINARY_EXTRACTION_CONTENT_TYPES:
        if raw_bytes:
            binary_result = _extract_binary_attachment_semantic_text(
                attachment=attachment,
                content_type=content_type,
                raw_bytes=raw_bytes,
                config=config,
                http_client=http_client,
            )
            if binary_result is not None:
                return binary_result
        reason = "missing_content" if raw_bytes is None else "empty_content"
        status = (
            f"pdf_{reason}"
            if content_type in _PDF_CONTENT_TYPES
            else f"docx_{reason}"
            if content_type in _DOCX_CONTENT_TYPES
            else f"image_{reason}"
        )
        return ClosedTicketAttachmentSemanticResult(
            attachment_id=attachment.attachment_id,
            ticket_id=attachment.ticket_id,
            filename=filename,
            content_type=content_type,
            metadata=metadata,
            semantic_text=_metadata_only_message(
                filename=filename,
                content_type=content_type,
                reason=reason,
            ),
            extraction_status=status,
        )

    if raw_bytes is not None or isinstance(attachment.raw_content, str):
        payload: Any = attachment.raw_content
        if raw_bytes is not None and not isinstance(attachment.raw_content, str):
            payload = raw_bytes
        decoded, status = decode_text_attachment(
            payload,
            content_type=content_type,
            config=config,
        )
        if decoded:
            return ClosedTicketAttachmentSemanticResult(
                attachment_id=attachment.attachment_id,
                ticket_id=attachment.ticket_id,
                filename=filename,
                content_type=content_type or None,
                metadata=metadata,
                semantic_text=decoded,
                extraction_status=status,
            )

    semantic = _metadata_only_message(
        filename=filename,
        content_type=content_type or None,
        reason="no_extractable_content",
    )
    return ClosedTicketAttachmentSemanticResult(
        attachment_id=attachment.attachment_id,
        ticket_id=attachment.ticket_id,
        filename=filename,
        content_type=content_type or None,
        metadata=metadata,
        semantic_text=semantic,
        extraction_status="metadata_only",
    )


def build_attachment_semantic_metadata(
    attachment: ClosedTicketAttachmentInput,
    config: Config,
    *,
    http_client: Any = None,
) -> ClosedTicketAttachmentSemanticResult:
    """Extract semantic text and merge extraction fields into attachment metadata."""
    result = extract_attachment_semantic_text(
        attachment,
        config,
        http_client=http_client,
    )
    metadata = dict(result.metadata)
    if result.semantic_text:
        metadata["semantic_description"] = result.semantic_text
    metadata["semantic_extraction_status"] = result.extraction_status
    return ClosedTicketAttachmentSemanticResult(
        attachment_id=result.attachment_id,
        ticket_id=result.ticket_id,
        filename=result.filename,
        content_type=result.content_type,
        metadata=metadata,
        semantic_text=result.semantic_text,
        extraction_status=result.extraction_status,
    )
