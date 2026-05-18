"""Tests for analyzer container healthcheck script."""
# pylint: disable=import-error,protected-access

from __future__ import annotations

import os
import sys
import tempfile
from contextlib import redirect_stderr
from io import StringIO
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

ANALYZER_IMAGE_ROOT = Path(__file__).resolve().parents[1]
if str(ANALYZER_IMAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(ANALYZER_IMAGE_ROOT))

import docker_healthcheck  # noqa: E402


class TestDockerHealthcheck(unittest.TestCase):
    def test_llm_models_url_from_chat_completions(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_API_URL": "http://litellm:4000/v1/chat/completions",
            },
            clear=False,
        ):
            self.assertEqual(
                docker_healthcheck._llm_models_url(),
                "http://litellm:4000/v1/models",
            )

    def test_directory_check_writes_and_removes_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            incoming = Path(tmp) / "incoming"
            processed = Path(tmp) / "processed"
            quarantine = Path(tmp) / "quarantine"
            reports = Path(tmp) / "reports"
            for path in (incoming, processed, quarantine, reports):
                path.mkdir()

            with patch.dict(
                os.environ,
                {
                    "INCOMING_DIR": str(incoming),
                    "PROCESSED_DIR": str(processed),
                    "QUARANTINE_DIR": str(quarantine),
                    "REPORT_DIR": str(reports),
                    "ANALYZER_HEALTHCHECK_CHECK_LLM": "false",
                    "ANALYZER_HEALTHCHECK_CHECK_POSTGRES": "false",
                },
                clear=False,
            ):
                self.assertEqual(docker_healthcheck.main(), 0)

            self.assertFalse(any(incoming.glob(".healthcheck_write")))

    def test_postgres_failure_is_sanitized(self) -> None:
        class FakePsycopgError(Exception):
            pass

        def fail_connect(*_args, **_kwargs):
            raise FakePsycopgError(
                "could not connect with password=secret host=postgres"
            )

        with tempfile.TemporaryDirectory() as tmp:
            incoming = Path(tmp) / "incoming"
            processed = Path(tmp) / "processed"
            quarantine = Path(tmp) / "quarantine"
            reports = Path(tmp) / "reports"
            for path in (incoming, processed, quarantine, reports):
                path.mkdir()

            fake_psycopg = SimpleNamespace(
                Error=FakePsycopgError,
                connect=fail_connect,
            )
            stderr = StringIO()
            with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
                with patch.dict(
                    os.environ,
                    {
                        "INCOMING_DIR": str(incoming),
                        "PROCESSED_DIR": str(processed),
                        "QUARANTINE_DIR": str(quarantine),
                        "REPORT_DIR": str(reports),
                        "ANALYZER_HEALTHCHECK_CHECK_LLM": "false",
                        "ANALYZER_HEALTHCHECK_CHECK_POSTGRES": "true",
                        "RAG_ENABLED": "true",
                        "RAG_BACKEND": "postgres",
                        "RAG_POSTGRES_DSN": (
                            "postgresql://user:secret@postgres:5432/notable_rag"
                        ),
                    },
                    clear=False,
                ):
                    with redirect_stderr(stderr):
                        self.assertEqual(docker_healthcheck.main(), 1)

            error_output = stderr.getvalue()
            self.assertIn("Postgres health probe failed", error_output)
            self.assertNotIn("secret", error_output)
            self.assertNotIn("postgresql://", error_output)


if __name__ == "__main__":
    unittest.main()
