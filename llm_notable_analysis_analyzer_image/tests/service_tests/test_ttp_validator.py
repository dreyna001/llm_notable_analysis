"""Behavior tests for MITRE ATT&CK TTP ID validation."""

import json
import tempfile
import unittest
from pathlib import Path

from onprem_service.ttp_validator import TTPValidator


class TestTtpValidator(unittest.TestCase):
    """Validate allowlist loading, filtering, and failure paths."""

    def _write_ids_file(self, tmp_dir: Path, payload: object) -> Path:
        """Writes JSON payload to a temp IDs file."""
        ids_path = tmp_dir / "ids.json"
        ids_path.write_text(json.dumps(payload), encoding="utf-8")
        return ids_path

    def test_loads_parent_and_subtechniques_and_validates_ids(self) -> None:
        """Loads IDs into parent/sub-technique sets and validates correctly."""
        with tempfile.TemporaryDirectory() as td:
            ids_path = self._write_ids_file(
                Path(td),
                ["T1110", "T1059.001", "T1059.003"],
            )
            validator = TTPValidator(ids_path)

        self.assertEqual(validator.get_ttp_count(), 3)
        self.assertTrue(validator.is_valid_ttp("T1110"))
        self.assertTrue(validator.is_valid_ttp("T1059.001"))
        self.assertFalse(validator.is_valid_ttp("T9999"))

    def test_filter_valid_ttps_drops_unknown_and_missing_ids(self) -> None:
        """Filters out entries whose ``ttp_id`` is missing or not allowlisted."""
        with tempfile.TemporaryDirectory() as td:
            ids_path = self._write_ids_file(Path(td), ["T1110"])
            validator = TTPValidator(ids_path)
            filtered = validator.filter_valid_ttps(
                [
                    {"ttp_id": "T1110", "score": 0.8},
                    {"ttp_id": "T9999", "score": 0.9},
                    {"score": 0.4},
                ]
            )

        self.assertEqual(filtered, [{"ttp_id": "T1110", "score": 0.8}])

    def test_get_valid_ttps_for_prompt_returns_csv_payload(self) -> None:
        """Returns a comma-separated list suitable for prompt injection."""
        with tempfile.TemporaryDirectory() as td:
            ids_path = self._write_ids_file(Path(td), ["T1110", "T1059.001"])
            validator = TTPValidator(ids_path)
            csv_payload = validator.get_valid_ttps_for_prompt()

        self.assertIn("T1110", csv_payload)
        self.assertIn("T1059.001", csv_payload)
        self.assertIn(", ", csv_payload)

    def test_empty_ids_file_raises_value_error(self) -> None:
        """Raises a contract error when allowlist file is empty."""
        with tempfile.TemporaryDirectory() as td:
            ids_path = self._write_ids_file(Path(td), [])
            with self.assertRaises(ValueError):
                TTPValidator(ids_path)

    def test_invalid_json_raises_decode_error(self) -> None:
        """Raises JSON decoding error when allowlist file is malformed."""
        with tempfile.TemporaryDirectory() as td:
            ids_path = Path(td) / "ids.json"
            ids_path.write_text("{bad-json", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                TTPValidator(ids_path)


if __name__ == "__main__":
    unittest.main()
