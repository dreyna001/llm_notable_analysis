"""Behavior tests for configuration loading and file-drop ingestion."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onprem_service.config import Config
from onprem_service.config import load_config
from onprem_service.ingest import discover_files
from onprem_service.ingest import get_notable_id
from onprem_service.ingest import move_to_processed
from onprem_service.ingest import move_to_quarantine
from onprem_service.ingest import normalize_notable


class TestConfigLoad(unittest.TestCase):
    """Verify environment-to-config contract behavior."""

    def test_load_config_uses_expected_defaults(self) -> None:
        """Loads default values when env keys are not provided."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()

        self.assertEqual(config.INGEST_MODE, "file_drop")
        self.assertEqual(config.LLM_MODEL_NAME, "gpt-oss-120b")
        self.assertEqual(config.LLM_TIMEOUT, 420)
        self.assertFalse(config.RAG_ENABLED)
        self.assertFalse(config.SPLUNK_SINK_ENABLED)
        self.assertFalse(config.CONCURRENCY_ENABLED)
        self.assertEqual(config.MAX_WORKERS, 1)
        self.assertEqual(config.MAX_QUEUE_DEPTH, 8)

    def test_load_config_parses_bool_int_and_path_overrides(self) -> None:
        """Parses booleans, integers, and paths from environment strings."""
        env = {
            "RAG_ENABLED": "YES",
            "SPLUNK_SINK_ENABLED": "1",
            "CONCURRENCY_ENABLED": "true",
            "POLL_INTERVAL": "11",
            "LLM_TIMEOUT": "777",
            "MAX_WORKERS": "4",
            "MAX_QUEUE_DEPTH": "33",
            "MITRE_IDS_PATH": "/tmp/custom_ids.json",
            "LLM_MODEL_NAME": "custom-model",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertTrue(config.RAG_ENABLED)
        self.assertTrue(config.SPLUNK_SINK_ENABLED)
        self.assertTrue(config.CONCURRENCY_ENABLED)
        self.assertEqual(config.POLL_INTERVAL, 11)
        self.assertEqual(config.LLM_TIMEOUT, 777)
        self.assertEqual(config.MAX_WORKERS, 4)
        self.assertEqual(config.MAX_QUEUE_DEPTH, 33)
        self.assertEqual(config.MITRE_IDS_PATH, Path("/tmp/custom_ids.json"))
        self.assertEqual(config.LLM_MODEL_NAME, "custom-model")


class TestIngestHelpers(unittest.TestCase):
    """Verify ingestion helpers with deterministic filesystem fixtures."""

    def test_discover_files_returns_fifo_for_supported_extensions(self) -> None:
        """Finds only ``.json``/``.txt`` and returns oldest-first ordering."""
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            incoming.mkdir(parents=True, exist_ok=True)
            file_a = incoming / "a.json"
            file_b = incoming / "b.txt"
            ignored = incoming / "ignore.csv"
            file_a.write_text("{}", encoding="utf-8")
            file_b.write_text("x", encoding="utf-8")
            ignored.write_text("x", encoding="utf-8")

            os.utime(file_a, (1000, 1000))
            os.utime(file_b, (2000, 2000))
            os.utime(ignored, (500, 500))

            files = discover_files(Config(INCOMING_DIR=incoming))

        self.assertEqual([path.name for path in files], ["a.json", "b.txt"])

    def test_normalize_notable_handles_json_and_fallback(self) -> None:
        """Parses valid JSON and falls back to raw content on parse error."""
        parsed = normalize_notable('{"k":"v","n":2}', content_type="json")
        fallback = normalize_notable("{not-json}", content_type="json")
        raw_text = normalize_notable("plain text", content_type="text")

        self.assertEqual(parsed, {"k": "v", "n": 2})
        self.assertEqual(fallback, "{not-json}")
        self.assertEqual(raw_text, "plain text")

    def test_get_notable_id_sanitizes_filename_stem(self) -> None:
        """Sanitizes unsafe filename characters into underscore."""
        notable_id = get_notable_id({}, Path("bad id#1.json"))
        self.assertEqual(notable_id, "bad_id_1")

    def test_move_to_processed_handles_name_collision(self) -> None:
        """Moves source file and appends numeric suffix on destination collision."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            incoming = root / "incoming"
            processed = root / "processed"
            incoming.mkdir(parents=True, exist_ok=True)
            processed.mkdir(parents=True, exist_ok=True)

            (processed / "alert.json").write_text("existing", encoding="utf-8")
            src = incoming / "alert.json"
            src.write_text("new", encoding="utf-8")

            config = Config(PROCESSED_DIR=processed)
            moved = move_to_processed(src, config)

            self.assertEqual(moved.name, "alert_1.json")
            self.assertTrue(moved.exists())
            self.assertFalse(src.exists())

    def test_move_to_quarantine_handles_name_collision(self) -> None:
        """Moves failed source file and appends numeric suffix on collision."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            incoming = root / "incoming"
            quarantine = root / "quarantine"
            incoming.mkdir(parents=True, exist_ok=True)
            quarantine.mkdir(parents=True, exist_ok=True)

            (quarantine / "alert.json").write_text("existing", encoding="utf-8")
            src = incoming / "alert.json"
            src.write_text("new", encoding="utf-8")

            config = Config(QUARANTINE_DIR=quarantine)
            moved = move_to_quarantine(src, config, reason="test")

            self.assertEqual(moved.name, "alert_1.json")
            self.assertTrue(moved.exists())
            self.assertFalse(src.exists())


if __name__ == "__main__":
    unittest.main()
