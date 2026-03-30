"""Manual ingestion command for on-prem retrieval artifacts.

Builds:
- kb.sqlite3
- kb.faiss
- chunks.jsonl
- ingest_report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from .chunking import ChunkRecord, chunk_sections, split_into_sections
from .keyword_index import reset_and_build_sqlite_index
from .vector_index import build_faiss_index

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".docx", ".txt"}


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


def _read_source(path: Path) -> str:
    """Read one supported source file.

    Args:
        path: Source document path.

    Returns:
        Extracted text content.

    Raises:
        ValueError: If file extension is unsupported.
    """
    if path.suffix.casefold() == ".txt":
        return _read_txt(path)
    if path.suffix.casefold() == ".docx":
        return _read_docx(path)
    raise ValueError(f"Unsupported source type: {path}")


def _discover_docs(source_dir: Path) -> List[Path]:
    """Discover supported source docs recursively.

    Args:
        source_dir: Root source-doc directory.

    Returns:
        Sorted list of `.docx`/`.txt` file paths.
    """
    if not source_dir.exists():
        return []
    files = [
        p
        for p in source_dir.rglob("*")
        if p.is_file() and p.suffix.casefold() in SUPPORTED_SUFFIXES
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


def _build_chunks(
    *,
    source_dir: Path,
    files: Sequence[Path],
    target_words: int,
    overlap_words: int,
) -> Tuple[List[ChunkRecord], List[str]]:
    """Parse source docs and build chunk records.

    Args:
        source_dir: Source-doc root directory.
        files: Source document paths.
        target_words: Desired chunk size.
        overlap_words: Overlap size between adjacent chunks.

    Returns:
        Tuple of `(chunks, warnings)`.
    """
    chunks: List[ChunkRecord] = []
    warnings: List[str] = []
    for path in files:
        try:
            raw_text = _read_source(path)
            if not (raw_text or "").strip():
                warnings.append(f"Skipped empty document: {path.name}")
                continue
            sections = split_into_sections(raw_text, default_title=path.stem)
            if not sections:
                warnings.append(f"No sections detected in {path.name}; skipped")
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
    return chunks, warnings


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
    embedding_model_name: str,
    target_words: int,
    overlap_words: int,
) -> dict:
    """Ingest source docs and publish retrieval artifacts.

    Args:
        source_dir: Source-doc root directory.
        index_dir: Live artifact output directory.
        embedding_model_name: sentence-transformers model name/path.
        target_words: Desired chunk size.
        overlap_words: Overlap size between adjacent chunks.

    Returns:
        Ingestion report dictionary.
    """
    started = time.time()
    files = _discover_docs(source_dir)
    chunks, warnings = _build_chunks(
        source_dir=source_dir,
        files=files,
        target_words=target_words,
        overlap_words=overlap_words,
    )

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
        indexed_vectors = build_faiss_index(
            sqlite_path=sqlite_tmp,
            faiss_path=faiss_tmp,
            embedding_model_name=embedding_model_name,
        )
        chunk_count = _write_chunks_jsonl(chunks_tmp, chunks)

        report = {
            "status": "success",
            "source_dir": str(source_dir),
            "index_dir": str(index_dir),
            "embedding_model": embedding_model_name,
            "source_file_count": len(files),
            "chunk_count": chunk_count,
            "vector_count": indexed_vectors,
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
    parser = argparse.ArgumentParser(description="Rebuild on-prem retrieval artifacts.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/opt/llm-notable-analysis/knowledge_base/source_docs"),
        help="Source docs directory (.docx, .txt).",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=Path("/opt/llm-notable-analysis/knowledge_base/index"),
        help="Output directory for kb.sqlite3/kb.faiss/chunks.jsonl/ingest_report.json.",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Local sentence-transformers model identifier/path.",
    )
    parser.add_argument("--target-words", type=int, default=500)
    parser.add_argument("--overlap-words", type=int, default=50)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    """CLI entry point for manual corpus ingestion.

    Returns:
        Process exit code (0 on success, 1 on failure).
    """
    args = _parse_args()
    _configure_logging(args.verbose)
    try:
        report = ingest_corpus(
            source_dir=args.source_dir,
            index_dir=args.index_dir,
            embedding_model_name=args.embedding_model,
            target_words=args.target_words,
            overlap_words=args.overlap_words,
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

