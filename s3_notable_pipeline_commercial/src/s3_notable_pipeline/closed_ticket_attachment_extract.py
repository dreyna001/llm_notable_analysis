"""Bounded Textract/OCR extraction for closed-ticket attachments stored in S3."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .closed_ticket_render import ClosedTicketAttachmentRecord
from .config import Config
from .kb_document_extract import (
    STATUS_EXTRACTED,
    STATUS_NO_TEXT,
    STATUS_OUTPUT_TRUNCATED,
    STATUS_PAGE_LIMIT_EXCEEDED,
    STATUS_PARSE_FAILED,
    STATUS_TEXTRACT_FAILED,
    DocumentExtractionResult,
    extract_kb_document,
)
from .opensearch_retrieval import config_value
from .servicenow_closed_ticket_sync import MAX_CHILD_RECORDS_PER_TICKET, _from_ddb_item

logger = logging.getLogger(__name__)

STATUS_VISION_DISABLED = "vision_disabled"
STATUS_BYTE_LIMIT_EXCEEDED = "byte_limit_exceeded"
STATUS_UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
STATUS_NOT_DOWNLOADED = "not_downloaded"
STATUS_S3_READ_FAILED = "s3_read_failed"
STATUS_EXTRACTED_TEXTRACT = "textract_extracted"
STATUS_EXTRACTED_PDF = "pdf_extracted"

_IMAGE_SUFFIXES = frozenset({"png", "jpg", "jpeg"})
_PDF_SUFFIXES = frozenset({"pdf"})
_SUPPORTED_SUFFIXES = _IMAGE_SUFFIXES | _PDF_SUFFIXES

_IMAGE_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
}
_PDF_CONTENT_TYPES = {"application/pdf": "pdf"}


@dataclass(frozen=True)
class ClosedTicketAttachmentExtractionResult:
    """Fail-soft outcome for one attachment extraction attempt."""

    semantic_text: str | None
    extraction_status: str
    extraction_detail: str = ""
    source_suffix: str = ""


def closed_ticket_vision_enabled(config: Config) -> bool:
    """Return True when closed-ticket attachment OCR is enabled."""

    return bool(getattr(config, "CLOSED_TICKET_VISION_ENABLED", False))


def _max_attachment_bytes(config: Config) -> int:
    return max(1, int(getattr(config, "CLOSED_TICKET_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)))


def _suffix_from_attachment(
    *,
    filename: str | None,
    content_type: str | None,
) -> str:
    normalized_type = str(content_type or "").strip().lower().split(";", 1)[0]
    if normalized_type in _IMAGE_CONTENT_TYPES:
        return _IMAGE_CONTENT_TYPES[normalized_type]
    if normalized_type in _PDF_CONTENT_TYPES:
        return _PDF_CONTENT_TYPES[normalized_type]

    name = str(filename or "").strip()
    if name:
        suffix = PurePosixPath(name).suffix.lower().lstrip(".")
        if suffix:
            return suffix
    return ""


def _semantic_text_with_provenance(
    *,
    filename: str | None,
    content_type: str | None,
    body: str,
) -> str:
    header_parts = ["attachment"]
    if filename:
        header_parts.append(f"filename={filename}")
    if content_type:
        header_parts.append(f"content_type={content_type}")
    header = " ".join(header_parts)
    return f"{header}\n---\n{body.strip()}".strip()


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


def _map_extraction_status(
    *,
    suffix: str,
    result: DocumentExtractionResult,
) -> str:
    status = result.extraction_status
    if suffix in _PDF_SUFFIXES:
        if status == STATUS_EXTRACTED:
            return STATUS_EXTRACTED_PDF
        if status in {STATUS_OUTPUT_TRUNCATED, STATUS_PAGE_LIMIT_EXCEEDED}:
            return f"pdf_{status}"
        if status == STATUS_NO_TEXT:
            return "pdf_no_text"
        if status == STATUS_TEXTRACT_FAILED:
            return "pdf_textract_failed"
        if status == STATUS_PARSE_FAILED:
            return "pdf_parse_failed"
        return f"pdf_{status}"
    if status == STATUS_EXTRACTED:
        return STATUS_EXTRACTED_TEXTRACT
    if status in {STATUS_OUTPUT_TRUNCATED, STATUS_NO_TEXT, STATUS_TEXTRACT_FAILED}:
        return f"image_{status}"
    return f"image_{status}"


def _extract_pdf_with_fallback(
    raw: bytes,
    *,
    suffix: str,
    config: Config,
    textract_client: Any | None,
    max_output_chars: int,
) -> DocumentExtractionResult:
    try:
        return extract_kb_document(
            raw,
            suffix=suffix,
            config=config,
            textract_client=textract_client,
        )
    except ValueError:
        pass
    except RuntimeError:
        return DocumentExtractionResult(
            text="",
            extraction_status=STATUS_PARSE_FAILED,
            extraction_detail="pdf extraction prerequisite missing",
            source_suffix=suffix,
        )

    if textract_client is None:
        return DocumentExtractionResult(
            text="",
            extraction_status=STATUS_TEXTRACT_FAILED,
            extraction_detail="textract client is not configured",
            source_suffix=suffix,
        )

    try:
        response = textract_client.detect_document_text(Document={"Bytes": raw})
    except Exception as exc:
        return DocumentExtractionResult(
            text="",
            extraction_status=STATUS_TEXTRACT_FAILED,
            extraction_detail=str(exc),
            source_suffix=suffix,
        )

    lines: list[str] = []
    for block in response.get("Blocks", []) if isinstance(response, dict) else []:
        if not isinstance(block, dict):
            continue
        if block.get("BlockType") == "LINE":
            line = str(block.get("Text", "") or "").strip()
            if line:
                lines.append(line)

    text = "\n".join(lines).strip()
    if not text:
        return DocumentExtractionResult(
            text="",
            extraction_status=STATUS_NO_TEXT,
            extraction_detail="Textract returned no line text for PDF",
            source_suffix=suffix,
        )

    limit = max(1, int(max_output_chars))
    detail = ""
    status = STATUS_EXTRACTED
    if len(text) > limit:
        text = text[:limit]
        status = STATUS_OUTPUT_TRUNCATED
        detail = f"output truncated to {limit} characters"

    return DocumentExtractionResult(
        text=text,
        extraction_status=status,
        extraction_detail=detail,
        source_suffix=suffix,
    )


def extract_closed_ticket_attachment(
    raw: bytes,
    *,
    filename: str | None,
    content_type: str | None,
    config: Config,
    textract_client: Any | None = None,
) -> ClosedTicketAttachmentExtractionResult:
    """Extract searchable text from one closed-ticket attachment payload."""

    if not closed_ticket_vision_enabled(config):
        return ClosedTicketAttachmentExtractionResult(
            semantic_text=None,
            extraction_status=STATUS_VISION_DISABLED,
            extraction_detail="CLOSED_TICKET_VISION_ENABLED=false",
        )

    max_bytes = _max_attachment_bytes(config)
    if len(raw) > max_bytes:
        return ClosedTicketAttachmentExtractionResult(
            semantic_text=None,
            extraction_status=STATUS_BYTE_LIMIT_EXCEEDED,
            extraction_detail=f"attachment exceeds {max_bytes} bytes",
        )

    suffix = _suffix_from_attachment(filename=filename, content_type=content_type)
    if suffix not in _SUPPORTED_SUFFIXES:
        return ClosedTicketAttachmentExtractionResult(
            semantic_text=None,
            extraction_status=STATUS_UNSUPPORTED_CONTENT_TYPE,
            extraction_detail=f"unsupported attachment type: {suffix or content_type or 'unknown'}",
            source_suffix=suffix,
        )

    max_output_chars = int(config_value(config, "KB_EXTRACT_MAX_OUTPUT_CHARS", 12_000))
    if suffix in _PDF_SUFFIXES:
        extraction = _extract_pdf_with_fallback(
            raw,
            suffix=suffix,
            config=config,
            textract_client=textract_client,
            max_output_chars=max_output_chars,
        )
    else:
        extraction = extract_kb_document(
            raw,
            suffix=suffix,
            config=config,
            textract_client=textract_client,
        )

    mapped_status = _map_extraction_status(suffix=suffix, result=extraction)
    text = (extraction.text or "").strip()
    if text:
        return ClosedTicketAttachmentExtractionResult(
            semantic_text=_semantic_text_with_provenance(
                filename=filename,
                content_type=content_type,
                body=text,
            ),
            extraction_status=mapped_status,
            extraction_detail=extraction.extraction_detail,
            source_suffix=suffix,
        )

    return ClosedTicketAttachmentExtractionResult(
        semantic_text=_metadata_only_message(
            filename=filename,
            content_type=content_type,
            reason=mapped_status,
        ),
        extraction_status=mapped_status,
        extraction_detail=extraction.extraction_detail,
        source_suffix=suffix,
    )


def _load_attachment_bytes(
    s3_client: Any,
    *,
    bucket: str,
    storage_key: str,
    max_bytes: int,
) -> bytes | None:
    try:
        response = s3_client.get_object(Bucket=bucket, Key=storage_key)
        body = response["Body"].read()
        if not isinstance(body, bytes):
            body = bytes(body)
        if len(body) > max_bytes:
            return None
        return body
    except Exception as exc:
        logger.warning("failed to read attachment s3://%s/%s: %s", bucket, storage_key, exc)
        return None


def _list_attachment_registry_rows(
    dynamodb_client: Any,
    *,
    table_name: str,
    ticket_id: str,
    max_rows: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    request: dict[str, Any] = {
        "TableName": table_name,
        "FilterExpression": "record_type = :attachment AND ticket_id = :ticket_id",
        "ExpressionAttributeValues": {
            ":attachment": {"S": "attachment"},
            ":ticket_id": {"S": ticket_id},
        },
    }
    while len(rows) < max_rows:
        response = dynamodb_client.scan(**request)
        for item in response.get("Items", []):
            row = _from_ddb_item(item)
            if str(row.get("ticket_id") or "") != ticket_id:
                continue
            rows.append(row)
            if len(rows) >= max_rows:
                break
        last_key = response.get("LastEvaluatedKey")
        if not last_key or len(rows) >= max_rows:
            break
        request["ExclusiveStartKey"] = last_key
    rows.sort(key=lambda row: str(row.get("attachment_id") or ""))
    return rows[:max_rows]


def load_closed_ticket_attachments(
    *,
    ticket_id: str,
    config: Config,
    s3_client: Any,
    dynamodb_client: Any,
    bucket: str,
    textract_client: Any | None = None,
) -> list[ClosedTicketAttachmentRecord]:
    """Load downloaded attachments for one ticket and extract semantic text."""

    if not closed_ticket_vision_enabled(config):
        return []

    table_name = str(config.CLOSED_TICKET_REGISTRY_TABLE or "").strip()
    if not table_name:
        return []

    max_bytes = _max_attachment_bytes(config)
    registry_rows = _list_attachment_registry_rows(
        dynamodb_client,
        table_name=table_name,
        ticket_id=ticket_id,
        max_rows=MAX_CHILD_RECORDS_PER_TICKET,
    )

    attachments: list[ClosedTicketAttachmentRecord] = []
    for row in registry_rows:
        attachment_id = str(row.get("attachment_id") or "").strip()
        if not attachment_id:
            continue
        filename = str(row.get("file_name") or row.get("filename") or "").strip() or None
        content_type = str(row.get("content_type") or "").strip() or None
        download_status = str(row.get("download_status") or "").strip()
        storage_key = str(row.get("storage_key") or "").strip()
        metadata = {
            key: value
            for key, value in row.items()
            if key
            not in {
                "ticket_id",
                "record_type",
                "attachment_id",
                "file_name",
                "filename",
                "content_type",
                "download_status",
                "storage_key",
            }
        }

        if download_status != "downloaded" or not storage_key:
            attachments.append(
                ClosedTicketAttachmentRecord(
                    attachment_id=attachment_id,
                    ticket_id=ticket_id,
                    filename=filename,
                    content_type=content_type,
                    metadata=metadata,
                    semantic_text=_metadata_only_message(
                        filename=filename,
                        content_type=content_type,
                        reason=STATUS_NOT_DOWNLOADED,
                    ),
                    extraction_status=STATUS_NOT_DOWNLOADED,
                )
            )
            continue

        raw = _load_attachment_bytes(
            s3_client,
            bucket=bucket,
            storage_key=storage_key,
            max_bytes=max_bytes,
        )
        if raw is None:
            reason = (
                STATUS_BYTE_LIMIT_EXCEEDED
                if storage_key
                else STATUS_S3_READ_FAILED
            )
            attachments.append(
                ClosedTicketAttachmentRecord(
                    attachment_id=attachment_id,
                    ticket_id=ticket_id,
                    filename=filename,
                    content_type=content_type,
                    metadata={**metadata, "storage_key": storage_key},
                    semantic_text=_metadata_only_message(
                        filename=filename,
                        content_type=content_type,
                        reason=reason,
                    ),
                    extraction_status=reason,
                )
            )
            continue

        extraction = extract_closed_ticket_attachment(
            raw,
            filename=filename,
            content_type=content_type,
            config=config,
            textract_client=textract_client,
        )
        semantic_text = extraction.semantic_text
        if semantic_text is None:
            logger.info(
                "closed ticket attachment skipped ticket=%s attachment=%s status=%s",
                ticket_id,
                attachment_id,
                extraction.extraction_status,
            )
            continue

        attachments.append(
            ClosedTicketAttachmentRecord(
                attachment_id=attachment_id,
                ticket_id=ticket_id,
                filename=filename,
                content_type=content_type,
                metadata={
                    **metadata,
                    "storage_key": storage_key,
                    "extraction_detail": extraction.extraction_detail,
                    "source_suffix": extraction.source_suffix,
                },
                semantic_text=semantic_text,
                extraction_status=extraction.extraction_status,
            )
        )
    return attachments
