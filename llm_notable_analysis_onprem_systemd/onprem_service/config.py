"""Configuration loading for on-prem notable analysis service.

Loads configuration from environment variables (typically via config.env).
All paths default to RHEL-standard locations.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Service configuration container.

    Attributes:
        INGEST_MODE: Input ingestion mode (`file_drop` by default).
        INCOMING_DIR: Directory watched for incoming notables.
        PROCESSED_DIR: Directory for successfully processed notables.
        QUARANTINE_DIR: Directory for failed/invalid notables.
        REPORT_DIR: Directory for generated markdown reports.
        ARCHIVE_DIR: Directory used by retention staging.
        POLL_INTERVAL: Polling interval in seconds.
        LLM_API_URL: Local vLLM/OpenAI-compatible endpoint URL.
        LLM_API_TOKEN: Optional bearer token for LLM API authentication.
        LLM_MODEL_NAME: Model identifier used for analysis.
        LLM_MAX_TOKENS: Per-request generation token cap.
        LLM_TIMEOUT: Request timeout in seconds.
        RAG_ENABLED: Enables retrieval-augmented prompt grounding.
        RAG_SQLITE_PATH: SQLite path for lexical retrieval index.
        RAG_FAISS_PATH: FAISS path for vector retrieval index.
        RAG_EMBEDDING_MODEL: Embedding model name/path.
        RAG_MAX_SNIPPETS_120B: Max RAG snippets for 120b profile.
        RAG_MAX_SNIPPETS_20B: Max RAG snippets for 20b profile.
        RAG_CONTEXT_BUDGET_CHARS_120B: Context char budget for 120b profile.
        RAG_CONTEXT_BUDGET_CHARS_20B: Context char budget for 20b profile.
        SPLUNK_BASE_URL: Splunk base URL for notable update sink.
        SPLUNK_API_TOKEN: Splunk token for REST sink authentication.
        SPLUNK_NOTABLE_UPDATE_PATH: Splunk notable update endpoint path.
        SPLUNK_SINK_ENABLED: Enables Splunk writeback sink.
        SPL_QUERY_GENERATION_ENABLED: Enables per-hypothesis SPL query generation.
        SPLUNK_CA_BUNDLE: Optional CA bundle for TLS verification.
        MITRE_IDS_PATH: Path to ATT&CK technique ID allowlist JSON.
        INPUT_RETENTION_DAYS: Retention window for processed/quarantine inputs.
        REPORT_RETENTION_DAYS: Retention window for generated reports.
        ARCHIVE_RETENTION_DAYS: Retention window for archived files.
        RETENTION_RUN_INTERVAL_SECONDS: Retention job interval.
        CONCURRENCY_ENABLED: Enables threaded processing mode.
        MAX_WORKERS: Thread-pool worker count when concurrency is enabled.
        MAX_QUEUE_DEPTH: Queue depth limit for backpressure.
    """

    # Ingest mode: file_drop (SOAR pushes via SFTP to INCOMING_DIR)
    INGEST_MODE: str = "file_drop"

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

    # Local LLM (vLLM)
    LLM_API_URL: str = "http://127.0.0.1:8000/v1/chat/completions"
    LLM_API_TOKEN: str = ""
    LLM_MODEL_NAME: str = "gemma-4-31B-it"
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT: int = 120  # seconds

    # Optional retrieval grounding (RAG)
    RAG_ENABLED: bool = False
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
    RAG_EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    RAG_MAX_SNIPPETS_120B: int = 5
    RAG_MAX_SNIPPETS_20B: int = 4
    RAG_CONTEXT_BUDGET_CHARS_120B: int = 2200
    RAG_CONTEXT_BUDGET_CHARS_20B: int = 1600

    # Splunk integration (optional)
    SPLUNK_BASE_URL: str = ""
    SPLUNK_API_TOKEN: str = ""
    SPLUNK_NOTABLE_UPDATE_PATH: str = "/services/notable_update"
    SPLUNK_SINK_ENABLED: bool = False
    SPL_QUERY_GENERATION_ENABLED: bool = False
    SPLUNK_CA_BUNDLE: str = (
        ""  # Path to PEM CA bundle for Splunk TLS; empty = system trust store
    )

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
    # Gemma 4 31B-it baseline profile:
    # - Xeon Gold: MAX_WORKERS=4, MAX_QUEUE_DEPTH=32 (default below)
    # - Xeon Platinum: MAX_WORKERS=6, MAX_QUEUE_DEPTH=48 (override in config.env)
    # - AMD EPYC 7J13 VM (KVM, ~30 vCPU observed): start with Gold profile (4/32),
    #   then increase only after validating CPU headroom and queue latency.
    CONCURRENCY_ENABLED: bool = False  # Sequential by default
    MAX_WORKERS: int = 4  # Thread pool size when enabled (A100 + Xeon Gold baseline)
    MAX_QUEUE_DEPTH: int = 32  # Backpressure limit (A100 + Xeon Gold baseline)


def load_config() -> Config:
    """Load configuration from environment variables.

    Returns:
        Populated Config dataclass.
    """
    return Config(
        INGEST_MODE=os.getenv("INGEST_MODE", "file_drop"),
        INCOMING_DIR=Path(os.getenv("INCOMING_DIR", "/var/notables/incoming")),
        PROCESSED_DIR=Path(os.getenv("PROCESSED_DIR", "/var/notables/processed")),
        QUARANTINE_DIR=Path(os.getenv("QUARANTINE_DIR", "/var/notables/quarantine")),
        REPORT_DIR=Path(os.getenv("REPORT_DIR", "/var/notables/reports")),
        ARCHIVE_DIR=Path(os.getenv("ARCHIVE_DIR", "/var/notables/archive")),
        POLL_INTERVAL=int(os.getenv("POLL_INTERVAL", "5")),
        LLM_API_URL=os.getenv(
            "LLM_API_URL", "http://127.0.0.1:8000/v1/chat/completions"
        ),
        LLM_API_TOKEN=os.getenv("LLM_API_TOKEN", ""),
        LLM_MODEL_NAME=os.getenv("LLM_MODEL_NAME", "gemma-4-31B-it"),
        LLM_MAX_TOKENS=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        LLM_TIMEOUT=int(os.getenv("LLM_TIMEOUT", "120")),
        RAG_ENABLED=os.getenv("RAG_ENABLED", "false").lower() in ("true", "1", "yes"),
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
            "RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        ),
        RAG_MAX_SNIPPETS_120B=int(os.getenv("RAG_MAX_SNIPPETS_120B", "5")),
        RAG_MAX_SNIPPETS_20B=int(os.getenv("RAG_MAX_SNIPPETS_20B", "4")),
        RAG_CONTEXT_BUDGET_CHARS_120B=int(
            os.getenv("RAG_CONTEXT_BUDGET_CHARS_120B", "2200")
        ),
        RAG_CONTEXT_BUDGET_CHARS_20B=int(
            os.getenv("RAG_CONTEXT_BUDGET_CHARS_20B", "1600")
        ),
        SPLUNK_BASE_URL=os.getenv("SPLUNK_BASE_URL", ""),
        SPLUNK_API_TOKEN=os.getenv("SPLUNK_API_TOKEN", ""),
        SPLUNK_NOTABLE_UPDATE_PATH=os.getenv(
            "SPLUNK_NOTABLE_UPDATE_PATH", "/services/notable_update"
        ),
        SPLUNK_SINK_ENABLED=os.getenv("SPLUNK_SINK_ENABLED", "false").lower()
        in ("true", "1", "yes"),
        SPL_QUERY_GENERATION_ENABLED=os.getenv(
            "SPL_QUERY_GENERATION_ENABLED", "false"
        ).lower()
        in ("true", "1", "yes"),
        SPLUNK_CA_BUNDLE=os.getenv("SPLUNK_CA_BUNDLE", ""),
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
        MAX_WORKERS=int(os.getenv("MAX_WORKERS", "4")),
        MAX_QUEUE_DEPTH=int(os.getenv("MAX_QUEUE_DEPTH", "32")),
    )
