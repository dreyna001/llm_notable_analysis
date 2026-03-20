"""Structured logging helpers for SDK events."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


def get_sdk_logger(name: str = "onprem_llm_sdk") -> logging.Logger:
    """Return SDK logger with a null handler by default."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Emit one JSON log line for easier ingestion and filtering."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    logger.log(level, json.dumps(payload, separators=(",", ":"), sort_keys=True))

