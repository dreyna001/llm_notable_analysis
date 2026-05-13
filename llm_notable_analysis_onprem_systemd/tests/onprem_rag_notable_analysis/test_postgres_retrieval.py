import unittest

from onprem_rag_notable_analysis.future.postgres_retrieval import (
    PostgresRAGContextProvider,
)
from onprem_rag_notable_analysis.future.rag_config import RAGConfig


class _FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        return [[1.0, 0.0, 0.0] for _text in texts]


class _WrongDimensionEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        return [[1.0, 0.0] for _text in texts]


class _FakeReranker:
    def predict(self, pairs):
        return [0.1, 0.9][: len(pairs)]


class _FailingReranker:
    def predict(self, pairs):
        del pairs
        raise RuntimeError("reranker unavailable")


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.executed_sql = ""
        self.executed_params = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params):
        self.executed.append((sql, params))
        self.executed_sql = sql
        self.executed_params = params
        return self

    def fetchall(self):
        return self.rows


class TestPostgresRetrieval(unittest.TestCase):
    def test_from_config_returns_provider_for_postgres_backend(self) -> None:
        """Provider should initialize only for enabled Postgres RAG config."""
        provider = PostgresRAGContextProvider.from_config(
            RAGConfig(enabled=True, backend="postgres", vector_dimensions=3),
            connect=lambda _dsn: _FakeConnection([]),
            embedding_model=_FakeEmbeddingModel(),
        )

        self.assertIsInstance(provider, PostgresRAGContextProvider)

    def test_build_context_uses_hybrid_rows_and_optional_rerank(self) -> None:
        """Postgres provider should render retrieved rows into SOC context."""
        rows = [
            {
                "section_path": "General",
                "source_file": "general.md",
                "text": "General login troubleshooting procedure.",
            },
            {
                "section_path": "PowerShell",
                "source_file": "powershell.md",
                "text": "PowerShell encodedcommand triage procedure.",
            },
        ]
        connection = _FakeConnection(rows)
        provider = PostgresRAGContextProvider(
            RAGConfig(
                enabled=True,
                backend="postgres",
                vector_dimensions=3,
                rerank_enabled=True,
                postgres_statement_timeout_ms=2500,
                rrf_k=42,
                max_snippets_120b=2,
            ),
            connect=lambda _dsn: connection,
            embedding_model=_FakeEmbeddingModel(),
            reranker_model=_FakeReranker(),
        )

        context = provider.build_context(
            alert_text="PowerShell EncodedCommand alert", llm_model_name="gemma-4-31B-it"
        )

        self.assertIn("SOC_OPERATIONAL_CONTEXT", context)
        self.assertIn("[1] [powershell.md :: PowerShell]", context)
        self.assertIn("PowerShell encodedcommand triage procedure", context)
        self.assertIn("plainto_tsquery", connection.executed_sql)
        self.assertIn("1.0 / (42 + lexical.lexical_rank)", connection.executed_sql)
        self.assertEqual(
            connection.executed[0],
            ("SELECT set_config('statement_timeout', %s, true)", ("2500ms",)),
        )
        self.assertEqual(connection.executed_params[2], 30)
        self.assertEqual(connection.executed_params[5], 30)
        self.assertEqual(connection.executed_params[6], 40)

    def test_build_context_uses_deterministic_query_token_order(self) -> None:
        """Same alert text should produce stable query text before embedding."""
        connection = _FakeConnection([])
        provider = PostgresRAGContextProvider(
            RAGConfig(
                enabled=True,
                backend="postgres",
                vector_dimensions=3,
                postgres_statement_timeout_ms=0,
            ),
            connect=lambda _dsn: connection,
            embedding_model=_FakeEmbeddingModel(),
        )

        provider.build_context(
            alert_text="PowerShell EncodedCommand alert from 10.0.0.1",
            llm_model_name="gemma-4-31B-it",
        )

        self.assertEqual(
            connection.executed_params[0],
            "10.0.0.1 powershell encodedcommand alert",
        )

    def test_build_context_skips_statement_timeout_when_disabled(self) -> None:
        """Postgres retrieval should allow timeout opt-out for local debugging."""
        connection = _FakeConnection([])
        provider = PostgresRAGContextProvider(
            RAGConfig(
                enabled=True,
                backend="postgres",
                vector_dimensions=3,
                postgres_statement_timeout_ms=0,
            ),
            connect=lambda _dsn: connection,
            embedding_model=_FakeEmbeddingModel(),
        )

        context = provider.build_context(
            alert_text="PowerShell EncodedCommand alert", llm_model_name="gemma-4-31B-it"
        )

        self.assertEqual(context, "")
        self.assertNotEqual(
            connection.executed[0][0],
            "SELECT set_config('statement_timeout', %s, true)",
        )
        self.assertIn("plainto_tsquery", connection.executed[0][0])

    def test_build_context_rejects_embedding_dimension_mismatch(self) -> None:
        """Wrong embedding model/config combinations should fail before SQL execution."""
        connection = _FakeConnection([])
        provider = PostgresRAGContextProvider(
            RAGConfig(enabled=True, backend="postgres", vector_dimensions=3),
            connect=lambda _dsn: connection,
            embedding_model=_WrongDimensionEmbeddingModel(),
        )

        with self.assertLogs(
            "onprem_rag_notable_analysis.future.postgres_retrieval",
            level="WARNING",
        ) as logs:
            context = provider.build_context(
                alert_text="PowerShell EncodedCommand alert",
                llm_model_name="gemma-4-31B-it",
            )

        self.assertEqual(context, "")
        self.assertIn("Postgres RAG context build failed", "\n".join(logs.output))
        self.assertEqual(connection.executed, [])

    def test_build_context_uses_hybrid_order_when_reranker_fails(self) -> None:
        """Reranker failures should degrade to deterministic hybrid search order."""
        rows = [
            {
                "section_path": "First",
                "source_file": "first.md",
                "text": "PowerShell encodedcommand first hybrid result.",
            },
            {
                "section_path": "Second",
                "source_file": "second.md",
                "text": "PowerShell encodedcommand second hybrid result.",
            },
        ]
        connection = _FakeConnection(rows)
        provider = PostgresRAGContextProvider(
            RAGConfig(
                enabled=True,
                backend="postgres",
                vector_dimensions=3,
                rerank_enabled=True,
            ),
            connect=lambda _dsn: connection,
            embedding_model=_FakeEmbeddingModel(),
            reranker_model=_FailingReranker(),
        )

        context = provider.build_context(
            alert_text="PowerShell EncodedCommand alert", llm_model_name="gemma-4-31B-it"
        )

        self.assertIn("[1] [first.md :: First]", context)
        self.assertIn("[2] [second.md :: Second]", context)

    def test_build_context_applies_quality_gate_to_sql_fused_rows(self) -> None:
        """Postgres RAG should not include rows without alert-term overlap."""
        rows = [
            {
                "section_path": "General",
                "source_file": "general.md",
                "text": "General helpdesk onboarding procedure.",
            },
            {
                "section_path": "PowerShell",
                "source_file": "powershell.md",
                "text": "PowerShell encodedcommand triage procedure.",
            },
        ]
        connection = _FakeConnection(rows)
        provider = PostgresRAGContextProvider(
            RAGConfig(
                enabled=True,
                backend="postgres",
                vector_dimensions=3,
                postgres_statement_timeout_ms=0,
            ),
            connect=lambda _dsn: connection,
            embedding_model=_FakeEmbeddingModel(),
        )

        context = provider.build_context(
            alert_text="PowerShell EncodedCommand alert",
            llm_model_name="gemma-4-31B-it",
        )

        self.assertNotIn("general.md", context)
        self.assertIn("powershell.md", context)

    def test_build_context_returns_empty_for_empty_alert(self) -> None:
        """Empty input should not load models or query Postgres."""
        connection = _FakeConnection([])
        provider = PostgresRAGContextProvider(
            RAGConfig(enabled=True, backend="postgres", vector_dimensions=3),
            connect=lambda _dsn: connection,
            embedding_model=_FakeEmbeddingModel(),
        )

        self.assertEqual(
            provider.build_context(alert_text="", llm_model_name="gemma-4-31B-it"),
            "",
        )
        self.assertEqual(connection.executed, [])

    def test_build_context_returns_empty_on_database_error(self) -> None:
        """Postgres retrieval should fail open to empty context on DB errors."""

        def _raise(_dsn):
            raise RuntimeError("database unavailable")

        provider = PostgresRAGContextProvider(
            RAGConfig(enabled=True, backend="postgres", vector_dimensions=3),
            connect=_raise,
            embedding_model=_FakeEmbeddingModel(),
        )

        with self.assertLogs(
            "onprem_rag_notable_analysis.future.postgres_retrieval",
            level="WARNING",
        ) as logs:
            context = provider.build_context(
                alert_text="PowerShell EncodedCommand alert",
                llm_model_name="gemma-4-31B-it",
            )

        self.assertEqual(context, "")
        self.assertIn("Postgres RAG context build failed", "\n".join(logs.output))

    def test_build_context_can_fail_closed_on_database_error(self) -> None:
        """Production profiles can require RAG instead of silently degrading."""

        def _raise(_dsn):
            raise RuntimeError("database unavailable")

        provider = PostgresRAGContextProvider(
            RAGConfig(
                enabled=True,
                backend="postgres",
                vector_dimensions=3,
                fail_closed=True,
            ),
            connect=_raise,
            embedding_model=_FakeEmbeddingModel(),
        )

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            provider.build_context(
                alert_text="PowerShell EncodedCommand alert",
                llm_model_name="gemma-4-31B-it",
            )


if __name__ == "__main__":
    unittest.main()
