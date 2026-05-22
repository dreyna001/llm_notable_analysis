"""Configuration loading for on-prem notable analysis service.

Loads configuration from environment variables (typically via config.env).
All paths default to RHEL-standard locations.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}

_CAPABILITY_PROFILE_FLAGS: dict[str, dict[str, bool]] = {
    "core": {},
    "html_reports": {"HTML_REPORT_ENABLED": True},
    "rag": {"RAG_ENABLED": True},
    "spl_readonly": {
        "SPL_QUERY_GENERATION_ENABLED": True,
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

    deduped: list[str] = []
    for profile in profiles:
        if profile not in deduped:
            deduped.append(profile)
    return tuple(deduped)


def _profile_flag_defaults(profiles: tuple[str, ...]) -> dict[str, bool]:
    """Return boolean defaults implied by the selected capability profiles."""
    flags: dict[str, bool] = {}
    for profile in profiles:
        flags.update(_CAPABILITY_PROFILE_FLAGS[profile])
    return flags


def _profile_bool(name: str, default: bool, profile_flags: dict[str, bool]) -> bool:
    """Resolve a boolean controlled first by profiles, then legacy env flags."""
    if name in profile_flags:
        return profile_flags[name]
    env_value = _bool_env_optional(name)
    if env_value is not None:
        return env_value
    return default


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
    RAG_EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
    RAG_RERANK_ENABLED: bool = False
    RAG_RERANK_MODEL: str = "BAAI/bge-reranker-base"
    RAG_POSTGRES_DSN: str = "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag"
    RAG_POSTGRES_SCHEMA: str = "notable_rag"
    RAG_POSTGRES_CHUNKS_TABLE: str = "kb_chunks"
    RAG_POSTGRES_FTS_CONFIG: str = "english"
    RAG_POSTGRES_STATEMENT_TIMEOUT_MS: int = 5000
    RAG_VECTOR_DIMENSIONS: int = 768
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
    SERVICENOW_DRAFT_ENABLED: bool = False
    SERVICENOW_CREATE_ENABLED: bool = False
    SERVICENOW_CREATE_REQUIRES_APPROVAL: bool = True
    SERVICENOW_BASE_URL: str = "https://your-instance.service-now.com"
    SERVICENOW_CREATE_PATH: str = "/api/now/table/incident"
    SERVICENOW_API_TOKEN: str = ""
    SERVICENOW_ASSIGNMENT_GROUP: str = ""
    SERVICENOW_TIMEOUT_SECONDS: int = 15

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


def load_config() -> Config:
    """Load configuration from environment variables.

    Returns:
        Populated Config dataclass.
    """
    capability_profiles = _parse_capability_profiles(
        os.getenv("CAPABILITY_PROFILES", "core")
    )
    profile_flags = _profile_flag_defaults(capability_profiles)

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
            "RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"
        ),
        RAG_RERANK_ENABLED=_bool_env("RAG_RERANK_ENABLED", False),
        RAG_RERANK_MODEL=os.getenv("RAG_RERANK_MODEL", "BAAI/bge-reranker-base"),
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
            os.getenv("RAG_VECTOR_DIMENSIONS", "768")
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
