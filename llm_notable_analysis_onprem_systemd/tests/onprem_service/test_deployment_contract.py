from pathlib import Path
import unittest

# Pylint cannot infer Path.parents indexing in this test module.
# pylint: disable=no-member


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent


class TestDeploymentContract(unittest.TestCase):
    def test_analyzer_depends_on_litellm_service(self) -> None:
        """Analyzer startup should be gated on the LiteLLM proxy."""
        service_text = (
            PROJECT_ROOT / "deploy" / "systemd" / "notable-analyzer.service"
        ).read_text(encoding="utf-8")

        self.assertIn("After=network.target litellm.service", service_text)
        self.assertIn("Requires=litellm.service", service_text)
        self.assertIn("HF_HOME=/var/notables/cache/huggingface", service_text)
        self.assertIn(
            "SENTENCE_TRANSFORMERS_HOME=/var/notables/cache/sentence-transformers",
            service_text,
        )
        self.assertIn(
            "ReadWritePaths=/var/notables /var/notables/cache /var/sftp/soar",
            service_text,
        )

    def test_freeform_analyzer_service_is_removed(self) -> None:
        """Structured analyzer is the only supported report path."""
        self.assertFalse(
            (
                PROJECT_ROOT
                / "deploy"
                / "systemd"
                / "notable-analyzer-freeform.service"
            ).exists()
        )

    def test_vllm_service_targets_notable_analysis_context_window(self) -> None:
        """Default vLLM unit should match gemma-4-31B-it notable-analysis tuning."""
        service_text = (
            PROJECT_ROOT / "deploy" / "systemd" / "vllm.service"
        ).read_text(encoding="utf-8")

        self.assertIn("--gpu-memory-utilization 0.92", service_text)
        self.assertIn("--max-model-len 32768", service_text)
        self.assertIn("--host 127.0.0.1", service_text)
        self.assertIn("--port 8000", service_text)
        self.assertIn('Environment="CUDA_HOME=/usr/local/cuda"', service_text)
        self.assertIn("/usr/local/cuda/bin:/opt/vllm/venv/bin", service_text)

    def test_litellm_service_is_loopback_only(self) -> None:
        """LiteLLM should bind only to loopback in the default unit."""
        service_text = (
            PROJECT_ROOT / "deploy" / "systemd" / "litellm.service"
        ).read_text(encoding="utf-8")

        self.assertIn("--host 127.0.0.1", service_text)
        self.assertIn("--port 4000", service_text)
        self.assertIn("User=litellm", service_text)
        self.assertIn("Wants=vllm.service", service_text)
        self.assertNotIn("Requires=vllm.service", service_text)

    def test_litellm_config_routes_default_model_to_local_vllm(self) -> None:
        """Default LiteLLM config should route analyzer model name to local vLLM."""
        config_text = (
            PROJECT_ROOT / "deploy" / "litellm" / "config.yaml.example"
        ).read_text(encoding="utf-8")

        self.assertIn("model_name: gemma-4-31B-it", config_text)
        self.assertIn("model: hosted_vllm/gemma-4-31B-it", config_text)
        self.assertIn("api_base: http://127.0.0.1:8000/v1", config_text)

    def test_installer_packages_rag_helpers_into_analyzer_venv(self) -> None:
        """Installer should install RAG helpers so runtime imports work on host."""
        install_text = (PROJECT_ROOT / "scripts" / "install.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("RAG_PACKAGE_SRC_DIR", install_text)
        self.assertIn("SDK_SOURCE_DIR", install_text)
        self.assertIn("RAG_PACKAGE_INSTALL_DIR", install_text)
        self.assertIn("onprem-llm-sdk from", install_text)
        self.assertIn("install_portal_os_packages", install_text)
        self.assertIn("install_portal_pgvector_os_package", install_text)
        self.assertIn("install_portal_pgvector_from_source", install_text)
        self.assertIn("verify_postgresql_pgvector_extension", install_text)
        self.assertIn("sync_portal_proxy_secret_to_config", install_text)
        self.assertIn("ensure_case_archive_postgres_passwords", install_text)
        self.assertIn("INSTALL_PORTAL_ALLOW_PARTIAL", install_text)
        self.assertIn("postgresql-server-devel", install_text)
        self.assertIn("postgresql-", install_text)
        self.assertIn("pgvector", install_text)
        self.assertIn("build_analyst_portal_frontend", install_text)
        self.assertIn("resolve_portal_frontend_toolchain", install_text)
        self.assertIn("PORTAL_NODE_TOOLCHAIN_PATH", install_text)
        self.assertIn("npm run build", install_text)
        self.assertIn("INSTALL_PORTAL_SKIP_OS_PACKAGES", install_text)
        self.assertIn("INSTALL_PORTAL_SKIP_FRONTEND_BUILD", install_text)
        self.assertIn("onprem_rag_notable_analysis package", install_text)
        self.assertIn("$DATA_DIR/cache/huggingface", install_text)
        self.assertIn("$DATA_DIR/cache/sentence-transformers", install_text)
        self.assertIn("future/__pycache__", install_text)
        self.assertIn("*.egg-info", install_text)
        self.assertIn("detect_cuda_home_best_effort", install_text)
        self.assertIn("patch_vllm_cuda_environment", install_text)
        self.assertIn("notable-portal.service", install_text)
        self.assertIn("install_analyst_portal_bringup_assets", install_text)
        self.assertIn("INSTALL_ANALYST_PORTAL", install_text)
        self.assertIn("setup_postgres_case_archive.sh", install_text)

        pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"onprem-rag-notable-analysis==0.1.0"', pyproject_text)

    def test_installer_smoke_does_not_source_config_env(self) -> None:
        """Installer smoke should parse config.env without executing shell."""
        install_text = (PROJECT_ROOT / "scripts" / "install.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("read_config_value_best_effort", install_text)
        self.assertIn("curl -fsS --max-time 5", install_text)
        self.assertIn("mktemp \"$incoming_dir/.", install_text)
        self.assertIn("frontend/analyst-portal/dist", install_text)
        self.assertIn("litellm[proxy]==", install_text)
        self.assertIn("vllm==0.21.0", install_text)
        self.assertIn("huggingface_hub==1.16.4", install_text)
        self.assertNotIn('source "$config_file"', install_text)

    def test_postgres_case_archive_helper_uses_config_and_portal_env(self) -> None:
        """Case archive helper should provision schema from analyzer and portal env."""
        script_text = (
            PROJECT_ROOT / "scripts" / "setup_postgres_case_archive.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("--config-env", script_text)
        self.assertIn("--portal-env", script_text)
        self.assertIn("notable_cases_schema.sql", script_text)
        self.assertIn("GRANT SELECT ON ALL TABLES", script_text)
        self.assertIn("notable_portal@127.0.0.1:5432/notable_rag", script_text)
        self.assertIn("GRANT INSERT, UPDATE, DELETE ON", script_text)
        self.assertIn(".chat_sessions TO", script_text)
        self.assertIn("GRANT INSERT, DELETE ON", script_text)
        self.assertIn(".chat_messages TO", script_text)

    def test_postgres_rag_helper_uses_config_env_and_ingest_module(self) -> None:
        """Postgres helper should keep RAG setup and ingest config-bound."""
        script_text = (PROJECT_ROOT / "scripts" / "setup_postgres_rag.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("--config-env", script_text)
        self.assertIn('"$ANALYZER_PYTHON" - "$CONFIG_ENV"', script_text)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", script_text)
        self.assertIn("onprem_rag_notable_analysis.future.corpus_ingest", script_text)
        self.assertIn("--spl-query-rag", script_text)
        self.assertIn("SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE_CONFIG", script_text)
        self.assertNotIn("--skip-postgres-schema-setup", script_text)
        self.assertIn('< "$file"', script_text)
        self.assertNotIn('source "$CONFIG_ENV"', script_text)
        self.assertNotIn('-f "$file"', script_text)

    def test_direct_python_dependencies_are_pinned(self) -> None:
        """On-prem installs should avoid drifting direct Python dependencies."""
        requirements_text = (PROJECT_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        )
        pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        expected_pins = [
            "requests==2.32.5",
            "onprem-llm-sdk==0.1.0",
            "psycopg[binary]==3.3.4",
            "pgvector==0.4.2",
            "faiss-cpu==1.13.2",
            "sentence-transformers==5.4.1",
            "transformers==5.9.0",
            "huggingface-hub==1.16.4",
            "numpy==2.4.4",
            "python-docx==1.2.0",
            "docx2txt==0.9",
        ]

        for pin in expected_pins:
            self.assertIn(pin, requirements_text)
            self.assertIn(pin, pyproject_text)

        unpinned_requirements = [
            line
            for line in requirements_text.splitlines()
            if line and not line.startswith("#") and "==" not in line
        ]
        self.assertEqual(unpinned_requirements, [])

    def test_python_projects_target_python_312_and_rag_has_metadata(self) -> None:
        """Python package metadata should match the supported runtime."""
        pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        rag_pyproject_text = (
            WORKSPACE_ROOT / "onprem_rag_notable_analysis" / "pyproject.toml"
        ).read_text(encoding="utf-8")

        self.assertIn('requires-python = ">=3.12"', pyproject_text)
        self.assertIn('requires-python = ">=3.12"', rag_pyproject_text)
        self.assertIn("psycopg[binary]==3.3.4", rag_pyproject_text)
        self.assertIn("sentence-transformers==5.4.1", rag_pyproject_text)
        self.assertIn("transformers==5.9.0", rag_pyproject_text)
        self.assertIn("huggingface-hub==1.16.4", rag_pyproject_text)
        self.assertIn("[project.optional-dependencies]", pyproject_text)
        self.assertIn("litellm[proxy]==1.83.14", pyproject_text)

    def test_service_chain_smoke_targets_default_litellm_path(self) -> None:
        """Service smoke should verify vLLM, LiteLLM, and analyzer file-drop."""
        script_text = (PROJECT_ROOT / "scripts" / "smoke_service_chain.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("http://127.0.0.1:8000/health", script_text)
        self.assertIn("http://127.0.0.1:4000/v1/models", script_text)
        self.assertIn("gemma-4-31B-it", script_text)
        self.assertIn("service-chain-smoke", script_text)
        self.assertIn('-H "@$auth_header_file"', script_text)
        self.assertIn("mv \"$tmp_payload\" \"$payload_file\"", script_text)
        self.assertIn("ALLOW_NON_LOOPBACK_HTTP", script_text)
        self.assertNotIn('-H "Authorization: Bearer $LLM_API_TOKEN"', script_text)

    def test_config_example_exposes_rag_runtime_contract(self) -> None:
        """Example config should stay aligned with code defaults and RAG knobs."""
        config_text = (PROJECT_ROOT / "config.env.example").read_text(encoding="utf-8")

        self.assertIn("CAPABILITY_PROFILES=core", config_text)
        self.assertIn("LLM_MAX_TOKENS=4096", config_text)
        self.assertIn("LLM_TIMEOUT=240", config_text)
        self.assertIn("INVESTIGATION_MAX_CONCURRENT_QUERIES=6", config_text)
        self.assertIn("SPLUNK_SEARCH_TIMEOUT_SECONDS=30", config_text)
        self.assertIn("MAX_WORKERS=1", config_text)
        self.assertIn("MAX_QUEUE_DEPTH=8", config_text)
        self.assertIn("MAX_INPUT_FILE_BYTES=4194304", config_text)
        self.assertIn("SIDE_EFFECT_IDEMPOTENCY_ENABLED=false", config_text)
        self.assertIn("SIDE_EFFECT_IDEMPOTENCY_DIR=/var/notables/idempotency", config_text)
        self.assertIn("SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS=30", config_text)
        self.assertIn("RAG_FAIL_CLOSED=false", config_text)
        self.assertIn("HF_HOME=/var/notables/cache/huggingface", config_text)
        self.assertIn("HTML_REPORT_ENABLED=false", config_text)
        self.assertIn("RAG_FUSED_RANK_LIMIT_120B=8", config_text)
        self.assertIn("RAG_RRF_K=60", config_text)
        self.assertIn("CASE_ARCHIVE_ENABLED=false", config_text)
        self.assertIn("CASE_POSTGRES_SCHEMA=notable_cases", config_text)
        self.assertIn("CASE_RETENTION_DAYS=30", config_text)
        self.assertIn("CASE_RETENTION_DELETE_BATCH_SIZE=500", config_text)
        self.assertIn("CASE_QA_ENABLED=false", config_text)
        self.assertIn("CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=200", config_text)
        self.assertIn("CASE_QA_CHAT_HISTORY_ENABLED=false", config_text)
        self.assertIn("CASE_QA_LEXICAL_TOP_K=30", config_text)
        self.assertIn("PORTAL_ENABLED=false", config_text)
        self.assertIn("PORTAL_BIND_HOST=127.0.0.1", config_text)
        self.assertIn("PORTAL_ALLOW_NON_LOOPBACK_BIND=false", config_text)
        self.assertIn("PORTAL_PROXY_SECRET=", config_text)
        self.assertIn(
            "PORTAL_PROXY_SECRET_HEADER=X-Notable-Portal-Proxy-Secret",
            config_text,
        )
        self.assertIn("SPL_QUERY_RAG_ENABLED=false", config_text)
        self.assertIn("SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE=spl_query_chunks", config_text)
        self.assertIn("SPL_QUERY_RAG_FAILURE_MODE=suppress", config_text)

        portal_config_text = (PROJECT_ROOT / "config.portal.env.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("CAPABILITY_PROFILES=core,analyst_portal", portal_config_text)
        self.assertIn("CASE_POSTGRES_DSN=postgresql://notable_portal@", portal_config_text)
        self.assertIn("PORTAL_PROXY_SECRET=<generate-a-random-shared-secret>", portal_config_text)
        self.assertIn("PORTAL_CHAT_MAX_CONCURRENCY=4", portal_config_text)
        self.assertNotIn("SPLUNK_API_TOKEN", portal_config_text)
        self.assertNotIn("SERVICENOW_API_TOKEN", portal_config_text)

    def test_portal_systemd_unit_runs_loopback_portal_module(self) -> None:
        """Portal service should run the read-only FastAPI app on loopback."""
        service_text = (
            PROJECT_ROOT / "deploy" / "systemd" / "notable-portal.service"
        ).read_text(encoding="utf-8")

        self.assertIn("After=network.target litellm.service", service_text)
        self.assertIn("Wants=litellm.service", service_text)
        self.assertIn("EnvironmentFile=/etc/notable-analyzer/portal.env", service_text)
        self.assertIn("HF_HOME=/var/notables/cache/huggingface", service_text)
        self.assertIn(
            "SENTENCE_TRANSFORMERS_HOME=/var/notables/cache/sentence-transformers",
            service_text,
        )
        self.assertIn(
            "ExecStart=/opt/notable-analyzer/venv/bin/python -m "
            "llm_notable_analysis_onprem_systemd.onprem_service.portal_app",
            service_text,
        )
        self.assertIn("ReadWritePaths=/var/notables/cache", service_text)
        self.assertIn("TimeoutStopSec=300", service_text)
        self.assertIn("SyslogIdentifier=notable-portal", service_text)
        self.assertIn("User=notable-analyzer", service_text)

    def test_portal_nginx_example_documents_auth_tls_and_loopback_proxy(self) -> None:
        """Nginx example should keep portal behind TLS/auth and loopback Uvicorn."""
        nginx_text = (
            PROJECT_ROOT / "deploy" / "nginx" / "notable-portal.conf"
        ).read_text(encoding="utf-8")

        self.assertIn("server_name notable-portal.internal.example.com", nginx_text)
        self.assertIn("ssl_certificate", nginx_text)
        self.assertIn("auth_basic", nginx_text)
        self.assertIn("client_max_body_size 1m", nginx_text)
        self.assertIn("root /opt/notable-analyzer/frontend/analyst-portal/dist", nginx_text)
        self.assertIn("try_files $uri $uri/ /index.html", nginx_text)
        self.assertIn("location /api/", nginx_text)
        self.assertIn("location = /health", nginx_text)
        self.assertIn("location = /ready", nginx_text)
        self.assertIn("proxy_pass http://127.0.0.1:8080", nginx_text)
        self.assertIn("proxy_set_header X-Forwarded-User $remote_user", nginx_text)
        self.assertIn("include /etc/nginx/notable-portal-proxy-secret.conf", nginx_text)
        self.assertIn("proxy_read_timeout 300s", nginx_text)
        self.assertIn("proxy_send_timeout 300s", nginx_text)

    def test_analyst_portal_operations_doc_covers_delivery_contract(self) -> None:
        """Portal operations doc should cover enablement, maintenance, and safety."""
        doc_text = (
            PROJECT_ROOT / "docs" / "operations" / "ANALYST_PORTAL_OPERATIONS.md"
        ).read_text(encoding="utf-8")

        self.assertIn("CAPABILITY_PROFILES=core,analyst_portal", doc_text)
        self.assertIn("notable-portal.service", doc_text)
        self.assertIn("deploy/nginx/notable-portal.conf", doc_text)
        self.assertIn("GET /health", doc_text)
        self.assertIn("GET /ready", doc_text)
        self.assertIn("scripts/rebuild_case_chunks.py", doc_text)
        self.assertIn("scripts/backfill_case_archive.py", doc_text)
        self.assertIn("answer_status=refused", doc_text)
        self.assertIn("all retained cases", doc_text)
        self.assertIn("PORTAL_ALLOW_NON_LOOPBACK_BIND=false", doc_text)
        self.assertIn("PORTAL_PROXY_SECRET_HEADER", doc_text)
        self.assertIn("analyst-lab-change-me", doc_text)
        self.assertIn("127.0.0.1:8080", doc_text)
        self.assertIn("TCP `443`", doc_text)
        self.assertIn("INSTALL_PORTAL_ALLOW_PARTIAL=true", doc_text)

    def test_docs_indexes_link_analyst_portal_operations(self) -> None:
        """Docs indexes should expose the shipped portal operations guide."""
        docs_index = (PROJECT_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        ops_index = (
            PROJECT_ROOT / "docs" / "operations" / "README.md"
        ).read_text(encoding="utf-8")

        self.assertIn("ANALYST_PORTAL_OPERATIONS.md", docs_index)
        self.assertIn("ANALYST_PORTAL_OPERATIONS.md", ops_index)

    def test_backfill_script_documents_dry_run_and_legacy_summary(self) -> None:
        """Backfill script should expose dry-run and legacy-summary behavior."""
        script_text = (
            PROJECT_ROOT / "scripts" / "backfill_case_archive.py"
        ).read_text(encoding="utf-8")

        self.assertIn("build_backfill_case_id", script_text)
        self.assertIn("backfill:<sha256-prefix>", script_text)
        self.assertIn("legacy_summary", script_text)
        self.assertIn("markdown_only", script_text)
        self.assertIn("--dry-run", script_text)
        self.assertIn("--batch-size", script_text)
        self.assertIn("--max-file-bytes", script_text)
        self.assertIn("CASE_ARCHIVE_ENABLED must be true", script_text)
        self.assertIn("--config-env is required", script_text)

    def test_pyproject_includes_portal_runtime_dependencies(self) -> None:
        """Portal diff should declare FastAPI and Uvicorn dependencies."""
        pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('"fastapi==0.115.12"', pyproject_text)
        self.assertIn('"uvicorn[standard]==0.34.0"', pyproject_text)

    def test_case_archive_schema_contains_expected_tables(self) -> None:
        """Postgres case archive schema should match the portal storage contract."""
        schema_text = (
            PROJECT_ROOT / "deploy" / "postgres" / "notable_cases_schema.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", schema_text)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", schema_text)
        self.assertIn("CREATE SCHEMA IF NOT EXISTS notable_cases", schema_text)
        self.assertIn("CREATE TABLE IF NOT EXISTS notable_cases.cases", schema_text)
        self.assertIn("CREATE TABLE IF NOT EXISTS notable_cases.case_chunks", schema_text)
        self.assertIn("CREATE TABLE IF NOT EXISTS notable_cases.chat_sessions", schema_text)
        self.assertIn("CREATE TABLE IF NOT EXISTS notable_cases.chat_messages", schema_text)
        self.assertIn("retrieval_status IN ('pending', 'ready', 'failed', 'not_indexed')", schema_text)
        self.assertIn("embedding vector(768)", schema_text)
        self.assertIn("ADD COLUMN IF NOT EXISTS search_vector", schema_text)
        self.assertIn("search_vector tsvector GENERATED ALWAYS AS", schema_text)
        self.assertIn("case_chunks_search_vector_gin_idx", schema_text)
        self.assertIn("case_chunks_embedding_hnsw_idx", schema_text)
        self.assertIn("cases_processed_at_case_id_idx", schema_text)
        self.assertIn("cases_search_name_trgm_idx", schema_text)
        self.assertIn("gin_trgm_ops", schema_text)

    def test_postgres_rag_smoke_uses_disposable_pgvector_container(self) -> None:
        """Live RAG smoke should validate pgvector without host psql."""
        script_text = (PROJECT_ROOT / "scripts" / "smoke_postgres_rag.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("pgvector/pgvector:pg16", script_text)
        self.assertIn(
            'psql -v ON_ERROR_STOP=1 -U postgres -d "$POSTGRES_DB" -c "SELECT 1"',
            script_text,
        )
        self.assertIn("build_postgres_index", script_text)
        self.assertIn("PostgresRAGContextProvider", script_text)
        self.assertIn("secrets.token_urlsafe", script_text)
        self.assertIn("assert \"SOC_OPERATIONAL_CONTEXT\" in context", script_text)
        self.assertIn("SPL_QUERY_GROUNDING_CONTEXT", script_text)
        self.assertIn("SMOKE_SPL_TABLE", script_text)
        self.assertNotIn(
            'POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"',
            script_text,
        )
        self.assertIn('rm -f "$CONTAINER_NAME"', script_text)
        self.assertIn("SMOKE_SCHEMA must be a simple PostgreSQL identifier", script_text)

    def test_kb_operations_doc_covers_document_lifecycle(self) -> None:
        """KB operations doc should explain content updates and rebuilds."""
        doc_text = (
            PROJECT_ROOT / "docs" / "operations" / "KNOWLEDGE_BASE_OPERATIONS.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Add Or Update Documents", doc_text)
        self.assertIn("Content Best Practices", doc_text)
        self.assertIn("setup_postgres_rag.sh", doc_text)
        self.assertIn("ingest_report.json", doc_text)
        self.assertIn("Rollback", doc_text)

    def test_capability_profiles_doc_is_operator_entrypoint(self) -> None:
        """Operators should be directed to profiles instead of raw enable flags."""
        docs_index = (PROJECT_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        ops_index = (
            PROJECT_ROOT / "docs" / "operations" / "README.md"
        ).read_text(encoding="utf-8")
        profile_doc = (
            PROJECT_ROOT / "docs" / "operations" / "CAPABILITY_PROFILES.md"
        ).read_text(encoding="utf-8")

        self.assertIn("CAPABILITY_PROFILES.md", docs_index)
        self.assertIn("CAPABILITY_PROFILES.md", ops_index)
        for profile in (
            "core",
            "html_reports",
            "rag",
            "spl_readonly",
            "ticket_draft",
            "action_gated",
            "analyst_portal",
        ):
            self.assertIn(f"`{profile}`", profile_doc)
        self.assertIn("Low-level `*_ENABLED` flags remain supported", profile_doc)

    def test_docs_do_not_reference_removed_kb_rebuild_units(self) -> None:
        """Docs should not point operators at removed KB systemd units."""
        docs_root = PROJECT_ROOT / "docs"
        offenders = []
        for path in docs_root.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if "kb-rebuild.service" in text or "kb-rebuild.timer" in text:
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

        self.assertEqual(offenders, [])

    def test_architecture_doc_uses_module_entrypoint(self) -> None:
        """Architecture doc should not show the obsolete script-style entrypoint."""
        doc_text = (
            PROJECT_ROOT
            / "docs"
            / "architecture"
            / "s3_notable_pipeline_onprem_airgapped_workflow.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "-m llm_notable_analysis_onprem_systemd.onprem_service.onprem_main",
            doc_text,
        )
        self.assertNotIn("python onprem_main.py", doc_text)
        self.assertNotIn("gpt-oss-20b", doc_text)
        self.assertIn("gemma-4-31B-it", doc_text)
        self.assertIn("After=network.target litellm.service", doc_text)

    def test_stale_container_plan_is_removed_from_active_docs(self) -> None:
        """The old Docker/llama.cpp plan should not remain in active systemd docs."""
        self.assertFalse(
            (
                PROJECT_ROOT
                / "docs"
                / "planning"
                / "CONTAINERIZED_DEPLOYMENT_PLAN.md"
            ).exists()
        )

    def test_analyzer_docker_image_matches_systemd_runtime(self) -> None:
        """Docker packaging should install the same packages and entrypoint as systemd."""
        dockerfile = (
            WORKSPACE_ROOT
            / "llm_notable_analysis_analyzer_image"
            / "Dockerfile.analyzer"
        ).read_text(encoding="utf-8")
        analyzer_readme = (
            WORKSPACE_ROOT / "llm_notable_analysis_analyzer_image" / "README.md"
        ).read_text(encoding="utf-8")

        self.assertIn("onprem-llm-sdk", dockerfile)
        self.assertIn("onprem_rag_notable_analysis", dockerfile)
        self.assertIn("llm_notable_analysis_onprem_systemd", dockerfile)
        self.assertIn(
            "llm_notable_analysis_onprem_systemd.onprem_service.onprem_main",
            dockerfile,
        )
        self.assertNotIn("onprem_service.onprem_main_nonsdk", dockerfile)
        self.assertNotIn(
            "llm_notable_analysis_analyzer_image/onprem_service", dockerfile
        )
        self.assertIn("AS builder", dockerfile)
        self.assertIn("COPY --from=builder", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("docker_healthcheck.py", dockerfile)
        compose_text = (
            WORKSPACE_ROOT
            / "llm_notable_analysis_analyzer_image"
            / "docker-compose.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("./data/notables:/var/notables", compose_text)
        self.assertIn("required: false", compose_text)
        self.assertIn("host.docker.internal:host-gateway", compose_text)
        self.assertIn("ANALYZER_UID", compose_text)
        self.assertIn("llm_notable_analysis_onprem_systemd/", analyzer_readme)
        self.assertIn("onprem_rag_notable_analysis/", analyzer_readme)
        self.assertNotIn("not production-equivalent", analyzer_readme)

    def test_readme_uses_current_sftp_chroot_contract(self) -> None:
        """README SFTP guidance should match installer-created paths."""
        readme_text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("chroot `/var/sftp/soar`", readme_text)
        self.assertIn("/var/notables/incoming -> /var/sftp/soar/incoming", readme_text)
        self.assertNotIn("ChrootDirectory /var/notables", readme_text)

    def test_dependency_manifest_captures_litellm_unit_and_venv(self) -> None:
        """Dependency evidence should include the LiteLLM proxy after refactor."""
        manifest_text = (
            PROJECT_ROOT / "scripts" / "tools" / "generate_dependency_manifest.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('freeze_venv "/opt/litellm/venv" "litellm_venv"', manifest_text)
        self.assertIn('litellm.service" "systemd/litellm.service"', manifest_text)


if __name__ == "__main__":
    unittest.main()
