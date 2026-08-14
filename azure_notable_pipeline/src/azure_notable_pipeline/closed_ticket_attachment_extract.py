"""Attachment semantic extraction for closed-ticket indexing (Azure Document Intelligence path)."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Any

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
    "image/tiff",
    "image/webp",
    "image/bmp",
}
_PDF_CONTENT_TYPES = {"application/pdf"}
_VISION_CONTENT_TYPES = _IMAGE_CONTENT_TYPES | _PDF_CONTENT_TYPES
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ClosedTicketAttachmentInput:
    """Raw attachment values used for semantic extraction."""

    attachment_id: str
    ticket_id: str
    filename: str | None
    content_type: str | None
    metadata: dict[str, Any]
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


def _bytes_from_raw(raw_content: Any) -> bytes | None:
    if raw_content is None:
        return None
    if isinstance(raw_content, (bytes, bytearray, memoryview)):
        return bytes(raw_content)
    if isinstance(raw_content, str):
        return raw_content.encode("utf-8", errors="replace")
    return None


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


def extract_text_with_document_intelligence(
    *,
    raw_bytes: bytes,
    content_type: str,
    config: Config,
    document_intelligence_client: Any,
) -> tuple[str | None, str]:
    """Extract document text with Azure Document Intelligence Read."""
    if not _config_bool(config, "CLOSED_TICKET_VISION_ENABLED", False):
        return None, "document_intelligence_disabled"
    if not document_intelligence_client:
        return None, "document_intelligence_not_configured"
    if len(raw_bytes) > _max_attachment_bytes(config):
        return None, "byte_limit_exceeded"
    if _normalize_content_type(content_type) not in _VISION_CONTENT_TYPES:
        return None, "unsupported_content_type"

    try:
        poller = document_intelligence_client.begin_analyze_document(
            "prebuilt-read",
            raw_bytes,
            content_type=content_type or "application/octet-stream",
        )
        result = poller.result()
    except Exception as exc:
        logger.warning("Document Intelligence analyze failed: %s", exc)
        return None, "document_intelligence_failed"

    lines: list[str] = []
    for page in getattr(result, "pages", []) or []:
        for line in getattr(page, "lines", []) or []:
            text = str(getattr(line, "content", "") or "").strip()
            if text:
                lines.append(text)

    if not lines:
        return None, "document_intelligence_empty"

    collapsed = _collapse_ws("\n".join(lines))
    limit = _max_text_chars(config)
    if len(collapsed) > limit:
        collapsed = collapsed[:limit].rstrip() + " [truncated]"
    return collapsed, "document_intelligence_extracted"


def extract_text_with_pypdf(raw_bytes: bytes, *, config: Config) -> tuple[str | None, str]:
    """Extract PDF text with pypdf when Document Intelligence is unavailable."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "pypdf_not_installed"

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        pages: list[str] = []
        for page in reader.pages:
            text = str(page.extract_text() or "").strip()
            if text:
                pages.append(text)
    except Exception as exc:
        logger.warning("pypdf extraction failed: %s", exc)
        return None, "pypdf_failed"

    if not pages:
        return None, "pypdf_empty"

    collapsed = _collapse_ws("\n".join(pages))
    limit = _max_text_chars(config)
    if len(collapsed) > limit:
        collapsed = collapsed[:limit].rstrip() + " [truncated]"
    return collapsed, "pypdf_extracted"


def extract_text_with_pillow(raw_bytes: bytes, *, config: Config) -> tuple[str | None, str]:
    """Best-effort image OCR is not provided by Pillow; return metadata-only signal."""
    try:
        from PIL import Image
    except ImportError:
        return None, "pillow_not_installed"

    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            width, height = image.size
    except Exception as exc:
        logger.warning("Pillow image open failed: %s", exc)
        return None, "pillow_failed"

    return None, f"pillow_image_only_{width}x{height}"


def extract_attachment_semantic_text(
    attachment: ClosedTicketAttachmentInput,
    config: Config,
    *,
    document_intelligence_client: Any = None,
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

    raw_bytes = _bytes_from_raw(attachment.raw_content)
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

    if raw_bytes and content_type in _VISION_CONTENT_TYPES:
        extracted, status = extract_text_with_document_intelligence(
            raw_bytes=raw_bytes,
            content_type=content_type,
            config=config,
            document_intelligence_client=document_intelligence_client,
        )
        if not extracted and content_type in _PDF_CONTENT_TYPES:
            extracted, status = extract_text_with_pypdf(raw_bytes, config=config)
        if not extracted and content_type in _IMAGE_CONTENT_TYPES:
            _, status = extract_text_with_pillow(raw_bytes, config=config)

        if extracted:
            return ClosedTicketAttachmentSemanticResult(
                attachment_id=attachment.attachment_id,
                ticket_id=attachment.ticket_id,
                filename=filename,
                content_type=content_type,
                metadata=metadata,
                semantic_text=extracted,
                extraction_status=status,
            )
        reason = status
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
            extraction_status=reason,
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
    document_intelligence_client: Any = None,
) -> ClosedTicketAttachmentSemanticResult:
    """Extract semantic text and merge extraction fields into attachment metadata."""
    result = extract_attachment_semantic_text(
        attachment,
        config,
        document_intelligence_client=document_intelligence_client,
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
