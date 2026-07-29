import unittest

from onprem_rag_notable_analysis.future.postgres_index import (
    PostgresRAGSchemaConfig,
    build_index_name,
    build_hybrid_search_sql,
    build_schema_statements,
    quote_identifier,
    validate_fts_config,
)


class TestPostgresIndex(unittest.TestCase):
    def test_build_schema_statements_include_pgvector_and_fts(self) -> None:
        """Postgres schema should create pgvector and FTS retrieval structures."""
        statements = build_schema_statements(
            PostgresRAGSchemaConfig(
                schema="soc_kb",
                chunks_table="chunks",
                vector_dimensions=768,
                fts_config="english",
            )
        )
        sql = "\n".join(statements)

        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", sql)
        self.assertIn('"soc_kb"."chunks"', sql)
        self.assertIn("embedding vector(768) NOT NULL", sql)
        self.assertIn("search_vector tsvector GENERATED ALWAYS AS", sql)
        self.assertIn("USING hnsw (embedding vector_cosine_ops)", sql)
        self.assertIn("USING gin (search_vector)", sql)

    def test_build_index_name_stays_within_postgres_identifier_limit(self) -> None:
        """Long valid schema/table names should not create truncated indexes."""
        config = PostgresRAGSchemaConfig(
            schema="s" + ("a" * 62),
            chunks_table="t" + ("b" * 62),
        )

        embedding_index = build_index_name(config, "embedding_hnsw_idx")
        fts_index = build_index_name(config, "fts_gin_idx")

        self.assertLessEqual(len(embedding_index), 63)
        self.assertLessEqual(len(fts_index), 63)
        self.assertNotEqual(embedding_index, fts_index)

        sql = "\n".join(build_schema_statements(config))
        self.assertIn(f'CREATE INDEX IF NOT EXISTS "{embedding_index}"', sql)
        self.assertIn(f'CREATE INDEX IF NOT EXISTS "{fts_index}"', sql)

    def test_build_hybrid_search_sql_includes_fts_and_pgvector(self) -> None:
        """Hybrid query should combine PostgreSQL FTS and pgvector ranking."""
        sql = build_hybrid_search_sql(
            PostgresRAGSchemaConfig(schema="soc_kb", chunks_table="chunks"),
            rrf_k=42,
        )

        self.assertIn('"soc_kb"."chunks"', sql)
        self.assertIn("plainto_tsquery('english'::regconfig, %s)", sql)
        self.assertIn("embedding <=> %s::vector", sql)
        self.assertIn("FULL OUTER JOIN semantic", sql)
        self.assertIn("1.0 / (42 + lexical.lexical_rank)", sql)
        self.assertIn("ORDER BY fused.fused_score DESC", sql)

    def test_identifier_validation_rejects_unsafe_names(self) -> None:
        """Schema and table names should not be interpolated without validation."""
        with self.assertRaisesRegex(ValueError, "schema"):
            quote_identifier("bad-name;drop", "schema")

    def test_fts_config_validation_rejects_unsafe_names(self) -> None:
        """FTS config names should be limited to simple PostgreSQL identifiers."""
        with self.assertRaisesRegex(ValueError, "fts_config"):
            validate_fts_config("english'); drop table x; --")

    def test_vector_dimensions_must_be_positive(self) -> None:
        """pgvector dimensions should fail early when malformed."""
        with self.assertRaisesRegex(ValueError, "vector_dimensions"):
            build_schema_statements(PostgresRAGSchemaConfig(vector_dimensions=0))

    def test_rrf_k_must_be_positive(self) -> None:
        """Hybrid query should fail early when RRF smoothing is malformed."""
        with self.assertRaisesRegex(ValueError, "rrf_k"):
            build_hybrid_search_sql(PostgresRAGSchemaConfig(), rrf_k=0)


if __name__ == "__main__":
    unittest.main()
