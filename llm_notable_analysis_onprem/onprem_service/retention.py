"""Retention housekeeping for on-prem notable analysis service.

Implements two-stage retention:
1) Move old files from processed/quarantine/reports into an archive tree.
2) Delete files from archive after N days in archive.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from .config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionStats:
    moved: int = 0
    deleted: int = 0
    errors: int = 0


def _iter_files(directory: Path) -> Iterable[Path]:
    """Iterate over files in a directory (non-recursive).
    
    Args:
        directory: Directory path to scan.
        
    Returns:
        Iterable of file paths. Empty if directory doesn't exist.
    """
    if not directory.exists():
        return []
    return [p for p in directory.iterdir() if p.is_file()]


def _is_older_than(path: Path, cutoff_epoch_seconds: float) -> bool:
    """Check if a file's mtime is older than the cutoff.
    
    Args:
        path: File path to check.
        cutoff_epoch_seconds: Epoch timestamp cutoff.
        
    Returns:
        True if file mtime is older than cutoff, False otherwise.
    """
    try:
        return path.stat().st_mtime < cutoff_epoch_seconds
    except OSError:
        return False


def _unique_dest_path(dest_dir: Path, filename: str) -> Path:
    """Generate a unique destination path, appending suffix if collision.
    
    Args:
        dest_dir: Destination directory.
        filename: Original filename.
        
    Returns:
        Unique path in dest_dir (creates dir if needed).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def move_older_than_days(
    src_dir: Path,
    dest_dir: Path,
    days: int,
    *,
    reset_mtime_on_archive: bool = True,
    now_epoch_seconds: Optional[float] = None,
) -> RetentionStats:
    """Move files older than N days from src_dir to dest_dir.

    If reset_mtime_on_archive is True, the moved file's mtime is set to "now"
    so archive retention represents "time spent in archive", not "time since creation".
    
    Args:
        src_dir: Source directory to scan.
        dest_dir: Destination directory for archived files.
        days: Age threshold in days.
        reset_mtime_on_archive: If True, reset mtime to now after move.
        now_epoch_seconds: Current time (for testing); defaults to time.time().
        
    Returns:
        RetentionStats with counts of moved/deleted/errors.
    """
    if now_epoch_seconds is None:
        now_epoch_seconds = time.time()
    cutoff = now_epoch_seconds - (days * 86400)
    moved = deleted = errors = 0

    if days <= 0:
        return RetentionStats()

    for p in _iter_files(src_dir):
        if not _is_older_than(p, cutoff):
            continue
        try:
            dest = _unique_dest_path(dest_dir, p.name)
            shutil.move(str(p), str(dest))
            moved += 1
            if reset_mtime_on_archive:
                try:
                    os.utime(dest, (now_epoch_seconds, now_epoch_seconds))
                except OSError:
                    # Non-fatal; archive delete will fallback to original mtime
                    errors += 1
        except OSError:
            errors += 1

    return RetentionStats(moved=moved, deleted=deleted, errors=errors)


def delete_older_than_days(
    target_dir: Path,
    days: int,
    *,
    now_epoch_seconds: Optional[float] = None,
) -> RetentionStats:
    """Delete files older than N days from target_dir.
    
    Args:
        target_dir: Directory to scan for old files.
        days: Age threshold in days.
        now_epoch_seconds: Current time (for testing); defaults to time.time().
        
    Returns:
        RetentionStats with counts of moved/deleted/errors.
    """
    if now_epoch_seconds is None:
        now_epoch_seconds = time.time()
    cutoff = now_epoch_seconds - (days * 86400)
    moved = deleted = errors = 0

    if days <= 0:
        return RetentionStats()

    for p in _iter_files(target_dir):
        if not _is_older_than(p, cutoff):
            continue
        try:
            p.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            errors += 1

    return RetentionStats(moved=moved, deleted=deleted, errors=errors)


def run_retention(config: Config) -> RetentionStats:
    """Run retention housekeeping for processed/quarantine/reports + archive delete.
    
    Stage 1: Move old files from live dirs to archive subdirs.
    Stage 2: Delete files from archive after additional retention window.
    
    Args:
        config: Service configuration with retention settings.
        
    Returns:
        RetentionStats with aggregate counts across all operations.
    """
    now = time.time()
    total_moved = total_deleted = total_errors = 0

    # Archive destinations (flat files; keep simple)
    archive_processed = config.ARCHIVE_DIR / "processed"
    archive_quarantine = config.ARCHIVE_DIR / "quarantine"
    archive_reports = config.ARCHIVE_DIR / "reports"

    # Stage 1: move into archive
    s1a = move_older_than_days(config.PROCESSED_DIR, archive_processed, config.INPUT_RETENTION_DAYS, now_epoch_seconds=now)
    s1b = move_older_than_days(config.QUARANTINE_DIR, archive_quarantine, config.INPUT_RETENTION_DAYS, now_epoch_seconds=now)
    s1c = move_older_than_days(config.REPORT_DIR, archive_reports, config.REPORT_RETENTION_DAYS, now_epoch_seconds=now)

    # Stage 2: delete from archive after days-in-archive
    s2a = delete_older_than_days(archive_processed, config.ARCHIVE_RETENTION_DAYS, now_epoch_seconds=now)
    s2b = delete_older_than_days(archive_quarantine, config.ARCHIVE_RETENTION_DAYS, now_epoch_seconds=now)
    s2c = delete_older_than_days(archive_reports, config.ARCHIVE_RETENTION_DAYS, now_epoch_seconds=now)

    for s in (s1a, s1b, s1c, s2a, s2b, s2c):
        total_moved += s.moved
        total_deleted += s.deleted
        total_errors += s.errors

    return RetentionStats(moved=total_moved, deleted=total_deleted, errors=total_errors)


