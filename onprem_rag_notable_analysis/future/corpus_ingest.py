"""Manual ingestion command for on-prem retrieval artifacts.

Builds:
- kb.sqlite3
- kb.faiss
- chunks.jsonl
- ingest_report.json
"""

# Optional document/vector dependencies are imported only when their ingest path
# needs them; ingestion should still import cleanly on minimal analyzer hosts.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Sequence, Tuple

from urllib.parse import urlparse

from .chunking import ChunkRecord, chunk_sections, split_into_sections
from .image_extraction import (
    STATUS_EMBEDDED_IMAGE_LIMIT_EXCEEDED,
    STATUS_EXTRACTED,
    STATUS_OUTPUT_TRUNCATED,
    STATUS_PAGE_LIMIT_EXCEEDED,
    STATUS_VISION_DESCRIBED,
    STATUS_VISION_PARTIAL,
    ImageExtractionResult,
    VisionDescriber,
    extract_image_content,
)
from .image_extraction_config import ImageExtractionConfig
from .image_vision import (
    ImageVisionConfig,
    describe_image_with_vision,
)
from .keyword_index import reset_and_build_sqlite_index
from .postgres_ingest import build_postgres_index

logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {".txt", ".docx"}
IMAGE_MEDIA_SUFFIXES = {".png", ".jpeg", ".jpg", ".webp", ".gif"}
PDF_SUFFIXES = {".pdf"}
MEDIA_SUFFIXES = IMAGE_MEDIA_SUFFIXES | PDF_SUFFIXES
ALL_SUPPORTED_SUFFIXES = TEXT_SUFFIXES | MEDIA_SUFFIXES

_INDEXABLE_EXTRACTION_STATUSES = frozenset(
    {
        STATUS_EXTRACTED,
        STATUS_OUTPUT_TRUNCATED,
        STATUS_PAGE_LIMIT_EXCEEDED,
        STATUS_EMBEDDED_IMAGE_LIMIT_EXCEEDED,
    }
)


def _is_indexable_extraction_result(result: ImageExtractionResult) -> bool:
    """Return True when extracted text should become KB chunks."""
    if not (result.text or "").strip():
        return False
    if result.status in _INDEXABLE_EXTRACTION_STATUSES:
        return True
    return result.vision_status in {STATUS_VISION_DESCRIBED, STATUS_VISION_PARTIAL}

_SUFFIX_TO_MIME: dict[str, str] = {
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}

_SECTION_BODY = "Body"
_SECTION_OCR = "OCR Content"
_SECTION_EMBEDDED_OCR = "Embedded Images OCR"


def _parse_bool_value(raw: str, *, default: bool) -> bool:
    """Parse a boolean string using the same tokens as onprem_service config."""
    normalized = (raw or "").strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    if not normalized:
        return default
    raise ValueError(f"Invalid boolean value: {raw!r}")


def _parse_byte_size(raw: str, *, default: int) -> int:
    """Parse a positive byte size (supports KiB/MiB/GiB suffixes)."""
    text = (raw or "").strip()
    if not text:
        return default
    match = re.fullmatch(r"^(\d+)([KMG]iB|[KMG]B)?$", text, re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid byte size: {raw!r}")
    amount = int(match.group(1))
    suffix = (match.group(2) or "").upper()
    multiplier = 1
    if suffix in {"KIB", "KB"}:
        multiplier = 1024
    elif suffix in {"MIB", "MB"}:
        multiplier = 1024 * 1024
    elif suffix in {"GIB", "GB"}:
        multiplier = 1024 * 1024 * 1024
    value = amount * multiplier
    if value <= 0:
        raise ValueError(f"Invalid byte size: {raw!r}")
    return value


def _parse_positive_int(raw: str, *, default: int) -> int:
    """Parse a positive integer from config text."""
    text = (raw or "").strip()
    if not text:
        return default
    value = int(text)
    if value <= 0:
        raise ValueError(f"Expected positive integer, got {raw!r}")
    return value


def _parse_positive_float(raw: str, *, default: float) -> float:
    """Parse a positive float from config text."""
    text = (raw or "").strip()
    if not text:
        return default
    value = float(text)
    if value <= 0:
        raise ValueError(f"Expected positive number, got {raw!r}")
    return value


def _parse_mime_allowlist(raw: str) -> frozenset[str]:
    """Parse a comma-separated MIME allowlist."""
    items = frozenset(
        part.split(";", 1)[0].strip().lower()
        for part in (raw or "").split(",")
        if part.strip()
    )
    if not items:
        raise ValueError("IMAGE_INGEST_ALLOWED_MIME_TYPES must contain at least one MIME type")
    return items


_DEFAULT_MIME_ALLOWLIST = (
    "application/pdf,"
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
    "image/gif,image/jpeg,image/jpg,image/png,image/webp"
)


@dataclass(frozen=True)
class CorpusImageIngestOptions:
    """Runtime options for KB image/PDF/DOCX-image extraction during ingest."""

    enabled: bool = False
    extraction_config: ImageExtractionConfig = field(
        default_factory=ImageExtractionConfig
    )
    vision_enabled: bool = False
    vision_config: ImageVisionConfig | None = None


@dataclass
class ExtractionStatusCounts:
    """Aggregate extraction outcomes surfaced in ingest_report.json."""

    attempted: int = 0
    indexed: int = 0
    failed: int = 0
    skipped: int = 0
    by_status: dict[str, int] = field(default_factory=dict)

    def record(self, status: str, *, indexed: bool) -> None:
        self.attempted += 1
        self.by_status[status] = self.by_status.get(status, 0) + 1
        if indexed:
            self.indexed += 1
        else:
            self.failed += 1

    def record_skip(self) -> None:
        self.skipped += 1

    def as_report_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "indexed": self.indexed,
            "failed": self.failed,
            "skipped": self.skipped,
            "by_status": dict(sorted(self.by_status.items())),
        }


def _llm_openai_api_base(llm_api_url: str) -> str:
    """Derive an OpenAI-compatible API base URL from LLM_API_URL."""
    text = str(llm_api_url or "").strip().rstrip("/")
    if text.endswith("/chat/completions"):
        return text[: -len("/chat/completions")]
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        path = (parsed.path or "").rstrip("/")
        if path.endswith("/chat/completions"):
            path = path[: -len("/chat/completions")]
        return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    return text


def _resolve_image_vision_config(
    config_values: dict[str, str],
    *,
    vision_enabled: bool,
) -> ImageVisionConfig | None:
    """Build loopback vision config, inheriting LLM gateway fields when empty."""
    if not vision_enabled:
        return None
    api_base = _config_default(config_values, "IMAGE_VISION_API_BASE", "").strip()
    model = _config_default(config_values, "IMAGE_VISION_MODEL", "").strip()
    api_key = _config_default(config_values, "IMAGE_VISION_API_KEY", "").strip()
    if not api_base:
        api_base = _llm_openai_api_base(
            _config_default(config_values, "LLM_API_URL", "")
        )
    if not model:
        model = _config_default(config_values, "LLM_MODEL_NAME", "").strip()
    if not api_key:
        api_key = _config_default(config_values, "LLM_API_TOKEN", "").strip()
    return ImageVisionConfig(
        enabled=True,
        api_base=api_base,
        model=model,
        api_key=api_key,
        timeout_seconds=_parse_positive_float(
            _config_default(config_values, "IMAGE_VISION_TIMEOUT_SECONDS", "30"),
            default=30.0,
        ),
        max_tokens=_parse_positive_int(
            _config_default(config_values, "IMAGE_VISION_MAX_TOKENS", "400"),
            default=400,
        ),
    )


def build_vision_describer_from_options(
    image_options: CorpusImageIngestOptions,
) -> VisionDescriber | None:
    """Return a loopback vision callback when KB vision is enabled and configured."""
    if not image_options.vision_enabled or image_options.vision_config is None:
        return None
    vision_config = image_options.vision_config

    def _describe(image_bytes: bytes, content_type: str):
        return describe_image_with_vision(
            image_bytes=image_bytes,
            content_type=content_type,
            config=vision_config,
        )

    return _describe


def build_image_ingest_options_from_config_values(
    config_values: dict[str, str],
) -> CorpusImageIngestOptions:
    """Build image-ingest options from parsed config.env key/value pairs."""
    enabled = _parse_bool_value(
        _config_default(config_values, "IMAGE_INGEST_ENABLED", "false"),
        default=False,
    )
    allowed_mime_types = _parse_mime_allowlist(
        _config_default(
            config_values,
            "IMAGE_INGEST_ALLOWED_MIME_TYPES",
            _DEFAULT_MIME_ALLOWLIST,
        )
    )
    extraction_config = ImageExtractionConfig(
        allowed_mime_types=allowed_mime_types,
        max_bytes=_parse_byte_size(
            _config_default(config_values, "IMAGE_INGEST_MAX_BYTES", "10485760"),
            default=10 * 1024 * 1024,
        ),
        max_pixels=_parse_positive_int(
            _config_default(config_values, "IMAGE_INGEST_MAX_PIXELS", "25000000"),
            default=25_000_000,
        ),
        max_width=_parse_positive_int(
            _config_default(config_values, "IMAGE_INGEST_MAX_WIDTH", "8192"),
            default=8192,
        ),
        max_height=_parse_positive_int(
            _config_default(config_values, "IMAGE_INGEST_MAX_HEIGHT", "8192"),
            default=8192,
        ),
        max_pdf_pages=_parse_positive_int(
            _config_default(config_values, "IMAGE_INGEST_MAX_PDF_PAGES", "50"),
            default=50,
        ),
        max_embedded_images=_parse_positive_int(
            _config_default(config_values, "IMAGE_INGEST_MAX_EMBEDDED_IMAGES", "20"),
            default=20,
        ),
        max_output_chars=_parse_positive_int(
            _config_default(config_values, "IMAGE_INGEST_MAX_OUTPUT_CHARS", "12000"),
            default=12_000,
        ),
        tesseract_binary=_config_default(
            config_values,
            "IMAGE_INGEST_TESSERACT_BINARY",
            "tesseract",
        ).strip()
        or "tesseract",
        tesseract_lang=_config_default(
            config_values,
            "IMAGE_INGEST_TESSERACT_LANG",
            "eng",
        ).strip()
        or "eng",
        tesseract_timeout_seconds=_parse_positive_float(
            _config_default(
                config_values,
                "IMAGE_INGEST_TESSERACT_TIMEOUT_SECONDS",
                "60",
            ),
            default=60.0,
        ),
    )
    vision_enabled = _parse_bool_value(
        _config_default(config_values, "IMAGE_VISION_ENABLED", "false"),
        default=False,
    )
    vision_config = _resolve_image_vision_config(
        config_values,
        vision_enabled=vision_enabled,
    )
    return CorpusImageIngestOptions(
        enabled=enabled,
        extraction_config=extraction_config,
        vision_enabled=vision_enabled,
        vision_config=vision_config,
    )


def _configure_logging(verbose: bool) -> None:
    """Configure process logging for ingestion CLI.

    Args:
        verbose: Enables debug-level logging when True.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _parse_config_env(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE config.env file without shell execution.

    Args:
        path: Config file path.

    Returns:
        Parsed environment-style key/value pairs.

    Raises:
        ValueError: If a non-comment line is not a simple assignment.
    """
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(f"Invalid config.env line {line_number}: {exc}") from exc
        if not tokens:
            continue
        if tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise ValueError(
                f"Invalid config.env line {line_number}: expected KEY=VALUE."
            )
        key, value = tokens[0].split("=", 1)
        if not key.isidentifier():
            raise ValueError(
                f"Invalid config.env line {line_number}: invalid key {key!r}."
            )
        values[key] = value
    return values


def _config_default(config_values: dict[str, str], key: str, fallback: str) -> str:
    """Return a CLI default from config.env, environment, or fallback."""
    return config_values.get(key, os.getenv(key, fallback))


def _read_txt(path: Path) -> str:
    """Read UTF-8 text file content with replacement on decode issues.

    Args:
        path: Source `.txt` path.

    Returns:
        File text content.
    """
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_docx(path: Path) -> str:
    """Extract text from a `.docx` file.

    Args:
        path: Source `.docx` path.

    Returns:
        Extracted document text.

    Raises:
        RuntimeError: If no supported DOCX extractor is available.
    """
    # python-docx first, then docx2txt fallback.
    try:
        import docx  # type: ignore

        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text and p.text.strip())
    except Exception:
        pass

    try:
        import docx2txt  # type: ignore

        return str(docx2txt.process(str(path)) or "")
    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse DOCX file {path}. Install python-docx or docx2txt."
        ) from exc


def _mime_for_path(path: Path) -> str:
    """Return the configured MIME type for a supported source suffix."""
    return _SUFFIX_TO_MIME[path.suffix.casefold()]


def _is_media_path(path: Path) -> bool:
    """Return whether a path is a non-text media source."""
    return path.suffix.casefold() in MEDIA_SUFFIXES


def _discover_docs(
    source_dir: Path,
    *,
    image_ingest_enabled: bool,
) -> List[Path]:
    """Discover supported source docs recursively.

    Args:
        source_dir: Root source-doc directory.
        image_ingest_enabled: When True, include PNG/JPEG/WebP/GIF/PDF sources.

    Returns:
        Sorted list of supported file paths.
    """
    if not source_dir.exists():
        return []
    allowed_suffixes = ALL_SUPPORTED_SUFFIXES if image_ingest_enabled else TEXT_SUFFIXES
    files = [
        p
        for p in source_dir.rglob("*")
        if p.is_file() and p.suffix.casefold() in allowed_suffixes
    ]
    return sorted(files)


def _doc_id_from_path(source_dir: Path, path: Path) -> str:
    """Build stable document ID from relative path.

    Args:
        source_dir: Source-doc root directory.
        path: Source document path.

    Returns:
        Deterministic document ID string.
    """
    rel = str(path.relative_to(source_dir)).replace("\\", "/")
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
    stem = path.stem.lower().replace(" ", "_")
    return f"{stem}_{digest}"


def _sections_from_extraction(
    *,
    path: Path,
    data: bytes,
    content_type: str,
    section_name: str,
    image_options: CorpusImageIngestOptions,
    extraction_counts: ExtractionStatusCounts,
    warnings: List[str],
    vision_describer: VisionDescriber | None,
) -> List[Tuple[str, str]]:
    """Run shared extraction and convert successful OCR output into sections."""
    result = extract_image_content(
        data,
        content_type=content_type,
        config=image_options.extraction_config,
        vision_describer=vision_describer,
    )
    indexed = _is_indexable_extraction_result(result)
    extraction_counts.record(result.status, indexed=indexed)
    if not indexed:
        detail = result.error_message or result.status
        warnings.append(f"Extraction failed for {path.name}: {detail}")
        return []

    if result.status != STATUS_EXTRACTED:
        if not (
            indexed
            and result.vision_status
            in {STATUS_VISION_DESCRIBED, STATUS_VISION_PARTIAL}
        ):
            warnings.append(
                f"Extraction for {path.name} completed with status={result.status}"
            )
    if result.vision_warnings:
        for vision_warning in result.vision_warnings:
            warnings.append(f"Vision for {path.name}: {vision_warning}")
    elif (
        image_options.vision_enabled
        and result.vision_status
        and result.vision_status not in {"vision_described"}
    ):
        warnings.append(
            f"Vision for {path.name} completed with status={result.vision_status}"
        )

    return [(section_name, result.text or "")]


def _build_docx_sections(
    *,
    path: Path,
    image_options: CorpusImageIngestOptions,
    extraction_counts: ExtractionStatusCounts,
    warnings: List[str],
    vision_describer: VisionDescriber | None,
) -> List[Tuple[str, str]]:
    """Build sections for DOCX body text plus optional embedded-image OCR."""
    sections: List[Tuple[str, str]] = []
    try:
        raw_text = _read_docx(path)
    except Exception as exc:
        warnings.append(f"Failed to parse DOCX body for {path.name}: {exc}")
        raw_text = ""

    if (raw_text or "").strip():
        body_sections = split_into_sections(raw_text, default_title=path.stem)
        if body_sections:
            for heading, body in body_sections:
                section_path = heading if heading != path.stem else _SECTION_BODY
                sections.append((section_path, body))
        else:
            sections.append((_SECTION_BODY, raw_text.strip()))
    elif not image_options.enabled:
        warnings.append(f"Skipped empty document: {path.name}")
        return []

    if not image_options.enabled:
        return sections

    data = path.read_bytes()
    embedded_sections = _sections_from_extraction(
        path=path,
        data=data,
        content_type=_mime_for_path(path),
        section_name=_SECTION_EMBEDDED_OCR,
        image_options=image_options,
        extraction_counts=extraction_counts,
        warnings=warnings,
        vision_describer=vision_describer,
    )
    sections.extend(embedded_sections)
    if not sections:
        warnings.append(f"No indexable content in {path.name}")
    return sections


def _build_media_sections(
    *,
    path: Path,
    image_options: CorpusImageIngestOptions,
    extraction_counts: ExtractionStatusCounts,
    warnings: List[str],
    vision_describer: VisionDescriber | None,
) -> List[Tuple[str, str]]:
    """Build OCR (and optional vision) sections for standalone image/PDF sources."""
    data = path.read_bytes()
    content_type = _mime_for_path(path)
    return _sections_from_extraction(
        path=path,
        data=data,
        content_type=content_type,
        section_name=_SECTION_OCR,
        image_options=image_options,
        extraction_counts=extraction_counts,
        warnings=warnings,
        vision_describer=vision_describer,
    )


def _build_chunks(
    *,
    source_dir: Path,
    files: Sequence[Path],
    target_words: int,
    overlap_words: int,
    image_options: CorpusImageIngestOptions,
    vision_describer: VisionDescriber | None = None,
) -> Tuple[List[ChunkRecord], List[str], ExtractionStatusCounts]:
    """Parse source docs and build chunk records.

    Args:
        source_dir: Source-doc root directory.
        files: Source document paths.
        target_words: Desired chunk size.
        overlap_words: Overlap size between adjacent chunks.
        image_options: Image/PDF/DOCX-image extraction settings.
        vision_describer: Optional injectable loopback vision callback.

    Returns:
        Tuple of `(chunks, warnings, extraction_counts)`.
    """
    chunks: List[ChunkRecord] = []
    warnings: List[str] = []
    extraction_counts = ExtractionStatusCounts()

    if image_options.vision_enabled and vision_describer is None:
        warnings.append(
            "IMAGE_VISION_ENABLED=true but vision is not configured "
            "(missing loopback api_base/model); OCR-only indexing continues"
        )

    for path in files:
        suffix = path.suffix.casefold()
        try:
            if _is_media_path(path):
                if not image_options.enabled:
                    extraction_counts.record_skip()
                    warnings.append(
                        f"Skipped non-text media (IMAGE_INGEST_ENABLED=false): {path.name}"
                    )
                    continue
                sections = _build_media_sections(
                    path=path,
                    image_options=image_options,
                    extraction_counts=extraction_counts,
                    warnings=warnings,
                    vision_describer=vision_describer,
                )
            elif suffix == ".docx":
                sections = _build_docx_sections(
                    path=path,
                    image_options=image_options,
                    extraction_counts=extraction_counts,
                    warnings=warnings,
                    vision_describer=vision_describer,
                )
            elif suffix == ".txt":
                raw_text = _read_txt(path)
                if not (raw_text or "").strip():
                    warnings.append(f"Skipped empty document: {path.name}")
                    continue
                sections = split_into_sections(raw_text, default_title=path.stem)
                if not sections:
                    warnings.append(f"No sections detected in {path.name}; skipped")
                    continue
            else:
                warnings.append(f"Unsupported source type: {path.name}")
                continue

            if not sections:
                continue

            doc_id = _doc_id_from_path(source_dir, path)
            chunks.extend(
                chunk_sections(
                    doc_id=doc_id,
                    source_file=path,
                    sections=sections,
                    target_words=target_words,
                    overlap_words=overlap_words,
                )
            )
        except Exception as exc:
            warnings.append(f"Failed to parse {path.name}: {exc}")
    return chunks, warnings, extraction_counts


def _write_chunks_jsonl(path: Path, chunks: Iterable[ChunkRecord]) -> int:
    """Write chunks to JSONL export artifact.

    Args:
        path: Output JSONL path.
        chunks: Chunk records to export.

    Returns:
        Number of written lines.
    """
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=True) + "\n")
            count += 1
    return count


def _atomic_publish_artifacts(temp_dir: Path, index_dir: Path) -> None:
    """Atomically replace live retrieval artifacts with build outputs.

    Args:
        temp_dir: Temporary build artifact directory.
        index_dir: Live index output directory.
    """
    index_dir.mkdir(parents=True, exist_ok=True)
    for name in ("kb.sqlite3", "kb.faiss", "chunks.jsonl", "ingest_report.json"):
        src = temp_dir / name
        dst = index_dir / name
        os.replace(src, dst)


def ingest_corpus(
    *,
    source_dir: Path,
    index_dir: Path,
    backend: str,
    embedding_model_name: str,
    target_words: int,
    overlap_words: int,
    postgres_dsn: str = "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
    postgres_schema: str = "notable_rag",
    postgres_chunks_table: str = "kb_chunks",
    postgres_fts_config: str = "english",
    vector_dimensions: int = 768,
    embedding_batch_size: int = 64,
    postgres_statement_timeout_ms: int = 0,
    ensure_postgres_schema: bool = True,
    image_options: CorpusImageIngestOptions | None = None,
    vision_describer: VisionDescriber | None = None,
) -> dict:
    """Ingest source docs and publish retrieval artifacts.

    Args:
        source_dir: Source-doc root directory.
        index_dir: Live artifact output directory.
        backend: Retrieval backend (`sqlite_faiss` or `postgres`).
        embedding_model_name: sentence-transformers model name/path.
        target_words: Desired chunk size.
        overlap_words: Overlap size between adjacent chunks.
        postgres_dsn: PostgreSQL DSN when `backend=postgres`.
        postgres_schema: PostgreSQL schema for chunks table.
        postgres_chunks_table: PostgreSQL chunks table name.
        postgres_fts_config: PostgreSQL FTS config.
        vector_dimensions: Embedding vector dimensions.
        embedding_batch_size: Embedding batch size for Postgres ingestion.
        postgres_statement_timeout_ms: Optional Postgres statement timeout for ingest.
        ensure_postgres_schema: Create schema/table/indexes before Postgres ingest.
        image_options: Optional KB image/PDF/DOCX-image extraction settings.
        vision_describer: Optional injectable loopback vision callback for KB images.

    Returns:
        Ingestion report dictionary.
    """
    resolved_image_options = image_options or CorpusImageIngestOptions()
    started = time.time()
    files = _discover_docs(
        source_dir,
        image_ingest_enabled=resolved_image_options.enabled,
    )
    chunks, warnings, extraction_counts = _build_chunks(
        source_dir=source_dir,
        files=files,
        target_words=target_words,
        overlap_words=overlap_words,
        image_options=resolved_image_options,
        vision_describer=vision_describer,
    )
    normalized_backend = (backend or "sqlite_faiss").strip().lower()

    if normalized_backend == "postgres":
        index_dir.mkdir(parents=True, exist_ok=True)
        chunk_count = _write_chunks_jsonl(index_dir / "chunks.jsonl", chunks)
        indexed_vectors = build_postgres_index(
            chunks=chunks,
            postgres_dsn=postgres_dsn,
            postgres_schema=postgres_schema,
            postgres_chunks_table=postgres_chunks_table,
            postgres_fts_config=postgres_fts_config,
            vector_dimensions=vector_dimensions,
            embedding_model_name=embedding_model_name,
            embedding_batch_size=embedding_batch_size,
            postgres_statement_timeout_ms=postgres_statement_timeout_ms,
            ensure_schema=ensure_postgres_schema,
        )
        report = {
            "status": "success",
            "backend": "postgres",
            "source_dir": str(source_dir),
            "index_dir": str(index_dir),
            "embedding_model": embedding_model_name,
            "embedding_batch_size": embedding_batch_size,
            "postgres_schema": postgres_schema,
            "postgres_chunks_table": postgres_chunks_table,
            "postgres_fts_config": postgres_fts_config,
            "postgres_statement_timeout_ms": postgres_statement_timeout_ms,
            "ensure_postgres_schema": ensure_postgres_schema,
            "vector_dimensions": vector_dimensions,
            "source_file_count": len(files),
            "chunk_count": chunk_count,
            "vector_count": indexed_vectors,
            "image_ingest_enabled": resolved_image_options.enabled,
            "image_vision_enabled": resolved_image_options.vision_enabled,
            "extraction_status": extraction_counts.as_report_dict(),
            "warnings": warnings,
            "elapsed_seconds": round(time.time() - started, 3),
        }
        (index_dir / "ingest_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        return report

    if normalized_backend != "sqlite_faiss":
        raise ValueError("backend must be either 'sqlite_faiss' or 'postgres'.")

    build_root = Path(
        tempfile.mkdtemp(prefix="kb_build_", dir=str(index_dir.parent if index_dir.parent else Path(".")))
    )
    temp_out = build_root / "index_artifacts"
    temp_out.mkdir(parents=True, exist_ok=True)
    sqlite_tmp = temp_out / "kb.sqlite3"
    faiss_tmp = temp_out / "kb.faiss"
    chunks_tmp = temp_out / "chunks.jsonl"
    report_tmp = temp_out / "ingest_report.json"

    try:
        reset_and_build_sqlite_index(sqlite_tmp, chunks)
        from .vector_index import build_faiss_index

        indexed_vectors = build_faiss_index(
            sqlite_path=sqlite_tmp,
            faiss_path=faiss_tmp,
            embedding_model_name=embedding_model_name,
        )
        chunk_count = _write_chunks_jsonl(chunks_tmp, chunks)

        report = {
            "status": "success",
            "backend": "sqlite_faiss",
            "source_dir": str(source_dir),
            "index_dir": str(index_dir),
            "embedding_model": embedding_model_name,
            "source_file_count": len(files),
            "chunk_count": chunk_count,
            "vector_count": indexed_vectors,
            "image_ingest_enabled": resolved_image_options.enabled,
            "image_vision_enabled": resolved_image_options.vision_enabled,
            "extraction_status": extraction_counts.as_report_dict(),
            "warnings": warnings,
            "elapsed_seconds": round(time.time() - started, 3),
        }
        report_tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")

        _atomic_publish_artifacts(temp_out, index_dir)
        return report
    finally:
        shutil.rmtree(build_root, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for corpus ingestion command."""
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--config-env",
        type=Path,
        default=None,
        help="Optional config.env file to read for RAG_* defaults.",
    )
    pre_args, _remaining = pre_parser.parse_known_args()
    config_values = (
        _parse_config_env(pre_args.config_env)
        if pre_args.config_env is not None
        else {}
    )

    parser = argparse.ArgumentParser(
        description="Rebuild on-prem retrieval artifacts.",
        parents=[pre_parser],
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/opt/llm-notable-analysis/knowledge_base/source_docs"),
        help="Source docs directory (.txt, .docx, and image/PDF when enabled).",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=Path("/opt/llm-notable-analysis/knowledge_base/index"),
        help="Output directory for kb.sqlite3/kb.faiss/chunks.jsonl/ingest_report.json.",
    )
    parser.add_argument(
        "--backend",
        choices=("sqlite_faiss", "postgres"),
        default=(
            _config_default(config_values, "RAG_BACKEND", "postgres").strip().lower()
            or "postgres"
        ),
        help="Retrieval backend to populate.",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=_config_default(
            config_values,
            "RAG_EMBEDDING_MODEL",
            "mixedbread-ai/mxbai-embed-large-v1",
        ),
        help="Local sentence-transformers model identifier/path.",
    )
    parser.add_argument("--target-words", type=int, default=500)
    parser.add_argument("--overlap-words", type=int, default=50)
    parser.add_argument(
        "--postgres-dsn",
        type=str,
        default=_config_default(
            config_values,
            "RAG_POSTGRES_DSN",
            "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
        ),
        help=(
            "PostgreSQL DSN when --backend postgres. Defaults to "
            "RAG_POSTGRES_DSN when set."
        ),
    )
    parser.add_argument(
        "--postgres-schema",
        type=str,
        default=_config_default(config_values, "RAG_POSTGRES_SCHEMA", "notable_rag"),
    )
    parser.add_argument(
        "--postgres-chunks-table",
        type=str,
        default=_config_default(
            config_values,
            "RAG_POSTGRES_CHUNKS_TABLE",
            "kb_chunks",
        ),
    )
    parser.add_argument(
        "--postgres-fts-config",
        type=str,
        default=_config_default(config_values, "RAG_POSTGRES_FTS_CONFIG", "english"),
    )
    parser.add_argument(
        "--vector-dimensions",
        type=int,
        default=int(_config_default(config_values, "RAG_VECTOR_DIMENSIONS", "768")),
    )
    parser.add_argument(
        "--postgres-statement-timeout-ms",
        type=int,
        default=int(
            _config_default(config_values, "RAG_POSTGRES_STATEMENT_TIMEOUT_MS", "0")
        ),
        help="PostgreSQL statement timeout for ingest/rebuild queries; 0 disables it.",
    )
    parser.add_argument(
        "--skip-postgres-schema-setup",
        action="store_true",
        help="Skip Postgres extension/schema/table/index DDL during ingest.",
    )
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument(
        "--image-ingest-enabled",
        action=argparse.BooleanOptionalAction,
        default=_parse_bool_value(
            _config_default(config_values, "IMAGE_INGEST_ENABLED", "false"),
            default=False,
        ),
        help="Enable OCR/PDF/DOCX-image extraction (IMAGE_INGEST_ENABLED).",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    """CLI entry point for manual corpus ingestion.

    Returns:
        Process exit code (0 on success, 1 on failure).
    """
    args = _parse_args()
    _configure_logging(args.verbose)
    pre_parser_config = {}
    if args.config_env is not None:
        pre_parser_config = _parse_config_env(args.config_env)
    image_options = build_image_ingest_options_from_config_values(pre_parser_config)
    image_options = CorpusImageIngestOptions(
        enabled=bool(args.image_ingest_enabled),
        extraction_config=image_options.extraction_config,
        vision_enabled=image_options.vision_enabled,
        vision_config=image_options.vision_config,
    )
    vision_describer = build_vision_describer_from_options(image_options)
    try:
        report = ingest_corpus(
            source_dir=args.source_dir,
            index_dir=args.index_dir,
            backend=args.backend,
            embedding_model_name=args.embedding_model,
            target_words=args.target_words,
            overlap_words=args.overlap_words,
            postgres_dsn=args.postgres_dsn,
            postgres_schema=args.postgres_schema,
            postgres_chunks_table=args.postgres_chunks_table,
            postgres_fts_config=args.postgres_fts_config,
            vector_dimensions=args.vector_dimensions,
            embedding_batch_size=args.embedding_batch_size,
            postgres_statement_timeout_ms=args.postgres_statement_timeout_ms,
            ensure_postgres_schema=not args.skip_postgres_schema_setup,
            image_options=image_options,
            vision_describer=vision_describer,
        )
        logger.info(
            "Ingestion succeeded: files=%s chunks=%s vectors=%s",
            report.get("source_file_count"),
            report.get("chunk_count"),
            report.get("vector_count"),
        )
        return 0
    except Exception as exc:
        logger.exception("Ingestion failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
