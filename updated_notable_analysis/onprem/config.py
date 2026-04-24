"""On-prem runtime configuration models for the thin deployment wrapper."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

from updated_notable_analysis.core.validators import (
    normalize_optional_string,
    require_int_gt_zero,
    require_non_empty_string,
)

DEFAULT_INCOMING_DIR = "/var/notables/incoming"
DEFAULT_PROCESSED_DIR = "/var/notables/processed"
DEFAULT_QUARANTINE_DIR = "/var/notables/quarantine"
DEFAULT_REPORT_OUTPUT_DIR = "/var/notables/reports"
DEFAULT_ADVISORY_CONTEXT_DIR = None
DEFAULT_LITELLM_BASE_URL = "http://127.0.0.1:4000"
DEFAULT_LITELLM_READINESS_PATH = "/v1/models"
DEFAULT_LITELLM_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
DEFAULT_LITELLM_MODEL_NAME = "gemma-4-31B-it"
DEFAULT_READINESS_TIMEOUT_SECONDS = 2
DEFAULT_LITELLM_REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_WORKER_IDLE_SLEEP_SECONDS = 5
DEFAULT_WORKER_MAX_FILES_PER_POLL = 10
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _require_env_string(env: Mapping[str, str], key: str) -> str:
    """Return one required environment value as a validated non-empty string."""
    if key not in env:
        raise ValueError(f"Environment variable {key!r} is required.")
    return require_non_empty_string(env.get(key), key)


def _optional_env_int_gt_zero(env: Mapping[str, str], key: str, default: int) -> int:
    """Parse an optional positive integer environment value."""
    raw_value = env.get(key)
    if raw_value is None:
        return default
    try:
        parsed_value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Environment variable {key!r} must be an integer greater than zero.") from exc
    return require_int_gt_zero(parsed_value, key)


def _normalize_loopback_base_url(value: str) -> str:
    """Validate and normalize the analyzer-facing LiteLLM base URL."""
    normalized = require_non_empty_string(value, "litellm_base_url").rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Field 'litellm_base_url' must be an absolute HTTP(S) URL.")
    if parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError("Field 'litellm_base_url' must target a loopback host.")
    return normalized


def _normalize_readiness_path(value: str) -> str:
    """Validate and normalize a LiteLLM request path."""
    normalized = require_non_empty_string(value, "litellm path")
    if not normalized.startswith("/"):
        raise ValueError("LiteLLM paths must start with '/'.")
    return normalized


@dataclass(slots=True, kw_only=True)
class OnPremRuntimeConfig:
    """Normalized runtime config contract for the on-prem wrapper.

    Attributes:
        incoming_dir: Directory scanned for inbound JSON payload files.
        processed_dir: Directory that stores successfully processed input files.
        quarantine_dir: Directory that stores invalid or failed input files.
        report_output_dir: Directory for report JSON output files.
        default_profile_name: Optional default capability profile.
        default_customer_bundle_name: Optional default customer bundle.
        advisory_context_dir: Optional directory containing local advisory context JSON files.
        litellm_base_url: Analyzer-facing local LiteLLM base URL.
        litellm_readiness_path: LiteLLM readiness probe path.
        litellm_chat_completions_path: LiteLLM chat-completions path.
        litellm_model_name: Analyzer-facing LiteLLM model name.
        readiness_timeout_seconds: Timeout for local readiness checks.
        litellm_request_timeout_seconds: Timeout for LiteLLM chat-completion requests.
        worker_idle_sleep_seconds: Bounded sleep interval when no files are available.
        worker_max_files_per_poll: Maximum files processed in one worker poll.
    """

    incoming_dir: str = DEFAULT_INCOMING_DIR
    processed_dir: str = DEFAULT_PROCESSED_DIR
    quarantine_dir: str = DEFAULT_QUARANTINE_DIR
    report_output_dir: str = DEFAULT_REPORT_OUTPUT_DIR
    default_profile_name: str | None = None
    default_customer_bundle_name: str | None = None
    advisory_context_dir: str | None = DEFAULT_ADVISORY_CONTEXT_DIR
    litellm_base_url: str = DEFAULT_LITELLM_BASE_URL
    litellm_readiness_path: str = DEFAULT_LITELLM_READINESS_PATH
    litellm_chat_completions_path: str = DEFAULT_LITELLM_CHAT_COMPLETIONS_PATH
    litellm_model_name: str = DEFAULT_LITELLM_MODEL_NAME
    readiness_timeout_seconds: int = DEFAULT_READINESS_TIMEOUT_SECONDS
    litellm_request_timeout_seconds: int = DEFAULT_LITELLM_REQUEST_TIMEOUT_SECONDS
    worker_idle_sleep_seconds: int = DEFAULT_WORKER_IDLE_SLEEP_SECONDS
    worker_max_files_per_poll: int = DEFAULT_WORKER_MAX_FILES_PER_POLL

    def __post_init__(self) -> None:
        """Validate and normalize on-prem wrapper config fields."""
        self.incoming_dir = require_non_empty_string(self.incoming_dir, "incoming_dir")
        self.processed_dir = require_non_empty_string(self.processed_dir, "processed_dir")
        self.quarantine_dir = require_non_empty_string(self.quarantine_dir, "quarantine_dir")
        self.report_output_dir = require_non_empty_string(
            self.report_output_dir,
            "report_output_dir",
        )
        self.default_profile_name = normalize_optional_string(
            self.default_profile_name,
            "default_profile_name",
        )
        self.default_customer_bundle_name = normalize_optional_string(
            self.default_customer_bundle_name,
            "default_customer_bundle_name",
        )
        self.advisory_context_dir = normalize_optional_string(
            self.advisory_context_dir,
            "advisory_context_dir",
        )
        self.litellm_base_url = _normalize_loopback_base_url(self.litellm_base_url)
        self.litellm_readiness_path = _normalize_readiness_path(self.litellm_readiness_path)
        self.litellm_chat_completions_path = _normalize_readiness_path(
            self.litellm_chat_completions_path
        )
        self.litellm_model_name = require_non_empty_string(
            self.litellm_model_name, "litellm_model_name"
        )
        self.readiness_timeout_seconds = require_int_gt_zero(
            self.readiness_timeout_seconds,
            "readiness_timeout_seconds",
        )
        self.litellm_request_timeout_seconds = require_int_gt_zero(
            self.litellm_request_timeout_seconds,
            "litellm_request_timeout_seconds",
        )
        self.worker_idle_sleep_seconds = require_int_gt_zero(
            self.worker_idle_sleep_seconds,
            "worker_idle_sleep_seconds",
        )
        self.worker_max_files_per_poll = require_int_gt_zero(
            self.worker_max_files_per_poll,
            "worker_max_files_per_poll",
        )

    @property
    def litellm_readiness_url(self) -> str:
        """Return the full local LiteLLM readiness URL."""
        return f"{self.litellm_base_url}{self.litellm_readiness_path}"

    @property
    def litellm_chat_completions_url(self) -> str:
        """Return the full local LiteLLM chat-completions URL."""
        return f"{self.litellm_base_url}{self.litellm_chat_completions_path}"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "OnPremRuntimeConfig":
        """Build config from environment variables.

        Args:
            environ: Optional mapping for deterministic tests. Defaults to `os.environ`.

        Returns:
            OnPremRuntimeConfig: Validated configuration.
        """

        env = os.environ if environ is None else environ
        return cls(
            incoming_dir=_require_env_string(
                env,
                "UPDATED_NOTABLE_ONPREM_INCOMING_DIR",
            ),
            processed_dir=_require_env_string(
                env,
                "UPDATED_NOTABLE_ONPREM_PROCESSED_DIR",
            ),
            quarantine_dir=_require_env_string(
                env,
                "UPDATED_NOTABLE_ONPREM_QUARANTINE_DIR",
            ),
            report_output_dir=_require_env_string(
                env,
                "UPDATED_NOTABLE_ONPREM_REPORT_OUTPUT_DIR",
            ),
            default_profile_name=env.get("UPDATED_NOTABLE_ONPREM_DEFAULT_PROFILE_NAME"),
            default_customer_bundle_name=env.get(
                "UPDATED_NOTABLE_ONPREM_DEFAULT_CUSTOMER_BUNDLE_NAME",
            ),
            advisory_context_dir=env.get("UPDATED_NOTABLE_ONPREM_ADVISORY_CONTEXT_DIR"),
            litellm_base_url=env.get(
                "UPDATED_NOTABLE_ONPREM_LITELLM_BASE_URL",
                DEFAULT_LITELLM_BASE_URL,
            ),
            litellm_readiness_path=env.get(
                "UPDATED_NOTABLE_ONPREM_LITELLM_READINESS_PATH",
                DEFAULT_LITELLM_READINESS_PATH,
            ),
            litellm_chat_completions_path=env.get(
                "UPDATED_NOTABLE_ONPREM_LITELLM_CHAT_COMPLETIONS_PATH",
                DEFAULT_LITELLM_CHAT_COMPLETIONS_PATH,
            ),
            litellm_model_name=env.get(
                "UPDATED_NOTABLE_ONPREM_LITELLM_MODEL_NAME",
                DEFAULT_LITELLM_MODEL_NAME,
            ),
            readiness_timeout_seconds=_optional_env_int_gt_zero(
                env,
                "UPDATED_NOTABLE_ONPREM_READINESS_TIMEOUT_SECONDS",
                DEFAULT_READINESS_TIMEOUT_SECONDS,
            ),
            litellm_request_timeout_seconds=_optional_env_int_gt_zero(
                env,
                "UPDATED_NOTABLE_ONPREM_LITELLM_REQUEST_TIMEOUT_SECONDS",
                DEFAULT_LITELLM_REQUEST_TIMEOUT_SECONDS,
            ),
            worker_idle_sleep_seconds=_optional_env_int_gt_zero(
                env,
                "UPDATED_NOTABLE_ONPREM_WORKER_IDLE_SLEEP_SECONDS",
                DEFAULT_WORKER_IDLE_SLEEP_SECONDS,
            ),
            worker_max_files_per_poll=_optional_env_int_gt_zero(
                env,
                "UPDATED_NOTABLE_ONPREM_WORKER_MAX_FILES_PER_POLL",
                DEFAULT_WORKER_MAX_FILES_PER_POLL,
            ),
        )
