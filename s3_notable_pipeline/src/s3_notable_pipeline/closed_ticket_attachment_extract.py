"""Attachment semantic extraction for closed-ticket indexing (AWS Textract path)."""

from __future__ import annotations

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
}
_PDF_CONTENT_TYPES = {"application/pdf"}
_TEXTRACT_CONTENT_TYPES = _IMAGE_CONTENT_TYPES | _PDF_CONTENT_TYPES
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


def extract_text_with_textract(
    *,
    raw_bytes: bytes,
    content_type: str,
    config: Config,
    textract_client: Any,
) -> tuple[str | None, str]:
    """Extract document text with Textract detect_document_text (GovCloud)."""
    if not _config_bool(config, "CLOSED_TICKET_VISION_ENABLED", False):
        return None, "textract_disabled"
    if not textract_client:
        return None, "textract_not_configured"
    if len(raw_bytes) > _max_attachment_bytes(config):
        return None, "byte_limit_exceeded"
    if _normalize_content_type(content_type) not in _TEXTRACT_CONTENT_TYPES:
        return None, "unsupported_content_type"

    try:
        response = textract_client.detect_document_text(Document={"Bytes": raw_bytes})
    except Exception as exc:
        logger.warning("Textract detect_document_text failed: %s", exc)
        return None, "textract_failed"

    lines: list[str] = []
    for block in response.get("Blocks", []):
        if not isinstance(block, dict):
            continue
        if block.get("BlockType") != "LINE":
            continue
        text = str(block.get("Text", "")).strip()
        if text:
            lines.append(text)

    if not lines:
        return None, "textract_empty"

    collapsed = _collapse_ws("\n".join(lines))
    limit = _max_text_chars(config)
    if len(collapsed) > limit:
        collapsed = collapsed[:limit].rstrip() + " [truncated]"
    return collapsed, "textract_extracted"


def extract_attachment_semantic_text(
    attachment: ClosedTicketAttachmentInput,
    config: Config,
    *,
    textract_client: Any = None,
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

    if raw_bytes and content_type in _TEXTRACT_CONTENT_TYPES:
        extracted, status = extract_text_with_textract(
            raw_bytes=raw_bytes,
            content_type=content_type,
            config=config,
            textract_client=textract_client,
        )
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
    textract_client: Any = None,
) -> ClosedTicketAttachmentSemanticResult:
    """Extract semantic text and merge extraction fields into attachment metadata."""
    result = extract_attachment_semantic_text(
        attachment,
        config,
        textract_client=textract_client,
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
