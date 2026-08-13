"""Bounded text extraction for KB PDF, DOCX, and image sources."""

from __future__ import annotations

import importlib.util
import io
import re
import xml.etree.ElementTree as ET
from typing import Any
from zipfile import BadZipFile, ZipFile

from .opensearch_retrieval import config_value

_IMAGE_SUFFIXES = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
_RICH_MEDIA_SUFFIXES = frozenset({"pdf", "docx"}) | _IMAGE_SUFFIXES
_SUFFIX_TO_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}
_DOCX_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WHITESPACE_RE = re.compile(r"\s+")


def image_ingest_enabled(config: Any) -> bool:
    """Return whether rich media KB ingest is enabled."""

    value = config_value(config, "IMAGE_INGEST_ENABLED", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def extract_document_text(data: bytes, suffix: str, config: Any) -> str:
    """Extract bounded plain text from one KB document payload."""

    normalized_suffix = (suffix or "").strip().lower().lstrip(".")
    if normalized_suffix not in _RICH_MEDIA_SUFFIXES:
        raise ValueError(f"unsupported KB document suffix: {normalized_suffix or suffix}")

    max_bytes = _positive_int(config, "IMAGE_INGEST_MAX_BYTES", 10 * 1024 * 1024)
    if len(data) > max_bytes:
        raise ValueError(
            f"KB document exceeds IMAGE_INGEST_MAX_BYTES ({max_bytes}): {len(data)} bytes"
        )

    mime = _suffix_to_mime(normalized_suffix)
    allowed = _allowed_mime_types(config)
    if mime not in allowed:
        raise ValueError(f"KB document MIME type not allowed: {mime}")

    if normalized_suffix == "pdf":
        text = _extract_pdf_text(data, config)
    elif normalized_suffix == "docx":
        text = _extract_docx_text(data, config)
    else:
        text = _extract_image_text(data, normalized_suffix, config)

    collapsed = _WHITESPACE_RE.sub(" ", (text or "").strip())
    if not collapsed:
        raise ValueError(f"KB document produced no extractable text: .{normalized_suffix}")

    max_output = _positive_int(config, "IMAGE_INGEST_MAX_OUTPUT_CHARS", 12_000)
    if len(collapsed) > max_output:
        return collapsed[:max_output].rstrip() + " [truncated]"
    return collapsed


def _extract_pdf_text(data: bytes, config: Any) -> str:
    max_pages = _positive_int(config, "IMAGE_INGEST_MAX_PDF_PAGES", 50)
    text = _extract_pdf_with_pypdf(data, max_pages)
    if text is None:
        text = _extract_pdf_with_pdfminer(data, max_pages)
    if text is None:
        raise ValueError(
            "PDF extraction requires pypdf or pdfminer.six; install one dependency in the Lambda image"
        )
    return text


def _extract_pdf_with_pypdf(data: bytes, max_pages: int) -> str | None:
    reader = None
    if _module_available("pypdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
    elif _module_available("PyPDF2"):
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(data))
    if reader is None:
        return None

    parts: list[str] = []
    for index, page in enumerate(reader.pages):
        if index >= max_pages:
            break
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text.strip())
    return "\n\n".join(parts)


def _extract_pdf_with_pdfminer(data: bytes, max_pages: int) -> str | None:
    if not _module_available("pdfminer"):
        return None
    from pdfminer.high_level import extract_text_to_fp

    output = io.StringIO()
    extract_text_to_fp(
        io.BytesIO(data),
        output,
        page_numbers=set(range(max_pages)),
    )
    return output.getvalue()


def _extract_docx_text(data: bytes, config: Any) -> str:
    text = _extract_docx_with_python_docx(data)
    if text is None:
        text = _extract_docx_via_zip_xml(data)
    if text is None:
        raise ValueError(
            "DOCX extraction requires python-docx or a valid word/document.xml payload"
        )

    max_embedded = _positive_int(config, "IMAGE_INGEST_MAX_EMBEDDED_IMAGES", 20)
    embedded_parts = _extract_docx_embedded_image_notes(data, config, max_embedded)
    if embedded_parts:
        combined = "\n\n".join(part for part in [text.strip(), embedded_parts] if part)
        return combined
    return text


def _extract_docx_with_python_docx(data: bytes) -> str | None:
    if not _module_available("docx"):
        return None
    import docx

    document = docx.Document(io.BytesIO(data))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n".join(paragraphs)


def _extract_docx_via_zip_xml(data: bytes) -> str | None:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (BadZipFile, KeyError, OSError):
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    texts: list[str] = []
    for node in root.iter(f"{{{_DOCX_WORD_NS}}}t"):
        if node.text:
            texts.append(node.text)
    return "\n".join(texts).strip() or None


def _extract_docx_embedded_image_notes(
    data: bytes,
    config: Any,
    max_embedded: int,
) -> str:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            media_names = [
                name
                for name in archive.namelist()
                if name.startswith("word/media/") and not name.endswith("/")
            ]
    except (BadZipFile, OSError):
        return ""

    if not media_names:
        return ""

    notes: list[str] = []
    for index, name in enumerate(media_names[:max_embedded], start=1):
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix not in _IMAGE_SUFFIXES:
            continue
        notes.append(f"[Embedded image {index}: {name}]")
    if len(media_names) > max_embedded:
        notes.append(
            f"[Embedded image limit exceeded: {len(media_names)} present, {max_embedded} allowed]"
        )
    return "\n".join(notes)


def _extract_image_text(data: bytes, suffix: str, config: Any) -> str:
    use_textract = _bool_config(config, "IMAGE_INGEST_USE_TEXTRACT", False)
    if use_textract:
        return _extract_image_with_textract(data)

    return _extract_image_placeholder(data, suffix, config)


def _extract_image_with_textract(data: bytes) -> str:
    from .aws_clients import aws_client

    client = aws_client("textract")
    response = client.detect_document_text(Document={"Bytes": data})
    lines = [
        str(block.get("Text", "")).strip()
        for block in response.get("Blocks", [])
        if block.get("BlockType") == "LINE" and str(block.get("Text", "")).strip()
    ]
    if not lines:
        raise ValueError("Textract returned no text for image document")
    return "\n".join(lines)


def _extract_image_placeholder(data: bytes, suffix: str, config: Any) -> str:
    if not _module_available("PIL"):
        return (
            f"[Image ingest: OCR disabled; Pillow unavailable; "
            f"suffix=.{suffix}; bytes={len(data)}]"
        )

    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"invalid image payload for .{suffix}") from exc

    width, height = image.size
    max_width = _positive_int(config, "IMAGE_INGEST_MAX_WIDTH", 8192)
    max_height = _positive_int(config, "IMAGE_INGEST_MAX_HEIGHT", 8192)
    max_pixels = _positive_int(config, "IMAGE_INGEST_MAX_PIXELS", 25_000_000)
    if width > max_width or height > max_height:
        raise ValueError(
            f"image dimensions exceed limits ({width}x{height}); "
            f"max {max_width}x{max_height}"
        )
    if width * height > max_pixels:
        raise ValueError(
            f"image pixel count exceeds IMAGE_INGEST_MAX_PIXELS ({max_pixels})"
        )

    decoded_format = (image.format or suffix).upper()
    return (
        f"[Image ingest: OCR disabled; image {width}x{height} {decoded_format}; "
        "enable IMAGE_INGEST_USE_TEXTRACT for text extraction]"
    )


def _suffix_to_mime(suffix: str) -> str:
    mime = _SUFFIX_TO_MIME.get(suffix)
    if not mime:
        raise ValueError(f"unsupported KB document suffix: {suffix}")
    return mime


def _allowed_mime_types(config: Any) -> frozenset[str]:
    raw = str(
        config_value(
            config,
            "IMAGE_INGEST_ALLOWED_MIME_TYPES",
            "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "image/gif,image/jpeg,image/jpg,image/png,image/webp",
        )
    )
    values = {
        item.split(";", 1)[0].strip().lower()
        for item in raw.replace(";", ",").split(",")
        if item.strip()
    }
    if not values:
        raise ValueError("IMAGE_INGEST_ALLOWED_MIME_TYPES must contain at least one MIME type")
    return frozenset(values)


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _positive_int(config: Any, name: str, default: int) -> int:
    value = int(config_value(config, name, default))
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def _bool_config(config: Any, name: str, default: bool) -> bool:
    value = config_value(config, name, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
