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
