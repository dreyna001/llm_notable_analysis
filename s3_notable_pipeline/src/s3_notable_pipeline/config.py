"""Runtime configuration for the S3 notable pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .runtime_security import validate_https_url

_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}

_CAPABILITY_PROFILE_FLAGS: dict[str, dict[str, Any]] = {
    "core": {},
    "html_reports": {"HTML_REPORT_ENABLED": True},
    "rag": {"RAG_ENABLED": True},
    "spl_readonly": {
        "SPL_QUERY_GENERATION_ENABLED": True,
        "INVESTIGATION_QUERY_EXECUTION_ENABLED": True,
        "INVESTIGATION_QUERY_BACKEND": "splunk",
    },
    "elastic_readonly": {
        "ELASTIC_QUERY_GENERATION_ENABLED": True,
        "INVESTIGATION_QUERY_EXECUTION_ENABLED": True,
        "INVESTIGATION_QUERY_BACKEND": "elasticsearch",
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


def _bool_env(name: str, default: bool) -> bool:
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
    if os.getenv(name) is None:
        return None
    return _bool_env(name, False)


def _positive_int_env(name: str, default: int, *, max_value: int | None = None) -> int:
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


def _parse_capability_profiles(raw: str) -> tuple[str, ...]:
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
    flags: dict[str, Any] = {}
    for profile in profiles:
        flags.update(_CAPABILITY_PROFILE_FLAGS[profile])
    return flags


def _profile_bool(name: str, default: bool, profile_flags: dict[str, Any]) -> bool:
    if name in profile_flags:
        return bool(profile_flags[name])
    env_value = _bool_env_optional(name)
    if env_value is not None:
        return env_value
    return default


def _profile_str(name: str, default: str, profile_flags: dict[str, Any]) -> str:
    if name in profile_flags:
        return str(profile_flags[name])
    return os.getenv(name, default).strip() or default


@dataclass
class Config:
    """Configuration container for AWS Lambda runtime settings."""

    CAPABILITY_PROFILES: str = "core"
    BEDROCK_MODEL_ID: str = ""
    SPLUNK_SINK_MODE: str = "s3"
    INPUT_BUCKET_NAME: str = ""
    OUTPUT_BUCKET_NAME: str = ""
    OUTPUT_PREFIX: str = "reports"
    MAX_DECOMPRESSED_INPUT_BYTES: int = 1_048_576
    ALLOW_PRIVATE_OUTBOUND_ENDPOINTS: bool = False

    HTML_REPORT_ENABLED: bool = False
    RAG_ENABLED: bool = False
    RAG_BEDROCK_KB_ID: str = ""
    RAG_MAX_SNIPPETS: int = 4
    RAG_CONTEXT_BUDGET_CHARS: int = 1600
    RAG_FAILURE_MODE: str = "suppress"

    SPLUNK_BASE_URL: str = ""
    SPLUNK_API_TOKEN_SECRET_ARN: str = ""
    SPLUNK_API_TOKEN_SECRET_FIELD: str = "token"
    SPLUNK_NOTABLE_UPDATE_PATH: str = "/services/notable_update"
    SPLUNK_SINK_ENABLED: bool = False
    SPLUNK_REQUIRE_PAYLOAD_FINDING_ID: bool = False

    SPL_QUERY_GENERATION_ENABLED: bool = False
    SPL_QUERY_RAG_ENABLED: bool = False
    SPL_QUERY_RAG_BEDROCK_KB_ID: str = ""
    SPL_QUERY_RAG_MAX_SNIPPETS: int = 4
    SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS: int = 1600
    SPL_QUERY_RAG_FAILURE_MODE: str = "suppress"

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
    SPLUNK_SEARCH_ALLOWED_FIELDS: str = ""
    SPLUNK_SEARCH_DENIED_COMMANDS: str = (
        "delete,collect,outputlookup,sendemail,map,rest,script,dbxquery,inputlookup"
    )
    SPLUNK_SEARCH_MAX_TIME_RANGE: str = "24h"
    SPLUNK_SEARCH_MAX_ROWS: int = 100
    SPLUNK_SEARCH_TIMEOUT_SECONDS: int = 30
    SPLUNK_MCP_ENDPOINT: str = ""
    SPLUNK_MCP_AUTH_SECRET_ARN: str = ""
    SPLUNK_MCP_AUTH_SECRET_FIELD: str = "token"
    SPLUNK_MCP_HTTP_TIMEOUT_SECONDS: int = 35
    SPLUNK_MCP_TOOL_NAME: str = "splunk_search"

    ELASTIC_QUERY_GENERATION_ENABLED: bool = False
    ELASTICSEARCH_BASE_URL: str = ""
    ELASTICSEARCH_API_KEY_SECRET_ARN: str = ""
    ELASTICSEARCH_INDEX_ALLOWLIST: str = ""
    ELASTICSEARCH_ALLOW_WILDCARD_INDEXES: bool = False
    ELASTICSEARCH_TIMESTAMP_FIELD: str = "@timestamp"
    ELASTICSEARCH_ALLOWED_FIELDS: str = ""
    ELASTICSEARCH_GROUNDING_ENABLED: bool = False
    ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID: str = ""
    ELASTICSEARCH_GROUNDING_MAX_SNIPPETS: int = 4
    ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS: int = 1600
    ELASTICSEARCH_GROUNDING_FAILURE_MODE: str = "suppress"
    ELASTICSEARCH_MAX_TIME_RANGE: str = "24h"
    ELASTICSEARCH_MAX_ROWS: int = 100
    ELASTICSEARCH_TIMEOUT_SECONDS: int = 30

    SERVICENOW_DRAFT_ENABLED: bool = False
    SERVICENOW_CREATE_ENABLED: bool = False
    SERVICENOW_CREATE_REQUIRES_APPROVAL: bool = True
    SERVICENOW_BASE_URL: str = "https://your-instance.service-now.com"
    SERVICENOW_CREATE_PATH: str = "/api/now/table/incident"
    SERVICENOW_API_TOKEN_SECRET_ARN: str = ""
    SERVICENOW_APPROVAL_HMAC_SECRET_ARN: str = ""
    SERVICENOW_ASSIGNMENT_GROUP: str = ""
    SERVICENOW_TIMEOUT_SECONDS: int = 15

    SIDE_EFFECT_IDEMPOTENCY_ENABLED: bool = False
    SIDE_EFFECT_IDEMPOTENCY_TABLE: str = ""
    SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS: int = 30
    SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS: int = 900

    def __post_init__(self) -> None:
        profiles = _parse_capability_profiles(self.CAPABILITY_PROFILES)
        self.CAPABILITY_PROFILES = ",".join(profiles)
        profile_flags = _profile_flag_defaults(profiles)
        for name, value in profile_flags.items():
            setattr(self, name, value)
        self.SPLUNK_SINK_MODE = (self.SPLUNK_SINK_MODE or "s3").strip().lower()
        if self.SPLUNK_SINK_MODE not in {"s3", "notable_rest"}:
            raise ValueError("SPLUNK_SINK_MODE must be s3 or notable_rest")
        self.INVESTIGATION_QUERY_BACKEND = (
            self.INVESTIGATION_QUERY_BACKEND or "splunk"
        ).strip().lower()
        if self.INVESTIGATION_QUERY_BACKEND not in {"splunk", "elasticsearch"}:
            raise ValueError(
                "INVESTIGATION_QUERY_BACKEND must be splunk or elasticsearch"
            )
        self.INVESTIGATION_QUERY_EXECUTOR = (
            self.INVESTIGATION_QUERY_EXECUTOR or "rest"
        ).strip().lower()
        if self.INVESTIGATION_QUERY_EXECUTOR not in {"rest", "mcp"}:
            raise ValueError("INVESTIGATION_QUERY_EXECUTOR must be rest or mcp")
        if self.SPLUNK_SINK_MODE == "notable_rest" or (
            self.INVESTIGATION_QUERY_BACKEND == "splunk"
            and self.INVESTIGATION_QUERY_EXECUTION_ENABLED
        ):
            if self.SPLUNK_BASE_URL:
                self.SPLUNK_BASE_URL = validate_https_url(
                    self.SPLUNK_BASE_URL,
                    setting_name="SPLUNK_BASE_URL",
                    allow_private=self.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
                )
            elif self.SPLUNK_SINK_MODE == "notable_rest":
                raise ValueError("SPLUNK_BASE_URL is required when notable_rest sink is enabled")
        if self.SPLUNK_MCP_ENDPOINT:
            self.SPLUNK_MCP_ENDPOINT = validate_https_url(
                self.SPLUNK_MCP_ENDPOINT,
                setting_name="SPLUNK_MCP_ENDPOINT",
                allow_private=self.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
            )
        if (
            self.INVESTIGATION_QUERY_BACKEND == "elasticsearch"
            and self.INVESTIGATION_QUERY_EXECUTION_ENABLED
        ):
            self.ELASTICSEARCH_BASE_URL = validate_https_url(
                self.ELASTICSEARCH_BASE_URL,
                setting_name="ELASTICSEARCH_BASE_URL",
                allow_private=self.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
            )
            if not self.ELASTICSEARCH_INDEX_ALLOWLIST.strip():
                raise ValueError(
                    "ELASTICSEARCH_INDEX_ALLOWLIST is required when Elasticsearch execution is enabled"
                )
            if not self.ELASTICSEARCH_ALLOWED_FIELDS.strip():
                raise ValueError(
                    "ELASTICSEARCH_ALLOWED_FIELDS is required when Elasticsearch execution is enabled"
                )
        if self.SERVICENOW_CREATE_ENABLED:
            self.SERVICENOW_BASE_URL = validate_https_url(
                self.SERVICENOW_BASE_URL,
                setting_name="SERVICENOW_BASE_URL",
                allow_private=self.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
            )
            if self.SERVICENOW_CREATE_REQUIRES_APPROVAL and not self.SERVICENOW_APPROVAL_HMAC_SECRET_ARN:
                raise ValueError(
                    "SERVICENOW_APPROVAL_HMAC_SECRET_ARN is required when ServiceNow create requires approval"
                )


def load_config() -> Config:
    """Load runtime configuration from Lambda environment variables."""

    capability_profiles = _parse_capability_profiles(
        os.getenv("CAPABILITY_PROFILES", "core")
    )
    profile_flags = _profile_flag_defaults(capability_profiles)
    splunk_timeout = _positive_int_env("SPLUNK_SEARCH_TIMEOUT_SECONDS", 30, max_value=300)

    return Config(
        CAPABILITY_PROFILES=",".join(capability_profiles),
        BEDROCK_MODEL_ID=os.getenv("BEDROCK_MODEL_ID", ""),
        SPLUNK_SINK_MODE=os.getenv("SPLUNK_SINK_MODE", "s3"),
        INPUT_BUCKET_NAME=os.getenv("INPUT_BUCKET_NAME", ""),
        OUTPUT_BUCKET_NAME=os.getenv("OUTPUT_BUCKET_NAME", ""),
        OUTPUT_PREFIX=os.getenv("OUTPUT_PREFIX", "reports").strip() or "reports",
        MAX_DECOMPRESSED_INPUT_BYTES=_positive_int_env(
            "MAX_DECOMPRESSED_INPUT_BYTES", 1_048_576
        ),
        ALLOW_PRIVATE_OUTBOUND_ENDPOINTS=_bool_env("ALLOW_PRIVATE_OUTBOUND_ENDPOINTS", False),
        HTML_REPORT_ENABLED=_profile_bool("HTML_REPORT_ENABLED", False, profile_flags),
        RAG_ENABLED=_profile_bool("RAG_ENABLED", False, profile_flags),
        RAG_BEDROCK_KB_ID=os.getenv("RAG_BEDROCK_KB_ID", ""),
        RAG_MAX_SNIPPETS=_positive_int_env("RAG_MAX_SNIPPETS", 4, max_value=20),
        RAG_CONTEXT_BUDGET_CHARS=_positive_int_env(
            "RAG_CONTEXT_BUDGET_CHARS", 1600, max_value=10000
        ),
        RAG_FAILURE_MODE=(
            os.getenv("RAG_FAILURE_MODE", "suppress").strip().lower() or "suppress"
        ),
        SPLUNK_BASE_URL=os.getenv("SPLUNK_BASE_URL", ""),
        SPLUNK_API_TOKEN_SECRET_ARN=os.getenv("SPLUNK_API_TOKEN_SECRET_ARN", ""),
        SPLUNK_API_TOKEN_SECRET_FIELD=(
            os.getenv("SPLUNK_API_TOKEN_SECRET_FIELD", "token").strip() or "token"
        ),
        SPLUNK_NOTABLE_UPDATE_PATH=os.getenv(
            "SPLUNK_NOTABLE_UPDATE_PATH", "/services/notable_update"
        ),
        SPLUNK_SINK_ENABLED=_profile_bool(
            "SPLUNK_SINK_ENABLED", False, profile_flags
        ),
        SPLUNK_REQUIRE_PAYLOAD_FINDING_ID=_bool_env("SPLUNK_REQUIRE_PAYLOAD_FINDING_ID", False),
        SPL_QUERY_GENERATION_ENABLED=_profile_bool(
            "SPL_QUERY_GENERATION_ENABLED", False, profile_flags
        ),
        SPL_QUERY_RAG_ENABLED=_bool_env("SPL_QUERY_RAG_ENABLED", False),
        SPL_QUERY_RAG_BEDROCK_KB_ID=os.getenv("SPL_QUERY_RAG_BEDROCK_KB_ID", ""),
        SPL_QUERY_RAG_MAX_SNIPPETS=_positive_int_env(
            "SPL_QUERY_RAG_MAX_SNIPPETS", 4, max_value=20
        ),
        SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS=_positive_int_env(
            "SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS", 1600, max_value=10000
        ),
        SPL_QUERY_RAG_FAILURE_MODE=(
            os.getenv("SPL_QUERY_RAG_FAILURE_MODE", "suppress").strip().lower()
            or "suppress"
        ),
        INVESTIGATION_QUERY_EXECUTION_ENABLED=_profile_bool(
            "INVESTIGATION_QUERY_EXECUTION_ENABLED", False, profile_flags
        ),
        INVESTIGATION_QUERY_BACKEND=_profile_str(
            "INVESTIGATION_QUERY_BACKEND", "splunk", profile_flags
        ),
        INVESTIGATION_QUERY_EXECUTOR=os.getenv("INVESTIGATION_QUERY_EXECUTOR", "rest"),
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
        SPLUNK_SEARCH_ALLOWED_FIELDS=os.getenv("SPLUNK_SEARCH_ALLOWED_FIELDS", ""),
        SPLUNK_SEARCH_DENIED_COMMANDS=os.getenv(
            "SPLUNK_SEARCH_DENIED_COMMANDS",
            "delete,collect,outputlookup,sendemail,map,rest,script,dbxquery,inputlookup",
        ),
        SPLUNK_SEARCH_MAX_TIME_RANGE=os.getenv("SPLUNK_SEARCH_MAX_TIME_RANGE", "24h"),
        SPLUNK_SEARCH_MAX_ROWS=_positive_int_env(
            "SPLUNK_SEARCH_MAX_ROWS", 100, max_value=1000
        ),
        SPLUNK_SEARCH_TIMEOUT_SECONDS=splunk_timeout,
        SPLUNK_MCP_ENDPOINT=os.getenv("SPLUNK_MCP_ENDPOINT", ""),
        SPLUNK_MCP_AUTH_SECRET_ARN=os.getenv("SPLUNK_MCP_AUTH_SECRET_ARN", ""),
        SPLUNK_MCP_AUTH_SECRET_FIELD=(
            os.getenv("SPLUNK_MCP_AUTH_SECRET_FIELD", "token").strip() or "token"
        ),
        SPLUNK_MCP_HTTP_TIMEOUT_SECONDS=_positive_int_env(
            "SPLUNK_MCP_HTTP_TIMEOUT_SECONDS", splunk_timeout + 5, max_value=305
        ),
        SPLUNK_MCP_TOOL_NAME=os.getenv("SPLUNK_MCP_TOOL_NAME", "splunk_search"),
        ELASTIC_QUERY_GENERATION_ENABLED=_profile_bool(
            "ELASTIC_QUERY_GENERATION_ENABLED", False, profile_flags
        ),
        ELASTICSEARCH_BASE_URL=os.getenv("ELASTICSEARCH_BASE_URL", ""),
        ELASTICSEARCH_API_KEY_SECRET_ARN=os.getenv(
            "ELASTICSEARCH_API_KEY_SECRET_ARN", ""
        ),
        ELASTICSEARCH_INDEX_ALLOWLIST=os.getenv("ELASTICSEARCH_INDEX_ALLOWLIST", ""),
        ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=_bool_env(
            "ELASTICSEARCH_ALLOW_WILDCARD_INDEXES", False
        ),
        ELASTICSEARCH_TIMESTAMP_FIELD=(
            os.getenv("ELASTICSEARCH_TIMESTAMP_FIELD", "@timestamp").strip()
            or "@timestamp"
        ),
        ELASTICSEARCH_ALLOWED_FIELDS=os.getenv("ELASTICSEARCH_ALLOWED_FIELDS", ""),
        ELASTICSEARCH_GROUNDING_ENABLED=_bool_env(
            "ELASTICSEARCH_GROUNDING_ENABLED", False
        ),
        ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID=os.getenv(
            "ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID", ""
        ),
        ELASTICSEARCH_GROUNDING_MAX_SNIPPETS=_positive_int_env(
            "ELASTICSEARCH_GROUNDING_MAX_SNIPPETS", 4, max_value=20
        ),
        ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS=_positive_int_env(
            "ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS", 1600, max_value=10000
        ),
        ELASTICSEARCH_GROUNDING_FAILURE_MODE=(
            os.getenv("ELASTICSEARCH_GROUNDING_FAILURE_MODE", "suppress")
            .strip()
            .lower()
            or "suppress"
        ),
        ELASTICSEARCH_MAX_TIME_RANGE=os.getenv("ELASTICSEARCH_MAX_TIME_RANGE", "24h"),
        ELASTICSEARCH_MAX_ROWS=_positive_int_env(
            "ELASTICSEARCH_MAX_ROWS", 100, max_value=1000
        ),
        ELASTICSEARCH_TIMEOUT_SECONDS=_positive_int_env(
            "ELASTICSEARCH_TIMEOUT_SECONDS", 30, max_value=300
        ),
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
        SERVICENOW_API_TOKEN_SECRET_ARN=os.getenv(
            "SERVICENOW_API_TOKEN_SECRET_ARN", ""
        ),
        SERVICENOW_APPROVAL_HMAC_SECRET_ARN=os.getenv(
            "SERVICENOW_APPROVAL_HMAC_SECRET_ARN", ""
        ),
        SERVICENOW_ASSIGNMENT_GROUP=os.getenv("SERVICENOW_ASSIGNMENT_GROUP", ""),
        SERVICENOW_TIMEOUT_SECONDS=_positive_int_env(
            "SERVICENOW_TIMEOUT_SECONDS", 15, max_value=300
        ),
        SIDE_EFFECT_IDEMPOTENCY_ENABLED=_profile_bool(
            "SIDE_EFFECT_IDEMPOTENCY_ENABLED", False, profile_flags
        ),
        SIDE_EFFECT_IDEMPOTENCY_TABLE=os.getenv("SIDE_EFFECT_IDEMPOTENCY_TABLE", ""),
        SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS=_positive_int_env(
            "SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS", 30, max_value=3650
        ),
        SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS=_positive_int_env(
            "SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS", 900, max_value=86400
        ),
    )
