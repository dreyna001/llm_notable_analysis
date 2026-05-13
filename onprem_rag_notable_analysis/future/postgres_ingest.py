"""PostgreSQL + pgvector corpus population helpers."""

# Optional retrieval dependencies are imported lazily so non-Postgres fallback
# deployments can import the package without Postgres/BGE runtime dependencies.
# pylint: disable=import-error

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Sequence

from .chunking import ChunkRecord
from .postgres_index import (
    PostgresRAGSchemaConfig,
    build_schema_statements,
    quote_identifier,
)

ConnectionFactory = Callable[[str], Any]


def _lazy_import_sentence_transformer():
    """Import SentenceTransformer lazily for optional Postgres ingestion."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "sentence-transformers is unavailable in the runtime."
        ) from exc
    return SentenceTransformer


def _default_connect(dsn: str):
    """Open a psycopg connection for ingestion."""
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is unavailable in the runtime.") from exc
    return psycopg.connect(dsn, connect_timeout=5)


def _vectors_to_lists(values: Any) -> list[list[float]]:
    """Normalize common embedding outputs into list-of-float vectors."""
    data = values.tolist() if hasattr(values, "tolist") else values
    return [[float(v) for v in row] for row in data]


def _l2_normalize_vector(values: Sequence[float]) -> list[float]:
    """Apply L2 normalization to one vector."""
    norm = math.sqrt(sum(float(v) * float(v) for v in values)) + 1e-12
    return [float(v) / norm for v in values]


def _vector_literal(values: Sequence[float]) -> str:
    """Format a pgvector literal from normalized embedding values."""
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def _qualified_table(schema: str, table: str) -> str:
    """Return validated, quoted schema-qualified table name."""
    return f"{quote_identifier(schema, 'schema')}.{quote_identifier(table, 'chunks_table')}"


def _disable_autocommit_if_present(conn: Any) -> None:
    """Ensure rebuild delete/insert work is not visible until transaction commit."""
    if getattr(conn, "autocommit", False):
        conn.autocommit = False


def _set_statement_timeout(conn: Any, timeout_ms: int) -> None:
    """Set a transaction-local statement timeout when configured."""
    if int(timeout_ms) > 0:
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{int(timeout_ms)}ms",),
        )


def _execute_many(conn: Any, sql: str, rows: Sequence[tuple[str, ...]]) -> None:
    """Execute many rows through either a test fake or a psycopg cursor."""
    executemany = getattr(conn, "executemany", None)
    if callable(executemany):
        executemany(sql, rows)
        return

    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)


def build_clear_table_sql(schema: str, table: str) -> str:
    """Build SQL that clears the configured chunks table."""
    return f"DELETE FROM {_qualified_table(schema, table)}"


def build_ingest_lock_sql() -> str:
    """Build SQL that serializes concurrent rebuilds for one chunks table."""
    return "SELECT pg_advisory_xact_lock(hashtext(%s))"


def build_insert_chunks_sql(schema: str, table: str) -> str:
    """Build parameterized upsert SQL for chunk rows."""
    qualified_table = _qualified_table(schema, table)
    return f"""
INSERT INTO {qualified_table} (
    doc_id,
    chunk_id,
    title,
    section_path,
    source_file,
    text,
    embedding
)
VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
ON CONFLICT (chunk_id) DO UPDATE SET
    doc_id = EXCLUDED.doc_id,
    title = EXCLUDED.title,
    section_path = EXCLUDED.section_path,
    source_file = EXCLUDED.source_file,
    text = EXCLUDED.text,
    embedding = EXCLUDED.embedding
""".strip()


def _batched(items: Sequence[ChunkRecord], batch_size: int) -> Iterable[Sequence[ChunkRecord]]:
    """Yield fixed-size batches from a chunk sequence."""
    size = max(1, int(batch_size))
    for start in range(0, len(items), size):
        yield items[start : start + size]


def build_postgres_index(
    *,
    chunks: Sequence[ChunkRecord],
    postgres_dsn: str,
    postgres_schema: str,
    postgres_chunks_table: str,
    postgres_fts_config: str,
    vector_dimensions: int,
    embedding_model_name: str,
    embedding_batch_size: int = 64,
    postgres_statement_timeout_ms: int = 0,
    ensure_schema: bool = True,
    connect: ConnectionFactory | None = None,
    embedding_model: Any = None,
) -> int:
    """Populate the PostgreSQL RAG table from chunk records.

    Args:
        chunks: Chunk records to embed and store.
        postgres_dsn: PostgreSQL connection string.
        postgres_schema: PostgreSQL schema name.
        postgres_chunks_table: Chunk table name.
        postgres_fts_config: PostgreSQL FTS config name.
        vector_dimensions: Expected pgvector dimensions.
        embedding_model_name: Sentence-transformers model identifier/path.
        embedding_batch_size: Embedding batch size.
        postgres_statement_timeout_ms: Optional transaction-local statement timeout.
        ensure_schema: Create extension/schema/table/indexes before rebuild.
        connect: Optional connection factory for tests.
        embedding_model: Optional embedding model for tests.

    Returns:
        Number of chunk rows inserted.
    """
    schema_config = PostgresRAGSchemaConfig(
        schema=postgres_schema,
        chunks_table=postgres_chunks_table,
        vector_dimensions=vector_dimensions,
        fts_config=postgres_fts_config,
    )
    schema_statements = build_schema_statements(schema_config)
    lock_sql = build_ingest_lock_sql()
    lock_key = f"{postgres_schema}.{postgres_chunks_table}"
    clear_sql = build_clear_table_sql(postgres_schema, postgres_chunks_table)
    insert_sql = build_insert_chunks_sql(postgres_schema, postgres_chunks_table)

    model = embedding_model
    if model is None:
        SentenceTransformer = _lazy_import_sentence_transformer()
        model = SentenceTransformer(embedding_model_name)

    connect_fn = connect or _default_connect
    inserted = 0
    with connect_fn(postgres_dsn) as conn:
        _disable_autocommit_if_present(conn)
        _set_statement_timeout(conn, postgres_statement_timeout_ms)
        conn.execute(lock_sql, (lock_key,))
        if ensure_schema:
            for statement in schema_statements:
                conn.execute(statement)
        conn.execute(clear_sql)

        for batch in _batched(chunks, embedding_batch_size):
            vectors = model.encode(
                [chunk.text for chunk in batch],
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            vector_lists = _vectors_to_lists(vectors)
            if len(vector_lists) != len(batch):
                raise ValueError(
                    "Embedding model returned an unexpected number of vectors: "
                    f"expected {len(batch)}, got {len(vector_lists)}."
                )
            rows = []
            for chunk, vector in zip(batch, vector_lists):
                if len(vector) != vector_dimensions:
                    raise ValueError(
                        "Embedding vector dimension mismatch: "
                        f"expected {vector_dimensions}, got {len(vector)}."
                    )
                rows.append(
                    (
                        chunk.doc_id,
                        chunk.chunk_id,
                        chunk.title,
                        chunk.section_path,
                        chunk.source_file,
                        chunk.text,
                        _vector_literal(_l2_normalize_vector(vector)),
                    )
                )
            if rows:
                _execute_many(conn, insert_sql, rows)
                inserted += len(rows)
    return inserted
