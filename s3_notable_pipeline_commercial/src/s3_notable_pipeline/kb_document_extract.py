"""Bounded KB document text extraction for RAG manifest ingest."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from .opensearch_retrieval import config_value

STATUS_EXTRACTED = "extracted"
STATUS_NO_TEXT = "no_text"
STATUS_OUTPUT_TRUNCATED = "output_truncated"
STATUS_PAGE_LIMIT_EXCEEDED = "page_limit_exceeded"
STATUS_TEXTRACT_FAILED = "textract_failed"
STATUS_PARSE_FAILED = "parse_failed"
STATUS_UNSUPPORTED = "unsupported"

PDF_SUFFIXES = frozenset({"pdf"})
DOCX_SUFFIXES = frozenset({"docx"})
IMAGE_SUFFIXES = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
MEDIA_SUFFIXES = PDF_SUFFIXES | DOCX_SUFFIXES | IMAGE_SUFFIXES

FAIL_SOFT_STATUSES = frozenset({STATUS_NO_TEXT, STATUS_TEXTRACT_FAILED})


@dataclass(frozen=True)
class DocumentExtractionResult:
    """Outcome of one bounded media extraction attempt."""

    text: str
    extraction_status: str
    extraction_detail: str = ""
    source_suffix: str = ""


def is_media_suffix(suffix: str) -> bool:
    """Return True when the suffix requires binary extraction."""

    return suffix.lower() in MEDIA_SUFFIXES


def extract_kb_document(
    raw: bytes,
    *,
    suffix: str,
    config: Any,
    textract_client: Any | None = None,
) -> DocumentExtractionResult:
    """Extract searchable text from PDF, DOCX, or raster image bytes."""

    normalized = suffix.lower().strip()
    max_output_chars = int(config_value(config, "KB_EXTRACT_MAX_OUTPUT_CHARS", 12_000))
    if normalized in PDF_SUFFIXES:
        return _extract_pdf(raw, suffix=normalized, config=config, max_output_chars=max_output_chars)
    if normalized in DOCX_SUFFIXES:
        return _extract_docx(raw, suffix=normalized, max_output_chars=max_output_chars)
    if normalized in IMAGE_SUFFIXES:
        return _extract_image(
            raw,
            suffix=normalized,
            textract_client=textract_client,
            max_output_chars=max_output_chars,
        )
    return DocumentExtractionResult(
        text="",
        extraction_status=STATUS_UNSUPPORTED,
        extraction_detail=f"unsupported suffix: {normalized}",
        source_suffix=normalized,
    )


def _extract_pdf(
    raw: bytes,
    *,
    suffix: str,
    config: Any,
    max_output_chars: int,
) -> DocumentExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF KB extraction") from exc

    max_pages = int(config_value(config, "KB_EXTRACT_MAX_PDF_PAGES", 50))
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:
        raise ValueError("invalid PDF document") from exc

    page_count = len(reader.pages)
    if page_count == 0:
        raise ValueError("PDF contains no pages")

    selected_pages = reader.pages[:max_pages]
    parts: list[str] = []
    for page in selected_pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text.strip())

    text = "\n\n".join(parts).strip()
    if not text:
        raise ValueError("PDF contains no extractable text (possibly scanned)")

    status = STATUS_EXTRACTED
    detail = ""
    if page_count > max_pages:
        status = STATUS_PAGE_LIMIT_EXCEEDED
        detail = f"indexed first {max_pages} of {page_count} pages"

    text, truncated = _truncate_output(text, max_output_chars)
    if truncated:
        status = STATUS_OUTPUT_TRUNCATED
        detail = f"output truncated to {max_output_chars} characters"

    return DocumentExtractionResult(
        text=text,
        extraction_status=status,
        extraction_detail=detail,
        source_suffix=suffix,
    )


def _extract_docx(raw: bytes, *, suffix: str, max_output_chars: int) -> DocumentExtractionResult:
    try:
        import docx
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX KB extraction") from exc

    try:
        document = docx.Document(io.BytesIO(raw))
    except Exception as exc:
        raise ValueError("invalid DOCX document") from exc

    paragraphs = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text and paragraph.text.strip()
    ]
    text = "\n".join(paragraphs).strip()
    if not text:
        raise ValueError("DOCX contains no extractable text")

    status = STATUS_EXTRACTED
    detail = ""
    text, truncated = _truncate_output(text, max_output_chars)
    if truncated:
        status = STATUS_OUTPUT_TRUNCATED
        detail = f"output truncated to {max_output_chars} characters"

    return DocumentExtractionResult(
        text=text,
        extraction_status=status,
        extraction_detail=detail,
        source_suffix=suffix,
    )


def _extract_image(
    raw: bytes,
    *,
    suffix: str,
    textract_client: Any | None,
    max_output_chars: int,
) -> DocumentExtractionResult:
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
            extraction_detail="Textract returned no line text",
            source_suffix=suffix,
        )

    status = STATUS_EXTRACTED
    detail = ""
    text, truncated = _truncate_output(text, max_output_chars)
    if truncated:
        status = STATUS_OUTPUT_TRUNCATED
        detail = f"output truncated to {max_output_chars} characters"

    return DocumentExtractionResult(
        text=text,
        extraction_status=status,
        extraction_detail=detail,
        source_suffix=suffix,
    )


def _truncate_output(text: str, max_output_chars: int) -> tuple[str, bool]:
    limit = max(1, int(max_output_chars))
    if len(text) <= limit:
        return text, False
    return text[:limit], True
