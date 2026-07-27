"""Attachment semantic extraction helpers for closed-ticket indexing."""

# Vision calls use stdlib HTTP only and fail soft when disabled or unavailable.
# pylint: disable=broad-exception-caught

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

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
_WHITESPACE_RE = re.compile(r"\s+")


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


def _max_attachment_bytes(config: Config) -> int:
    return max(1, int(getattr(config, "CLOSED_TICKET_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)))


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


def _image_data_url(content_type: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def describe_image_with_vision_model(
    *,
    image_bytes: bytes,
    content_type: str,
    config: Config,
    http_client: Any = None,
) -> tuple[str | None, str]:
    """Call an optional OpenAI-compatible vision endpoint; fails soft when disabled."""
    if not _config_bool(config, "CLOSED_TICKET_VISION_ENABLED", False):
        return None, "vision_disabled"
    api_base = str(getattr(config, "CLOSED_TICKET_VISION_API_BASE", "") or "").strip().rstrip("/")
    model = str(getattr(config, "CLOSED_TICKET_VISION_MODEL", "") or "").strip()
    if not api_base or not model:
        return None, "vision_not_configured"
    timeout = float(getattr(config, "CLOSED_TICKET_VISION_TIMEOUT_SECONDS", 30.0))
    api_key = str(getattr(config, "CLOSED_TICKET_VISION_API_KEY", "") or "").strip()
    data_url = _image_data_url(content_type, image_bytes)
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Describe this image for a security operations analyst. "
                            "State only what is visible. Do not infer intent or malware."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": int(getattr(config, "CLOSED_TICKET_VISION_MAX_TOKENS", 400)),
    }
    payload = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = f"{api_base}/chat/completions"
    try:
        if http_client is not None:
            response_bytes = http_client(url, payload, headers, timeout)
        else:
            req = urllib_request.Request(url, data=payload, headers=headers, method="POST")
            with urllib_request.urlopen(req, timeout=timeout) as response:
                response_bytes = response.read()
        parsed = json.loads(response_bytes.decode("utf-8"))
        choices = parsed.get("choices") or []
        if not choices:
            return None, "vision_empty_response"
        message = choices[0].get("message") or {}
        content = _collapse_ws(str(message.get("content") or ""))
        if not content:
            return None, "vision_empty_response"
        return content, "vision_described"
    except Exception as exc:
        logger.warning("Closed-ticket vision extraction failed: %s", exc)
        return None, "vision_failed"


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

    if content_type in _PDF_CONTENT_TYPES:
        status = "pdf_unsupported_metadata_only"
        semantic = _metadata_only_message(
            filename=filename,
            content_type=content_type,
            reason="pdf_ocr_unsupported",
        )
        return ClosedTicketAttachmentSemanticResult(
            attachment_id=attachment.attachment_id,
            ticket_id=attachment.ticket_id,
            filename=filename,
            content_type=content_type,
            metadata=metadata,
            semantic_text=semantic,
            extraction_status=status,
        )

    raw_bytes = _attachment_payload_bytes(attachment, config)
    if content_type in _IMAGE_CONTENT_TYPES and raw_bytes:
        description, status = describe_image_with_vision_model(
            image_bytes=raw_bytes,
            content_type=content_type,
            config=config,
            http_client=http_client,
        )
        if description:
            return ClosedTicketAttachmentSemanticResult(
                attachment_id=attachment.attachment_id,
                ticket_id=attachment.ticket_id,
                filename=filename,
                content_type=content_type,
                metadata=metadata,
                semantic_text=description,
                extraction_status=status,
            )
        semantic = _metadata_only_message(
            filename=filename,
            content_type=content_type,
            reason=status,
        )
        return ClosedTicketAttachmentSemanticResult(
            attachment_id=attachment.attachment_id,
            ticket_id=attachment.ticket_id,
            filename=filename,
            content_type=content_type,
            metadata=metadata,
            semantic_text=semantic,
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
