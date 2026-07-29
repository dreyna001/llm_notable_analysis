"""Configuration for deterministic image and document image extraction."""

from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/gif",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
    }
)


@dataclass(frozen=True)
class ImageExtractionConfig:
    """Bounds and OCR settings for shared image extraction.

    Consumers construct this dataclass explicitly; it does not read environment
    variables. Validation runs in ``__post_init__``.

    Attributes:
        allowed_mime_types: MIME types accepted by ``extract_image_content``.
        max_bytes: Maximum raw payload size in bytes.
        max_pixels: Maximum total pixel count per decoded raster image.
        max_width: Maximum decoded image width in pixels.
        max_height: Maximum decoded image height in pixels.
        max_pdf_pages: Maximum PDF pages rendered and OCR'd.
        max_embedded_images: Maximum embedded images extracted from DOCX payloads.
        max_output_chars: Maximum combined OCR/text output length.
        tesseract_binary: Tesseract executable name or path (no shell).
        tesseract_lang: Tesseract language code passed to ``-l``.
        tesseract_timeout_seconds: Subprocess timeout for one OCR invocation.
    """

    allowed_mime_types: frozenset[str] = _DEFAULT_ALLOWED_MIME_TYPES
    max_bytes: int = 10 * 1024 * 1024
    max_pixels: int = 25_000_000
    max_width: int = 8192
    max_height: int = 8192
    max_pdf_pages: int = 50
    max_embedded_images: int = 20
    max_output_chars: int = 12_000
    tesseract_binary: str = "tesseract"
    tesseract_lang: str = "eng"
    tesseract_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.allowed_mime_types:
            raise ValueError("allowed_mime_types must not be empty")
        normalized = frozenset(
            (item or "").split(";", 1)[0].strip().lower()
            for item in self.allowed_mime_types
            if (item or "").strip()
        )
        if not normalized:
            raise ValueError("allowed_mime_types must contain at least one MIME type")
        object.__setattr__(self, "allowed_mime_types", normalized)

        if self.max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        if self.max_pixels < 1:
            raise ValueError("max_pixels must be >= 1")
        if self.max_width < 1 or self.max_height < 1:
            raise ValueError("max_width and max_height must be >= 1")
        if self.max_pdf_pages < 1:
            raise ValueError("max_pdf_pages must be >= 1")
        if self.max_embedded_images < 1:
            raise ValueError("max_embedded_images must be >= 1")
        if self.max_output_chars < 1:
            raise ValueError("max_output_chars must be >= 1")
        if not (self.tesseract_binary or "").strip():
            raise ValueError("tesseract_binary must not be empty")
        if not (self.tesseract_lang or "").strip():
            raise ValueError("tesseract_lang must not be empty")
        if self.tesseract_timeout_seconds <= 0:
            raise ValueError("tesseract_timeout_seconds must be > 0")
