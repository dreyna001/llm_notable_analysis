"""Tests for shared image extraction core."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from onprem_rag_notable_analysis.future.image_extraction import (
    PREREQ_PILLOW,
    PREREQ_PYPDFIUM2,
    PREREQ_PYTHON_DOCX,
    PREREQ_TESSERACT,
    STATUS_BYTE_LIMIT_EXCEEDED,
    STATUS_EMBEDDED_IMAGE_LIMIT_EXCEEDED,
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
    extract_image_content,
)
from onprem_rag_notable_analysis.future.image_extraction_config import (
    ImageExtractionConfig,
)
from onprem_rag_notable_analysis.future.image_vision import (
    STATUS_VISION_DESCRIBED,
    STATUS_VISION_FAILED,
    ImageVisionResult,
)


def _make_png_bytes(*, width: int = 32, height: int = 32, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), rgb)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _make_png_with_exif_bytes() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (24, 24), (0, 128, 255))
    exif = image.getexif()
    exif[270] = "SensitiveCameraMetadata"
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _make_docx_with_images(image_payloads: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        archive.writestr("word/document.xml", "<w:document></w:document>")
        for name, payload in image_payloads:
            archive.writestr(f"word/media/{name}", payload)
    return buffer.getvalue()


class TestImageExtractionConfig(unittest.TestCase):
    def test_defaults_validate(self) -> None:
        config = ImageExtractionConfig()
        self.assertIn("image/png", config.allowed_mime_types)
        self.assertEqual(config.max_bytes, 10 * 1024 * 1024)

    def test_invalid_bounds_raise(self) -> None:
        with self.assertRaises(ValueError):
            ImageExtractionConfig(max_bytes=0)


class TestImageExtraction(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ImageExtractionConfig(max_output_chars=500)

    def test_valid_png_extracts_with_mock_ocr(self) -> None:
        png_bytes = _make_png_bytes()

        def fake_tesseract(_path: Path, _config: ImageExtractionConfig) -> tuple[str | None, str]:
            return "HELLO PNG", STATUS_EXTRACTED

        result = extract_image_content(
            png_bytes,
            content_type="image/png",
            config=self.config,
            tesseract_runner=fake_tesseract,
        )
        self.assertEqual(result.status, STATUS_EXTRACTED)
        self.assertEqual(result.text, "HELLO PNG")
        self.assertEqual(result.decoded_format, "PNG")

    def test_mime_mismatch_rejected(self) -> None:
        png_bytes = _make_png_bytes()

        result = extract_image_content(
            png_bytes,
            content_type="image/jpeg",
            config=self.config,
            tesseract_runner=lambda _p, _c: ("ignored", STATUS_EXTRACTED),
        )
        self.assertEqual(result.status, STATUS_MIME_MISMATCH)
        self.assertIsNone(result.text)
        self.assertEqual(result.decoded_format, "PNG")

    def test_bad_image_bytes_invalid(self) -> None:
        result = extract_image_content(
            b"not-an-image",
            content_type="image/png",
            config=self.config,
            tesseract_runner=lambda _p, _c: ("ignored", STATUS_EXTRACTED),
        )
        self.assertEqual(result.status, STATUS_INVALID_IMAGE)

    def test_byte_limit_enforced(self) -> None:
        tight = ImageExtractionConfig(max_bytes=16)
        result = extract_image_content(
            _make_png_bytes(width=64, height=64),
            content_type="image/png",
            config=tight,
            tesseract_runner=lambda _p, _c: ("ignored", STATUS_EXTRACTED),
        )
        self.assertEqual(result.status, STATUS_BYTE_LIMIT_EXCEEDED)

    def test_pixel_limit_enforced(self) -> None:
        tight = ImageExtractionConfig(max_width=8, max_height=8, max_pixels=64)
        result = extract_image_content(
            _make_png_bytes(width=32, height=32),
            content_type="image/png",
            config=tight,
            tesseract_runner=lambda _p, _c: ("ignored", STATUS_EXTRACTED),
        )
        self.assertEqual(result.status, STATUS_PIXEL_LIMIT_EXCEEDED)

    def test_exif_not_present_in_output(self) -> None:
        jpeg_with_exif = _make_png_with_exif_bytes()

        def fake_tesseract(path: Path, _config: ImageExtractionConfig) -> tuple[str | None, str]:
            saved = path.read_bytes()
            self.assertNotIn(b"SensitiveCameraMetadata", saved)
            return "visible text only", STATUS_EXTRACTED

        result = extract_image_content(
            jpeg_with_exif,
            content_type="image/jpeg",
            config=self.config,
            tesseract_runner=fake_tesseract,
        )
        self.assertEqual(result.status, STATUS_EXTRACTED)
        self.assertEqual(result.text, "visible text only")
        self.assertNotIn("SensitiveCameraMetadata", result.text or "")

    def test_ocr_success_empty_and_timeout_and_failure(self) -> None:
        png_bytes = _make_png_bytes()

        empty = extract_image_content(
            png_bytes,
            content_type="image/png",
            config=self.config,
            tesseract_runner=lambda _p, _c: (None, STATUS_OCR_EMPTY),
        )
        self.assertEqual(empty.status, STATUS_OCR_EMPTY)

        timeout = extract_image_content(
            png_bytes,
            content_type="image/png",
            config=self.config,
            tesseract_runner=lambda _p, _c: (None, STATUS_OCR_TIMEOUT),
        )
        self.assertEqual(timeout.status, STATUS_OCR_TIMEOUT)

        failed = extract_image_content(
            png_bytes,
            content_type="image/png",
            config=self.config,
            tesseract_runner=lambda _p, _c: (None, STATUS_OCR_FAILED),
        )
        self.assertEqual(failed.status, STATUS_OCR_FAILED)

    def test_pdf_page_cap_and_render_mock(self) -> None:
        config = ImageExtractionConfig(max_pdf_pages=1, max_output_chars=500)
        png_page = _make_png_bytes()
        calls: list[int] = []

        def fake_renderer(_data: bytes, page_index: int, _config: ImageExtractionConfig) -> bytes | None:
            calls.append(page_index)
            return png_page

        def fake_tesseract(_path: Path, _config: ImageExtractionConfig) -> tuple[str | None, str]:
            return f"page-{calls[-1]}", STATUS_EXTRACTED

        fake_pdf = mock.Mock()
        fake_pdf.__len__ = mock.Mock(return_value=3)

        with mock.patch(
            "onprem_rag_notable_analysis.future.image_extraction._module_available",
            return_value=True,
        ):
            with mock.patch("pypdfium2.PdfDocument", return_value=fake_pdf):
                result = extract_image_content(
                    b"%PDF-1.4 mock",
                    content_type="application/pdf",
                    config=config,
                    tesseract_runner=fake_tesseract,
                    pdf_page_renderer=fake_renderer,
                )
        self.assertEqual(result.status, STATUS_PAGE_LIMIT_EXCEEDED)
        self.assertEqual(calls, [0])
        self.assertIn("page-0", result.text or "")
        self.assertEqual(result.page_count, 3)

    def test_pdf_render_mock_success(self) -> None:
        png_page = _make_png_bytes()
        fake_pdf = mock.Mock()
        fake_pdf.__len__ = mock.Mock(return_value=1)

        def fake_renderer(_data: bytes, page_index: int, _config: ImageExtractionConfig) -> bytes | None:
            if page_index == 0:
                return png_page
            return None

        with mock.patch(
            "onprem_rag_notable_analysis.future.image_extraction._module_available",
            return_value=True,
        ):
            with mock.patch("pypdfium2.PdfDocument", return_value=fake_pdf):
                result = extract_image_content(
                    b"%PDF-1.4 mock",
                    content_type="application/pdf",
                    config=ImageExtractionConfig(max_pdf_pages=1),
                    tesseract_runner=lambda _p, _c: ("pdf text", STATUS_EXTRACTED),
                    pdf_page_renderer=fake_renderer,
                )
        self.assertEqual(result.status, STATUS_EXTRACTED)
        self.assertEqual(result.text, "pdf text")

    def test_docx_embedded_image_extraction_and_cap(self) -> None:
        png_a = _make_png_bytes(rgb=(255, 0, 0))
        png_b = _make_png_bytes(rgb=(0, 255, 0))
        docx_bytes = _make_docx_with_images([("a.png", png_a), ("b.png", png_b)])
        seen: list[str] = []

        def fake_tesseract(path: Path, _config: ImageExtractionConfig) -> tuple[str | None, str]:
            seen.append(path.name)
            return f"ocr-{len(seen)}", STATUS_EXTRACTED

        tight = ImageExtractionConfig(max_embedded_images=1, max_output_chars=500)
        result = extract_image_content(
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            config=tight,
            tesseract_runner=fake_tesseract,
        )
        self.assertEqual(result.status, STATUS_EMBEDDED_IMAGE_LIMIT_EXCEEDED)
        self.assertEqual(result.embedded_image_count, 2)
        self.assertEqual(len(seen), 1)

    def test_output_truncation(self) -> None:
        tight = ImageExtractionConfig(max_output_chars=20)
        long_text = "word " * 20

        result = extract_image_content(
            _make_png_bytes(),
            content_type="image/png",
            config=tight,
            tesseract_runner=lambda _p, _c: (long_text, STATUS_EXTRACTED),
        )
        self.assertEqual(result.status, STATUS_OUTPUT_TRUNCATED)
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.text or ""), 20 + len(" [truncated]"))

    def test_unsupported_content_type(self) -> None:
        result = extract_image_content(
            b"abc",
            content_type="text/plain",
            config=self.config,
            tesseract_runner=lambda _p, _c: ("ignored", STATUS_EXTRACTED),
        )
        self.assertEqual(result.status, STATUS_UNSUPPORTED_CONTENT_TYPE)

    def test_missing_prerequisites(self) -> None:
        png_bytes = _make_png_bytes()

        with mock.patch(
            "onprem_rag_notable_analysis.future.image_extraction._module_available",
            return_value=False,
        ):
            pillow = extract_image_content(
                png_bytes,
                content_type="image/png",
                config=self.config,
            )
        self.assertEqual(pillow.status, STATUS_PREREQUISITE_MISSING)
        self.assertEqual(pillow.error_message, PREREQ_PILLOW)

        with mock.patch(
            "onprem_rag_notable_analysis.future.image_extraction._module_available",
            side_effect=lambda name: name == "PIL",
        ):
            pdf = extract_image_content(
                b"%PDF",
                content_type="application/pdf",
                config=self.config,
            )
        self.assertEqual(pdf.error_message, PREREQ_PYPDFIUM2)

        with mock.patch(
            "onprem_rag_notable_analysis.future.image_extraction._module_available",
            side_effect=lambda name: name != "docx",
        ):
            missing_docx = extract_image_content(
                _make_docx_with_images([]),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                config=self.config,
            )
        self.assertEqual(missing_docx.status, STATUS_PREREQUISITE_MISSING)
        self.assertEqual(missing_docx.error_message, PREREQ_PYTHON_DOCX)

        with mock.patch(
            "onprem_rag_notable_analysis.future.image_extraction._module_available",
            return_value=True,
        ):
            with mock.patch(
                "onprem_rag_notable_analysis.future.image_extraction.shutil.which",
                return_value=None,
            ):
                missing_tesseract = extract_image_content(
                    png_bytes,
                    content_type="image/png",
                    config=self.config,
                )
        self.assertEqual(missing_tesseract.status, STATUS_PREREQUISITE_MISSING)
        self.assertEqual(missing_tesseract.error_message, PREREQ_TESSERACT)

    def test_tesseract_uses_fixed_argv_without_shell(self) -> None:
        png_bytes = _make_png_bytes()
        captured: dict[str, object] = {}

        def capture_run(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return mock.Mock(returncode=0, stdout=b"ocr ok", stderr=b"")

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "onprem_rag_notable_analysis.future.image_extraction.shutil.which",
                return_value=str(Path(tmpdir) / "tesseract.exe"),
            ):
                with mock.patch(
                    "onprem_rag_notable_analysis.future.image_extraction.subprocess.run",
                    side_effect=capture_run,
                ):
                    result = extract_image_content(
                        png_bytes,
                        content_type="image/png",
                        config=ImageExtractionConfig(tesseract_binary="tesseract"),
                    )
        self.assertEqual(result.status, STATUS_EXTRACTED)
        argv = captured.get("argv")
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[0], "tesseract")
        self.assertNotIn("shell", captured.get("kwargs", {}))

    def test_result_dataclass_is_stable(self) -> None:
        result = ImageExtractionResult(
            status=STATUS_EXTRACTED,
            text="x",
            source_mime="image/png",
            decoded_format="PNG",
        )
        self.assertFalse(result.truncated)
        self.assertEqual(result.vision_raster_attempts, 0)

    def test_vision_callback_combined_with_ocr(self) -> None:
        png_bytes = _make_png_bytes()

        def fake_tesseract(_path: Path, _config: ImageExtractionConfig) -> tuple[str | None, str]:
            return "HELLO PNG", STATUS_EXTRACTED

        def fake_vision(_data: bytes, _mime: str) -> ImageVisionResult:
            return ImageVisionResult(
                status=STATUS_VISION_DESCRIBED,
                description="A red square image.",
            )

        result = extract_image_content(
            png_bytes,
            content_type="image/png",
            config=self.config,
            tesseract_runner=fake_tesseract,
            vision_describer=fake_vision,
        )
        self.assertEqual(result.status, STATUS_EXTRACTED)
        self.assertIn("[Vision description (advisory)]", result.text or "")
        self.assertIn("A red square image.", result.text or "")
        self.assertIn("[OCR text]", result.text or "")
        self.assertIn("HELLO PNG", result.text or "")
        self.assertEqual(result.vision_status, STATUS_VISION_DESCRIBED)
        self.assertEqual(result.vision_raster_attempts, 1)
        self.assertEqual(result.vision_raster_described, 1)

    def test_vision_failure_preserves_ocr(self) -> None:
        png_bytes = _make_png_bytes()

        def fake_vision(_data: bytes, _mime: str) -> ImageVisionResult:
            return ImageVisionResult(status=STATUS_VISION_FAILED, description=None)

        result = extract_image_content(
            png_bytes,
            content_type="image/png",
            config=self.config,
            tesseract_runner=lambda _p, _c: ("OCR ONLY", STATUS_EXTRACTED),
            vision_describer=fake_vision,
        )
        self.assertEqual(result.status, STATUS_EXTRACTED)
        self.assertIn("OCR ONLY", result.text or "")
        self.assertNotIn("[Vision description (advisory)]", result.text or "")
        self.assertEqual(result.vision_status, STATUS_VISION_FAILED)
        self.assertEqual(result.vision_raster_failed, 1)
        self.assertTrue(result.vision_warnings)

    def test_pdf_vision_per_page_with_mock_renderer(self) -> None:
        png_page = _make_png_bytes()
        fake_pdf = mock.Mock()
        fake_pdf.__len__ = mock.Mock(return_value=1)
        vision_calls: list[int] = []

        def fake_renderer(_data: bytes, page_index: int, _config: ImageExtractionConfig) -> bytes | None:
            return png_page if page_index == 0 else None

        def fake_vision(_data: bytes, _mime: str) -> ImageVisionResult:
            vision_calls.append(1)
            return ImageVisionResult(
                status=STATUS_VISION_DESCRIBED,
                description="Scanned page layout.",
            )

        with mock.patch(
            "onprem_rag_notable_analysis.future.image_extraction._module_available",
            return_value=True,
        ):
            with mock.patch("pypdfium2.PdfDocument", return_value=fake_pdf):
                result = extract_image_content(
                    b"%PDF-1.4 mock",
                    content_type="application/pdf",
                    config=ImageExtractionConfig(max_pdf_pages=1),
                    tesseract_runner=lambda _p, _c: ("pdf ocr", STATUS_EXTRACTED),
                    pdf_page_renderer=fake_renderer,
                    vision_describer=fake_vision,
                )
        self.assertEqual(result.status, STATUS_EXTRACTED)
        self.assertIn("[Page 1]", result.text or "")
        self.assertIn("Scanned page layout.", result.text or "")
        self.assertIn("pdf ocr", result.text or "")
        self.assertEqual(len(vision_calls), 1)


if __name__ == "__main__":
    unittest.main()
