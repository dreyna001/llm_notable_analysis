"""Environment-driven SDK configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

from .errors import ConfigError


def _get_env(key: str, default: str) -> str:
    value = os.getenv(key)
    return default if value is None else value


def _parse_int(raw: str, *, key: str, minimum: int) -> int:
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc
    if parsed < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {parsed}")
    return parsed


def _parse_float(raw: str, *, key: str, minimum: float) -> float:
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc
    if parsed < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {parsed}")
    return parsed


def _parse_bool(raw: str, *, key: str) -> bool:
    norm = raw.strip().lower()
    if norm in {"1", "true", "yes", "on"}:
        return True
    if norm in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} must be a boolean string, got {raw!r}")


@dataclass(frozen=True)
class SDKConfig:
    """Runtime contract for SDK behavior and endpoint usage."""

    llm_api_url: str = "http://127.0.0.1:8000/v1/completions"
    llm_model_name: str = "gpt-oss-20b"
    llm_api_token: str = ""
    llm_app_name: str = "unknown-app"
    llm_max_tokens_default: int = 2048
    llm_connect_timeout_sec: float = 5.0
    llm_read_timeout_sec: float = 120.0
    llm_max_retries: int = 3
    llm_retry_backoff_sec: float = 1.0
    llm_max_inflight: int = 2
    llm_verify_tls: bool = True

    @classmethod
    def from_env(cls, *, overrides: Optional[Mapping[str, Any]] = None) -> "SDKConfig":
        """Load config from environment, then apply explicit overrides."""
        cfg = cls(
            llm_api_url=_get_env("LLM_API_URL", cls.llm_api_url),
            llm_model_name=_get_env("LLM_MODEL_NAME", cls.llm_model_name),
            llm_api_token=_get_env("LLM_API_TOKEN", cls.llm_api_token),
            llm_app_name=_get_env("LLM_APP_NAME", cls.llm_app_name),
            llm_max_tokens_default=_parse_int(
                _get_env("LLM_MAX_TOKENS_DEFAULT", str(cls.llm_max_tokens_default)),
                key="LLM_MAX_TOKENS_DEFAULT",
                minimum=1,
            ),
            llm_connect_timeout_sec=_parse_float(
                _get_env("LLM_CONNECT_TIMEOUT_SEC", str(cls.llm_connect_timeout_sec)),
                key="LLM_CONNECT_TIMEOUT_SEC",
                minimum=0.1,
            ),
            llm_read_timeout_sec=_parse_float(
                _get_env("LLM_READ_TIMEOUT_SEC", str(cls.llm_read_timeout_sec)),
                key="LLM_READ_TIMEOUT_SEC",
                minimum=0.1,
            ),
            llm_max_retries=_parse_int(
                _get_env("LLM_MAX_RETRIES", str(cls.llm_max_retries)),
                key="LLM_MAX_RETRIES",
                minimum=0,
            ),
            llm_retry_backoff_sec=_parse_float(
                _get_env("LLM_RETRY_BACKOFF_SEC", str(cls.llm_retry_backoff_sec)),
                key="LLM_RETRY_BACKOFF_SEC",
                minimum=0.0,
            ),
            llm_max_inflight=_parse_int(
                _get_env("LLM_MAX_INFLIGHT", str(cls.llm_max_inflight)),
                key="LLM_MAX_INFLIGHT",
                minimum=1,
            ),
            llm_verify_tls=_parse_bool(
                _get_env("LLM_VERIFY_TLS", "true"),
                key="LLM_VERIFY_TLS",
            ),
        )
        cfg = cfg._validate()

        if not overrides:
            return cfg

        sanitized: dict[str, Any] = {}
        for key, value in overrides.items():
            if not hasattr(cfg, key):
                raise ConfigError(f"Unknown override key: {key}")
            sanitized[key] = value
        return replace(cfg, **sanitized)._validate()

    def _validate(self) -> "SDKConfig":
        if not self.llm_api_url:
            raise ConfigError("LLM_API_URL must not be empty")
        if not self.llm_model_name:
            raise ConfigError("LLM_MODEL_NAME must not be empty")
        if not self.llm_app_name:
            raise ConfigError("LLM_APP_NAME must not be empty")
        if self.llm_max_tokens_default <= 0:
            raise ConfigError("LLM_MAX_TOKENS_DEFAULT must be > 0")
        if self.llm_max_inflight <= 0:
            raise ConfigError("LLM_MAX_INFLIGHT must be > 0")
        return self

