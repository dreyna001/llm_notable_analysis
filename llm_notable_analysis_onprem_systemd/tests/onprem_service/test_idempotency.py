import tempfile
import unittest
from pathlib import Path

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.idempotency import (
    begin_side_effect,
    complete_side_effect_success,
    release_side_effect_lock,
)


class TestSideEffectIdempotency(unittest.TestCase):
    def test_completed_marker_skips_duplicate_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = Config(
                SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
                SIDE_EFFECT_IDEMPOTENCY_DIR=Path(td),
            )

            reservation = begin_side_effect(
                config, operation="servicenow_incident_create", key="finding-1"
            )
            self.assertTrue(reservation.should_execute)
            recorded = complete_side_effect_success(
                reservation,
                metadata={"number": "INC001", "sys_id": "abc123"},
            )
            duplicate = begin_side_effect(
                config, operation="servicenow_incident_create", key="finding-1"
            )

        self.assertTrue(recorded)
        self.assertFalse(duplicate.should_execute)
        self.assertEqual(
            duplicate.existing_marker["metadata"],
            {"number": "INC001", "sys_id": "abc123"},
        )

    def test_open_lock_blocks_concurrent_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = Config(
                SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
                SIDE_EFFECT_IDEMPOTENCY_DIR=Path(td),
            )

            reservation = begin_side_effect(
                config, operation="splunk_notable_update", key="finding-1"
            )
            with self.assertRaisesRegex(TimeoutError, "idempotency lock"):
                begin_side_effect(
                    config,
                    operation="splunk_notable_update",
                    key="finding-1",
                    wait_timeout_seconds=0.0,
                )
            release_side_effect_lock(reservation)

    def test_enabled_idempotency_rejects_generic_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = Config(
                SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
                SIDE_EFFECT_IDEMPOTENCY_DIR=Path(td),
            )

            with self.assertRaisesRegex(ValueError, "key must be specific"):
                begin_side_effect(
                    config,
                    operation="servicenow_incident_create",
                    key="unknown",
                )

    def test_enabled_idempotency_requires_absolute_directory(self) -> None:
        config = Config(
            SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
            SIDE_EFFECT_IDEMPOTENCY_DIR=Path("relative/idempotency"),
        )

        with self.assertRaisesRegex(ValueError, "must be an absolute path"):
            begin_side_effect(
                config,
                operation="splunk_notable_update",
                key="finding-1",
            )


if __name__ == "__main__":
    unittest.main()
