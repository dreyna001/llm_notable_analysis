"""Structured logging helpers for SDK events."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


def get_sdk_logger(name: str = "onprem_llm_sdk") -> logging.Logger:
    """Return SDK logger configured with a NullHandler when needed.

    Args:
        name: Logger name.

    Returns:
        Logger instance.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Emit one JSON log line for easier ingestion and filtering.

    Args:
        logger: Logger used to emit the event.
        level: Logging level constant.
        event: Event name.
        **fields: Additional structured fields to include in output.
    """
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    logger.log(level, json.dumps(payload, separators=(",", ":"), sort_keys=True))
