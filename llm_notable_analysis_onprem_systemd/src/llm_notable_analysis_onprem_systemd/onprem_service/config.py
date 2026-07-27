"""Configuration loading for on-prem notable analysis service.

Loads configuration from environment variables (typically via config.env).
All paths default to RHEL-standard locations.
"""

import os
import re
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}
_POSTGRES_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

_CAPABILITY_PROFILE_FLAGS: dict[str, dict[str, Any]] = {
    "core": {},
    "html_reports": {"HTML_REPORT_ENABLED": True},
    "rag": {"RAG_ENABLED": True},
    "spl_readonly": {
        "SPL_QUERY_GENERATION_ENABLED": True,
        "INVESTIGATION_QUERY_EXECUTION_ENABLED": True,
    },
    "elastic_readonly": {
        "ELASTIC_QUERY_GENERATION_ENABLED": True,
        "INVESTIGATION_QUERY_EXECUTION_ENABLED": True,
    },
    "ticket_draft": {"SERVICENOW_DRAFT_ENABLED": True},
    "action_gated": {
        "SPLUNK_SINK_ENABLED": True,
        "SERVICENOW_DRAFT_ENABLED": True,
        "SERVICENOW_CREATE_ENABLED": True,
        "SERVICENOW_CREATE_REQUIRES_APPROVAL": True,
        "SIDE_EFFECT_IDEMPOTENCY_ENABLED": True,
    },
    "analyst_portal": {
        "CASE_ARCHIVE_ENABLED": True,
        "PORTAL_ENABLED": True,
        "CASE_QA_ENABLED": True,
    },
}


def _positive_int_env(name: str, default: int, *, max_value: int | None = None) -> int:
    """Read a positive integer env var with an optional upper bound."""
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    """Read a boolean env var with explicit true/false values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be a boolean")


def _bool_env_optional(name: str) -> bool | None:
    """Read an optional boolean env var, returning None when unset."""
    if os.getenv(name) is None:
        return None
    return _bool_env(name, False)


def _parse_capability_profiles(raw: str) -> tuple[str, ...]:
    """Parse and validate configured capability profile names."""
    names = [part.strip().lower() for part in raw.replace(";", ",").split(",")]
    profiles = [name for name in names if name]
    if not profiles:
        profiles = ["core"]
    if "core" not in profiles:
        profiles.insert(0, "core")

    unknown = sorted(set(profiles) - set(_CAPABILITY_PROFILE_FLAGS))
    if unknown:
        raise ValueError(
            "CAPABILITY_PROFILES contains unsupported profile(s): "
            + ", ".join(unknown)
        )
    if "spl_readonly" in profiles and "elastic_readonly" in profiles:
        raise ValueError(
            "CAPABILITY_PROFILES cannot include both spl_readonly and elastic_readonly"
        )

    deduped: list[str] = []
    for profile in profiles:
        if profile not in deduped:
            deduped.append(profile)
    return tuple(deduped)


def _profile_flag_defaults(profiles: tuple[str, ...]) -> dict[str, Any]:
    """Return boolean defaults implied by the selected capability profiles."""
    flags: dict[str, Any] = {}
    for profile in profiles:
        flags.update(_CAPABILITY_PROFILE_FLAGS[profile])
    if "elastic_readonly" in profiles:
        flags["INVESTIGATION_QUERY_BACKEND"] = "elasticsearch"
    elif "spl_readonly" in profiles:
        flags["INVESTIGATION_QUERY_BACKEND"] = "splunk"
    return flags


def _profile_bool(name: str, default: bool, profile_flags: dict[str, Any]) -> bool:
    """Resolve a boolean controlled first by profiles, then legacy env flags."""
    if name in profile_flags:
        return profile_flags[name]
    env_value = _bool_env_optional(name)
    if env_value is not None:
        return env_value
    return default


def _profile_str(name: str, default: str, profile_flags: dict[str, Any]) -> str:
    """Resolve a string controlled first by profiles, then env/default."""
    if name in profile_flags:
        return str(profile_flags[name])
    return os.getenv(name, default).strip() or default


def _csv_has_values(value: str) -> bool:
    """Return whether a CSV config value contains at least one item."""
    return any(part.strip() for part in str(value or "").split(","))


def _validate_postgres_identifier(value: str, name: str) -> None:
    """Validate a simple Postgres identifier used in generated SQL."""
    if not _POSTGRES_IDENTIFIER_RE.fullmatch((value or "").strip()):
        raise ValueError(f"{name} must be a simple PostgreSQL identifier")


_CLOSED_TICKET_RETENTION_ALLOWED = frozenset({30, 60, 90})
_BYTE_SIZE_RE = re.compile(r"^(\d+)([KMG]iB|[KMG]B)?$", re.IGNORECASE)


def _closed_ticket_retention_days(name: str, default: int) -> int:
    """Read closed-ticket retention days (whitelist 30/60/90)."""
    value = _positive_int_env(name, default, max_value=90)
    if value not in _CLOSED_TICKET_RETENTION_ALLOWED:
        raise ValueError(f"{name} must be one of 30, 60, or 90")
    return value


def _byte_size_env(name: str, default: int) -> int:
    """Read a positive byte-size env var (supports KiB/MiB/GiB suffixes)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    text = raw.strip()
    if not text:
        return default
    match = _BYTE_SIZE_RE.fullmatch(text)
    if not match:
        raise ValueError(f"{name} must be a byte size such as 10485760 or 10MiB")
    amount = int(match.group(1))
    suffix = (match.group(2) or "").upper()
    multiplier = 1
    if suffix in {"KIB", "KB"}:
        multiplier = 1024
    elif suffix in {"MIB", "MB"}:
        multiplier = 1024 * 1024
    elif suffix in {"GIB", "GB"}:
        multiplier = 1024 * 1024 * 1024
    value = amount * multiplier
    if value <= 0:
        raise ValueError(f"{name} must be a positive byte size")
    return value


def _validate_servicenow_table_name(value: str, name: str) -> None:
    """Validate a ServiceNow table API table name."""
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[a-z0-9_]+", normalized):
        raise ValueError(f"{name} must match [a-z0-9_]+")


def _llm_openai_api_base(llm_api_url: str) -> str:
    """Derive an OpenAI-compatible API base URL from LLM_API_URL."""
    text = str(llm_api_url or "").strip().rstrip("/")
    if text.endswith("/chat/completions"):
        return text[:-len("/chat/completions")]
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        path = (parsed.path or "").rstrip("/")
        if path.endswith("/chat/completions"):
            path = path[:-len("/chat/completions")]
        return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    return text


def _validate_openai_compatible_endpoint_url(value: str, name: str) -> None:
    """Validate HTTPS or loopback HTTP for local OpenAI-compatible endpoints."""
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme == "https":
        if not parsed.netloc or parsed.username or parsed.password:
            raise ValueError(f"{name} must be an HTTPS URL without userinfo")
        return
    if parsed.scheme == "http":
        host = (parsed.hostname or "").strip().lower()
        if host in {"127.0.0.1", "localhost"} or host.endswith(".localhost"):
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise ValueError(f"{name} must use HTTPS or loopback HTTP")
    raise ValueError(f"{name} must use http:// or https://")


def _apply_closed_ticket_vision_defaults(config: "Config") -> None:
    """Resolve closed-ticket vision defaults from the primary LLM gateway settings."""
    if not bool(config.CLOSED_TICKET_VISION_ENABLED):
        return
    if not str(config.CLOSED_TICKET_VISION_API_BASE or "").strip():
        config.CLOSED_TICKET_VISION_API_BASE = _llm_openai_api_base(config.LLM_API_URL)
    if not str(config.CLOSED_TICKET_VISION_MODEL or "").strip():
        config.CLOSED_TICKET_VISION_MODEL = str(config.LLM_MODEL_NAME or "").strip()
    if not str(config.CLOSED_TICKET_VISION_API_KEY or "").strip():
        config.CLOSED_TICKET_VISION_API_KEY = str(config.LLM_API_TOKEN or "").strip()
    _validate_openai_compatible_endpoint_url(
        config.CLOSED_TICKET_VISION_API_BASE,
        "CLOSED_TICKET_VISION_API_BASE",
    )
    if not str(config.CLOSED_TICKET_VISION_MODEL or "").strip():
        raise ValueError(
            "CLOSED_TICKET_VISION_MODEL or LLM_MODEL_NAME is required when "
            "CLOSED_TICKET_VISION_ENABLED=true"
        )


def _validate_elasticsearch_runtime_contract(config: "Config") -> None:
    """Fail fast on unsafe or incomplete Elasticsearch read-only configuration."""
    if config.INVESTIGATION_QUERY_BACKEND != "elasticsearch":
        return

    elastic_generation_enabled = bool(config.ELASTIC_QUERY_GENERATION_ENABLED)
    elastic_execution_enabled = bool(config.INVESTIGATION_QUERY_EXECUTION_ENABLED)
    if not elastic_generation_enabled and not elastic_execution_enabled:
        return

    if not _csv_has_values(config.ELASTICSEARCH_INDEX_ALLOWLIST):
        raise ValueError(
            "ELASTICSEARCH_INDEX_ALLOWLIST is required when Elasticsearch query generation or execution is enabled"
        )
    has_allowed_fields = _csv_has_values(config.ELASTICSEARCH_ALLOWED_FIELDS)
    if not has_allowed_fields:
        if elastic_execution_enabled:
            raise ValueError(
                "ELASTICSEARCH_ALLOWED_FIELDS is required when Elasticsearch query execution is enabled"
            )
        if not bool(config.ELASTICSEARCH_GROUNDING_ENABLED):
            raise ValueError(
                "ELASTICSEARCH_ALLOWED_FIELDS is required unless ELASTICSEARCH_GROUNDING_ENABLED=true"
            )

    if not elastic_execution_enabled:
        return

    base_url = str(config.ELASTICSEARCH_BASE_URL or "").strip()
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("ELASTICSEARCH_BASE_URL must be an HTTPS URL without userinfo")
    if not str(config.ELASTICSEARCH_API_KEY or "").strip():
        raise ValueError(
            "ELASTICSEARCH_API_KEY is required when Elasticsearch query execution is enabled"
        )


@dataclass
class Config:
    """Service configuration container.

    Attributes:
        INGEST_MODE: Input ingestion mode (`file_drop` by default).
        CAPABILITY_PROFILES: Comma-separated named capability profiles.
        INCOMING_DIR: Directory watched for incoming notables.
        PROCESSED_DIR: Directory for successfully processed notables.
        QUARANTINE_DIR: Directory for failed/invalid notables.
        REPORT_DIR: Directory for generated markdown and HTML reports.
        ARCHIVE_DIR: Directory used by retention staging.
        POLL_INTERVAL: Polling interval in seconds.
        LLM_API_URL: Local LiteLLM/OpenAI-compatible endpoint URL.
        LLM_API_TOKEN: Optional bearer token for LLM API authentication.
        LLM_MODEL_NAME: Model identifier used for analysis.
        LLM_STRUCTURED_OUTPUT_MODE: Structured output strategy (`prompt_json` or `tool_call`).
        LLM_MAX_TOKENS: Per-request generation token cap.
        LLM_TIMEOUT: Request timeout in seconds.
        HTML_REPORT_ENABLED: Enables generated static HTML dashboard reports.
        RAG_ENABLED: Enables retrieval-augmented prompt grounding.
        RAG_BACKEND: Retrieval backend (`sqlite_faiss` or `postgres`).
        RAG_FAIL_CLOSED: Raises analysis errors when configured RAG is unavailable.
        RAG_SQLITE_PATH: SQLite path for lexical retrieval index.
        RAG_FAISS_PATH: FAISS path for vector retrieval index.
        RAG_EMBEDDING_MODEL: Embedding model name/path.
        RAG_RERANK_ENABLED: Enables second-stage reranking for retrieval hits.
        RAG_RERANK_MODEL: Reranker model name/path.
        RAG_POSTGRES_DSN: PostgreSQL DSN for Postgres-backed RAG.
        RAG_POSTGRES_SCHEMA: PostgreSQL schema for retrieval tables.
        RAG_POSTGRES_CHUNKS_TABLE: PostgreSQL chunks table name.
        RAG_POSTGRES_FTS_CONFIG: PostgreSQL text search configuration.
        RAG_POSTGRES_STATEMENT_TIMEOUT_MS: Per-query timeout for Postgres RAG.
        RAG_VECTOR_DIMENSIONS: Embedding vector dimensions for pgvector.
        RAG_MAX_SNIPPETS_120B: Max RAG snippets for 120b profile.
        RAG_MAX_SNIPPETS_20B: Max RAG snippets for 20b profile.
        RAG_CONTEXT_BUDGET_CHARS_120B: Context char budget for 120b profile.
        RAG_CONTEXT_BUDGET_CHARS_20B: Context char budget for 20b profile.
        RAG_FUSED_RANK_LIMIT_120B: Max fused retrieval rank accepted for 120b profile.
        RAG_FUSED_RANK_LIMIT_20B: Max fused retrieval rank accepted for 20b profile.
        RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD: Similarity threshold for dedupe.
        RAG_LEXICAL_TOP_K: PostgreSQL/SQLite FTS candidate pull size.
        RAG_VECTOR_TOP_K: pgvector/FAISS candidate pull size.
        RAG_CANDIDATE_POOL_LIMIT: Candidate cap before quality gates.
        RAG_RRF_K: Reciprocal-rank-fusion smoothing constant.
        CASE_ARCHIVE_ENABLED: Enables Postgres case archive writes.
        CASE_POSTGRES_DSN: PostgreSQL DSN for case archive storage.
        CASE_POSTGRES_SCHEMA: PostgreSQL schema for case archive tables.
        CASE_RETENTION_DAYS: Retention window for archived cases.
        CASE_RETENTION_DELETE_BATCH_SIZE: Max expired case rows deleted per retention batch.
        CASE_ARCHIVE_WRITE_MAX_ATTEMPTS: Max attempts for transient archive write failures.
        CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS: Backoff between archive write attempts.
        CASE_POSTGRES_STATEMENT_TIMEOUT_MS: Per-write timeout for case archive operations.
        CASE_SCHEMA_VERSION: Case record schema version.
        CASE_ANALYSIS_SCHEMA_VERSION: Structured analysis schema version.
        CASE_QA_ENABLED: Enables portal case Q&A.
        CASE_QA_MAX_CHUNKS_PER_LANE: Max chunks per chat source lane.
        CASE_QA_MAX_TOTAL_CHUNKS: Max total chunks supplied to chat.
        CASE_QA_MAX_INDEX_CHUNKS_PER_CASE: Max chunks built and embedded per archived case.
        CASE_QA_CONTEXT_BUDGET_CHARS: Max retrieval context characters for chat.
        CASE_QA_MAX_QUESTION_CHARS: Max analyst question length.
        CASE_QA_MAX_ANSWER_TOKENS: Max chat answer generation tokens.
        CASE_QA_MODEL_CONTEXT_TOKENS: Estimated model context window for portal usage UI.
        CASE_QA_CHUNK_SCHEMA_VERSION: Case chunk schema version.
        CASE_QA_EMBEDDING_MODEL: Embedding model used for case chunks.
        CASE_QA_VECTOR_DIMENSIONS: pgvector dimensions for case chunks.
        CASE_QA_CHAT_HISTORY_ENABLED: Enables bounded persisted portal chat history.
        CASE_QA_GENERAL_KNOWLEDGE_ENABLED: Enables broad technology fallback when archive context is insufficient.
        CASE_QA_CHAT_HISTORY_RETENTION_DAYS: Retention window for chat sessions.
        CASE_QA_MAX_MESSAGES_PER_SESSION: Max persisted chat messages per session.
        CASE_QA_MAX_SESSIONS_PER_USER: Max active chat sessions per authenticated user.
        CASE_QA_MAX_STORED_MESSAGE_BYTES: Max stored chat message size.
        CASE_QA_LEXICAL_TOP_K: Case chat lexical retrieval candidate count.
        CASE_QA_VECTOR_TOP_K: Case chat vector retrieval candidate count.
        CASE_QA_RRF_K: Case chat reciprocal-rank-fusion smoothing constant.
        PORTAL_ENABLED: Enables the FastAPI analyst portal.
        PORTAL_BIND_HOST: Portal bind host.
        PORTAL_PORT: Portal bind port.
        PORTAL_PAGE_SIZE: Default portal page size.
        PORTAL_CHAT_MAX_CONCURRENCY: Max concurrent portal chat requests.
        PORTAL_TRUSTED_USER_HEADER: Trusted reverse-proxy user header.
        PORTAL_ALLOW_NON_LOOPBACK_BIND: Allows explicitly reviewed non-loopback portal binds.
        PORTAL_PROXY_SECRET: Optional shared secret required for non-loopback proxy mode.
        PORTAL_PROXY_SECRET_HEADER: Header carrying the proxy shared secret.
        SPLUNK_BASE_URL: Splunk base URL for notable update sink.
        SPLUNK_API_TOKEN: Splunk token for REST sink authentication.
        SPLUNK_NOTABLE_UPDATE_PATH: Splunk notable update endpoint path.
        SPLUNK_SINK_ENABLED: Enables Splunk writeback sink.
        SPL_QUERY_GENERATION_ENABLED: Enables per-hypothesis SPL query generation.
        SPL_QUERY_RAG_ENABLED: Enables SPL-dedicated grounding for SPL generation.
        SPL_QUERY_RAG_SOURCE_DIR: Source docs for SPL-dedicated KB ingest.
        SPL_QUERY_RAG_INDEX_DIR: Ingest artifacts for SPL-dedicated KB.
        SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE: Postgres table for SPL KB chunks.
        SPL_QUERY_RAG_MAX_SNIPPETS: Max SPL grounding snippets in SPL prompt.
        SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS: Character budget for SPL grounding.
        SPL_QUERY_RAG_FAILURE_MODE: `suppress` or `fallback_to_ungrounded`.
        SPLUNK_CA_BUNDLE: Optional CA bundle for TLS verification.
        INVESTIGATION_QUERY_EXECUTION_ENABLED: Enables read-only query execution.
        INVESTIGATION_QUERY_EXECUTOR: Query executor mode (`rest` or `mcp`).
        INVESTIGATION_MAX_QUERIES_PER_ALERT: Max queries attempted per alert.
        INVESTIGATION_MAX_CONCURRENT_QUERIES: Max concurrent query execution.
        QUERY_RESULT_INTERPRETATION_ENABLED: Enables optional LLM interpretation of query results.
        QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS: Prompt budget for query-result interpretation.
        QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS: Max sample rows supplied to interpretation prompt.
        QUERY_RESULT_INTERPRETATION_MAX_TOKENS: Token cap for query-result interpretation output.
        SPLUNK_SEARCH_ENDPOINT_PATH: Splunk REST search endpoint path.
        SPLUNK_SEARCH_ALLOWED_INDEXES: CSV allowlist of query index names.
        SPLUNK_SEARCH_ALLOWED_COMMANDS: CSV allowlist of SPL commands.
        SPLUNK_SEARCH_DENIED_COMMANDS: CSV denylist of SPL commands.
        SPLUNK_SEARCH_MAX_TIME_RANGE: Max allowed query lookback duration.
        SPLUNK_SEARCH_MAX_ROWS: Max rows per query.
        SPLUNK_SEARCH_TIMEOUT_SECONDS: Max query timeout in seconds.
        SPLUNK_MCP_TOOL_NAME: MCP tool identifier for Splunk search.
        SERVICENOW_DRAFT_ENABLED: Enables ServiceNow draft payload generation.
        SERVICENOW_CREATE_ENABLED: Enables ServiceNow incident create operation.
        SERVICENOW_CREATE_REQUIRES_APPROVAL: Requires payload-level approval to create.
        SERVICENOW_BASE_URL: ServiceNow instance base URL.
        SERVICENOW_CREATE_PATH: Incident create endpoint path.
        SERVICENOW_API_TOKEN: Bearer token for ServiceNow API.
        SERVICENOW_ASSIGNMENT_GROUP: Assignment group used for incident drafts.
        SERVICENOW_TIMEOUT_SECONDS: Create request timeout in seconds.
        SERVICENOW_DISPOSITION_SYNC_ENABLED: Enables read-only closed disposition sync.
        SERVICENOW_DISPOSITION_SYNC_TOKEN: Bearer token for disposition Table API reads.
        SERVICENOW_DISPOSITION_FIELD_MAP: Path to ServiceNow disposition field map JSON.
        SERVICENOW_DISPOSITION_CODE_MAP: Path to ServiceNow disposition code map JSON.
        SERVICENOW_DISPOSITION_BACKFILL_DAYS: First-run closed_at lookback window.
        DISPOSITION_RETENTION_DAYS: Retention window for synced disposition rows.
        CLOSED_TICKET_RAG_ENABLED: Enables closed-ticket RAG retrieval lane.
        CLOSED_TICKET_RETENTION_DAYS: Retention window for raw closed tickets (30/60/90).
        SERVICENOW_CLOSED_TICKET_SYNC_ENABLED: Enables ServiceNow closed ticket raw sync.
        SERVICENOW_CLOSED_TICKET_TOKEN: Bearer token for closed ticket Table API reads.
        SERVICENOW_CLOSED_TICKET_TABLE: ServiceNow table for closed ticket pull.
        SERVICENOW_CLOSED_TICKET_QUERY: Encoded query for closed security tickets.
        SERVICENOW_CLOSED_TICKET_BACKFILL_DAYS: First-run sys_updated_on lookback window.
        SERVICENOW_CLOSED_TICKET_CURSOR_OVERLAP_HOURS: Cursor overlap for incremental sync.
        SERVICENOW_CLOSED_TICKET_RECONCILE_INTERVAL_DAYS: Reconciliation interval.
        SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS: Fetch sys_journal_field rows per ticket.
        SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS: Fetch attachment metadata/content.
        CLOSED_TICKET_ATTACHMENT_DIR: Local directory for downloaded attachments.
        CLOSED_TICKET_ATTACHMENT_MAX_BYTES: Max attachment download size in bytes.
        CLOSED_TICKET_POSTGRES_SCHEMA: Postgres schema for closed ticket raw store.
        CLOSED_TICKET_POSTGRES_CHUNKS_TABLE: Chunks table name within closed ticket schema.
        CLOSED_TICKET_RAG_MAX_SNIPPETS: Max snippets for closed-ticket RAG lane.
        CLOSED_TICKET_RAG_CONTEXT_BUDGET_CHARS: Context budget for closed-ticket RAG lane.
        CASE_QA_CLOSED_TICKET_ENABLED: Enables closed-ticket lane in case QA.
        CASE_QA_CLOSED_TICKET_MAX_TICKETS: Max closed tickets in case QA lane.
        CLOSED_TICKET_VISION_ENABLED: Enables optional vision extraction for images.
        CLOSED_TICKET_VISION_API_BASE: OpenAI-compatible vision API base URL.
        CLOSED_TICKET_VISION_MODEL: Vision-capable model name.
        CLOSED_TICKET_VISION_API_KEY: Optional bearer token for vision API calls.
        CLOSED_TICKET_VISION_TIMEOUT_SECONDS: Vision request timeout in seconds.
        CLOSED_TICKET_VISION_MAX_TOKENS: Max tokens for vision descriptions.
        CLOSED_TICKET_ATTACHMENT_MAX_TEXT_CHARS: Max decoded attachment text chars.
        SIDE_EFFECT_IDEMPOTENCY_ENABLED: Enables file-backed side-effect dedupe.
        SIDE_EFFECT_IDEMPOTENCY_DIR: Directory for side-effect idempotency markers.
        SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS: Retention window for idempotency markers.
        MITRE_IDS_PATH: Path to ATT&CK technique ID allowlist JSON.
        INPUT_RETENTION_DAYS: Retention window for processed/quarantine inputs.
        REPORT_RETENTION_DAYS: Retention window for generated reports.
        ARCHIVE_RETENTION_DAYS: Retention window for archived files.
        RETENTION_RUN_INTERVAL_SECONDS: Retention job interval.
        CONCURRENCY_ENABLED: Enables threaded processing mode.
        MAX_WORKERS: Thread-pool worker count when concurrency is enabled.
        MAX_QUEUE_DEPTH: Queue depth limit for backpressure.
        MAX_INPUT_FILE_BYTES: Maximum incoming notable file size (bytes) before read.
    """

    # Ingest mode: file_drop (SOAR pushes via SFTP to INCOMING_DIR)
    INGEST_MODE: str = "file_drop"
    CAPABILITY_PROFILES: str = "core"

    # Directories (for file_drop mode)
    INCOMING_DIR: Path = field(default_factory=lambda: Path("/var/notables/incoming"))
    PROCESSED_DIR: Path = field(default_factory=lambda: Path("/var/notables/processed"))
    QUARANTINE_DIR: Path = field(
        default_factory=lambda: Path("/var/notables/quarantine")
    )
    REPORT_DIR: Path = field(default_factory=lambda: Path("/var/notables/reports"))
    ARCHIVE_DIR: Path = field(default_factory=lambda: Path("/var/notables/archive"))

    # Polling interval (seconds) for file_drop mode
    POLL_INTERVAL: int = 5

    # Reject incoming notables larger than this (bytes) before read_text (DoS guard)
    MAX_INPUT_FILE_BYTES: int = 4 * 1024 * 1024

    # Local LLM gateway (LiteLLM -> vLLM by default)
    LLM_API_URL: str = "http://127.0.0.1:4000/v1/chat/completions"
    LLM_API_TOKEN: str = ""
    LLM_MODEL_NAME: str = "gemma-4-31B-it"
    LLM_STRUCTURED_OUTPUT_MODE: str = "prompt_json"
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT: int = 240  # seconds
    HTML_REPORT_ENABLED: bool = False

    # Optional retrieval grounding (RAG)
    RAG_ENABLED: bool = False
    RAG_BACKEND: str = "postgres"
    RAG_FAIL_CLOSED: bool = False
    RAG_SQLITE_PATH: Path = field(
        default_factory=lambda: Path(
            "/opt/llm-notable-analysis/knowledge_base/index/kb.sqlite3"
        )
    )
    RAG_FAISS_PATH: Path = field(
        default_factory=lambda: Path(
            "/opt/llm-notable-analysis/knowledge_base/index/kb.faiss"
        )
    )
    RAG_EMBEDDING_MODEL: str = "mixedbread-ai/mxbai-embed-large-v1"
    RAG_RERANK_ENABLED: bool = False
    RAG_RERANK_MODEL: str = "mixedbread-ai/mxbai-rerank-large-v2"
    RAG_POSTGRES_DSN: str = "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag"
    RAG_POSTGRES_SCHEMA: str = "notable_rag"
    RAG_POSTGRES_CHUNKS_TABLE: str = "kb_chunks"
    RAG_POSTGRES_FTS_CONFIG: str = "english"
    RAG_POSTGRES_STATEMENT_TIMEOUT_MS: int = 5000
    RAG_VECTOR_DIMENSIONS: int = 1024
    RAG_MAX_SNIPPETS_120B: int = 5
    RAG_MAX_SNIPPETS_20B: int = 4
    RAG_CONTEXT_BUDGET_CHARS_120B: int = 2200
    RAG_CONTEXT_BUDGET_CHARS_20B: int = 1600
    RAG_FUSED_RANK_LIMIT_120B: int = 8
    RAG_FUSED_RANK_LIMIT_20B: int = 6
    RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD: float = 0.80
    RAG_LEXICAL_TOP_K: int = 30
    RAG_VECTOR_TOP_K: int = 30
    RAG_CANDIDATE_POOL_LIMIT: int = 40
    RAG_RRF_K: int = 60

    # Analyst portal and case archive (planned portal path, disabled by default)
    CASE_ARCHIVE_ENABLED: bool = False
    CASE_POSTGRES_DSN: str = "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag"
    CASE_POSTGRES_SCHEMA: str = "notable_cases"
    CASE_RETENTION_DAYS: int = 30
    CASE_RETENTION_DELETE_BATCH_SIZE: int = 500
    CASE_ARCHIVE_WRITE_MAX_ATTEMPTS: int = 3
    CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS: int = 1
    CASE_POSTGRES_STATEMENT_TIMEOUT_MS: int = 5000
    CASE_SCHEMA_VERSION: int = 1
    CASE_ANALYSIS_SCHEMA_VERSION: int = 1
    CASE_QA_ENABLED: bool = False
    CASE_QA_MAX_CHUNKS_PER_LANE: int = 6
    CASE_QA_MAX_TOTAL_CHUNKS: int = 18
    CASE_QA_MAX_INDEX_CHUNKS_PER_CASE: int = 200
    CASE_QA_CONTEXT_BUDGET_CHARS: int = 12000
    CASE_QA_MAX_QUESTION_CHARS: int = 2000
    CASE_QA_MAX_ANSWER_TOKENS: int = 800
    CASE_QA_MODEL_CONTEXT_TOKENS: int = 128_000
    CASE_QA_CHUNK_SCHEMA_VERSION: int = 1
    CASE_QA_EMBEDDING_MODEL: str = "mixedbread-ai/mxbai-embed-large-v1"
    CASE_QA_VECTOR_DIMENSIONS: int = 1024
    CASE_QA_CHAT_HISTORY_ENABLED: bool = False
    CASE_QA_GENERAL_KNOWLEDGE_ENABLED: bool = True
    CASE_QA_CHAT_HISTORY_RETENTION_DAYS: int = 7
    CASE_QA_MAX_MESSAGES_PER_SESSION: int = 30
    CASE_QA_MAX_SESSIONS_PER_USER: int = 10
    CASE_QA_MAX_STORED_MESSAGE_BYTES: int = 4000
    CASE_QA_MAX_CONVERSATION_TURNS: int = 10
    CASE_QA_MAX_CONVERSATION_CHARS: int = 6000
    CASE_QA_LEXICAL_TOP_K: int = 30
    CASE_QA_VECTOR_TOP_K: int = 30
    CASE_QA_RRF_K: int = 60
    PORTAL_ENABLED: bool = False
    PORTAL_BIND_HOST: str = "127.0.0.1"
    PORTAL_PORT: int = 8080
    PORTAL_PAGE_SIZE: int = 50
    PORTAL_CHAT_MAX_CONCURRENCY: int = 18
    PORTAL_TRUSTED_USER_HEADER: str = "X-Forwarded-User"
    PORTAL_ALLOW_NON_LOOPBACK_BIND: bool = False
    PORTAL_PROXY_SECRET: str = ""
    PORTAL_PROXY_SECRET_HEADER: str = "X-Notable-Portal-Proxy-Secret"

    # Splunk integration (optional)
    SPLUNK_BASE_URL: str = ""
    SPLUNK_API_TOKEN: str = ""
    SPLUNK_NOTABLE_UPDATE_PATH: str = "/services/notable_update"
    SPLUNK_SINK_ENABLED: bool = False
    SPL_QUERY_GENERATION_ENABLED: bool = False
    SPL_QUERY_RAG_ENABLED: bool = False
    SPL_QUERY_RAG_SOURCE_DIR: Path = field(
        default_factory=lambda: Path(
            "/opt/llm-notable-analysis/knowledge_base/spl_query_source_docs"
        )
    )
    SPL_QUERY_RAG_INDEX_DIR: Path = field(
        default_factory=lambda: Path(
            "/opt/llm-notable-analysis/knowledge_base/spl_query_index"
        )
    )
    SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE: str = "spl_query_chunks"
    SPL_QUERY_RAG_MAX_SNIPPETS: int = 4
    SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS: int = 1600
    SPL_QUERY_RAG_FAILURE_MODE: str = "suppress"
    SPLUNK_CA_BUNDLE: str = (
        ""  # Path to PEM CA bundle for Splunk TLS; empty = system trust store
    )
    INVESTIGATION_QUERY_EXECUTION_ENABLED: bool = False
    INVESTIGATION_QUERY_BACKEND: str = "splunk"
    INVESTIGATION_QUERY_EXECUTOR: str = "rest"
    INVESTIGATION_MAX_QUERIES_PER_ALERT: int = 6
    INVESTIGATION_MAX_CONCURRENT_QUERIES: int = 6
    QUERY_RESULT_INTERPRETATION_ENABLED: bool = False
    QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS: int = 4000
    QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS: int = 3
    QUERY_RESULT_INTERPRETATION_MAX_TOKENS: int = 768
    SPLUNK_SEARCH_ENDPOINT_PATH: str = "/services/search/jobs/oneshot"
    SPLUNK_SEARCH_ALLOWED_INDEXES: str = "main,notable,risk"
    SPLUNK_SEARCH_ALLOWED_COMMANDS: str = "search,stats,table,fields,where,head"
    SPLUNK_SEARCH_DENIED_COMMANDS: str = (
        "delete,collect,outputlookup,sendemail,map,rest,script,dbxquery"
    )
    SPLUNK_SEARCH_MAX_TIME_RANGE: str = "24h"
    SPLUNK_SEARCH_MAX_ROWS: int = 100
    SPLUNK_SEARCH_TIMEOUT_SECONDS: int = 30
    SPLUNK_MCP_TOOL_NAME: str = "splunk_search"
    ELASTIC_QUERY_GENERATION_ENABLED: bool = False
    ELASTICSEARCH_BASE_URL: str = ""
    ELASTICSEARCH_API_KEY: str = ""
    ELASTICSEARCH_INDEX_ALLOWLIST: str = ""
    ELASTICSEARCH_ALLOW_WILDCARD_INDEXES: bool = False
    ELASTICSEARCH_TIMESTAMP_FIELD: str = "@timestamp"
    ELASTICSEARCH_ALLOWED_FIELDS: str = ""
    ELASTICSEARCH_GROUNDING_ENABLED: bool = False
    ELASTICSEARCH_GROUNDING_SOURCE_DIR: Path = field(
        default_factory=lambda: Path(
            "/opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs"
        )
    )
    ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE: str = "elasticsearch_query_chunks"
    ELASTICSEARCH_GROUNDING_MAX_SNIPPETS: int = 4
    ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS: int = 1600
    ELASTICSEARCH_GROUNDING_FAILURE_MODE: str = "suppress"
    ELASTICSEARCH_MAX_TIME_RANGE: str = "24h"
    ELASTICSEARCH_MAX_ROWS: int = 100
    ELASTICSEARCH_TIMEOUT_SECONDS: int = 30
    ELASTICSEARCH_CA_BUNDLE: str = ""
    SERVICENOW_DRAFT_ENABLED: bool = False
    SERVICENOW_CREATE_ENABLED: bool = False
    SERVICENOW_CREATE_REQUIRES_APPROVAL: bool = True
    SERVICENOW_BASE_URL: str = "https://your-instance.service-now.com"
    SERVICENOW_CREATE_PATH: str = "/api/now/table/incident"
    SERVICENOW_API_TOKEN: str = ""
    SERVICENOW_ASSIGNMENT_GROUP: str = ""
    SERVICENOW_TIMEOUT_SECONDS: int = 15
    SERVICENOW_DISPOSITION_SYNC_ENABLED: bool = False
    SERVICENOW_DISPOSITION_SYNC_TOKEN: str = ""
    SERVICENOW_DISPOSITION_FIELD_MAP: Path = field(
        default_factory=lambda: Path(
            "/etc/notable-analyzer/servicenow/disposition_field_map.json"
        )
    )
    SERVICENOW_DISPOSITION_CODE_MAP: Path = field(
        default_factory=lambda: Path(
            "/etc/notable-analyzer/servicenow/disposition_code_map.json"
        )
    )
    SERVICENOW_DISPOSITION_BACKFILL_DAYS: int = 90
    DISPOSITION_RETENTION_DAYS: int = 365

    CLOSED_TICKET_RAG_ENABLED: bool = False
    CLOSED_TICKET_RETENTION_DAYS: int = 30
    SERVICENOW_CLOSED_TICKET_SYNC_ENABLED: bool = False
    SERVICENOW_CLOSED_TICKET_TOKEN: str = ""
    SERVICENOW_CLOSED_TICKET_TABLE: str = "sn_si_incident"
    SERVICENOW_CLOSED_TICKET_QUERY: str = ""
    SERVICENOW_CLOSED_TICKET_BACKFILL_DAYS: int = 30
    SERVICENOW_CLOSED_TICKET_CURSOR_OVERLAP_HOURS: int = 24
    SERVICENOW_CLOSED_TICKET_RECONCILE_INTERVAL_DAYS: int = 7
    SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS: bool = True
    SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS: bool = True
    CLOSED_TICKET_ATTACHMENT_DIR: Path = field(
        default_factory=lambda: Path("/var/notables/closed_ticket_attachments")
    )
    CLOSED_TICKET_ATTACHMENT_MAX_BYTES: int = 10 * 1024 * 1024
    CLOSED_TICKET_POSTGRES_SCHEMA: str = "notable_closed_tickets"
    CLOSED_TICKET_POSTGRES_CHUNKS_TABLE: str = "ticket_chunks"
    CLOSED_TICKET_RAG_MAX_SNIPPETS: int = 6
    CLOSED_TICKET_RAG_CONTEXT_BUDGET_CHARS: int = 6000
    CASE_QA_CLOSED_TICKET_ENABLED: bool = False
    CASE_QA_CLOSED_TICKET_MAX_TICKETS: int = 5
    CLOSED_TICKET_VISION_ENABLED: bool = False
    CLOSED_TICKET_VISION_API_BASE: str = ""
    CLOSED_TICKET_VISION_MODEL: str = ""
    CLOSED_TICKET_VISION_API_KEY: str = ""
    CLOSED_TICKET_VISION_TIMEOUT_SECONDS: float = 30.0
    CLOSED_TICKET_VISION_MAX_TOKENS: int = 400
    CLOSED_TICKET_ATTACHMENT_MAX_TEXT_CHARS: int = 12000

    # Side-effect idempotency (external writes/actions only)
    SIDE_EFFECT_IDEMPOTENCY_ENABLED: bool = False
    SIDE_EFFECT_IDEMPOTENCY_DIR: Path = field(
        default_factory=lambda: Path("/var/notables/idempotency")
    )
    SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS: int = 30

    # MITRE ATT&CK data
    MITRE_IDS_PATH: Path = field(
        default_factory=lambda: (
            Path(__file__).parent / "enterprise_attack_v17.1_ids.json"
        )
    )

    # Retention (days)
    # Stage 1: Move old processed/quarantine/report files into ARCHIVE_DIR
    INPUT_RETENTION_DAYS: int = 2
    REPORT_RETENTION_DAYS: int = 7
    # Stage 2: Delete files from ARCHIVE_DIR after this many days in archive
    ARCHIVE_RETENTION_DAYS: int = 14
    # How often to run retention housekeeping (seconds)
    RETENTION_RUN_INTERVAL_SECONDS: int = 86400

    # Concurrency (optional)
    # Gemma 4 31B-it on RTX PRO 6000 (96 GB) baseline:
    # - Start sequential: CONCURRENCY_ENABLED=false, MAX_WORKERS=1, MAX_QUEUE_DEPTH=8
    # - After load tests: try MAX_WORKERS=2 and MAX_QUEUE_DEPTH=16 with vLLM headroom
    CONCURRENCY_ENABLED: bool = False  # Sequential by default
    MAX_WORKERS: int = 1  # Thread pool size when enabled
    MAX_QUEUE_DEPTH: int = 8  # Backpressure limit

    def __post_init__(self) -> None:
        profiles = _parse_capability_profiles(self.CAPABILITY_PROFILES)
        self.CAPABILITY_PROFILES = ",".join(profiles)
        for name, value in _profile_flag_defaults(profiles).items():
            setattr(self, name, value)
        self.INVESTIGATION_QUERY_BACKEND = (
            str(self.INVESTIGATION_QUERY_BACKEND or "splunk").strip().lower()
        )
        if self.INVESTIGATION_QUERY_BACKEND not in {"splunk", "elasticsearch"}:
            raise ValueError(
                "INVESTIGATION_QUERY_BACKEND must be splunk or elasticsearch"
            )
        if (
            self.ELASTIC_QUERY_GENERATION_ENABLED
            and self.SPL_QUERY_GENERATION_ENABLED
            and self.INVESTIGATION_QUERY_BACKEND == "elasticsearch"
        ):
            self.SPL_QUERY_GENERATION_ENABLED = False
        if self.CASE_QA_VECTOR_DIMENSIONS != 1024:
            raise ValueError("CASE_QA_VECTOR_DIMENSIONS must be 1024 for v1")
        if self.RAG_VECTOR_DIMENSIONS != self.CASE_QA_VECTOR_DIMENSIONS:
            raise ValueError(
                "RAG_VECTOR_DIMENSIONS must match CASE_QA_VECTOR_DIMENSIONS"
            )
        if bool(self.CASE_ARCHIVE_ENABLED):
            if not str(self.CASE_POSTGRES_DSN or "").strip():
                raise ValueError("CASE_POSTGRES_DSN is required when CASE_ARCHIVE_ENABLED=true")
            _validate_postgres_identifier(
                self.CASE_POSTGRES_SCHEMA,
                "CASE_POSTGRES_SCHEMA",
            )
        if bool(self.PORTAL_ENABLED):
            if not bool(self.CASE_ARCHIVE_ENABLED):
                raise ValueError("CASE_ARCHIVE_ENABLED is required when PORTAL_ENABLED=true")
            if not str(self.PORTAL_PROXY_SECRET or "").strip():
                raise ValueError("PORTAL_PROXY_SECRET is required when PORTAL_ENABLED=true")
        if bool(self.CASE_QA_ENABLED) and not bool(self.CASE_ARCHIVE_ENABLED):
            raise ValueError("CASE_ARCHIVE_ENABLED is required when CASE_QA_ENABLED=true")
        if bool(self.CASE_QA_CHAT_HISTORY_ENABLED) and not bool(self.CASE_QA_ENABLED):
            raise ValueError(
                "CASE_QA_ENABLED is required when CASE_QA_CHAT_HISTORY_ENABLED=true"
            )
        if bool(self.SERVICENOW_DISPOSITION_SYNC_ENABLED):
            if not str(self.SERVICENOW_DISPOSITION_SYNC_TOKEN or "").strip():
                raise ValueError(
                    "SERVICENOW_DISPOSITION_SYNC_TOKEN is required when "
                    "SERVICENOW_DISPOSITION_SYNC_ENABLED=true"
                )
            if not str(self.SERVICENOW_BASE_URL or "").strip().startswith("https://"):
                raise ValueError(
                    "SERVICENOW_BASE_URL must be HTTPS when "
                    "SERVICENOW_DISPOSITION_SYNC_ENABLED=true"
                )
            if not str(self.CASE_POSTGRES_DSN or "").strip():
                raise ValueError(
                    "CASE_POSTGRES_DSN is required when "
                    "SERVICENOW_DISPOSITION_SYNC_ENABLED=true"
                )
            _validate_postgres_identifier(
                self.CASE_POSTGRES_SCHEMA,
                "CASE_POSTGRES_SCHEMA",
            )
        if self.CLOSED_TICKET_RETENTION_DAYS not in _CLOSED_TICKET_RETENTION_ALLOWED:
            raise ValueError("CLOSED_TICKET_RETENTION_DAYS must be one of 30, 60, or 90")
        if bool(self.SERVICENOW_CLOSED_TICKET_SYNC_ENABLED):
            if not str(self.SERVICENOW_CLOSED_TICKET_TOKEN or "").strip():
                raise ValueError(
                    "SERVICENOW_CLOSED_TICKET_TOKEN is required when "
                    "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=true"
                )
            if not str(self.SERVICENOW_CLOSED_TICKET_QUERY or "").strip():
                raise ValueError(
                    "SERVICENOW_CLOSED_TICKET_QUERY is required when "
                    "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=true"
                )
            if not str(self.SERVICENOW_BASE_URL or "").strip().startswith("https://"):
                raise ValueError(
                    "SERVICENOW_BASE_URL must be HTTPS when "
                    "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=true"
                )
            if not str(self.CASE_POSTGRES_DSN or "").strip():
                raise ValueError(
                    "CASE_POSTGRES_DSN is required when "
                    "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=true"
                )
            _validate_servicenow_table_name(
                self.SERVICENOW_CLOSED_TICKET_TABLE,
                "SERVICENOW_CLOSED_TICKET_TABLE",
            )
            _validate_postgres_identifier(
                self.CLOSED_TICKET_POSTGRES_SCHEMA,
                "CLOSED_TICKET_POSTGRES_SCHEMA",
            )
            _validate_postgres_identifier(
                self.CLOSED_TICKET_POSTGRES_CHUNKS_TABLE,
                "CLOSED_TICKET_POSTGRES_CHUNKS_TABLE",
            )
            if bool(self.SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS):
                if not str(self.CLOSED_TICKET_ATTACHMENT_DIR):
                    raise ValueError(
                        "CLOSED_TICKET_ATTACHMENT_DIR is required when "
                        "SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=true"
                    )
        if bool(self.CLOSED_TICKET_RAG_ENABLED):
            if not str(self.CASE_POSTGRES_DSN or "").strip():
                raise ValueError(
                    "CASE_POSTGRES_DSN is required when CLOSED_TICKET_RAG_ENABLED=true"
                )
            _validate_postgres_identifier(
                self.CLOSED_TICKET_POSTGRES_SCHEMA,
                "CLOSED_TICKET_POSTGRES_SCHEMA",
            )
            _validate_postgres_identifier(
                self.CLOSED_TICKET_POSTGRES_CHUNKS_TABLE,
                "CLOSED_TICKET_POSTGRES_CHUNKS_TABLE",
            )
        _apply_closed_ticket_vision_defaults(self)
        _validate_elasticsearch_runtime_contract(self)


def load_config() -> Config:
    """Load configuration from environment variables.

    Returns:
        Populated Config dataclass.
    """
    capability_profiles = _parse_capability_profiles(
        os.getenv("CAPABILITY_PROFILES", "core")
    )
    profile_flags = _profile_flag_defaults(capability_profiles)
    closed_ticket_retention_days = _closed_ticket_retention_days(
        "CLOSED_TICKET_RETENTION_DAYS", 30
    )

    return Config(
        INGEST_MODE=os.getenv("INGEST_MODE", "file_drop"),
        CAPABILITY_PROFILES=",".join(capability_profiles),
        INCOMING_DIR=Path(os.getenv("INCOMING_DIR", "/var/notables/incoming")),
        PROCESSED_DIR=Path(os.getenv("PROCESSED_DIR", "/var/notables/processed")),
        QUARANTINE_DIR=Path(os.getenv("QUARANTINE_DIR", "/var/notables/quarantine")),
        REPORT_DIR=Path(os.getenv("REPORT_DIR", "/var/notables/reports")),
        ARCHIVE_DIR=Path(os.getenv("ARCHIVE_DIR", "/var/notables/archive")),
        POLL_INTERVAL=int(os.getenv("POLL_INTERVAL", "5")),
        MAX_INPUT_FILE_BYTES=_positive_int_env(
            "MAX_INPUT_FILE_BYTES", 4 * 1024 * 1024, max_value=100 * 1024 * 1024
        ),
        LLM_API_URL=os.getenv(
            "LLM_API_URL", "http://127.0.0.1:4000/v1/chat/completions"
        ),
        LLM_API_TOKEN=os.getenv("LLM_API_TOKEN", ""),
        LLM_MODEL_NAME=os.getenv("LLM_MODEL_NAME", "gemma-4-31B-it"),
        LLM_STRUCTURED_OUTPUT_MODE=(
            os.getenv("LLM_STRUCTURED_OUTPUT_MODE", "prompt_json").strip().lower()
            or "prompt_json"
        ),
        LLM_MAX_TOKENS=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        LLM_TIMEOUT=int(os.getenv("LLM_TIMEOUT", "240")),
        HTML_REPORT_ENABLED=_profile_bool(
            "HTML_REPORT_ENABLED", False, profile_flags
        ),
        RAG_ENABLED=_profile_bool("RAG_ENABLED", False, profile_flags),
        RAG_BACKEND=os.getenv("RAG_BACKEND", "postgres").strip().lower()
        or "postgres",
        RAG_FAIL_CLOSED=_bool_env("RAG_FAIL_CLOSED", False),
        RAG_SQLITE_PATH=Path(
            os.getenv(
                "RAG_SQLITE_PATH",
                "/opt/llm-notable-analysis/knowledge_base/index/kb.sqlite3",
            )
        ),
        RAG_FAISS_PATH=Path(
            os.getenv(
                "RAG_FAISS_PATH",
                "/opt/llm-notable-analysis/knowledge_base/index/kb.faiss",
            )
        ),
        RAG_EMBEDDING_MODEL=os.getenv(
            "RAG_EMBEDDING_MODEL", "mixedbread-ai/mxbai-embed-large-v1"
        ),
        RAG_RERANK_ENABLED=_bool_env("RAG_RERANK_ENABLED", False),
        RAG_RERANK_MODEL=os.getenv(
            "RAG_RERANK_MODEL", "mixedbread-ai/mxbai-rerank-large-v2"
        ),
        RAG_POSTGRES_DSN=os.getenv(
            "RAG_POSTGRES_DSN",
            "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
        ),
        RAG_POSTGRES_SCHEMA=os.getenv("RAG_POSTGRES_SCHEMA", "notable_rag"),
        RAG_POSTGRES_CHUNKS_TABLE=os.getenv("RAG_POSTGRES_CHUNKS_TABLE", "kb_chunks"),
        RAG_POSTGRES_FTS_CONFIG=os.getenv("RAG_POSTGRES_FTS_CONFIG", "english"),
        RAG_POSTGRES_STATEMENT_TIMEOUT_MS=int(
            os.getenv("RAG_POSTGRES_STATEMENT_TIMEOUT_MS", "5000")
        ),
        RAG_VECTOR_DIMENSIONS=int(
            os.getenv("RAG_VECTOR_DIMENSIONS", "1024")
        ),
        RAG_MAX_SNIPPETS_120B=int(os.getenv("RAG_MAX_SNIPPETS_120B", "5")),
        RAG_MAX_SNIPPETS_20B=int(os.getenv("RAG_MAX_SNIPPETS_20B", "4")),
        RAG_CONTEXT_BUDGET_CHARS_120B=int(
            os.getenv("RAG_CONTEXT_BUDGET_CHARS_120B", "2200")
        ),
        RAG_CONTEXT_BUDGET_CHARS_20B=int(
            os.getenv("RAG_CONTEXT_BUDGET_CHARS_20B", "1600")
        ),
        RAG_FUSED_RANK_LIMIT_120B=int(os.getenv("RAG_FUSED_RANK_LIMIT_120B", "8")),
        RAG_FUSED_RANK_LIMIT_20B=int(os.getenv("RAG_FUSED_RANK_LIMIT_20B", "6")),
        RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD=float(
            os.getenv("RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD", "0.80")
        ),
        RAG_LEXICAL_TOP_K=int(os.getenv("RAG_LEXICAL_TOP_K", "30")),
        RAG_VECTOR_TOP_K=int(os.getenv("RAG_VECTOR_TOP_K", "30")),
        RAG_CANDIDATE_POOL_LIMIT=int(os.getenv("RAG_CANDIDATE_POOL_LIMIT", "40")),
        RAG_RRF_K=int(os.getenv("RAG_RRF_K", "60")),
        CASE_ARCHIVE_ENABLED=_profile_bool(
            "CASE_ARCHIVE_ENABLED", False, profile_flags
        ),
        CASE_POSTGRES_DSN=os.getenv(
            "CASE_POSTGRES_DSN",
            "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
        ),
        CASE_POSTGRES_SCHEMA=os.getenv("CASE_POSTGRES_SCHEMA", "notable_cases"),
        CASE_RETENTION_DAYS=_positive_int_env(
            "CASE_RETENTION_DAYS", 30, max_value=3650
        ),
        CASE_RETENTION_DELETE_BATCH_SIZE=_positive_int_env(
            "CASE_RETENTION_DELETE_BATCH_SIZE", 500, max_value=10000
        ),
        CASE_ARCHIVE_WRITE_MAX_ATTEMPTS=_positive_int_env(
            "CASE_ARCHIVE_WRITE_MAX_ATTEMPTS", 3, max_value=10
        ),
        CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS=_positive_int_env(
            "CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS", 1, max_value=300
        ),
        CASE_POSTGRES_STATEMENT_TIMEOUT_MS=_positive_int_env(
            "CASE_POSTGRES_STATEMENT_TIMEOUT_MS", 5000, max_value=300000
        ),
        CASE_SCHEMA_VERSION=_positive_int_env(
            "CASE_SCHEMA_VERSION", 1, max_value=1000
        ),
        CASE_ANALYSIS_SCHEMA_VERSION=_positive_int_env(
            "CASE_ANALYSIS_SCHEMA_VERSION", 1, max_value=1000
        ),
        CASE_QA_ENABLED=_profile_bool("CASE_QA_ENABLED", False, profile_flags),
        CASE_QA_MAX_CHUNKS_PER_LANE=_positive_int_env(
            "CASE_QA_MAX_CHUNKS_PER_LANE", 6, max_value=100
        ),
        CASE_QA_MAX_TOTAL_CHUNKS=_positive_int_env(
            "CASE_QA_MAX_TOTAL_CHUNKS", 18, max_value=300
        ),
        CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=_positive_int_env(
            "CASE_QA_MAX_INDEX_CHUNKS_PER_CASE", 200, max_value=5000
        ),
        CASE_QA_CONTEXT_BUDGET_CHARS=_positive_int_env(
            "CASE_QA_CONTEXT_BUDGET_CHARS", 12000, max_value=200000
        ),
        CASE_QA_MAX_QUESTION_CHARS=_positive_int_env(
            "CASE_QA_MAX_QUESTION_CHARS", 2000, max_value=20000
        ),
        CASE_QA_MAX_ANSWER_TOKENS=_positive_int_env(
            "CASE_QA_MAX_ANSWER_TOKENS", 800, max_value=16000
        ),
        CASE_QA_MODEL_CONTEXT_TOKENS=_positive_int_env(
            "CASE_QA_MODEL_CONTEXT_TOKENS", 128_000, max_value=2_000_000
        ),
        CASE_QA_CHUNK_SCHEMA_VERSION=_positive_int_env(
            "CASE_QA_CHUNK_SCHEMA_VERSION", 1, max_value=1000
        ),
        CASE_QA_EMBEDDING_MODEL=os.getenv(
            "CASE_QA_EMBEDDING_MODEL", "mixedbread-ai/mxbai-embed-large-v1"
        ),
        CASE_QA_VECTOR_DIMENSIONS=_positive_int_env(
            "CASE_QA_VECTOR_DIMENSIONS", 1024, max_value=100000
        ),
        CASE_QA_CHAT_HISTORY_ENABLED=_profile_bool(
            "CASE_QA_CHAT_HISTORY_ENABLED", False, profile_flags
        ),
        CASE_QA_GENERAL_KNOWLEDGE_ENABLED=_profile_bool(
            "CASE_QA_GENERAL_KNOWLEDGE_ENABLED", True, profile_flags
        ),
        CASE_QA_CHAT_HISTORY_RETENTION_DAYS=_positive_int_env(
            "CASE_QA_CHAT_HISTORY_RETENTION_DAYS", 7, max_value=365
        ),
        CASE_QA_MAX_MESSAGES_PER_SESSION=_positive_int_env(
            "CASE_QA_MAX_MESSAGES_PER_SESSION", 30, max_value=1000
        ),
        CASE_QA_MAX_SESSIONS_PER_USER=_positive_int_env(
            "CASE_QA_MAX_SESSIONS_PER_USER", 10, max_value=100
        ),
        CASE_QA_MAX_STORED_MESSAGE_BYTES=_positive_int_env(
            "CASE_QA_MAX_STORED_MESSAGE_BYTES", 4000, max_value=100000
        ),
        CASE_QA_MAX_CONVERSATION_TURNS=_positive_int_env(
            "CASE_QA_MAX_CONVERSATION_TURNS", 10, max_value=100
        ),
        CASE_QA_MAX_CONVERSATION_CHARS=_positive_int_env(
            "CASE_QA_MAX_CONVERSATION_CHARS", 6000, max_value=65536
        ),
        CASE_QA_LEXICAL_TOP_K=_positive_int_env(
            "CASE_QA_LEXICAL_TOP_K", 30, max_value=1000
        ),
        CASE_QA_VECTOR_TOP_K=_positive_int_env(
            "CASE_QA_VECTOR_TOP_K", 30, max_value=1000
        ),
        CASE_QA_RRF_K=_positive_int_env("CASE_QA_RRF_K", 60, max_value=10000),
        PORTAL_ENABLED=_profile_bool("PORTAL_ENABLED", False, profile_flags),
        PORTAL_BIND_HOST=os.getenv("PORTAL_BIND_HOST", "127.0.0.1"),
        PORTAL_PORT=_positive_int_env("PORTAL_PORT", 8080, max_value=65535),
        PORTAL_PAGE_SIZE=_positive_int_env("PORTAL_PAGE_SIZE", 50, max_value=100),
        PORTAL_CHAT_MAX_CONCURRENCY=_positive_int_env(
            "PORTAL_CHAT_MAX_CONCURRENCY", 18, max_value=64
        ),
        PORTAL_TRUSTED_USER_HEADER=os.getenv(
            "PORTAL_TRUSTED_USER_HEADER", "X-Forwarded-User"
        ),
        PORTAL_ALLOW_NON_LOOPBACK_BIND=_bool_env("PORTAL_ALLOW_NON_LOOPBACK_BIND", False),
        PORTAL_PROXY_SECRET=os.getenv("PORTAL_PROXY_SECRET", ""),
        PORTAL_PROXY_SECRET_HEADER=os.getenv(
            "PORTAL_PROXY_SECRET_HEADER", "X-Notable-Portal-Proxy-Secret"
        ),
        SPLUNK_BASE_URL=os.getenv("SPLUNK_BASE_URL", ""),
        SPLUNK_API_TOKEN=os.getenv("SPLUNK_API_TOKEN", ""),
        SPLUNK_NOTABLE_UPDATE_PATH=os.getenv(
            "SPLUNK_NOTABLE_UPDATE_PATH", "/services/notable_update"
        ),
        SPLUNK_SINK_ENABLED=_profile_bool(
            "SPLUNK_SINK_ENABLED", False, profile_flags
        ),
        SPL_QUERY_GENERATION_ENABLED=_profile_bool(
            "SPL_QUERY_GENERATION_ENABLED", False, profile_flags
        ),
        SPL_QUERY_RAG_ENABLED=_bool_env("SPL_QUERY_RAG_ENABLED", False),
        SPL_QUERY_RAG_SOURCE_DIR=Path(
            os.getenv(
                "SPL_QUERY_RAG_SOURCE_DIR",
                "/opt/llm-notable-analysis/knowledge_base/spl_query_source_docs",
            )
        ),
        SPL_QUERY_RAG_INDEX_DIR=Path(
            os.getenv(
                "SPL_QUERY_RAG_INDEX_DIR",
                "/opt/llm-notable-analysis/knowledge_base/spl_query_index",
            )
        ),
        SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE=os.getenv(
            "SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE", "spl_query_chunks"
        ),
        SPL_QUERY_RAG_MAX_SNIPPETS=int(os.getenv("SPL_QUERY_RAG_MAX_SNIPPETS", "4")),
        SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS=int(
            os.getenv("SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS", "1600")
        ),
        SPL_QUERY_RAG_FAILURE_MODE=(
            os.getenv("SPL_QUERY_RAG_FAILURE_MODE", "suppress").strip().lower()
            or "suppress"
        ),
        SPLUNK_CA_BUNDLE=os.getenv("SPLUNK_CA_BUNDLE", ""),
        INVESTIGATION_QUERY_EXECUTION_ENABLED=_profile_bool(
            "INVESTIGATION_QUERY_EXECUTION_ENABLED", False, profile_flags
        ),
        INVESTIGATION_QUERY_BACKEND=_profile_str(
            "INVESTIGATION_QUERY_BACKEND", "splunk", profile_flags
        ).lower(),
        INVESTIGATION_QUERY_EXECUTOR=os.getenv(
            "INVESTIGATION_QUERY_EXECUTOR", "rest"
        ).strip()
        or "rest",
        INVESTIGATION_MAX_QUERIES_PER_ALERT=_positive_int_env(
            "INVESTIGATION_MAX_QUERIES_PER_ALERT", 6, max_value=24
        ),
        INVESTIGATION_MAX_CONCURRENT_QUERIES=_positive_int_env(
            "INVESTIGATION_MAX_CONCURRENT_QUERIES", 6, max_value=8
        ),
        QUERY_RESULT_INTERPRETATION_ENABLED=_bool_env(
            "QUERY_RESULT_INTERPRETATION_ENABLED", False
        ),
        QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS=_positive_int_env(
            "QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS", 4000, max_value=20000
        ),
        QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS=_positive_int_env(
            "QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS", 3, max_value=10
        ),
        QUERY_RESULT_INTERPRETATION_MAX_TOKENS=_positive_int_env(
            "QUERY_RESULT_INTERPRETATION_MAX_TOKENS", 768, max_value=2048
        ),
        SPLUNK_SEARCH_ENDPOINT_PATH=os.getenv(
            "SPLUNK_SEARCH_ENDPOINT_PATH", "/services/search/jobs/oneshot"
        ),
        SPLUNK_SEARCH_ALLOWED_INDEXES=os.getenv(
            "SPLUNK_SEARCH_ALLOWED_INDEXES", "main,notable,risk"
        ),
        SPLUNK_SEARCH_ALLOWED_COMMANDS=os.getenv(
            "SPLUNK_SEARCH_ALLOWED_COMMANDS", "search,stats,table,fields,where,head"
        ),
        SPLUNK_SEARCH_DENIED_COMMANDS=os.getenv(
            "SPLUNK_SEARCH_DENIED_COMMANDS",
            "delete,collect,outputlookup,sendemail,map,rest,script,dbxquery",
        ),
        SPLUNK_SEARCH_MAX_TIME_RANGE=os.getenv("SPLUNK_SEARCH_MAX_TIME_RANGE", "24h"),
        SPLUNK_SEARCH_MAX_ROWS=_positive_int_env(
            "SPLUNK_SEARCH_MAX_ROWS", 100, max_value=1000
        ),
        SPLUNK_SEARCH_TIMEOUT_SECONDS=_positive_int_env(
            "SPLUNK_SEARCH_TIMEOUT_SECONDS", 30, max_value=300
        ),
        SPLUNK_MCP_TOOL_NAME=os.getenv("SPLUNK_MCP_TOOL_NAME", "splunk_search"),
        ELASTIC_QUERY_GENERATION_ENABLED=_profile_bool(
            "ELASTIC_QUERY_GENERATION_ENABLED", False, profile_flags
        ),
        ELASTICSEARCH_BASE_URL=os.getenv("ELASTICSEARCH_BASE_URL", ""),
        ELASTICSEARCH_API_KEY=os.getenv("ELASTICSEARCH_API_KEY", ""),
        ELASTICSEARCH_INDEX_ALLOWLIST=os.getenv("ELASTICSEARCH_INDEX_ALLOWLIST", ""),
        ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=_bool_env(
            "ELASTICSEARCH_ALLOW_WILDCARD_INDEXES", False
        ),
        ELASTICSEARCH_TIMESTAMP_FIELD=os.getenv(
            "ELASTICSEARCH_TIMESTAMP_FIELD", "@timestamp"
        ).strip()
        or "@timestamp",
        ELASTICSEARCH_ALLOWED_FIELDS=os.getenv("ELASTICSEARCH_ALLOWED_FIELDS", ""),
        ELASTICSEARCH_GROUNDING_ENABLED=_bool_env(
            "ELASTICSEARCH_GROUNDING_ENABLED", False
        ),
        ELASTICSEARCH_GROUNDING_SOURCE_DIR=Path(
            os.getenv(
                "ELASTICSEARCH_GROUNDING_SOURCE_DIR",
                "/opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs",
            )
        ),
        ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE=os.getenv(
            "ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE",
            "elasticsearch_query_chunks",
        ),
        ELASTICSEARCH_GROUNDING_MAX_SNIPPETS=_positive_int_env(
            "ELASTICSEARCH_GROUNDING_MAX_SNIPPETS", 4, max_value=20
        ),
        ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS=_positive_int_env(
            "ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS", 1600, max_value=10000
        ),
        ELASTICSEARCH_GROUNDING_FAILURE_MODE=(
            os.getenv("ELASTICSEARCH_GROUNDING_FAILURE_MODE", "suppress").strip().lower()
            or "suppress"
        ),
        ELASTICSEARCH_MAX_TIME_RANGE=os.getenv("ELASTICSEARCH_MAX_TIME_RANGE", "24h"),
        ELASTICSEARCH_MAX_ROWS=_positive_int_env(
            "ELASTICSEARCH_MAX_ROWS", 100, max_value=1000
        ),
        ELASTICSEARCH_TIMEOUT_SECONDS=_positive_int_env(
            "ELASTICSEARCH_TIMEOUT_SECONDS", 30, max_value=300
        ),
        ELASTICSEARCH_CA_BUNDLE=os.getenv("ELASTICSEARCH_CA_BUNDLE", ""),
        SERVICENOW_DRAFT_ENABLED=_profile_bool(
            "SERVICENOW_DRAFT_ENABLED", False, profile_flags
        ),
        SERVICENOW_CREATE_ENABLED=_profile_bool(
            "SERVICENOW_CREATE_ENABLED", False, profile_flags
        ),
        SERVICENOW_CREATE_REQUIRES_APPROVAL=_profile_bool(
            "SERVICENOW_CREATE_REQUIRES_APPROVAL", True, profile_flags
        ),
        SERVICENOW_BASE_URL=os.getenv(
            "SERVICENOW_BASE_URL", "https://your-instance.service-now.com"
        ),
        SERVICENOW_CREATE_PATH=os.getenv(
            "SERVICENOW_CREATE_PATH", "/api/now/table/incident"
        ),
        SERVICENOW_API_TOKEN=os.getenv("SERVICENOW_API_TOKEN", ""),
        SERVICENOW_ASSIGNMENT_GROUP=os.getenv("SERVICENOW_ASSIGNMENT_GROUP", ""),
        SERVICENOW_TIMEOUT_SECONDS=int(os.getenv("SERVICENOW_TIMEOUT_SECONDS", "15")),
        SERVICENOW_DISPOSITION_SYNC_ENABLED=_bool_env(
            "SERVICENOW_DISPOSITION_SYNC_ENABLED", False
        ),
        SERVICENOW_DISPOSITION_SYNC_TOKEN=os.getenv(
            "SERVICENOW_DISPOSITION_SYNC_TOKEN", ""
        ),
        SERVICENOW_DISPOSITION_FIELD_MAP=Path(
            os.getenv(
                "SERVICENOW_DISPOSITION_FIELD_MAP",
                "/etc/notable-analyzer/servicenow/disposition_field_map.json",
            )
        ),
        SERVICENOW_DISPOSITION_CODE_MAP=Path(
            os.getenv(
                "SERVICENOW_DISPOSITION_CODE_MAP",
                "/etc/notable-analyzer/servicenow/disposition_code_map.json",
            )
        ),
        SERVICENOW_DISPOSITION_BACKFILL_DAYS=_positive_int_env(
            "SERVICENOW_DISPOSITION_BACKFILL_DAYS", 90, max_value=3650
        ),
        DISPOSITION_RETENTION_DAYS=_positive_int_env(
            "DISPOSITION_RETENTION_DAYS", 365, max_value=3650
        ),
        CLOSED_TICKET_RAG_ENABLED=_bool_env("CLOSED_TICKET_RAG_ENABLED", False),
        CLOSED_TICKET_RETENTION_DAYS=closed_ticket_retention_days,
        SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=_bool_env(
            "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED", False
        ),
        SERVICENOW_CLOSED_TICKET_TOKEN=os.getenv("SERVICENOW_CLOSED_TICKET_TOKEN", ""),
        SERVICENOW_CLOSED_TICKET_TABLE=os.getenv(
            "SERVICENOW_CLOSED_TICKET_TABLE", "sn_si_incident"
        ).strip()
        or "sn_si_incident",
        SERVICENOW_CLOSED_TICKET_QUERY=os.getenv("SERVICENOW_CLOSED_TICKET_QUERY", ""),
        SERVICENOW_CLOSED_TICKET_BACKFILL_DAYS=_positive_int_env(
            "SERVICENOW_CLOSED_TICKET_BACKFILL_DAYS",
            closed_ticket_retention_days,
            max_value=3650,
        ),
        SERVICENOW_CLOSED_TICKET_CURSOR_OVERLAP_HOURS=_positive_int_env(
            "SERVICENOW_CLOSED_TICKET_CURSOR_OVERLAP_HOURS", 24, max_value=168
        ),
        SERVICENOW_CLOSED_TICKET_RECONCILE_INTERVAL_DAYS=_positive_int_env(
            "SERVICENOW_CLOSED_TICKET_RECONCILE_INTERVAL_DAYS", 7, max_value=90
        ),
        SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS=_bool_env(
            "SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS", True
        ),
        SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS=_bool_env(
            "SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS", True
        ),
        CLOSED_TICKET_ATTACHMENT_DIR=Path(
            os.getenv(
                "CLOSED_TICKET_ATTACHMENT_DIR",
                "/var/notables/closed_ticket_attachments",
            )
        ),
        CLOSED_TICKET_ATTACHMENT_MAX_BYTES=_byte_size_env(
            "CLOSED_TICKET_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024
        ),
        CLOSED_TICKET_POSTGRES_SCHEMA=os.getenv(
            "CLOSED_TICKET_POSTGRES_SCHEMA", "notable_closed_tickets"
        ).strip()
        or "notable_closed_tickets",
        CLOSED_TICKET_POSTGRES_CHUNKS_TABLE=os.getenv(
            "CLOSED_TICKET_POSTGRES_CHUNKS_TABLE", "ticket_chunks"
        ).strip()
        or "ticket_chunks",
        CLOSED_TICKET_RAG_MAX_SNIPPETS=_positive_int_env(
            "CLOSED_TICKET_RAG_MAX_SNIPPETS", 6, max_value=20
        ),
        CLOSED_TICKET_RAG_CONTEXT_BUDGET_CHARS=_positive_int_env(
            "CLOSED_TICKET_RAG_CONTEXT_BUDGET_CHARS", 6000, max_value=50000
        ),
        CASE_QA_CLOSED_TICKET_ENABLED=_bool_env("CASE_QA_CLOSED_TICKET_ENABLED", False),
        CASE_QA_CLOSED_TICKET_MAX_TICKETS=_positive_int_env(
            "CASE_QA_CLOSED_TICKET_MAX_TICKETS", 5, max_value=20
        ),
        CLOSED_TICKET_VISION_ENABLED=_bool_env("CLOSED_TICKET_VISION_ENABLED", False),
        CLOSED_TICKET_VISION_API_BASE=os.getenv("CLOSED_TICKET_VISION_API_BASE", ""),
        CLOSED_TICKET_VISION_MODEL=os.getenv("CLOSED_TICKET_VISION_MODEL", ""),
        CLOSED_TICKET_VISION_API_KEY=os.getenv("CLOSED_TICKET_VISION_API_KEY", ""),
        CLOSED_TICKET_VISION_TIMEOUT_SECONDS=float(
            os.getenv("CLOSED_TICKET_VISION_TIMEOUT_SECONDS", "30")
        ),
        CLOSED_TICKET_VISION_MAX_TOKENS=_positive_int_env(
            "CLOSED_TICKET_VISION_MAX_TOKENS", 400, max_value=4096
        ),
        CLOSED_TICKET_ATTACHMENT_MAX_TEXT_CHARS=_positive_int_env(
            "CLOSED_TICKET_ATTACHMENT_MAX_TEXT_CHARS", 12000, max_value=200000
        ),
        SIDE_EFFECT_IDEMPOTENCY_ENABLED=_profile_bool(
            "SIDE_EFFECT_IDEMPOTENCY_ENABLED", False, profile_flags
        ),
        SIDE_EFFECT_IDEMPOTENCY_DIR=Path(
            os.getenv("SIDE_EFFECT_IDEMPOTENCY_DIR", "/var/notables/idempotency")
        ),
        SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS=_positive_int_env(
            "SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS", 30, max_value=3650
        ),
        MITRE_IDS_PATH=Path(
            os.getenv(
                "MITRE_IDS_PATH",
                str(Path(__file__).parent / "enterprise_attack_v17.1_ids.json"),
            )
        ),
        INPUT_RETENTION_DAYS=int(os.getenv("INPUT_RETENTION_DAYS", "2")),
        REPORT_RETENTION_DAYS=int(os.getenv("REPORT_RETENTION_DAYS", "7")),
        ARCHIVE_RETENTION_DAYS=int(os.getenv("ARCHIVE_RETENTION_DAYS", "14")),
        RETENTION_RUN_INTERVAL_SECONDS=int(
            os.getenv("RETENTION_RUN_INTERVAL_SECONDS", "86400")
        ),
        CONCURRENCY_ENABLED=os.getenv("CONCURRENCY_ENABLED", "false").lower()
        in ("true", "1", "yes"),
        MAX_WORKERS=int(os.getenv("MAX_WORKERS", "1")),
        MAX_QUEUE_DEPTH=int(os.getenv("MAX_QUEUE_DEPTH", "8")),
    )
