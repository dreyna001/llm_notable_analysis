import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onprem_rag_notable_analysis.future.chunking import ChunkRecord
from onprem_rag_notable_analysis.future import corpus_ingest
from onprem_rag_notable_analysis.future.postgres_ingest import (
    build_ingest_lock_sql,
    build_insert_chunks_sql,
    build_postgres_index,
)

# CLI parser behavior is part of the runtime contract for config.env binding.
# pylint: disable=protected-access


class _FakeEmbeddingModel:
    def __init__(self, vectors):
        self.vectors = vectors
        self.encoded_text_batches = []

    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        self.encoded_text_batches.append(list(texts))
        return self.vectors[: len(texts)]


class _FakeConnection:
    def __init__(self):
        self.executed = []
        self.executemany_calls = []
        self.autocommit = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, list(rows)))


def _sample_chunks():
    return [
        ChunkRecord(
            doc_id="doc1",
            chunk_id="doc1::chunk_0001",
            title="SOC SOP",
            section_path="PowerShell",
            source_file="sop.txt",
            text="PowerShell encodedcommand triage steps.",
        ),
        ChunkRecord(
            doc_id="doc1",
            chunk_id="doc1::chunk_0002",
            title="SOC SOP",
            section_path="Authentication",
            source_file="sop.txt",
            text="Authentication lockout triage steps.",
        ),
    ]


class TestPostgresIngest(unittest.TestCase):
    def test_build_insert_chunks_sql_quotes_configured_table(self) -> None:
        """Insert SQL should target only validated schema and table names."""
        sql = build_insert_chunks_sql("soc_kb", "chunks")

        self.assertIn('INSERT INTO "soc_kb"."chunks"', sql)
        self.assertIn("%s::vector", sql)
        self.assertIn("ON CONFLICT (chunk_id) DO UPDATE", sql)

    def test_build_ingest_lock_sql_uses_parameterized_key(self) -> None:
        """Ingest lock SQL should avoid interpolating configured names."""
        self.assertEqual(
            build_ingest_lock_sql(),
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
        )

    def test_build_postgres_index_creates_schema_and_inserts_vectors(self) -> None:
        """Postgres ingest should serialize rebuilds, clear table, and insert vectors."""
        connection = _FakeConnection()
        model = _FakeEmbeddingModel([[3.0, 4.0, 0.0], [0.0, 0.0, 2.0]])

        inserted = build_postgres_index(
            chunks=_sample_chunks(),
            postgres_dsn="postgresql://svc@127.0.0.1:5432/kb",
            postgres_schema="soc_kb",
            postgres_chunks_table="chunks",
            postgres_fts_config="english",
            vector_dimensions=3,
            embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
            embedding_batch_size=10,
            connect=lambda _dsn: connection,
            embedding_model=model,
        )

        self.assertEqual(inserted, 2)
        self.assertTrue(
            any(
                "CREATE EXTENSION IF NOT EXISTS vector" in sql
                for sql, _ in connection.executed
            )
        )
        self.assertIn(
            ("SELECT pg_advisory_xact_lock(hashtext(%s))", ("soc_kb.chunks",)),
            connection.executed,
        )
        self.assertTrue(
            any(
                'DELETE FROM "soc_kb"."chunks"' in sql
                for sql, _ in connection.executed
            )
        )
        self.assertEqual(len(connection.executemany_calls), 1)
        insert_sql, rows = connection.executemany_calls[0]
        self.assertIn('INSERT INTO "soc_kb"."chunks"', insert_sql)
        self.assertEqual(rows[0][6], "[0.60000000,0.80000000,0.00000000]")
        self.assertEqual(rows[1][6], "[0.00000000,0.00000000,1.00000000]")

    def test_build_postgres_index_rejects_dimension_mismatch(self) -> None:
        """Embedding dimension mismatches should fail before bad vectors are stored."""
        connection = _FakeConnection()
        model = _FakeEmbeddingModel([[1.0, 2.0]])

        with self.assertRaisesRegex(ValueError, "dimension mismatch"):
            build_postgres_index(
                chunks=_sample_chunks()[:1],
                postgres_dsn="postgresql://svc@127.0.0.1:5432/kb",
                postgres_schema="soc_kb",
                postgres_chunks_table="chunks",
                postgres_fts_config="english",
                vector_dimensions=3,
                embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
                connect=lambda _dsn: connection,
                embedding_model=model,
            )

    def test_ingest_corpus_postgres_writes_report_and_chunk_export(self) -> None:
        """Corpus ingestion should produce traceable Postgres ingest artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            index_dir = root / "index"
            source_dir.mkdir()
            (source_dir / "sop.txt").write_text(
                "# PowerShell\nEncodedCommand triage procedure.",
                encoding="utf-8",
            )

            with patch.object(
                corpus_ingest,
                "build_postgres_index",
                return_value=1,
            ) as build:
                report = corpus_ingest.ingest_corpus(
                    source_dir=source_dir,
                    index_dir=index_dir,
                    backend="postgres",
                    embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
                    target_words=100,
                    overlap_words=0,
                    postgres_dsn="postgresql://svc@127.0.0.1:5432/kb",
                    postgres_schema="soc_kb",
                    postgres_chunks_table="chunks",
                    postgres_fts_config="english",
                    vector_dimensions=1024,
                    embedding_batch_size=32,
                )

            self.assertEqual(report["backend"], "postgres")
            self.assertEqual(report["vector_count"], 1)
            self.assertEqual(report["postgres_schema"], "soc_kb")
            self.assertTrue((index_dir / "chunks.jsonl").exists())
            stored_report = json.loads((index_dir / "ingest_report.json").read_text())
            self.assertEqual(stored_report["backend"], "postgres")
            build.assert_called_once()
        self.assertEqual(build.call_args.kwargs["postgres_statement_timeout_ms"], 0)
        self.assertTrue(build.call_args.kwargs["ensure_schema"])

    def test_build_postgres_index_can_skip_schema_and_sets_timeout(self) -> None:
        """Postgres ingest should support pre-created schemas with bounded queries."""
        connection = _FakeConnection()
        connection.autocommit = True
        model = _FakeEmbeddingModel([[3.0, 4.0, 0.0]])

        inserted = build_postgres_index(
            chunks=_sample_chunks()[:1],
            postgres_dsn="postgresql://svc@127.0.0.1:5432/kb",
            postgres_schema="soc_kb",
            postgres_chunks_table="chunks",
            postgres_fts_config="english",
            vector_dimensions=3,
            embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
            postgres_statement_timeout_ms=2500,
            ensure_schema=False,
            connect=lambda _dsn: connection,
            embedding_model=model,
        )

        self.assertEqual(inserted, 1)
        self.assertFalse(connection.autocommit)
        self.assertEqual(
            connection.executed[0],
            ("SELECT set_config('statement_timeout', %s, true)", ("2500ms",)),
        )
        self.assertFalse(
            any(
                "CREATE EXTENSION IF NOT EXISTS vector" in sql
                for sql, _params in connection.executed
            )
        )

    def test_build_postgres_index_rejects_missing_vectors(self) -> None:
        """Embedding output count must match the batch size exactly."""
        connection = _FakeConnection()
        model = _FakeEmbeddingModel([[1.0, 0.0, 0.0]])

        with self.assertRaisesRegex(ValueError, "unexpected number of vectors"):
            build_postgres_index(
                chunks=_sample_chunks(),
                postgres_dsn="postgresql://svc@127.0.0.1:5432/kb",
                postgres_schema="soc_kb",
                postgres_chunks_table="chunks",
                postgres_fts_config="english",
                vector_dimensions=3,
                embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
                embedding_batch_size=10,
                connect=lambda _dsn: connection,
                embedding_model=model,
            )

    def test_parse_args_defaults_postgres_values_from_environment(self) -> None:
        """CLI defaults should allow DSNs to come from env instead of argv."""
        env = {
            "RAG_EMBEDDING_MODEL": "mixedbread-ai/mxbai-embed-large-v1",
            "RAG_POSTGRES_DSN": "postgresql://svc@127.0.0.1:5432/kb",
            "RAG_POSTGRES_SCHEMA": "soc_kb",
            "RAG_POSTGRES_CHUNKS_TABLE": "chunks",
            "RAG_POSTGRES_FTS_CONFIG": "simple",
            "RAG_POSTGRES_STATEMENT_TIMEOUT_MS": "2500",
            "RAG_VECTOR_DIMENSIONS": "1024",
        }

        with patch.dict(os.environ, env, clear=False), patch.object(
            sys,
            "argv",
            ["corpus_ingest", "--backend", "postgres"],
        ):
            args = corpus_ingest._parse_args()

        self.assertEqual(args.embedding_model, "mixedbread-ai/mxbai-embed-large-v1")
        self.assertEqual(args.postgres_dsn, "postgresql://svc@127.0.0.1:5432/kb")
        self.assertEqual(args.postgres_schema, "soc_kb")
        self.assertEqual(args.postgres_chunks_table, "chunks")
        self.assertEqual(args.postgres_fts_config, "simple")
        self.assertEqual(args.postgres_statement_timeout_ms, 2500)
        self.assertEqual(args.vector_dimensions, 1024)

    def test_parse_args_defaults_postgres_values_from_config_env(self) -> None:
        """CLI should safely parse config.env defaults without shell sourcing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = Path(tmpdir) / "config.env"
            config_env.write_text(
                "\n".join(
                    [
                        "RAG_BACKEND=postgres",
                        "RAG_EMBEDDING_MODEL=mixedbread-ai/mxbai-embed-large-v1",
                        "RAG_POSTGRES_DSN='postgresql://svc@127.0.0.1:5432/kb'",
                        "RAG_POSTGRES_SCHEMA=soc_kb",
                        "RAG_POSTGRES_CHUNKS_TABLE=chunks",
                        "RAG_POSTGRES_FTS_CONFIG=simple",
                        "RAG_POSTGRES_STATEMENT_TIMEOUT_MS=2500",
                        "RAG_VECTOR_DIMENSIONS=1024",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                [
                    "corpus_ingest",
                    "--config-env",
                    str(config_env),
                    "--skip-postgres-schema-setup",
                ],
            ):
                args = corpus_ingest._parse_args()

        self.assertEqual(args.backend, "postgres")
        self.assertEqual(args.postgres_dsn, "postgresql://svc@127.0.0.1:5432/kb")
        self.assertEqual(args.postgres_schema, "soc_kb")
        self.assertEqual(args.postgres_chunks_table, "chunks")
        self.assertEqual(args.postgres_fts_config, "simple")
        self.assertEqual(args.postgres_statement_timeout_ms, 2500)
        self.assertTrue(args.skip_postgres_schema_setup)
        self.assertEqual(args.vector_dimensions, 1024)

    def test_parse_args_defaults_backend_from_environment(self) -> None:
        """CLI backend should follow RAG_BACKEND when argv omits --backend."""
        with patch.dict(os.environ, {"RAG_BACKEND": "postgres"}, clear=False), patch.object(
            sys,
            "argv",
            ["corpus_ingest"],
        ):
            args = corpus_ingest._parse_args()

        self.assertEqual(args.backend, "postgres")


if __name__ == "__main__":
    unittest.main()
