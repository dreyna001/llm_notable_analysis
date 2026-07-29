"""Deterministic shared extraction for raster images, PDF, and DOCX embedded images."""
from __future__ import annotations
import importlib.util
import io
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence
from zipfile import BadZipFile, ZipFile
from .image_extraction_config import ImageExtractionConfig
from .image_vision import (
    STATUS_VISION_DESCRIBED,
    STATUS_VISION_FAILED,
    STATUS_VISION_PARTIAL,
    ImageVisionResult,
)
logger = logging.getLogger(__name__)
# Stable extraction status values for callers and tests.
STATUS_EXTRACTED = "extracted"
STATUS_MIME_MISMATCH = "mime_mismatch"
STATUS_INVALID_IMAGE = "invalid_image"
STATUS_BYTE_LIMIT_EXCEEDED = "byte_limit_exceeded"
STATUS_PIXEL_LIMIT_EXCEEDED = "pixel_limit_exceeded"
STATUS_PAGE_LIMIT_EXCEEDED = "page_limit_exceeded"
STATUS_EMBEDDED_IMAGE_LIMIT_EXCEEDED = "embedded_image_limit_exceeded"
STATUS_OUTPUT_TRUNCATED = "output_truncated"
STATUS_OCR_EMPTY = "ocr_empty"
STATUS_OCR_FAILED = "ocr_failed"
STATUS_OCR_TIMEOUT = "ocr_timeout"
STATUS_PREREQUISITE_MISSING = "prerequisite_missing"
STATUS_UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
STATUS_EMPTY_CONTENT = "empty_content"
# Prerequisite identifiers surfaced in ``error_message`` when status is
# ``prerequisite_missing``. Callers may branch on these stable tokens.
PREREQ_PILLOW = "pillow"
PREREQ_PYPDFIUM2 = "pypdfium2"
PREREQ_PYTHON_DOCX = "python_docx"
PREREQ_TESSERACT = "tesseract"
_LABEL_VISION = "[Vision description (advisory)]"
_LABEL_OCR = "[OCR text]"
_STANDALONE_IMAGE_MIMES = frozenset(
    {"image/gif", "image/jpeg", "image/jpg", "image/png", "image/webp"}
)
_PDF_MIMES = frozenset({"application/pdf"})
_DOCX_MIMES = frozenset(
    {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
)
_MIME_TO_PIL_FORMAT: dict[str, str] = {
    "image/gif": "GIF",
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_TesseractRunner = Callable[[Path, ImageExtractionConfig], tuple[str | None, str]]
_PdfPageRenderer = Callable[[bytes, int, ImageExtractionConfig], bytes | None]
VisionDescriber = Callable[[bytes, str], ImageVisionResult]

@dataclass

class _VisionAccumulator:
    """Tracks advisory vision outcomes across one or more validated rasters."""
    attempts: int = 0
    described: int = 0
    failed: int = 0
    warnings: list[str] = field(default_factory=list)
    def record(self, result: ImageVisionResult, *, context: str) -> str | None:
        self.attempts += 1
        if result.status == STATUS_VISION_DESCRIBED and result.description:
            self.described += 1
            return result.description
        self.failed += 1
        detail = result.error_message or result.status
        self.warnings.append(f"{context}: vision unavailable ({detail})")
        return None
    def overall_status(self) -> str | None:
        if self.attempts == 0:
            return None
        if self.described == self.attempts:
            return STATUS_VISION_DESCRIBED
        if self.described == 0:
            return STATUS_VISION_FAILED
        return STATUS_VISION_PARTIAL
    def as_result_fields(self) -> dict[str, object]:
        return {
            "vision_status": self.overall_status(),
            "vision_raster_attempts": self.attempts,
            "vision_raster_described": self.described,
            "vision_raster_failed": self.failed,
            "vision_warnings": tuple(self.warnings),
        }

@dataclass(frozen=True)

class ImageExtractionResult:
    """Structured output from ``extract_image_content``."""
    status: str
    text: str | None
    source_mime: str | None
    decoded_format: str | None = None
    page_count: int | None = None
    embedded_image_count: int | None = None
    truncated: bool = False
    error_message: str | None = None
    vision_status: str | None = None
    vision_raster_attempts: int = 0
    vision_raster_described: int = 0
    vision_raster_failed: int = 0
    vision_warnings: tuple[str, ...] = ()

def _normalize_mime(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()

def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None

def _prerequisite_result(
    *,
    source_mime: str | None,
    prerequisite: str,
) -> ImageExtractionResult:
    return ImageExtractionResult(
        status=STATUS_PREREQUISITE_MISSING,
        text=None,
        source_mime=source_mime,
        error_message=prerequisite,
    )

def _truncate_text(text: str, config: ImageExtractionConfig) -> tuple[str, bool]:
    collapsed = " ".join(text.split())
    if len(collapsed) <= config.max_output_chars:
        return collapsed, False
    trimmed = collapsed[: config.max_output_chars].rstrip() + " [truncated]"
    return trimmed, True

def _combine_labeled_raster_text(
    *,
    vision_text: str | None,
    ocr_text: str | None,
    unit_label: str = "",
) -> str | None:
    vision = (vision_text or "").strip()
    ocr = (ocr_text or "").strip()
    if not vision:
        return ocr or None
    prefix = f"{unit_label} " if unit_label else ""
    parts: list[str] = [f"{prefix}{_LABEL_VISION}\n{vision}"]
    if ocr:
        parts.append(f"{prefix}{_LABEL_OCR}\n{ocr}")
    return "\n\n".join(parts)

def _pil_image_to_png_bytes(image) -> bytes:
    buffer = io.BytesIO()
    cleaned = image.convert("RGB")
    cleaned.save(buffer, format="PNG")
    return buffer.getvalue()

def _describe_validated_raster(
    image,
    *,
    content_type: str,
    vision_describer: VisionDescriber | None,
    context: str,
    accumulator: _VisionAccumulator,
) -> str | None:
    if vision_describer is None:
        return None
    png_bytes = _pil_image_to_png_bytes(image)
    try:
        vision_result = vision_describer(png_bytes, content_type)
    except Exception as exc:
        logger.warning("Vision callback failed for %s: %s", context, exc.__class__.__name__)
        accumulator.attempts += 1
        accumulator.failed += 1
        accumulator.warnings.append(f"{context}: vision unavailable ({exc.__class__.__name__})")
        return None
    return accumulator.record(vision_result, context=context)

def _finalize_text(
    parts: Sequence[str],
    *,
    source_mime: str | None,
    decoded_format: str | None,
    config: ImageExtractionConfig,
    page_count: int | None = None,
    embedded_image_count: int | None = None,
    page_limit_hit: bool = False,
    embedded_limit_hit: bool = False,
    vision: _VisionAccumulator | None = None,
) -> ImageExtractionResult:
    combined = "\n".join(part.strip() for part in parts if part and part.strip())
    vision_fields = vision.as_result_fields() if vision is not None else {}
    if not combined:
        return ImageExtractionResult(
            status=STATUS_OCR_EMPTY,
            text=None,
            source_mime=source_mime,
            decoded_format=decoded_format,
            page_count=page_count,
            embedded_image_count=embedded_image_count,
            **vision_fields,
        )
    text, truncated = _truncate_text(combined, config)
    status = STATUS_EXTRACTED
    if truncated:
        status = STATUS_OUTPUT_TRUNCATED
    elif page_limit_hit:
        status = STATUS_PAGE_LIMIT_EXCEEDED
    elif embedded_limit_hit:
        status = STATUS_EMBEDDED_IMAGE_LIMIT_EXCEEDED
    return ImageExtractionResult(
        status=status,
        text=text,
        source_mime=source_mime,
        decoded_format=decoded_format,
        page_count=page_count,
        embedded_image_count=embedded_image_count,
        truncated=truncated,
        **vision_fields,
    )

def _load_pillow_image(data: bytes):
    if not _module_available("PIL"):
        return None, PREREQ_PILLOW
    from PIL import Image, UnidentifiedImageError
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image, None
    except UnidentifiedImageError:
        return None, STATUS_INVALID_IMAGE
    except OSError:
        return None, STATUS_INVALID_IMAGE

def _strip_exif_and_save(image, destination: Path) -> None:
    """Write a raster without EXIF metadata for OCR subprocess input."""
    from PIL import Image
    cleaned = image.convert("RGB")
    cleaned.save(destination, format="PNG")

def _validate_raster_bounds(image, config: ImageExtractionConfig) -> str | None:
    width, height = image.size
    pixels = width * height
    if width > config.max_width or height > config.max_height:
        return STATUS_PIXEL_LIMIT_EXCEEDED
    if pixels > config.max_pixels:
        return STATUS_PIXEL_LIMIT_EXCEEDED
    return None

def _default_tesseract_runner(image_path: Path, config: ImageExtractionConfig) -> tuple[str | None, str]:
    if shutil.which(config.tesseract_binary) is None:
        return None, PREREQ_TESSERACT
    argv = [
        config.tesseract_binary,
        str(image_path),
        "stdout",
        "-l",
        config.tesseract_lang,
        "--oem",
        "1",
        "--psm",
        "3",
    ]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            timeout=config.tesseract_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, STATUS_OCR_TIMEOUT
    except OSError as exc:
        logger.warning("Tesseract invocation failed: %s", exc.__class__.__name__)
        return None, STATUS_OCR_FAILED
    if completed.returncode != 0:
        return None, STATUS_OCR_FAILED
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return None, STATUS_OCR_EMPTY
    return text, STATUS_EXTRACTED

def _ocr_pil_image(
    image,
    *,
    config: ImageExtractionConfig,
    tesseract_runner: _TesseractRunner,
) -> tuple[str | None, str]:
    bound_error = _validate_raster_bounds(image, config)
    if bound_error:
        return None, bound_error
    with tempfile.TemporaryDirectory(prefix="img_extract_") as tmpdir:
        image_path = Path(tmpdir) / "frame.png"
        _strip_exif_and_save(image, image_path)
        return tesseract_runner(image_path, config)

def _extract_standalone_image(
    data: bytes,
    *,
    source_mime: str,
    config: ImageExtractionConfig,
    tesseract_runner: _TesseractRunner,
    vision_describer: VisionDescriber | None = None,
) -> ImageExtractionResult:
    if not _module_available("PIL"):
        return _prerequisite_result(source_mime=source_mime, prerequisite=PREREQ_PILLOW)
    image, load_error = _load_pillow_image(data)
    if load_error == PREREQ_PILLOW:
        return _prerequisite_result(source_mime=source_mime, prerequisite=PREREQ_PILLOW)
    if image is None:
        return ImageExtractionResult(
            status=STATUS_INVALID_IMAGE,
            text=None,
            source_mime=source_mime,
        )
    expected_format = _MIME_TO_PIL_FORMAT.get(source_mime)
    decoded_format = (image.format or "").upper()
    if expected_format and decoded_format and decoded_format != expected_format:
        return ImageExtractionResult(
            status=STATUS_MIME_MISMATCH,
            text=None,
            source_mime=source_mime,
            decoded_format=decoded_format,
        )
    if source_mime == "image/gif":
        try:
            image.seek(0)
        except EOFError:
            return ImageExtractionResult(
                status=STATUS_INVALID_IMAGE,
                text=None,
                source_mime=source_mime,
                decoded_format=decoded_format or "GIF",
            )
    text, ocr_status = _ocr_pil_image(
        image,
        config=config,
        tesseract_runner=tesseract_runner,
    )
    if ocr_status == PREREQ_TESSERACT:
        return _prerequisite_result(source_mime=source_mime, prerequisite=PREREQ_TESSERACT)
    if ocr_status == STATUS_PIXEL_LIMIT_EXCEEDED:
        return ImageExtractionResult(
            status=STATUS_PIXEL_LIMIT_EXCEEDED,
            text=None,
            source_mime=source_mime,
            decoded_format=decoded_format or expected_format,
        )
    if ocr_status in {STATUS_OCR_FAILED, STATUS_OCR_TIMEOUT}:
        return ImageExtractionResult(
            status=ocr_status,
            text=None,
            source_mime=source_mime,
            decoded_format=decoded_format or expected_format,
        )
    vision = _VisionAccumulator()
    vision_text = _describe_validated_raster(
        image,
        content_type=source_mime,
        vision_describer=vision_describer,
        context="standalone image",
        accumulator=vision,
    )
    ocr_text = text if ocr_status == STATUS_EXTRACTED and text else None
    combined = _combine_labeled_raster_text(vision_text=vision_text, ocr_text=ocr_text)
    vision_fields = vision.as_result_fields()
    if not combined:
        return ImageExtractionResult(
            status=STATUS_OCR_EMPTY,
            text=None,
            source_mime=source_mime,
            decoded_format=decoded_format or expected_format,
            **vision_fields,
        )
    final_text, truncated = _truncate_text(combined, config)
    status = STATUS_OUTPUT_TRUNCATED if truncated else STATUS_EXTRACTED
    return ImageExtractionResult(
        status=status,
        text=final_text,
        source_mime=source_mime,
        decoded_format=decoded_format or expected_format,
        truncated=truncated,
        **vision_fields,
    )

def _default_pdf_page_renderer(data: bytes, page_index: int, config: ImageExtractionConfig) -> bytes | None:
    if not _module_available("pypdfium2"):
        return None
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    if page_index < 0 or page_index >= len(pdf):
        return None
    page = pdf[page_index]
    bitmap = page.render(scale=1.0)
    pil_image = bitmap.to_pil()
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    return buffer.getvalue()

def _extract_pdf(
    data: bytes,
    *,
    source_mime: str,
    config: ImageExtractionConfig,
    tesseract_runner: _TesseractRunner,
    pdf_page_renderer: _PdfPageRenderer,
    vision_describer: VisionDescriber | None = None,
) -> ImageExtractionResult:
    if not _module_available("pypdfium2"):
        return _prerequisite_result(source_mime=source_mime, prerequisite=PREREQ_PYPDFIUM2)
    if not _module_available("PIL"):
        return _prerequisite_result(source_mime=source_mime, prerequisite=PREREQ_PILLOW)
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        return ImageExtractionResult(
            status=STATUS_INVALID_IMAGE,
            text=None,
            source_mime=source_mime,
            decoded_format="PDF",
        )
    total_pages = len(pdf)
    pages_to_render = min(total_pages, config.max_pdf_pages)
    page_limit_hit = total_pages > config.max_pdf_pages
    text_parts: list[str] = []
    vision = _VisionAccumulator()
    for page_index in range(pages_to_render):
        rendered = pdf_page_renderer(data, page_index, config)
        if rendered is None:
            return ImageExtractionResult(
                status=STATUS_INVALID_IMAGE,
                text=None,
                source_mime=source_mime,
                decoded_format="PDF",
                page_count=total_pages,
                **vision.as_result_fields(),
            )
        image, load_error = _load_pillow_image(rendered)
        if load_error == PREREQ_PILLOW or image is None:
            return ImageExtractionResult(
                status=STATUS_INVALID_IMAGE,
                text=None,
                source_mime=source_mime,
                decoded_format="PDF",
                page_count=total_pages,
                **vision.as_result_fields(),
            )
        page_text, ocr_status = _ocr_pil_image(
            image,
            config=config,
            tesseract_runner=tesseract_runner,
        )
        if ocr_status == PREREQ_TESSERACT:
            return _prerequisite_result(source_mime=source_mime, prerequisite=PREREQ_TESSERACT)
        if ocr_status == STATUS_PIXEL_LIMIT_EXCEEDED:
            return ImageExtractionResult(
                status=STATUS_PIXEL_LIMIT_EXCEEDED,
                text=None,
                source_mime=source_mime,
                decoded_format="PDF",
                page_count=total_pages,
                **vision.as_result_fields(),
            )
        if ocr_status in {STATUS_OCR_FAILED, STATUS_OCR_TIMEOUT}:
            return ImageExtractionResult(
                status=ocr_status,
                text=None,
                source_mime=source_mime,
                decoded_format="PDF",
                page_count=total_pages,
                **vision.as_result_fields(),
            )
        page_label = f"[Page {page_index + 1}]"
        vision_text = _describe_validated_raster(
            image,
            content_type="image/png",
            vision_describer=vision_describer,
            context=f"PDF page {page_index + 1}",
            accumulator=vision,
        )
        ocr_text = page_text if page_text else None
        if vision_describer is None:
            if ocr_text:
                text_parts.append(ocr_text)
            continue
        combined = _combine_labeled_raster_text(
            vision_text=vision_text,
            ocr_text=ocr_text,
            unit_label=page_label,
        )
        if combined:
            text_parts.append(combined)
    return _finalize_text(
        text_parts,
        source_mime=source_mime,
        decoded_format="PDF",
        config=config,
        page_count=total_pages,
        page_limit_hit=page_limit_hit,
        vision=vision,
    )

def _docx_media_entries(data: bytes) -> tuple[list[tuple[str, bytes]] | None, str | None]:
    if not _module_available("docx"):
        return None, PREREQ_PYTHON_DOCX
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            entries = [
                (name, archive.read(name))
                for name in archive.namelist()
                if name.startswith("word/media/") and not name.endswith("/")
            ]
    except BadZipFile:
        return None, STATUS_INVALID_IMAGE
    except OSError:
        return None, STATUS_INVALID_IMAGE
    return entries, None

def _extract_docx(
    data: bytes,
    *,
    source_mime: str,
    config: ImageExtractionConfig,
    tesseract_runner: _TesseractRunner,
    vision_describer: VisionDescriber | None = None,
) -> ImageExtractionResult:
    entries, error = _docx_media_entries(data)
    if error == PREREQ_PYTHON_DOCX:
        return _prerequisite_result(source_mime=source_mime, prerequisite=PREREQ_PYTHON_DOCX)
    if entries is None:
        return ImageExtractionResult(
            status=STATUS_INVALID_IMAGE,
            text=None,
            source_mime=source_mime,
            decoded_format="DOCX",
        )
    image_entries = [
        (name, payload)
        for name, payload in entries
        if payload and _MIME_TO_PIL_FORMAT.get(_guess_media_mime(name))
    ]
    total_images = len(image_entries)
    selected = image_entries[: config.max_embedded_images]
    embedded_limit_hit = total_images > config.max_embedded_images
    text_parts: list[str] = []
    vision = _VisionAccumulator()
    for index, (name, payload) in enumerate(selected, 1):
        guessed_mime = _guess_media_mime(name)
        if guessed_mime not in config.allowed_mime_types:
            continue
        result = _extract_standalone_image(
            payload,
            source_mime=guessed_mime,
            config=config,
            tesseract_runner=tesseract_runner,
            vision_describer=vision_describer,
        )
        if result.status == STATUS_PREREQUISITE_MISSING:
            return result
        if result.status == STATUS_PIXEL_LIMIT_EXCEEDED:
            return result
        if result.status in {STATUS_OCR_FAILED, STATUS_OCR_TIMEOUT}:
            return result
        vision.attempts += result.vision_raster_attempts
        vision.described += result.vision_raster_described
        vision.failed += result.vision_raster_failed
        vision.warnings.extend(result.vision_warnings)
        if result.text:
            embedded_label = f"[Embedded image {index}]"
            text_parts.append(f"{embedded_label}\n{result.text}")
    return _finalize_text(
        text_parts,
        source_mime=source_mime,
        decoded_format="DOCX",
        config=config,
        embedded_image_count=total_images,
        embedded_limit_hit=embedded_limit_hit,
        vision=vision,
    )

def _guess_media_mime(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"

def extract_image_content(
    data: bytes,
    *,
    content_type: str,
    config: ImageExtractionConfig,
    tesseract_runner: _TesseractRunner | None = None,
    pdf_page_renderer: _PdfPageRenderer | None = None,
    vision_describer: VisionDescriber | None = None,
) -> ImageExtractionResult:
    """Extract OCR text from supported image, PDF, or DOCX payloads.
    When ``vision_describer`` is provided, each bounds-validated raster also
    receives an advisory vision description. OCR remains deterministic; vision
    failures are recorded in ``vision_status`` / ``vision_warnings`` while
    preserving any OCR text in ``text``.
    Missing optional dependencies or the Tesseract binary yield
    ``status=prerequisite_missing`` and ``error_message`` set to one of:
    ``pillow``, ``pypdfium2``, ``python_docx``, or ``tesseract``.
    """
    runner = tesseract_runner or _default_tesseract_runner
    renderer = pdf_page_renderer or _default_pdf_page_renderer
    source_mime = _normalize_mime(content_type)
    if not data:
        return ImageExtractionResult(
            status=STATUS_EMPTY_CONTENT,
            text=None,
            source_mime=source_mime or None,
        )
    if len(data) > config.max_bytes:
        return ImageExtractionResult(
            status=STATUS_BYTE_LIMIT_EXCEEDED,
            text=None,
            source_mime=source_mime or None,
        )
    if source_mime not in config.allowed_mime_types:
        return ImageExtractionResult(
            status=STATUS_UNSUPPORTED_CONTENT_TYPE,
            text=None,
            source_mime=source_mime or None,
        )
    if source_mime in _STANDALONE_IMAGE_MIMES:
        return _extract_standalone_image(
            data,
            source_mime=source_mime,
            config=config,
            tesseract_runner=runner,
            vision_describer=vision_describer,
        )
    if source_mime in _PDF_MIMES:
        return _extract_pdf(
            data,
            source_mime=source_mime,
            config=config,
            tesseract_runner=runner,
            pdf_page_renderer=renderer,
            vision_describer=vision_describer,
        )
    if source_mime in _DOCX_MIMES:
        return _extract_docx(
            data,
            source_mime=source_mime,
            config=config,
            tesseract_runner=runner,
            vision_describer=vision_describer,
        )
    return ImageExtractionResult(
        status=STATUS_UNSUPPORTED_CONTENT_TYPE,
        text=None,
        source_mime=source_mime or None,
    )
