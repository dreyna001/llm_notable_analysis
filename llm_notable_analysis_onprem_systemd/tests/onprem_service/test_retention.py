import os
import tempfile
import time
import unittest
from pathlib import Path

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.retention import run_retention


class TestRetention(unittest.TestCase):
    def test_run_retention_prunes_old_idempotency_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            idempotency_dir = root / "idempotency"
            idempotency_dir.mkdir()
            old_marker = idempotency_dir / "old.json"
            new_marker = idempotency_dir / "new.json"
            old_marker.write_text("{}", encoding="utf-8")
            new_marker.write_text("{}", encoding="utf-8")
            now = time.time()
            os.utime(old_marker, (now - 3 * 86400, now - 3 * 86400))
            os.utime(new_marker, (now, now))

            config = Config(
                PROCESSED_DIR=root / "processed",
                QUARANTINE_DIR=root / "quarantine",
                REPORT_DIR=root / "reports",
                ARCHIVE_DIR=root / "archive",
                SIDE_EFFECT_IDEMPOTENCY_DIR=idempotency_dir,
                SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS=2,
            )
            stats = run_retention(config)

            self.assertEqual(stats.deleted, 1)
            self.assertFalse(old_marker.exists())
            self.assertTrue(new_marker.exists())


if __name__ == "__main__":
    unittest.main()
