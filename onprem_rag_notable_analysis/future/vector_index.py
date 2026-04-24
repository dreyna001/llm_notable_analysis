"""FAISS index build/search helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class VectorHit:
    """Vector retrieval result item.

    Attributes:
        row_id: SQLite chunk row ID mapped from FAISS vector position.
        score: Similarity score (inner product on normalized vectors).
    """

    row_id: int
    score: float


def _lazy_import_faiss():
    """Import FAISS lazily to keep import-time dependencies optional.

    Returns:
        Imported `faiss` module.

    Raises:
        RuntimeError: If FAISS is unavailable in the runtime environment.
    """
    try:
        import faiss  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "FAISS is unavailable. Install faiss-cpu/faiss-gpu in the runtime."
        ) from exc
    return faiss


def _lazy_import_sentence_transformer():
    """Import SentenceTransformer lazily.

    Returns:
        `SentenceTransformer` class.

    Raises:
        RuntimeError: If sentence-transformers is unavailable.
    """
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "sentence-transformers is unavailable in the runtime."
        ) from exc
    return SentenceTransformer


def _l2_normalize(arr: np.ndarray) -> np.ndarray:
    """Apply row-wise L2 normalization.

    Args:
        arr: Embedding matrix.

    Returns:
        L2-normalized embedding matrix.
    """
    norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
    return arr / norms


def _get_chunk_rows(sqlite_path: Path) -> List[Tuple[int, str]]:
    """Load `(row_id, text)` pairs from SQLite chunk table.

    Args:
        sqlite_path: SQLite index file path.

    Returns:
        Ordered list of `(id, text)` rows.
    """
    conn = sqlite3.connect(str(sqlite_path))
    try:
        rows = conn.execute("SELECT id, text FROM chunks ORDER BY id ASC").fetchall()
        return [(int(r[0]), str(r[1])) for r in rows]
    finally:
        conn.close()


def _store_row_mapping(sqlite_path: Path, ordered_row_ids: Sequence[int]) -> None:
    """Persist FAISS vector-position to SQLite row-id mapping.

    Args:
        sqlite_path: SQLite index file path.
        ordered_row_ids: Row IDs in vector insertion order.
    """
    conn = sqlite3.connect(str(sqlite_path))
    try:
        with conn:
            conn.execute("DROP TABLE IF EXISTS faiss_map")
            conn.execute(
                """
                CREATE TABLE faiss_map (
                    vector_pos INTEGER PRIMARY KEY,
                    row_id INTEGER NOT NULL
                )
                """
            )
            conn.executemany(
                "INSERT INTO faiss_map (vector_pos, row_id) VALUES (?, ?)",
                [(i, int(rid)) for i, rid in enumerate(ordered_row_ids)],
            )
        conn.commit()
    finally:
        conn.close()


def _map_vector_positions(sqlite_path: Path, positions: Sequence[int]) -> List[int]:
    """Map FAISS vector positions back to SQLite row IDs.

    Args:
        sqlite_path: SQLite index file path.
        positions: FAISS vector positions.

    Returns:
        Row IDs ordered by input positions.
    """
    if not positions:
        return []
    conn = sqlite3.connect(str(sqlite_path))
    try:
        placeholders = ",".join("?" for _ in positions)
        rows = conn.execute(
            f"SELECT vector_pos, row_id FROM faiss_map WHERE vector_pos IN ({placeholders})",
            tuple(int(p) for p in positions),
        ).fetchall()
        by_pos = {int(p): int(rid) for p, rid in rows}
        return [by_pos[p] for p in positions if p in by_pos]
    finally:
        conn.close()


def build_faiss_index(
    *,
    sqlite_path: Path,
    faiss_path: Path,
    embedding_model_name: str,
) -> int:
    """Build FAISS index and row mapping table from SQLite chunks.

    Args:
        sqlite_path: SQLite path containing `chunks` table.
        faiss_path: Destination FAISS index file path.
        embedding_model_name: sentence-transformers model name/path.

    Returns:
        Number of vectors written to the index.
    """
    rows = _get_chunk_rows(sqlite_path)
    if not rows:
        if faiss_path.exists():
            faiss_path.unlink()
        _store_row_mapping(sqlite_path, [])
        return 0

    row_ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]

    SentenceTransformer = _lazy_import_sentence_transformer()
    model = SentenceTransformer(embedding_model_name)
    vectors = model.encode(
        texts,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    if not isinstance(vectors, np.ndarray):
        vectors = np.asarray(vectors, dtype=np.float32)
    vectors = vectors.astype(np.float32, copy=False)
    vectors = _l2_normalize(vectors)

    faiss = _lazy_import_faiss()
    dim = int(vectors.shape[1])
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    faiss_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(faiss_path))
    _store_row_mapping(sqlite_path, row_ids)
    return len(row_ids)


class VectorSearchClient:
    """Lazy FAISS + embedding model client for query-time vector retrieval."""

    def __init__(self, *, sqlite_path: Path, faiss_path: Path, embedding_model_name: str):
        """Initialize lazy vector-search client.

        Args:
            sqlite_path: SQLite path containing FAISS row mapping.
            faiss_path: FAISS index file path.
            embedding_model_name: sentence-transformers model name/path.
        """
        self.sqlite_path = sqlite_path
        self.faiss_path = faiss_path
        self.embedding_model_name = embedding_model_name
        self._faiss = None
        self._index = None
        self._model = None

    def _ensure_loaded(self) -> None:
        """Lazily load FAISS index and embedding model."""
        if self._index is None:
            faiss = _lazy_import_faiss()
            if not self.faiss_path.exists():
                raise FileNotFoundError(f"FAISS index not found: {self.faiss_path}")
            self._faiss = faiss
            self._index = faiss.read_index(str(self.faiss_path))
        if self._model is None:
            SentenceTransformer = _lazy_import_sentence_transformer()
            self._model = SentenceTransformer(self.embedding_model_name)

    def search(self, query_text: str, top_k: int) -> List[VectorHit]:
        """Search semantic-nearest chunk vectors for a query.

        Args:
            query_text: Query text to embed.
            top_k: Maximum result count.

        Returns:
            Ranked vector hits with mapped SQLite row IDs.
        """
        if not (query_text or "").strip():
            return []
        self._ensure_loaded()
        assert self._model is not None
        assert self._index is not None

        q = self._model.encode(
            [query_text],
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        if not isinstance(q, np.ndarray):
            q = np.asarray(q, dtype=np.float32)
        q = q.astype(np.float32, copy=False)
        q = _l2_normalize(q)
        scores, positions = self._index.search(q, int(top_k))
        pos_list = [int(p) for p in positions[0] if int(p) >= 0]
        mapped_row_ids = _map_vector_positions(self.sqlite_path, pos_list)
        score_map = {
            int(p): float(s) for p, s in zip(positions[0].tolist(), scores[0].tolist())
        }
        out: List[VectorHit] = []
        for pos, rid in zip(pos_list, mapped_row_ids):
            out.append(VectorHit(row_id=int(rid), score=float(score_map.get(pos, 0.0))))
        return out

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Encode texts with the same model used for vector search.

        Args:
            texts: Text sequence to encode.

        Returns:
            L2-normalized embeddings as a float32 NumPy array.
        """
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        self._ensure_loaded()
        assert self._model is not None
        vecs = self._model.encode(
            list(texts),
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        if not isinstance(vecs, np.ndarray):
            vecs = np.asarray(vecs, dtype=np.float32)
        vecs = vecs.astype(np.float32, copy=False)
        return _l2_normalize(vecs)

