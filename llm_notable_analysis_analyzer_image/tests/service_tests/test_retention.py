"""Behavior tests for retention move/delete workflows."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onprem_service.config import Config
from onprem_service.retention import delete_older_than_days
from onprem_service.retention import move_older_than_days
from onprem_service.retention import run_retention


def _write_file(path: Path, contents: str, mtime: float) -> None:
    """Creates a file and sets deterministic mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    os.utime(path, (mtime, mtime))


class TestRetention(unittest.TestCase):
    """Validate retention behavior for move/archive/delete stages."""

    def test_move_older_than_days_moves_only_old_files(self) -> None:
        """Moves old files, keeps new files, and resets archived mtime."""
        now = 1_000_000.0
        old_mtime = now - (3 * 86400)
        new_mtime = now - 300

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src"
            dst = root / "dst"
            old_file = src / "old.log"
            new_file = src / "new.log"
            _write_file(old_file, "old", old_mtime)
            _write_file(new_file, "new", new_mtime)

            stats = move_older_than_days(
                src,
                dst,
                days=2,
                now_epoch_seconds=now,
                reset_mtime_on_archive=True,
            )

            moved_path = dst / "old.log"
            self.assertEqual(stats.moved, 1)
            self.assertEqual(stats.deleted, 0)
            self.assertEqual(stats.errors, 0)
            self.assertTrue(moved_path.exists())
            self.assertTrue(new_file.exists())
            self.assertEqual(int(moved_path.stat().st_mtime), int(now))

    def test_move_older_than_days_uses_unique_destination_name(self) -> None:
        """Appends numeric suffix when archived filename already exists."""
        now = 2_000_000.0
        old_mtime = now - (5 * 86400)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src"
            dst = root / "dst"
            _write_file(src / "duplicate.txt", "new", old_mtime)
            _write_file(dst / "duplicate.txt", "existing", now)

            stats = move_older_than_days(src, dst, days=2, now_epoch_seconds=now)

            self.assertEqual(stats.moved, 1)
            self.assertTrue((dst / "duplicate_1.txt").exists())

    def test_delete_older_than_days_deletes_only_old_files(self) -> None:
        """Deletes files older than threshold and keeps recent files."""
        now = 3_000_000.0
        old_mtime = now - (10 * 86400)
        new_mtime = now - 60

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "archive"
            old_file = target / "old.md"
            new_file = target / "new.md"
            _write_file(old_file, "old", old_mtime)
            _write_file(new_file, "new", new_mtime)

            stats = delete_older_than_days(target, days=7, now_epoch_seconds=now)

            self.assertEqual(stats.moved, 0)
            self.assertEqual(stats.deleted, 1)
            self.assertEqual(stats.errors, 0)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())

    def test_run_retention_aggregates_stage_counts(self) -> None:
        """Aggregates stage-one moves and stage-two archive deletes."""
        now = 4_000_000.0
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "processed"
            quarantine = root / "quarantine"
            reports = root / "reports"
            archive = root / "archive"

            _write_file(processed / "p.log", "p", now - (3 * 86400))
            _write_file(quarantine / "q.log", "q", now - (3 * 86400))
            _write_file(reports / "r.md", "r", now - (8 * 86400))
            _write_file(archive / "processed" / "old.log", "x", now - (15 * 86400))

            config = Config(
                PROCESSED_DIR=processed,
                QUARANTINE_DIR=quarantine,
                REPORT_DIR=reports,
                ARCHIVE_DIR=archive,
                INPUT_RETENTION_DAYS=2,
                REPORT_RETENTION_DAYS=7,
                ARCHIVE_RETENTION_DAYS=14,
            )
            with patch("onprem_service.retention.time.time", return_value=now):
                stats = run_retention(config)

            self.assertEqual(stats.moved, 3)
            self.assertEqual(stats.deleted, 1)
            self.assertEqual(stats.errors, 0)
            self.assertTrue((archive / "processed" / "p.log").exists())
            self.assertTrue((archive / "quarantine" / "q.log").exists())
            self.assertTrue((archive / "reports" / "r.md").exists())
            self.assertFalse((archive / "processed" / "old.log").exists())


if __name__ == "__main__":
    unittest.main()
