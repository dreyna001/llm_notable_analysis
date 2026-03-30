"""File-drop ingestion for on-prem notable analysis service.

Handles discovery, normalization, ID extraction, and atomic file movement
for the file_drop ingest mode.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Any, List, Optional

from .config import Config

logger = logging.getLogger(__name__)


def discover_files(config: Config) -> List[Path]:
    """Discover unprocessed notable files in INCOMING_DIR.

    Looks for .json and .txt files. Does not recurse into subdirectories.

    Args:
        config: Service configuration.

    Returns:
        List of file paths to process (sorted by modification time, oldest first).
    """
    incoming = config.INCOMING_DIR
    if not incoming.exists():
        logger.warning(f"INCOMING_DIR does not exist: {incoming}")
        return []

    files = list(incoming.glob("*.json")) + list(incoming.glob("*.txt"))
    # Sort by modification time (oldest first for FIFO processing)
    files.sort(key=lambda f: f.stat().st_mtime)
    return files


def normalize_notable(content: str, content_type: str = "text") -> Any:
    """Normalize notable content into a format-agnostic alert payload.

    Args:
        content: Raw content from file (JSON string or plain text).
        content_type: Type hint for content ('json' or 'text').

    Returns:
        Parsed JSON object for JSON alerts when valid; otherwise raw text.
    """
    stripped = (content or "").strip()
    if content_type == "json" or stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse content as JSON, treating as raw text")
    return content


def get_notable_id(alert_payload: Any, file_path: Path) -> str:
    """Extract or generate a report identifier for output file naming.

    Args:
        alert_payload: Parsed alert object or raw text.
        file_path: Original file path (used as primary identifier source).

    Returns:
        Sanitized identifier string (safe for filenames).
    """
    # Priority agreed for format-agnostic input path:
    # 1) filename stem
    # 2) common alert keys when the filename stem is unusable
    raw_id = file_path.stem
    if not raw_id and isinstance(alert_payload, dict):
        raw_id = (
            alert_payload.get("notable_id")
            or alert_payload.get("event_id")
            or str(alert_payload.get("search_name", ""))[:50].replace(" ", "_")
        )

    # Sanitize for filename safety (no path traversal, no special chars)
    sanitized = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(raw_id))
    return sanitized[:100] or "unknown"


def move_to_processed(file_path: Path, config: Config) -> Path:
    """Move a successfully processed file to PROCESSED_DIR.

    Args:
        file_path: Original file path.
        config: Service configuration.

    Returns:
        New path in PROCESSED_DIR.
    """
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.PROCESSED_DIR / file_path.name
    # Handle collision by appending suffix
    if dest.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1
        while dest.exists():
            dest = config.PROCESSED_DIR / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.move(str(file_path), str(dest))
    logger.info(f"Moved processed file to {dest}")
    return dest


def move_to_quarantine(
    file_path: Path, config: Config, reason: Optional[str] = None
) -> Path:
    """Move a failed file to QUARANTINE_DIR.

    Args:
        file_path: Original file path.
        config: Service configuration.
        reason: Optional reason for quarantine (logged).

    Returns:
        New path in QUARANTINE_DIR.
    """
    config.QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.QUARANTINE_DIR / file_path.name
    # Handle collision
    if dest.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1
        while dest.exists():
            dest = config.QUARANTINE_DIR / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.move(str(file_path), str(dest))
    logger.warning(f"Quarantined file to {dest}" + (f": {reason}" if reason else ""))
    return dest
