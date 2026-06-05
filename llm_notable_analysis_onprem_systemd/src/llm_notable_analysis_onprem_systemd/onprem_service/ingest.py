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


class NotableReadError(Exception):
    """Incoming notable could not be read (I/O failure or size limit)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _is_relative_to(path: Path, root: Path) -> bool:
    """Return whether path is under root after resolution."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_incoming_path(file_path: Path, *, root: Path | None = None) -> None:
    """Reject symlinks and paths that escape the incoming directory."""
    if file_path.is_symlink():
        raise NotableReadError("symlinked notable files are not supported")
    if root is None:
        return
    try:
        root_resolved = root.resolve(strict=True)
        resolved = file_path.resolve(strict=True)
    except OSError as exc:
        raise NotableReadError(f"cannot resolve notable file: {exc}") from exc
    if not _is_relative_to(resolved, root_resolved):
        raise NotableReadError("notable file must remain under INCOMING_DIR")


def read_notable_text(
    file_path: Path,
    max_bytes: int,
    *,
    root: Path | None = None,
) -> str:
    """Read a notable file as UTF-8 after verifying on-disk size.

    Uses :func:`Path.stat` before :meth:`Path.read_text` so arbitrarily large
    files are not fully loaded into memory.

    Args:
        file_path: Path to the incoming notable.
        max_bytes: Maximum allowed file size in bytes (``MAX_INPUT_FILE_BYTES``).

    Returns:
        File contents decoded as UTF-8.

    Raises:
        NotableReadError: If the file cannot be stat'd, exceeds ``max_bytes``,
            or cannot be read.
    """
    _validate_incoming_path(file_path, root=root)
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise NotableReadError(f"cannot stat notable file: {exc}") from exc
    if size > max_bytes:
        raise NotableReadError(
            f"file size {size} bytes exceeds MAX_INPUT_FILE_BYTES ({max_bytes})"
        )
    try:
        return file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotableReadError(f"cannot read notable file: {exc}") from exc


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
        logger.warning("INCOMING_DIR does not exist: %s", incoming)
        return []

    candidates = list(incoming.glob("*.json")) + list(incoming.glob("*.txt"))
    files: list[Path] = []
    for candidate in candidates:
        try:
            _validate_incoming_path(candidate, root=incoming)
            if not candidate.is_file():
                continue
        except NotableReadError as exc:
            logger.warning("Skipping unsafe incoming file %s: %s", candidate.name, exc)
            continue
        files.append(candidate)
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
    logger.info("Moved processed file to %s", dest)
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
    if reason:
        logger.warning("Quarantined file to %s: %s", dest, reason)
    else:
        logger.warning("Quarantined file to %s", dest)
    return dest
