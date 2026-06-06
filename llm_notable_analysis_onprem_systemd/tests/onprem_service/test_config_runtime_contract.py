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
        self.assertFalse(config.CASE_ARCHIVE_ENABLED)
        self.assertEqual(config.CASE_POSTGRES_SCHEMA, "notable_cases")
        self.assertEqual(config.CASE_RETENTION_DAYS, 30)
        self.assertEqual(config.CASE_RETENTION_DELETE_BATCH_SIZE, 500)
        self.assertFalse(config.PORTAL_ENABLED)
        self.assertEqual(config.PORTAL_CHAT_MAX_CONCURRENCY, 4)
        self.assertFalse(config.CASE_QA_ENABLED)
        self.assertFalse(config.CASE_QA_GLOBAL_RETRIEVAL_ENABLED)
        self.assertFalse(config.CASE_QA_CHAT_HISTORY_ENABLED)
        self.assertEqual(config.CASE_QA_EMBEDDING_MODEL, "BAAI/bge-base-en-v1.5")
        self.assertEqual(config.CASE_QA_VECTOR_DIMENSIONS, 768)
        self.assertEqual(config.CASE_QA_LEXICAL_TOP_K, 30)
        self.assertEqual(config.CASE_QA_VECTOR_TOP_K, 30)
        self.assertEqual(config.CASE_QA_RRF_K, 60)
        self.assertEqual(config.CASE_QA_MAX_INDEX_CHUNKS_PER_CASE, 200)
        self.assertEqual(config.LLM_MODEL_NAME, "gemma-4-31B-it")
        self.assertEqual(config.LLM_TIMEOUT, 240)
        self.assertEqual(config.MAX_WORKERS, 1)
        self.assertEqual(config.MAX_QUEUE_DEPTH, 8)
        self.assertEqual(config.INVESTIGATION_MAX_CONCURRENT_QUERIES, 6)
        self.assertEqual(config.SPLUNK_SEARCH_TIMEOUT_SECONDS, 30)
        self.assertEqual(config.CAPABILITY_PROFILES, "core")
        self.assertFalse(config.HTML_REPORT_ENABLED)
        self.assertFalse(config.RAG_ENABLED)
        self.assertFalse(config.SPL_QUERY_GENERATION_ENABLED)
        self.assertFalse(config.ELASTIC_QUERY_GENERATION_ENABLED)
        self.assertFalse(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)
        self.assertEqual(config.INVESTIGATION_QUERY_BACKEND, "splunk")
        self.assertFalse(config.SERVICENOW_DRAFT_ENABLED)
        self.assertFalse(config.SERVICENOW_CREATE_ENABLED)
        self.assertFalse(config.SIDE_EFFECT_IDEMPOTENCY_ENABLED)
        self.assertEqual(config.SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS, 30)
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
        self.assertEqual(config.ELASTICSEARCH_TIMESTAMP_FIELD, "@timestamp")
        self.assertFalse(config.ELASTICSEARCH_GROUNDING_ENABLED)
        self.assertEqual(
            config.ELASTICSEARCH_GROUNDING_SOURCE_DIR.as_posix(),
            "/opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs",
        )
        self.assertEqual(
            config.ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE,
            "elasticsearch_query_chunks",
        )
        self.assertEqual(config.ELASTICSEARCH_MAX_ROWS, 100)
        self.assertEqual(config.ELASTICSEARCH_TIMEOUT_SECONDS, 30)

    def test_html_report_flag_loads_from_environment(self) -> None:
        """HTML dashboard report generation should be opt-in by config."""
        with patch.dict(os.environ, {"HTML_REPORT_ENABLED": "true"}, clear=True):
            config = load_config()

        self.assertTrue(config.HTML_REPORT_ENABLED)

    def test_capability_profiles_enable_named_feature_bundles(self) -> None:
        """Profiles should make supported feature bundles explicit at startup."""
        env = {
            "CAPABILITY_PROFILES": (
                "html_reports,rag,spl_readonly,ticket_draft,action_gated"
            )
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(
            config.CAPABILITY_PROFILES,
            "core,html_reports,rag,spl_readonly,ticket_draft,action_gated",
        )
        self.assertTrue(config.HTML_REPORT_ENABLED)
        self.assertTrue(config.RAG_ENABLED)
        self.assertTrue(config.SPL_QUERY_GENERATION_ENABLED)
        self.assertTrue(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)
        self.assertTrue(config.SPLUNK_SINK_ENABLED)
        self.assertTrue(config.SERVICENOW_DRAFT_ENABLED)
        self.assertTrue(config.SERVICENOW_CREATE_ENABLED)
        self.assertTrue(config.SERVICENOW_CREATE_REQUIRES_APPROVAL)
        self.assertTrue(config.SIDE_EFFECT_IDEMPOTENCY_ENABLED)
        self.assertEqual(config.INVESTIGATION_QUERY_BACKEND, "splunk")

    def test_analyst_portal_profile_enables_archive_portal_and_case_qa(self) -> None:
        """Analyst portal profile should enable only portal/archive capabilities."""
        with patch.dict(
            os.environ,
            {
                "CAPABILITY_PROFILES": "analyst_portal",
                "PORTAL_PROXY_SECRET": "portal-secret",
            },
            clear=True,
        ):
            config = load_config()

        self.assertEqual(config.CAPABILITY_PROFILES, "core,analyst_portal")
        self.assertTrue(config.CASE_ARCHIVE_ENABLED)
        self.assertTrue(config.PORTAL_ENABLED)
        self.assertTrue(config.CASE_QA_ENABLED)
        self.assertFalse(config.CASE_QA_GLOBAL_RETRIEVAL_ENABLED)
        self.assertFalse(config.CASE_QA_CHAT_HISTORY_ENABLED)
        self.assertFalse(config.SPLUNK_SINK_ENABLED)
        self.assertFalse(config.SERVICENOW_CREATE_ENABLED)
        self.assertFalse(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)

    def test_elastic_readonly_profile_enables_elastic_backend(self) -> None:
        """Elastic profile should mirror spl_readonly without enabling Splunk queries."""
        env = {
            "CAPABILITY_PROFILES": "elastic_readonly",
            "ELASTICSEARCH_BASE_URL": "https://elastic.internal:9200",
            "ELASTICSEARCH_API_KEY": "test-key",
            "ELASTICSEARCH_INDEX_ALLOWLIST": "logs-auth",
            "ELASTICSEARCH_ALLOWED_FIELDS": "@timestamp,user.name",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(config.CAPABILITY_PROFILES, "core,elastic_readonly")
        self.assertTrue(config.ELASTIC_QUERY_GENERATION_ENABLED)
        self.assertTrue(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)
        self.assertEqual(config.INVESTIGATION_QUERY_BACKEND, "elasticsearch")
        self.assertFalse(config.SPL_QUERY_GENERATION_ENABLED)

    def test_elastic_backend_selection_does_not_force_generation(self) -> None:
        """Backend selection alone should not silently enable query generation."""
        with patch.dict(
            os.environ,
            {"INVESTIGATION_QUERY_BACKEND": "elasticsearch"},
            clear=True,
        ):
            config = load_config()

        self.assertEqual(config.INVESTIGATION_QUERY_BACKEND, "elasticsearch")
        self.assertFalse(config.ELASTIC_QUERY_GENERATION_ENABLED)
        self.assertFalse(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)

    def test_elastic_execution_fails_fast_without_required_runtime_contract(self) -> None:
        """Enabled Elastic execution should not discover missing secrets at query time."""
        with patch.dict(
            os.environ,
            {
                "INVESTIGATION_QUERY_BACKEND": "elasticsearch",
                "INVESTIGATION_QUERY_EXECUTION_ENABLED": "true",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "ELASTICSEARCH_INDEX_ALLOWLIST"):
                load_config()

    def test_elastic_execution_requires_https_endpoint(self) -> None:
        """Elastic API keys should not be sent to plaintext endpoints."""
        env = {
            "INVESTIGATION_QUERY_BACKEND": "elasticsearch",
            "INVESTIGATION_QUERY_EXECUTION_ENABLED": "true",
            "ELASTICSEARCH_BASE_URL": "http://elastic.internal:9200",
            "ELASTICSEARCH_API_KEY": "test-key",
            "ELASTICSEARCH_INDEX_ALLOWLIST": "logs-auth",
            "ELASTICSEARCH_ALLOWED_FIELDS": "@timestamp,user.name",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                load_config()

    def test_elastic_execution_requires_allowed_fields_even_with_grounding(self) -> None:
        """Execution needs projection fields even when generation is grounded."""
        env = {
            "INVESTIGATION_QUERY_BACKEND": "elasticsearch",
            "INVESTIGATION_QUERY_EXECUTION_ENABLED": "true",
            "ELASTICSEARCH_BASE_URL": "https://elastic.internal:9200",
            "ELASTICSEARCH_API_KEY": "test-key",
            "ELASTICSEARCH_INDEX_ALLOWLIST": "logs-auth",
            "ELASTICSEARCH_GROUNDING_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "ELASTICSEARCH_ALLOWED_FIELDS"):
                load_config()

    def test_readonly_profiles_are_mutually_exclusive(self) -> None:
        """A deployment should choose one read-only investigation backend for v1."""
        with patch.dict(
            os.environ,
            {"CAPABILITY_PROFILES": "spl_readonly,elastic_readonly"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "spl_readonly and elastic_readonly"):
                load_config()

    def test_capability_profile_rejects_unknown_profile(self) -> None:
        """Unsupported profile names should fail fast instead of silently drifting."""
        with patch.dict(os.environ, {"CAPABILITY_PROFILES": "core,unknown"}, clear=True):
            with self.assertRaisesRegex(ValueError, "unsupported profile"):
                load_config()

    def test_profile_defaults_take_precedence_over_baseline_false_flags(self) -> None:
        """Copied config examples should not accidentally disable selected profiles."""
        env = {
            "CAPABILITY_PROFILES": "html_reports",
            "HTML_REPORT_ENABLED": "false",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertTrue(config.HTML_REPORT_ENABLED)

    def test_legacy_true_flag_still_enables_capability_without_profile(self) -> None:
        """Existing deployments can still use raw flags outside profile bundles."""
        with patch.dict(os.environ, {"HTML_REPORT_ENABLED": "true"}, clear=True):
            config = load_config()

        self.assertTrue(config.HTML_REPORT_ENABLED)

    def test_capability_profiles_accept_semicolon_separator(self) -> None:
        """Semicolon-separated profile lists should normalize to comma output."""
        with patch.dict(
            os.environ,
            {"CAPABILITY_PROFILES": "html_reports;rag"},
            clear=True,
        ):
            config = load_config()

        self.assertEqual(config.CAPABILITY_PROFILES, "core,html_reports,rag")
        self.assertTrue(config.HTML_REPORT_ENABLED)
        self.assertTrue(config.RAG_ENABLED)

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

    def test_case_archive_contract_loads_from_environment(self) -> None:
        """Case archive and portal settings should be explicit env values."""
        env = {
            "CASE_ARCHIVE_ENABLED": "true",
            "CASE_POSTGRES_DSN": "postgresql://cases@127.0.0.1:5432/notables",
            "CASE_POSTGRES_SCHEMA": "customer_cases",
            "CASE_RETENTION_DAYS": "120",
            "CASE_RETENTION_DELETE_BATCH_SIZE": "250",
            "CASE_ARCHIVE_WRITE_MAX_ATTEMPTS": "4",
            "CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS": "2",
            "CASE_POSTGRES_STATEMENT_TIMEOUT_MS": "2500",
            "CASE_SCHEMA_VERSION": "2",
            "CASE_ANALYSIS_SCHEMA_VERSION": "3",
            "CASE_QA_ENABLED": "true",
            "CASE_QA_GLOBAL_RETRIEVAL_ENABLED": "true",
            "CASE_QA_MAX_RETRIEVED_CASES": "7",
            "CASE_QA_MAX_CHUNKS_PER_LANE": "8",
            "CASE_QA_MAX_TOTAL_CHUNKS": "20",
            "CASE_QA_MAX_INDEX_CHUNKS_PER_CASE": "210",
            "CASE_QA_CONTEXT_BUDGET_CHARS": "15000",
            "CASE_QA_MAX_QUESTION_CHARS": "3000",
            "CASE_QA_MAX_ANSWER_TOKENS": "900",
            "CASE_QA_CHUNK_SCHEMA_VERSION": "2",
            "CASE_QA_EMBEDDING_MODEL": "custom/bge",
            "CASE_QA_VECTOR_DIMENSIONS": "768",
            "CASE_QA_CHAT_HISTORY_RETENTION_DAYS": "14",
            "CASE_QA_MAX_MESSAGES_PER_SESSION": "40",
            "CASE_QA_MAX_STORED_MESSAGE_BYTES": "5000",
            "CASE_QA_LEXICAL_TOP_K": "31",
            "CASE_QA_VECTOR_TOP_K": "32",
            "CASE_QA_RRF_K": "61",
            "PORTAL_ENABLED": "true",
            "PORTAL_BIND_HOST": "127.0.0.2",
            "PORTAL_PORT": "8081",
            "PORTAL_PAGE_SIZE": "25",
            "PORTAL_CHAT_MAX_CONCURRENCY": "8",
            "PORTAL_TRUSTED_USER_HEADER": "X-Test-User",
            "PORTAL_PROXY_SECRET": "portal-secret",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertTrue(config.CASE_ARCHIVE_ENABLED)
        self.assertEqual(config.CASE_POSTGRES_DSN, "postgresql://cases@127.0.0.1:5432/notables")
        self.assertEqual(config.CASE_POSTGRES_SCHEMA, "customer_cases")
        self.assertEqual(config.CASE_RETENTION_DAYS, 120)
        self.assertEqual(config.CASE_RETENTION_DELETE_BATCH_SIZE, 250)
        self.assertEqual(config.CASE_ARCHIVE_WRITE_MAX_ATTEMPTS, 4)
        self.assertEqual(config.CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS, 2)
        self.assertEqual(config.CASE_POSTGRES_STATEMENT_TIMEOUT_MS, 2500)
        self.assertEqual(config.CASE_SCHEMA_VERSION, 2)
        self.assertEqual(config.CASE_ANALYSIS_SCHEMA_VERSION, 3)
        self.assertTrue(config.CASE_QA_ENABLED)
        self.assertTrue(config.CASE_QA_GLOBAL_RETRIEVAL_ENABLED)
        self.assertEqual(config.CASE_QA_MAX_RETRIEVED_CASES, 7)
        self.assertEqual(config.CASE_QA_MAX_CHUNKS_PER_LANE, 8)
        self.assertEqual(config.CASE_QA_MAX_TOTAL_CHUNKS, 20)
        self.assertEqual(config.CASE_QA_MAX_INDEX_CHUNKS_PER_CASE, 210)
        self.assertEqual(config.CASE_QA_CONTEXT_BUDGET_CHARS, 15000)
        self.assertEqual(config.CASE_QA_MAX_QUESTION_CHARS, 3000)
        self.assertEqual(config.CASE_QA_MAX_ANSWER_TOKENS, 900)
        self.assertEqual(config.CASE_QA_CHUNK_SCHEMA_VERSION, 2)
        self.assertEqual(config.CASE_QA_EMBEDDING_MODEL, "custom/bge")
        self.assertEqual(config.CASE_QA_VECTOR_DIMENSIONS, 768)
        self.assertFalse(config.CASE_QA_CHAT_HISTORY_ENABLED)
        self.assertEqual(config.CASE_QA_CHAT_HISTORY_RETENTION_DAYS, 14)
        self.assertEqual(config.CASE_QA_MAX_MESSAGES_PER_SESSION, 40)
        self.assertEqual(config.CASE_QA_MAX_STORED_MESSAGE_BYTES, 5000)
        self.assertEqual(config.CASE_QA_LEXICAL_TOP_K, 31)
        self.assertEqual(config.CASE_QA_VECTOR_TOP_K, 32)
        self.assertEqual(config.CASE_QA_RRF_K, 61)
        self.assertTrue(config.PORTAL_ENABLED)
        self.assertEqual(config.PORTAL_BIND_HOST, "127.0.0.2")
        self.assertEqual(config.PORTAL_PORT, 8081)
        self.assertEqual(config.PORTAL_PAGE_SIZE, 25)
        self.assertEqual(config.PORTAL_CHAT_MAX_CONCURRENCY, 8)
        self.assertEqual(config.PORTAL_TRUSTED_USER_HEADER, "X-Test-User")

    def test_portal_enabled_requires_proxy_secret(self) -> None:
        """Portal deployments should not trust a forgeable user header alone."""
        with patch.dict(
            os.environ,
            {"PORTAL_ENABLED": "true", "CASE_ARCHIVE_ENABLED": "true"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "PORTAL_PROXY_SECRET"):
                load_config()

    def test_chat_enabled_requires_case_archive(self) -> None:
        """Archive-backed chat should not start without the case archive."""
        with patch.dict(os.environ, {"CASE_QA_ENABLED": "true"}, clear=True):
            with self.assertRaisesRegex(ValueError, "CASE_ARCHIVE_ENABLED"):
                load_config()

    def test_chat_history_enabled_requires_case_qa(self) -> None:
        """Persisted chat history should not start without portal chat."""
        with patch.dict(
            os.environ,
            {
                "CASE_ARCHIVE_ENABLED": "true",
                "CASE_QA_CHAT_HISTORY_ENABLED": "true",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "CASE_QA_ENABLED"):
                load_config()

    def test_chat_history_enabled_loads_with_case_qa(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CASE_ARCHIVE_ENABLED": "true",
                "CASE_QA_ENABLED": "true",
                "CASE_QA_CHAT_HISTORY_ENABLED": "true",
            },
            clear=True,
        ):
            config = load_config()
        self.assertTrue(config.CASE_QA_CHAT_HISTORY_ENABLED)

    def test_case_qa_vector_dimensions_are_fixed_for_v1(self) -> None:
        """Case archive schema is vector(768), so v1 config must not drift."""
        with patch.dict(
            os.environ,
            {"CASE_QA_VECTOR_DIMENSIONS": "1024"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "CASE_QA_VECTOR_DIMENSIONS"):
                load_config()

    def test_case_archive_enabled_rejects_invalid_postgres_schema(self) -> None:
        """Archive writes should fail at startup for unsafe schema names."""
        with patch.dict(
            os.environ,
            {
                "CASE_ARCHIVE_ENABLED": "true",
                "CASE_POSTGRES_SCHEMA": "bad-schema",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "CASE_POSTGRES_SCHEMA"):
                load_config()

    def test_case_archive_enabled_requires_postgres_dsn(self) -> None:
        """Archive-enabled deployments should not fall through to libpq defaults."""
        with patch.dict(
            os.environ,
            {
                "CASE_ARCHIVE_ENABLED": "true",
                "CASE_POSTGRES_DSN": "",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "CASE_POSTGRES_DSN"):
                load_config()

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

    def test_elasticsearch_contract_loads_from_environment(self) -> None:
        """Elasticsearch read-only query path should expose explicit tuning values."""
        env = {
            "INVESTIGATION_QUERY_BACKEND": "elasticsearch",
            "ELASTIC_QUERY_GENERATION_ENABLED": "true",
            "ELASTICSEARCH_BASE_URL": "https://elastic.internal:9200",
            "ELASTICSEARCH_API_KEY": "test-key",
            "ELASTICSEARCH_INDEX_ALLOWLIST": "logs-auth,security-*",
            "ELASTICSEARCH_ALLOW_WILDCARD_INDEXES": "true",
            "ELASTICSEARCH_TIMESTAMP_FIELD": "event.ingested",
            "ELASTICSEARCH_ALLOWED_FIELDS": "event.ingested,user.name,host.name",
            "ELASTICSEARCH_GROUNDING_ENABLED": "true",
            "ELASTICSEARCH_GROUNDING_SOURCE_DIR": "/kb/elastic/source",
            "ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE": "customer_elastic_chunks",
            "ELASTICSEARCH_GROUNDING_MAX_SNIPPETS": "3",
            "ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS": "900",
            "ELASTICSEARCH_GROUNDING_FAILURE_MODE": "fallback_to_ungrounded",
            "ELASTICSEARCH_MAX_TIME_RANGE": "12h",
            "ELASTICSEARCH_MAX_ROWS": "50",
            "ELASTICSEARCH_TIMEOUT_SECONDS": "12",
            "ELASTICSEARCH_CA_BUNDLE": "/etc/pki/elastic-ca.pem",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(config.INVESTIGATION_QUERY_BACKEND, "elasticsearch")
        self.assertTrue(config.ELASTIC_QUERY_GENERATION_ENABLED)
        self.assertEqual(config.ELASTICSEARCH_BASE_URL, "https://elastic.internal:9200")
        self.assertEqual(config.ELASTICSEARCH_API_KEY, "test-key")
        self.assertEqual(config.ELASTICSEARCH_INDEX_ALLOWLIST, "logs-auth,security-*")
        self.assertTrue(config.ELASTICSEARCH_ALLOW_WILDCARD_INDEXES)
        self.assertEqual(config.ELASTICSEARCH_TIMESTAMP_FIELD, "event.ingested")
        self.assertEqual(
            config.ELASTICSEARCH_ALLOWED_FIELDS,
            "event.ingested,user.name,host.name",
        )
        self.assertTrue(config.ELASTICSEARCH_GROUNDING_ENABLED)
        self.assertEqual(
            config.ELASTICSEARCH_GROUNDING_SOURCE_DIR.as_posix(),
            "/kb/elastic/source",
        )
        self.assertEqual(
            config.ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE,
            "customer_elastic_chunks",
        )
        self.assertEqual(config.ELASTICSEARCH_GROUNDING_MAX_SNIPPETS, 3)
        self.assertEqual(config.ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS, 900)
        self.assertEqual(
            config.ELASTICSEARCH_GROUNDING_FAILURE_MODE,
            "fallback_to_ungrounded",
        )
        self.assertEqual(config.ELASTICSEARCH_MAX_TIME_RANGE, "12h")
        self.assertEqual(config.ELASTICSEARCH_MAX_ROWS, 50)
        self.assertEqual(config.ELASTICSEARCH_TIMEOUT_SECONDS, 12)
        self.assertEqual(config.ELASTICSEARCH_CA_BUNDLE, "/etc/pki/elastic-ca.pem")

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
            {"ELASTICSEARCH_MAX_ROWS": "0"},
            {"ELASTICSEARCH_TIMEOUT_SECONDS": "0"},
            {"ELASTICSEARCH_GROUNDING_MAX_SNIPPETS": "0"},
            {"ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS": "0"},
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
        self.assertEqual(direct.CAPABILITY_PROFILES, loaded.CAPABILITY_PROFILES)
        self.assertEqual(direct.HTML_REPORT_ENABLED, loaded.HTML_REPORT_ENABLED)
        self.assertEqual(direct.RAG_ENABLED, loaded.RAG_ENABLED)
        self.assertEqual(direct.SPLUNK_SINK_ENABLED, loaded.SPLUNK_SINK_ENABLED)
        self.assertEqual(
            direct.SIDE_EFFECT_IDEMPOTENCY_ENABLED,
            loaded.SIDE_EFFECT_IDEMPOTENCY_ENABLED,
        )

    def test_direct_config_applies_selected_profiles(self) -> None:
        """Direct Config construction should not bypass profile flag resolution."""
        config = Config(
            CAPABILITY_PROFILES="html_reports;rag;action_gated",
            HTML_REPORT_ENABLED=False,
            RAG_ENABLED=False,
            SPLUNK_SINK_ENABLED=False,
            SERVICENOW_CREATE_ENABLED=False,
        )

        self.assertEqual(
            config.CAPABILITY_PROFILES,
            "core,html_reports,rag,action_gated",
        )
        self.assertTrue(config.HTML_REPORT_ENABLED)
        self.assertTrue(config.RAG_ENABLED)
        self.assertTrue(config.SPLUNK_SINK_ENABLED)
        self.assertTrue(config.SERVICENOW_CREATE_ENABLED)
        self.assertTrue(config.SIDE_EFFECT_IDEMPOTENCY_ENABLED)

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
