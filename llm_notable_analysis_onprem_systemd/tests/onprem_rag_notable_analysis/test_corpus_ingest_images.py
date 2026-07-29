"""Tests for KB image/PDF/DOCX-image corpus ingest wiring."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from onprem_rag_notable_analysis.future import corpus_ingest
from onprem_rag_notable_analysis.future.image_extraction import (
    STATUS_EXTRACTED,
    STATUS_OCR_FAILED,
    ImageExtractionResult,
)
from onprem_rag_notable_analysis.future.image_extraction_config import (
    ImageExtractionConfig,
)
from onprem_rag_notable_analysis.future.image_vision import (
    STATUS_VISION_DESCRIBED,
    ImageVisionConfig,
    ImageVisionResult,
)

# pylint: disable=protected-access


def _make_png_bytes(*, width: int = 32, height: int = 32) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), (255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
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


class TestCorpusImageIngestConfig(unittest.TestCase):
    def test_build_image_ingest_options_from_config_values(self) -> None:
        values = {
            "IMAGE_INGEST_ENABLED": "true",
            "IMAGE_INGEST_MAX_BYTES": "5MiB",
            "IMAGE_INGEST_MAX_PDF_PAGES": "10",
            "IMAGE_INGEST_TESSERACT_LANG": "eng",
            "IMAGE_VISION_ENABLED": "false",
        }
        options = corpus_ingest.build_image_ingest_options_from_config_values(values)
        self.assertTrue(options.enabled)
        self.assertEqual(options.extraction_config.max_bytes, 5 * 1024 * 1024)
        self.assertEqual(options.extraction_config.max_pdf_pages, 10)
        self.assertFalse(options.vision_enabled)

    def test_build_image_ingest_options_inherits_llm_vision_defaults(self) -> None:
        values = {
            "IMAGE_VISION_ENABLED": "true",
            "LLM_API_URL": "http://127.0.0.1:4000/v1/chat/completions",
            "LLM_MODEL_NAME": "gemma-vision",
            "LLM_API_TOKEN": "local-token",
        }
        options = corpus_ingest.build_image_ingest_options_from_config_values(values)
        self.assertTrue(options.vision_enabled)
        self.assertIsNotNone(options.vision_config)
        assert options.vision_config is not None
        self.assertEqual(options.vision_config.api_base, "http://127.0.0.1:4000/v1")
        self.assertEqual(options.vision_config.model, "gemma-vision")
        self.assertEqual(options.vision_config.api_key, "local-token")

    def test_build_vision_describer_disabled_returns_none(self) -> None:
        options = corpus_ingest.CorpusImageIngestOptions(enabled=True, vision_enabled=False)
        self.assertIsNone(corpus_ingest.build_vision_describer_from_options(options))

    def test_non_loopback_vision_config_still_fails_at_runtime(self) -> None:
        options = corpus_ingest.CorpusImageIngestOptions(
            enabled=True,
            vision_enabled=True,
            vision_config=ImageVisionConfig(
                enabled=True,
                api_base="https://vision.example/v1",
                model="gemma-vision",
            ),
        )
        describer = corpus_ingest.build_vision_describer_from_options(options)
        assert describer is not None
        result = describer(b"img", "image/png")
        self.assertEqual(result.status, "vision_endpoint_not_loopback")
        self.assertIsNone(result.description)

    def test_invalid_byte_size_raises(self) -> None:
        with self.assertRaises(ValueError):
            corpus_ingest.build_image_ingest_options_from_config_values(
                {"IMAGE_INGEST_MAX_BYTES": "not-a-size"}
            )


class TestCorpusDiscovery(unittest.TestCase):
    def test_discover_includes_media_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "note.txt").write_text("hello", encoding="utf-8")
            (root / "diagram.png").write_bytes(_make_png_bytes())
            (root / "scan.pdf").write_bytes(b"%PDF-1.4")

            disabled = corpus_ingest._discover_docs(root, image_ingest_enabled=False)
            enabled = corpus_ingest._discover_docs(root, image_ingest_enabled=True)

        self.assertEqual([p.name for p in disabled], ["note.txt"])
        self.assertEqual(
            [p.name for p in enabled],
            ["diagram.png", "note.txt", "scan.pdf"],
        )


class TestCorpusImageChunks(unittest.TestCase):
    def setUp(self) -> None:
        self.image_options = corpus_ingest.CorpusImageIngestOptions(
            enabled=True,
            extraction_config=ImageExtractionConfig(max_output_chars=500),
        )

    def test_png_ocr_creates_chunk_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            png_path = source_dir / "alert.png"
            png_path.write_bytes(_make_png_bytes())

            fake_result = ImageExtractionResult(
                status=STATUS_EXTRACTED,
                text="MALWARE ALERT TEXT",
                source_mime="image/png",
                decoded_format="PNG",
            )
            with mock.patch.object(
                corpus_ingest,
                "extract_image_content",
                return_value=fake_result,
            ):
                chunks, warnings, counts = corpus_ingest._build_chunks(
                    source_dir=source_dir,
                    files=[png_path],
                    target_words=100,
                    overlap_words=0,
                    image_options=self.image_options,
                )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section_path, corpus_ingest._SECTION_OCR)
        self.assertIn("MALWARE ALERT TEXT", chunks[0].text)
        self.assertEqual(chunks[0].source_file, "alert.png")
        self.assertEqual(counts.indexed, 1)
        self.assertEqual(warnings, [])

    def test_pdf_scan_ocr_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            pdf_path = source_dir / "scan.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake")

            fake_result = ImageExtractionResult(
                status=STATUS_EXTRACTED,
                text="PAGE ONE TEXT",
                source_mime="application/pdf",
                decoded_format="PDF",
                page_count=1,
            )
            with mock.patch.object(
                corpus_ingest,
                "extract_image_content",
                return_value=fake_result,
            ):
                chunks, _warnings, counts = corpus_ingest._build_chunks(
                    source_dir=source_dir,
                    files=[pdf_path],
                    target_words=100,
                    overlap_words=0,
                    image_options=self.image_options,
                )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section_path, corpus_ingest._SECTION_OCR)
        self.assertEqual(counts.by_status[STATUS_EXTRACTED], 1)

    def test_docx_body_and_embedded_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            docx_path = source_dir / "runbook.docx"
            docx_path.write_bytes(b"placeholder")

            body_result = ImageExtractionResult(
                status=STATUS_EXTRACTED,
                text="SCREENSHOT LABEL",
                source_mime=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                decoded_format="DOCX",
                embedded_image_count=1,
            )

            def fake_read_docx(_path: Path) -> str:
                return "# Triage\nFollow these steps."

            with mock.patch.object(corpus_ingest, "_read_docx", fake_read_docx), mock.patch.object(
                corpus_ingest,
                "extract_image_content",
                return_value=body_result,
            ):
                chunks, _warnings, counts = corpus_ingest._build_chunks(
                    source_dir=source_dir,
                    files=[docx_path],
                    target_words=100,
                    overlap_words=0,
                    image_options=self.image_options,
                )

        section_paths = {chunk.section_path for chunk in chunks}
        self.assertIn("Triage", section_paths)
        self.assertIn(corpus_ingest._SECTION_EMBEDDED_OCR, section_paths)
        self.assertEqual(counts.indexed, 1)

    def test_disabled_image_ingest_skips_media_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            png_path = source_dir / "skip.png"
            png_path.write_bytes(_make_png_bytes())
            txt_path = source_dir / "note.txt"
            txt_path.write_text("plain text body", encoding="utf-8")

            disabled = corpus_ingest.CorpusImageIngestOptions(enabled=False)
            chunks, warnings, counts = corpus_ingest._build_chunks(
                source_dir=source_dir,
                files=[png_path, txt_path],
                target_words=100,
                overlap_words=0,
                image_options=disabled,
            )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].source_file, "note.txt")
        self.assertEqual(counts.skipped, 1)
        self.assertTrue(
            any("IMAGE_INGEST_ENABLED=false" in warning for warning in warnings)
        )

    def test_failed_extraction_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            png_path = source_dir / "bad.png"
            png_path.write_bytes(_make_png_bytes())

            fake_result = ImageExtractionResult(
                status=STATUS_OCR_FAILED,
                text=None,
                source_mime="image/png",
            )
            with mock.patch.object(
                corpus_ingest,
                "extract_image_content",
                return_value=fake_result,
            ):
                chunks, warnings, counts = corpus_ingest._build_chunks(
                    source_dir=source_dir,
                    files=[png_path],
                    target_words=100,
                    overlap_words=0,
                    image_options=self.image_options,
                )

        self.assertEqual(chunks, [])
        self.assertEqual(counts.failed, 1)
        self.assertTrue(any("Extraction failed" in warning for warning in warnings))

    def test_vision_callback_adds_combined_labeled_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            png_path = source_dir / "shot.png"
            png_path.write_bytes(_make_png_bytes())

            options = corpus_ingest.CorpusImageIngestOptions(
                enabled=True,
                extraction_config=ImageExtractionConfig(),
                vision_enabled=True,
            )

            def fake_ocr(*_args, **_kwargs) -> ImageExtractionResult:
                return ImageExtractionResult(
                    status=STATUS_EXTRACTED,
                    text=(
                        "[Vision description (advisory)]\n"
                        "A red square image.\n\n"
                        "[OCR text]\n"
                        "OCR TEXT"
                    ),
                    source_mime="image/png",
                    vision_status=STATUS_VISION_DESCRIBED,
                    vision_raster_attempts=1,
                    vision_raster_described=1,
                )

            def fake_vision(_data: bytes, _mime: str) -> ImageVisionResult:
                return ImageVisionResult(
                    status=STATUS_VISION_DESCRIBED,
                    description="A red square image.",
                )

            with mock.patch.object(
                corpus_ingest, "extract_image_content", side_effect=fake_ocr
            ):
                chunks, warnings, _counts = corpus_ingest._build_chunks(
                    source_dir=source_dir,
                    files=[png_path],
                    target_words=100,
                    overlap_words=0,
                    image_options=options,
                    vision_describer=fake_vision,
                )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section_path, corpus_ingest._SECTION_OCR)
        self.assertIn("[Vision description (advisory)]", chunks[0].text)
        self.assertIn("[OCR text]", chunks[0].text)
        self.assertEqual(warnings, [])

    def test_vision_failure_warning_preserves_ocr_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            png_path = source_dir / "shot.png"
            png_path.write_bytes(_make_png_bytes())

            options = corpus_ingest.CorpusImageIngestOptions(
                enabled=True,
                extraction_config=ImageExtractionConfig(),
                vision_enabled=True,
            )

            fake_result = ImageExtractionResult(
                status=STATUS_EXTRACTED,
                text="[OCR text]\nOCR TEXT",
                source_mime="image/png",
                vision_status="vision_failed",
                vision_raster_attempts=1,
                vision_raster_failed=1,
                vision_warnings=("standalone image: vision unavailable (vision_failed)",),
            )

            with mock.patch.object(
                corpus_ingest,
                "extract_image_content",
                return_value=fake_result,
            ):
                chunks, warnings, _counts = corpus_ingest._build_chunks(
                    source_dir=source_dir,
                    files=[png_path],
                    target_words=100,
                    overlap_words=0,
                    image_options=options,
                    vision_describer=lambda _d, _m: ImageVisionResult(
                        status="vision_failed",
                        description=None,
                    ),
                )

        self.assertEqual(len(chunks), 1)
        self.assertIn("OCR TEXT", chunks[0].text)
        self.assertTrue(any("Vision for shot.png" in warning for warning in warnings))

    def test_vision_only_extraction_indexes_when_text_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            png_path = source_dir / "diagram.png"
            png_path.write_bytes(_make_png_bytes())

            options = corpus_ingest.CorpusImageIngestOptions(
                enabled=True,
                extraction_config=ImageExtractionConfig(),
                vision_enabled=True,
            )
            fake_result = ImageExtractionResult(
                status="ocr_empty",
                text="[Vision description (advisory)] Solid coral field.",
                source_mime="image/png",
                vision_status=STATUS_VISION_DESCRIBED,
                vision_raster_attempts=1,
                vision_raster_described=1,
            )

            with mock.patch.object(
                corpus_ingest,
                "extract_image_content",
                return_value=fake_result,
            ):
                chunks, warnings, counts = corpus_ingest._build_chunks(
                    source_dir=source_dir,
                    files=[png_path],
                    target_words=100,
                    overlap_words=0,
                    image_options=options,
                    vision_describer=lambda _d, _m: ImageVisionResult(
                        status=STATUS_VISION_DESCRIBED,
                        description="Solid coral field.",
                    ),
                )

        self.assertEqual(len(chunks), 1)
        self.assertIn("coral field", chunks[0].text.lower())
        self.assertEqual(counts.indexed, 1)
        self.assertEqual(warnings, [])

    def test_txt_regression_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            txt_path = source_dir / "sop.txt"
            txt_path.write_text("# PowerShell\nEncodedCommand triage.", encoding="utf-8")

            chunks, warnings, counts = corpus_ingest._build_chunks(
                source_dir=source_dir,
                files=[txt_path],
                target_words=100,
                overlap_words=0,
                image_options=corpus_ingest.CorpusImageIngestOptions(enabled=False),
            )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section_path, "PowerShell")
        self.assertEqual(counts.attempted, 0)
        self.assertEqual(warnings, [])


class TestCorpusIngestReport(unittest.TestCase):
    def test_ingest_report_includes_extraction_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            index_dir = root / "index"
            source_dir.mkdir()
            (source_dir / "sop.txt").write_text("hello world", encoding="utf-8")

            with mock.patch.object(
                corpus_ingest,
                "build_postgres_index",
                return_value=1,
            ):
                report = corpus_ingest.ingest_corpus(
                    source_dir=source_dir,
                    index_dir=index_dir,
                    backend="postgres",
                    embedding_model_name="ibm-granite/granite-embedding-english-r2",
                    target_words=100,
                    overlap_words=0,
                    image_options=corpus_ingest.CorpusImageIngestOptions(enabled=True),
                )

            stored = json.loads((index_dir / "ingest_report.json").read_text())

        self.assertIn("extraction_status", report)
        self.assertIn("image_ingest_enabled", report)
        self.assertTrue(report["image_ingest_enabled"])
        self.assertEqual(stored["extraction_status"]["attempted"], 0)


class TestCorpusIngestCli(unittest.TestCase):
    def test_parse_args_reads_image_ingest_from_config_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = Path(tmpdir) / "config.env"
            config_env.write_text(
                "\n".join(
                    [
                        "IMAGE_INGEST_ENABLED=true",
                        "IMAGE_INGEST_MAX_PDF_PAGES=12",
                        "IMAGE_VISION_ENABLED=false",
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "sys.argv",
                [
                    "corpus_ingest",
                    "--config-env",
                    str(config_env),
                ],
            ):
                args = corpus_ingest._parse_args()

        self.assertTrue(args.image_ingest_enabled)

    def test_main_wires_vision_describer_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            index_dir = root / "index"
            source_dir.mkdir()
            config_env = root / "config.env"
            config_env.write_text(
                "\n".join(
                    [
                        "IMAGE_INGEST_ENABLED=true",
                        "IMAGE_VISION_ENABLED=true",
                        "LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions",
                        "LLM_MODEL_NAME=gemma-vision",
                    ]
                ),
                encoding="utf-8",
            )
            (source_dir / "note.txt").write_text("hello", encoding="utf-8")

            captured: dict[str, object] = {}

            def fake_ingest_corpus(**kwargs):
                captured["vision_describer"] = kwargs.get("vision_describer")
                return {"source_file_count": 1, "chunk_count": 1, "vector_count": 1}

            with mock.patch.object(corpus_ingest, "ingest_corpus", side_effect=fake_ingest_corpus):
                with mock.patch(
                    "sys.argv",
                    [
                        "corpus_ingest",
                        "--config-env",
                        str(config_env),
                        "--source-dir",
                        str(source_dir),
                        "--index-dir",
                        str(index_dir),
                    ],
                ):
                    exit_code = corpus_ingest.main()

        self.assertEqual(exit_code, 0)
        self.assertIsNotNone(captured.get("vision_describer"))

    def test_main_skips_vision_describer_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            index_dir = root / "index"
            source_dir.mkdir()
            config_env = root / "config.env"
            config_env.write_text("IMAGE_VISION_ENABLED=false\n", encoding="utf-8")
            (source_dir / "note.txt").write_text("hello", encoding="utf-8")

            captured: dict[str, object] = {}

            def fake_ingest_corpus(**kwargs):
                captured["vision_describer"] = kwargs.get("vision_describer")
                return {"source_file_count": 1, "chunk_count": 1, "vector_count": 1}

            with mock.patch.object(corpus_ingest, "ingest_corpus", side_effect=fake_ingest_corpus):
                with mock.patch(
                    "sys.argv",
                    [
                        "corpus_ingest",
                        "--config-env",
                        str(config_env),
                        "--source-dir",
                        str(source_dir),
                        "--index-dir",
                        str(index_dir),
                    ],
                ):
                    exit_code = corpus_ingest.main()

        self.assertEqual(exit_code, 0)
        self.assertIsNone(captured.get("vision_describer"))
