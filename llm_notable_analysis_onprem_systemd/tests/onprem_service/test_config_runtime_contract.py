import os
import unittest
from unittest.mock import patch

# Runtime-contract tests intentionally call the private RAG provider factory.
# pylint: disable=protected-access,import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config, load_config
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import (
    LocalLLMClient,
)
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client_nonsdk import (
    LocalLLMClient as NonSDKLocalLLMClient,
)


class TestConfigRuntimeContract(unittest.TestCase):
    def test_defaults_target_litellm_and_bge_contract(self) -> None:
        """Default config should expose the new on-prem runtime targets."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()

        self.assertEqual(
            config.LLM_API_URL,
            "http://127.0.0.1:4000/v1/chat/completions",
        )
        self.assertEqual(config.RAG_BACKEND, "postgres")
        self.assertFalse(config.RAG_FAIL_CLOSED)
        self.assertEqual(config.RAG_EMBEDDING_MODEL, "BAAI/bge-base-en-v1.5")
        self.assertFalse(config.RAG_RERANK_ENABLED)
        self.assertEqual(config.RAG_RERANK_MODEL, "BAAI/bge-reranker-base")
        self.assertEqual(config.RAG_VECTOR_DIMENSIONS, 768)
        self.assertEqual(config.RAG_POSTGRES_STATEMENT_TIMEOUT_MS, 5000)
        self.assertEqual(config.RAG_FUSED_RANK_LIMIT_120B, 8)
        self.assertEqual(config.RAG_FUSED_RANK_LIMIT_20B, 6)
        self.assertEqual(config.RAG_LEXICAL_TOP_K, 30)
        self.assertEqual(config.RAG_VECTOR_TOP_K, 30)
        self.assertEqual(config.RAG_CANDIDATE_POOL_LIMIT, 40)
        self.assertEqual(config.RAG_RRF_K, 60)
        self.assertEqual(config.LLM_MODEL_NAME, "gemma-4-31B-it")
        self.assertEqual(config.LLM_TIMEOUT, 120)
        self.assertFalse(config.SPL_QUERY_RAG_ENABLED)
        self.assertEqual(
            config.SPL_QUERY_RAG_SOURCE_DIR.as_posix(),
            "/opt/llm-notable-analysis/knowledge_base/spl_query_source_docs",
        )
        self.assertEqual(
            config.SPL_QUERY_RAG_INDEX_DIR.as_posix(),
            "/opt/llm-notable-analysis/knowledge_base/spl_query_index",
        )
        self.assertEqual(config.SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE, "spl_query_chunks")
        self.assertEqual(config.SPL_QUERY_RAG_MAX_SNIPPETS, 4)
        self.assertEqual(config.SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS, 1600)
        self.assertEqual(config.SPL_QUERY_RAG_FAILURE_MODE, "suppress")
        self.assertFalse(config.QUERY_RESULT_INTERPRETATION_ENABLED)
        self.assertEqual(config.QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS, 4000)
        self.assertEqual(config.QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS, 3)
        self.assertEqual(config.QUERY_RESULT_INTERPRETATION_MAX_TOKENS, 768)

    def test_postgres_rag_contract_loads_from_environment(self) -> None:
        """Postgres/pgvector RAG settings should be explicit env contract values."""
        env = {
            "RAG_BACKEND": "postgres",
            "RAG_FAIL_CLOSED": "true",
            "RAG_POSTGRES_DSN": "postgresql://svc@127.0.0.1:5432/kb",
            "RAG_POSTGRES_SCHEMA": "soc_kb",
            "RAG_POSTGRES_CHUNKS_TABLE": "chunks",
            "RAG_POSTGRES_FTS_CONFIG": "simple",
            "RAG_POSTGRES_STATEMENT_TIMEOUT_MS": "2500",
            "RAG_VECTOR_DIMENSIONS": "1024",
            "RAG_RERANK_ENABLED": "true",
            "RAG_RERANK_MODEL": "BAAI/bge-reranker-large",
            "RAG_FUSED_RANK_LIMIT_120B": "9",
            "RAG_FUSED_RANK_LIMIT_20B": "7",
            "RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD": "0.85",
            "RAG_LEXICAL_TOP_K": "20",
            "RAG_VECTOR_TOP_K": "21",
            "RAG_CANDIDATE_POOL_LIMIT": "22",
            "RAG_RRF_K": "50",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(config.RAG_BACKEND, "postgres")
        self.assertTrue(config.RAG_FAIL_CLOSED)
        self.assertEqual(config.RAG_POSTGRES_DSN, "postgresql://svc@127.0.0.1:5432/kb")
        self.assertEqual(config.RAG_POSTGRES_SCHEMA, "soc_kb")
        self.assertEqual(config.RAG_POSTGRES_CHUNKS_TABLE, "chunks")
        self.assertEqual(config.RAG_POSTGRES_FTS_CONFIG, "simple")
        self.assertEqual(config.RAG_POSTGRES_STATEMENT_TIMEOUT_MS, 2500)
        self.assertEqual(config.RAG_VECTOR_DIMENSIONS, 1024)
        self.assertTrue(config.RAG_RERANK_ENABLED)
        self.assertEqual(config.RAG_RERANK_MODEL, "BAAI/bge-reranker-large")
        self.assertEqual(config.RAG_FUSED_RANK_LIMIT_120B, 9)
        self.assertEqual(config.RAG_FUSED_RANK_LIMIT_20B, 7)
        self.assertEqual(config.RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD, 0.85)
        self.assertEqual(config.RAG_LEXICAL_TOP_K, 20)
        self.assertEqual(config.RAG_VECTOR_TOP_K, 21)
        self.assertEqual(config.RAG_CANDIDATE_POOL_LIMIT, 22)
        self.assertEqual(config.RAG_RRF_K, 50)

    def test_spl_query_rag_contract_loads_from_environment(self) -> None:
        """SPL-dedicated RAG should expose a separate config contract."""
        env = {
            "SPL_QUERY_RAG_ENABLED": "true",
            "SPL_QUERY_RAG_SOURCE_DIR": "/kb/spl/source",
            "SPL_QUERY_RAG_INDEX_DIR": "/kb/spl/index",
            "SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE": "customer_spl_chunks",
            "SPL_QUERY_RAG_MAX_SNIPPETS": "3",
            "SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS": "900",
            "SPL_QUERY_RAG_FAILURE_MODE": "fallback_to_ungrounded",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertTrue(config.SPL_QUERY_RAG_ENABLED)
        self.assertEqual(config.SPL_QUERY_RAG_SOURCE_DIR.as_posix(), "/kb/spl/source")
        self.assertEqual(config.SPL_QUERY_RAG_INDEX_DIR.as_posix(), "/kb/spl/index")
        self.assertEqual(
            config.SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE,
            "customer_spl_chunks",
        )
        self.assertEqual(config.SPL_QUERY_RAG_MAX_SNIPPETS, 3)
        self.assertEqual(config.SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS, 900)
        self.assertEqual(config.SPL_QUERY_RAG_FAILURE_MODE, "fallback_to_ungrounded")

    def test_query_result_interpretation_contract_loads_from_environment(self) -> None:
        """Query-result interpretation should be independently flag-gated."""
        env = {
            "QUERY_RESULT_INTERPRETATION_ENABLED": "true",
            "QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS": "2500",
            "QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS": "2",
            "QUERY_RESULT_INTERPRETATION_MAX_TOKENS": "512",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertTrue(config.QUERY_RESULT_INTERPRETATION_ENABLED)
        self.assertEqual(config.QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS, 2500)
        self.assertEqual(config.QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS, 2)
        self.assertEqual(config.QUERY_RESULT_INTERPRETATION_MAX_TOKENS, 512)

    def test_query_execution_and_interpretation_bounds_reject_invalid_values(self) -> None:
        """Bounded execution settings should fail fast on invalid integers."""
        invalid_envs = [
            {"QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS": "0"},
            {"QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS": "-1"},
            {"QUERY_RESULT_INTERPRETATION_MAX_TOKENS": "0"},
            {"INVESTIGATION_MAX_CONCURRENT_QUERIES": "0"},
            {"INVESTIGATION_MAX_QUERIES_PER_ALERT": "0"},
            {"SPLUNK_SEARCH_MAX_ROWS": "0"},
            {"SPLUNK_SEARCH_TIMEOUT_SECONDS": "0"},
        ]

        for env in invalid_envs:
            with self.subTest(env=env):
                with patch.dict(os.environ, env, clear=True):
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        load_config()

    def test_dataclass_defaults_match_loader_defaults(self) -> None:
        """Direct Config construction should match the runtime loader defaults."""
        with patch.dict(os.environ, {}, clear=True):
            loaded = load_config()

        direct = Config()

        self.assertEqual(direct.LLM_API_URL, loaded.LLM_API_URL)
        self.assertEqual(direct.LLM_TIMEOUT, loaded.LLM_TIMEOUT)
        self.assertEqual(direct.RAG_BACKEND, loaded.RAG_BACKEND)
        self.assertEqual(direct.RAG_EMBEDDING_MODEL, loaded.RAG_EMBEDDING_MODEL)
        self.assertEqual(direct.RAG_POSTGRES_DSN, loaded.RAG_POSTGRES_DSN)
        self.assertEqual(
            direct.RAG_POSTGRES_STATEMENT_TIMEOUT_MS,
            loaded.RAG_POSTGRES_STATEMENT_TIMEOUT_MS,
        )
        self.assertEqual(
            direct.SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE,
            loaded.SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE,
        )
        self.assertEqual(
            direct.QUERY_RESULT_INTERPRETATION_ENABLED,
            loaded.QUERY_RESULT_INTERPRETATION_ENABLED,
        )
        self.assertEqual(
            direct.QUERY_RESULT_INTERPRETATION_MAX_TOKENS,
            loaded.QUERY_RESULT_INTERPRETATION_MAX_TOKENS,
        )

    def test_local_llm_client_selects_postgres_rag_provider(self) -> None:
        """LocalLLMClient should wire the Postgres provider when configured."""
        client = object.__new__(LocalLLMClient)
        client.config = Config(RAG_ENABLED=True, RAG_BACKEND="postgres")
        sentinel = object()

        with patch(
            "onprem_rag_notable_analysis.future.postgres_retrieval."
            "PostgresRAGContextProvider.from_config",
            return_value=sentinel,
        ) as from_config:
            provider = client._init_rag_provider()

        self.assertIs(provider, sentinel)
        from_config.assert_called_once()
        rag_config = from_config.call_args.args[0]
        self.assertEqual(rag_config.backend, "postgres")
        self.assertEqual(rag_config.rrf_k, 60)

    def test_local_llm_client_selects_sqlite_faiss_fallback_provider(self) -> None:
        """LocalLLMClient should keep the SQLite/FAISS fallback path wired."""
        client = object.__new__(LocalLLMClient)
        client.config = Config(RAG_ENABLED=True, RAG_BACKEND="sqlite_faiss")
        sentinel = object()

        with patch(
            "onprem_rag_notable_analysis.future.retrieval."
            "RAGContextProvider.from_config",
            return_value=sentinel,
        ) as from_config:
            provider = client._init_rag_provider()

        self.assertIs(provider, sentinel)
        from_config.assert_called_once()

    def test_local_llm_client_selects_spl_query_rag_provider(self) -> None:
        """SPL query RAG should use the configured separate Postgres table."""
        client = object.__new__(LocalLLMClient)
        client.config = Config(
            SPL_QUERY_RAG_ENABLED=True,
            SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE="customer_spl_chunks",
        )
        sentinel = object()

        with patch(
            "onprem_rag_notable_analysis.future.postgres_retrieval."
            "PostgresRAGContextProvider.from_config",
            return_value=sentinel,
        ) as from_config:
            provider = client._init_spl_query_rag_provider()

        self.assertIs(provider, sentinel)
        rag_config = from_config.call_args.args[0]
        self.assertEqual(rag_config.context_header, "SPL_QUERY_GROUNDING_CONTEXT")
        self.assertEqual(rag_config.postgres_chunks_table, "customer_spl_chunks")
        self.assertTrue(rag_config.fail_closed)

    def test_local_llm_client_rejects_unsupported_rag_backend(self) -> None:
        """Unsupported RAG backends should fail open without provider setup."""
        client = object.__new__(LocalLLMClient)
        client.config = Config(RAG_ENABLED=True, RAG_BACKEND="unknown_backend")

        with self.assertLogs(
            "llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client",
            level="WARNING",
        ) as logs:
            provider = client._init_rag_provider()

        self.assertIsNone(provider)
        self.assertIn("Unsupported RAG backend 'unknown_backend'", "\n".join(logs.output))

    def test_local_llm_client_can_fail_closed_for_unsupported_rag_backend(self) -> None:
        """Fail-closed RAG should turn unsupported backend config into startup error."""
        client = object.__new__(LocalLLMClient)
        client.config = Config(
            RAG_ENABLED=True,
            RAG_BACKEND="unknown_backend",
            RAG_FAIL_CLOSED=True,
        )

        with self.assertRaisesRegex(ValueError, "Unsupported RAG backend"):
            client._init_rag_provider()

    def test_local_llm_client_fails_closed_when_provider_missing_at_request_time(self) -> None:
        """Fail-closed RAG should not silently drop context when provider is missing."""
        client = object.__new__(LocalLLMClient)
        client.config = Config(RAG_ENABLED=True, RAG_FAIL_CLOSED=True)
        client._rag_provider = None

        with self.assertRaisesRegex(RuntimeError, "provider is unavailable"):
            client._build_soc_operational_context("PowerShell alert")

    def test_nonsdk_local_llm_client_selects_postgres_rag_provider(self) -> None:
        """Non-SDK client should keep RAG wiring parity with the SDK client."""
        client = object.__new__(NonSDKLocalLLMClient)
        client.config = Config(RAG_ENABLED=True, RAG_BACKEND="postgres", RAG_RRF_K=55)
        sentinel = object()

        with patch(
            "onprem_rag_notable_analysis.future.postgres_retrieval."
            "PostgresRAGContextProvider.from_config",
            return_value=sentinel,
        ) as from_config:
            provider = client._init_rag_provider()

        self.assertIs(provider, sentinel)
        rag_config = from_config.call_args.args[0]
        self.assertEqual(rag_config.backend, "postgres")
        self.assertEqual(rag_config.rrf_k, 55)

    def test_nonsdk_local_llm_client_selects_spl_query_rag_provider(self) -> None:
        """Non-SDK client should keep SPL query RAG wiring parity."""
        client = object.__new__(NonSDKLocalLLMClient)
        client.config = Config(
            SPL_QUERY_RAG_ENABLED=True,
            SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE="customer_spl_chunks",
        )
        sentinel = object()

        with patch(
            "onprem_rag_notable_analysis.future.postgres_retrieval."
            "PostgresRAGContextProvider.from_config",
            return_value=sentinel,
        ) as from_config:
            provider = client._init_spl_query_rag_provider()

        self.assertIs(provider, sentinel)
        rag_config = from_config.call_args.args[0]
        self.assertEqual(rag_config.context_header, "SPL_QUERY_GROUNDING_CONTEXT")
        self.assertEqual(rag_config.postgres_chunks_table, "customer_spl_chunks")

    def test_nonsdk_local_llm_client_can_fail_closed_for_bad_rag_backend(self) -> None:
        """Non-SDK client should also honor fail-closed RAG configuration."""
        client = object.__new__(NonSDKLocalLLMClient)
        client.config = Config(
            RAG_ENABLED=True,
            RAG_BACKEND="unknown_backend",
            RAG_FAIL_CLOSED=True,
        )

        with self.assertRaisesRegex(ValueError, "Unsupported RAG backend"):
            client._init_rag_provider()

    def test_nonsdk_local_llm_client_fails_closed_when_provider_missing(self) -> None:
        """Non-SDK fail-closed RAG should also reject missing providers."""
        client = object.__new__(NonSDKLocalLLMClient)
        client.config = Config(RAG_ENABLED=True, RAG_FAIL_CLOSED=True)
        client._rag_provider = None

        with self.assertRaisesRegex(RuntimeError, "provider is unavailable"):
            client._build_soc_operational_context("PowerShell alert")


if __name__ == "__main__":
    unittest.main()
