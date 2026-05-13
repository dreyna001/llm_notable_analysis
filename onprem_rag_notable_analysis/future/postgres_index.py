"""PostgreSQL + pgvector schema helpers for on-prem retrieval grounding.

This module contains deterministic SQL construction only; runtime database I/O
lives in `postgres_retrieval.py`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_FTS_CONFIG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


@dataclass(frozen=True)
class PostgresRAGSchemaConfig:
    """Configuration needed to create the Postgres retrieval schema."""

    schema: str = "notable_rag"
    chunks_table: str = "kb_chunks"
    vector_dimensions: int = 768
    fts_config: str = "english"


def quote_identifier(value: str, field_name: str) -> str:
    """Validate and quote a PostgreSQL identifier.

    Args:
        value: Identifier value from config.
        field_name: Human-readable field name for errors.

    Returns:
        Double-quoted PostgreSQL identifier.

    Raises:
        ValueError: If the value is not a simple PostgreSQL identifier.
    """
    normalized = (value or "").strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a simple PostgreSQL identifier.")
    return f'"{normalized}"'


def validate_fts_config(value: str) -> str:
    """Validate a PostgreSQL text-search configuration name."""
    normalized = (value or "").strip()
    if not _FTS_CONFIG_RE.fullmatch(normalized):
        raise ValueError("fts_config must be a simple PostgreSQL configuration name.")
    return normalized


def build_index_name(config: PostgresRAGSchemaConfig, suffix: str) -> str:
    """Build a deterministic PostgreSQL index name within identifier limits."""
    if not _IDENTIFIER_RE.fullmatch(suffix or ""):
        raise ValueError("index suffix must be a simple PostgreSQL identifier.")
    source = f"{config.schema}.{config.chunks_table}.{suffix}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"rag_{digest}_{suffix}"


def build_schema_statements(config: PostgresRAGSchemaConfig) -> List[str]:
    """Build SQL statements for the Postgres/pgvector retrieval schema.

    Args:
        config: Schema configuration.

    Returns:
        Ordered SQL statements safe to execute as one-time migration DDL.

    Raises:
        ValueError: If identifiers or vector dimensions are invalid.
    """
    if config.vector_dimensions <= 0:
        raise ValueError("vector_dimensions must be greater than zero.")

    schema = quote_identifier(config.schema, "schema")
    table = quote_identifier(config.chunks_table, "chunks_table")
    fts_config = validate_fts_config(config.fts_config)
    qualified_table = f"{schema}.{table}"
    embedding_index = build_index_name(config, "embedding_hnsw_idx")
    fts_index = build_index_name(config, "fts_gin_idx")
    source_file_index = build_index_name(config, "source_file_idx")

    return [
        "CREATE EXTENSION IF NOT EXISTS vector;",
        f"CREATE SCHEMA IF NOT EXISTS {schema};",
        f"""
CREATE TABLE IF NOT EXISTS {qualified_table} (
    id BIGSERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    section_path TEXT NOT NULL DEFAULT '',
    source_file TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding vector({config.vector_dimensions}) NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('{fts_config}'::regconfig, title || ' ' || section_path || ' ' || text)
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""".strip(),
        f"""
CREATE INDEX IF NOT EXISTS "{embedding_index}"
ON {qualified_table}
USING hnsw (embedding vector_cosine_ops);
""".strip(),
        f"""
CREATE INDEX IF NOT EXISTS "{fts_index}"
ON {qualified_table}
USING gin (search_vector);
""".strip(),
        f"""
CREATE INDEX IF NOT EXISTS "{source_file_index}"
ON {qualified_table} (source_file);
""".strip(),
    ]


def build_hybrid_search_sql(config: PostgresRAGSchemaConfig, *, rrf_k: int = 60) -> str:
    """Build parameterized hybrid PostgreSQL FTS + pgvector search SQL.

    Args:
        config: Schema configuration.
        rrf_k: Reciprocal rank fusion smoothing constant.

    Returns:
        SQL string with psycopg `%s` placeholders for query text, query vector,
        and result limits.

    Raises:
        ValueError: If identifiers or vector dimensions are invalid.
    """
    if config.vector_dimensions <= 0:
        raise ValueError("vector_dimensions must be greater than zero.")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be greater than zero.")

    schema = quote_identifier(config.schema, "schema")
    table = quote_identifier(config.chunks_table, "chunks_table")
    fts_config = validate_fts_config(config.fts_config)
    qualified_table = f"{schema}.{table}"

    return f"""
WITH lexical AS (
    SELECT
        id,
        row_number() OVER (
            ORDER BY ts_rank_cd(search_vector, plainto_tsquery('{fts_config}'::regconfig, %s)) DESC
        ) AS lexical_rank
    FROM {qualified_table}
    WHERE search_vector @@ plainto_tsquery('{fts_config}'::regconfig, %s)
    LIMIT %s
),
semantic AS (
    SELECT
        id,
        row_number() OVER (ORDER BY embedding <=> %s::vector) AS vector_rank
    FROM {qualified_table}
    ORDER BY embedding <=> %s::vector
    LIMIT %s
),
fused AS (
    SELECT
        COALESCE(lexical.id, semantic.id) AS id,
        lexical.lexical_rank,
        semantic.vector_rank,
        COALESCE(1.0 / ({int(rrf_k)} + lexical.lexical_rank), 0.0)
            + COALESCE(1.0 / ({int(rrf_k)} + semantic.vector_rank), 0.0) AS fused_score
    FROM lexical
    FULL OUTER JOIN semantic ON lexical.id = semantic.id
)
SELECT
    c.id AS row_id,
    c.doc_id,
    c.chunk_id,
    c.title,
    c.section_path,
    c.source_file,
    c.text,
    fused.lexical_rank,
    fused.vector_rank,
    fused.fused_score
FROM fused
JOIN {qualified_table} c ON c.id = fused.id
ORDER BY fused.fused_score DESC
LIMIT %s
""".strip()
