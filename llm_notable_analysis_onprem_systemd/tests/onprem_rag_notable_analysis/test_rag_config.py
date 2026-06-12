import unittest
from pathlib import Path

from onprem_rag_notable_analysis.future.rag_config import RAGConfig


class TestRAGConfig(unittest.TestCase):
    def test_default_embedding_model_is_mixedbread(self) -> None:
        """RAG defaults should match the on-prem Mixedbread embedding target."""
        config = RAGConfig()

        self.assertEqual(config.backend, "postgres")
        self.assertEqual(
            config.embedding_model_name, "mixedbread-ai/mxbai-embed-large-v1"
        )
        self.assertEqual(config.vector_dimensions, 1024)
        self.assertFalse(config.fail_closed)

    def test_postgres_config_requires_dsn(self) -> None:
        """Postgres backend should be invalid without a DSN."""
        config = RAGConfig(backend="postgres", postgres_dsn=" ")

        self.assertFalse(config.is_valid)

    def test_sqlite_faiss_config_requires_artifacts(self) -> None:
        """Fallback backend should require both local retrieval artifacts."""
        config = RAGConfig(
            backend="sqlite_faiss",
            sqlite_path=Path("/missing/kb.sqlite3"),
            faiss_path=Path("/missing/kb.faiss"),
        )

        self.assertFalse(config.is_valid)

    def test_unknown_backend_is_invalid(self) -> None:
        """Unsupported backend names should not look runtime-ready."""
        config = RAGConfig(backend="unknown")

        self.assertFalse(config.is_valid)


if __name__ == "__main__":
    unittest.main()
