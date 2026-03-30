"""Section-aware chunking utilities for retrieval corpus ingestion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_ALL_CAPS_HEADING_RE = re.compile(r"^[A-Z0-9][A-Z0-9 _/\-:]{4,}$")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ChunkRecord:
    """One chunk row persisted to retrieval index stores.

    Attributes:
        doc_id: Stable document identifier.
        chunk_id: Stable chunk identifier within a document.
        title: Document title.
        section_path: Section heading path for provenance.
        source_file: Source filename.
        text: Chunk text content.
    """

    doc_id: str
    chunk_id: str
    title: str
    section_path: str
    source_file: str
    text: str


def normalize_text(text: str) -> str:
    """Collapse whitespace to stable retrieval-friendly content.

    Args:
        text: Raw text content.

    Returns:
        Whitespace-normalized text.
    """
    return _WHITESPACE_RE.sub(" ", (text or "").strip())


def _is_heading(line: str) -> Tuple[bool, str]:
    """Detect markdown or ALL-CAPS heading lines.

    Args:
        line: Raw line content.

    Returns:
        Tuple `(is_heading, heading_text)`.
    """
    line = (line or "").strip()
    if not line:
        return False, ""
    m = _HEADING_RE.match(line)
    if m:
        return True, m.group(2).strip()
    # Heuristic for plaintext SOPs with all-caps section names.
    if _ALL_CAPS_HEADING_RE.match(line):
        return True, line.strip()
    return False, ""


def split_into_sections(text: str, *, default_title: str) -> List[Tuple[str, str]]:
    """Split document text into titled sections.

    Args:
        text: Raw document text.
        default_title: Fallback section title when no headings exist.

    Returns:
        List of tuples: (section_path, section_text)
    """
    lines = (text or "").splitlines()
    if not lines:
        return []

    current_heading = default_title
    current_lines: List[str] = []
    sections: List[Tuple[str, str]] = []

    def flush() -> None:
        nonlocal current_lines
        body = normalize_text("\n".join(current_lines))
        if body:
            sections.append((current_heading, body))
        current_lines = []

    for raw in lines:
        is_heading, heading = _is_heading(raw)
        if is_heading:
            flush()
            current_heading = heading
            continue
        current_lines.append(raw)
    flush()
    return sections


def _chunk_words(words: Sequence[str], *, target_words: int, overlap_words: int) -> List[str]:
    """Split a token list into overlapping word chunks.

    Args:
        words: Pre-tokenized words.
        target_words: Desired chunk size.
        overlap_words: Overlap size between adjacent chunks.

    Returns:
        List of chunk strings.
    """
    if not words:
        return []
    chunks: List[str] = []
    i = 0
    n = len(words)
    step = max(1, target_words - overlap_words)
    while i < n:
        j = min(n, i + target_words)
        snippet = " ".join(words[i:j]).strip()
        if snippet:
            chunks.append(snippet)
        if j >= n:
            break
        i += step
    return chunks


def chunk_sections(
    *,
    doc_id: str,
    source_file: Path,
    sections: Iterable[Tuple[str, str]],
    target_words: int = 500,
    overlap_words: int = 50,
) -> List[ChunkRecord]:
    """Create chunk records from section text.

    Args:
        doc_id: Stable document identifier.
        source_file: Source file path.
        sections: Iterable of `(section_path, section_text)` pairs.
        target_words: Desired chunk size in words.
        overlap_words: Overlap size between adjacent chunks.

    Returns:
        Chunk records ready for indexing.
    """
    out: List[ChunkRecord] = []
    source_name = source_file.name
    title = source_file.stem
    index = 0
    for section_path, section_text in sections:
        words = section_text.split()
        for chunk_text in _chunk_words(
            words, target_words=target_words, overlap_words=overlap_words
        ):
            index += 1
            out.append(
                ChunkRecord(
                    doc_id=doc_id,
                    chunk_id=f"{doc_id}::chunk_{index:04d}",
                    title=title,
                    section_path=section_path or title,
                    source_file=source_name,
                    text=chunk_text,
                )
            )
    return out

