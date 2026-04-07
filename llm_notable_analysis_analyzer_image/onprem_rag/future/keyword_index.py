"""SQLite + FTS5 index helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from .chunking import ChunkRecord


@dataclass(frozen=True)
class LexicalHit:
    """Lexical retrieval hit joined with chunk metadata.

    Attributes:
        row_id: SQLite chunk row ID.
        doc_id: Source document ID.
        chunk_id: Source chunk ID.
        title: Document title.
        section_path: Section path/title.
        source_file: Source filename.
        text: Chunk text content.
        bm25_score: BM25 score from FTS5 (lower is better).
    """

    row_id: int
    doc_id: str
    chunk_id: str
    title: str
    section_path: str
    source_file: str
    text: str
    bm25_score: float


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    section_path TEXT,
    source_file TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    title,
    section_path,
    source_file,
    tokenize='unicode61 remove_diacritics 2'
);
"""


def ensure_parent(path: Path) -> None:
    """Ensure parent directory exists for the given file path.

    Args:
        path: File path whose parent directory should exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)


def reset_and_build_sqlite_index(sqlite_path: Path, chunks: Sequence[ChunkRecord]) -> None:
    """Build SQLite and FTS5 indexes from scratch.

    Args:
        sqlite_path: Destination SQLite file path.
        chunks: Chunk records to persist/index.
    """
    ensure_parent(sqlite_path)
    if sqlite_path.exists():
        sqlite_path.unlink()

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.executescript(SCHEMA_SQL)
        with conn:
            conn.executemany(
                """
                INSERT INTO chunks (doc_id, chunk_id, title, section_path, source_file, text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.doc_id,
                        c.chunk_id,
                        c.title,
                        c.section_path,
                        c.source_file,
                        c.text,
                    )
                    for c in chunks
                ],
            )
            # Keep row ordering aligned with chunk table IDs.
            conn.execute("DELETE FROM chunks_fts")
            conn.execute(
                """
                INSERT INTO chunks_fts(rowid, text, title, section_path, source_file)
                SELECT id, text, title, COALESCE(section_path, ''), source_file
                FROM chunks
                ORDER BY id ASC
                """
            )
        conn.commit()
    finally:
        conn.close()


def _build_match_query(tokens: Iterable[str]) -> str:
    """Build FTS5 MATCH query from normalized tokens.

    Args:
        tokens: Normalized query tokens.

    Returns:
        OR-joined quoted token expression for SQLite FTS5 MATCH.
    """
    quoted = []
    for token in tokens:
        t = (token or "").strip()
        if not t:
            continue
        t = t.replace('"', '""')
        quoted.append(f'"{t}"')
    if not quoted:
        return ""
    return " OR ".join(quoted)


def lexical_search(sqlite_path: Path, tokens: Sequence[str], top_k: int) -> List[LexicalHit]:
    """Run FTS5 BM25 search for normalized tokens.

    Args:
        sqlite_path: SQLite index file path.
        tokens: Normalized query tokens.
        top_k: Maximum result count.

    Returns:
        Ranked lexical hits.
    """
    if not sqlite_path.exists():
        return []
    match_query = _build_match_query(tokens)
    if not match_query:
        return []
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                c.id AS row_id,
                c.doc_id AS doc_id,
                c.chunk_id AS chunk_id,
                c.title AS title,
                c.section_path AS section_path,
                c.source_file AS source_file,
                c.text AS text,
                bm25(chunks_fts) AS bm25_score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY bm25_score ASC
            LIMIT ?
            """,
            (match_query, int(top_k)),
        ).fetchall()
        return [
            LexicalHit(
                row_id=int(r["row_id"]),
                doc_id=str(r["doc_id"]),
                chunk_id=str(r["chunk_id"]),
                title=str(r["title"]),
                section_path=str(r["section_path"] or ""),
                source_file=str(r["source_file"]),
                text=str(r["text"]),
                bm25_score=float(r["bm25_score"]),
            )
            for r in rows
        ]
    finally:
        conn.close()


def fetch_chunks_by_row_ids(sqlite_path: Path, row_ids: Sequence[int]) -> List[LexicalHit]:
    """Fetch chunk rows by SQLite row IDs preserving input order.

    Args:
        sqlite_path: SQLite index file path.
        row_ids: Ordered row IDs to fetch.

    Returns:
        Chunk hits ordered to match `row_ids`.
    """
    if not row_ids or not sqlite_path.exists():
        return []
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in row_ids)
        rows = conn.execute(
            f"""
            SELECT
                id AS row_id,
                doc_id,
                chunk_id,
                title,
                section_path,
                source_file,
                text
            FROM chunks
            WHERE id IN ({placeholders})
            """,
            tuple(int(x) for x in row_ids),
        ).fetchall()
        by_id = {int(r["row_id"]): r for r in rows}
        out: List[LexicalHit] = []
        for rid in row_ids:
            r = by_id.get(int(rid))
            if not r:
                continue
            out.append(
                LexicalHit(
                    row_id=int(r["row_id"]),
                    doc_id=str(r["doc_id"]),
                    chunk_id=str(r["chunk_id"]),
                    title=str(r["title"]),
                    section_path=str(r["section_path"] or ""),
                    source_file=str(r["source_file"]),
                    text=str(r["text"]),
                    bm25_score=0.0,
                )
            )
        return out
    finally:
        conn.close()

