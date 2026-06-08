"""Tests for shared case archive Postgres helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_notable_analysis_onprem_systemd.onprem_service.case_db import (
    is_transient_postgres_error,
    postgres_operation_errors,
    row_get,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.ingest import quarantine_after_failure


class _MappingRow:
    def __init__(self, mapping: dict[str, object]) -> None:
        self._mapping = mapping


class _SequenceRow:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def __getitem__(self, index: int) -> object:
        return self._values[index]


class _AttrRow:
    case_id = "CASE-1"


def test_row_get_reads_dict_mapping_and_sequence_rows() -> None:
    assert row_get({"case_id": "CASE-1"}, 0, "case_id") == "CASE-1"
    assert row_get(_MappingRow({"case_id": "CASE-2"}), 0, "case_id") == "CASE-2"
    assert row_get(_SequenceRow(["a", "b"]), 1, "ignored") == "b"
    assert row_get(_AttrRow(), 0, "case_id") == "CASE-1"
    assert row_get(None, 0, "case_id") is None


def test_postgres_operation_errors_includes_base_and_optional_psycopg() -> None:
    errors = postgres_operation_errors()
    assert OSError in errors
    assert RuntimeError in errors
    assert ValueError in errors


def test_is_transient_postgres_error_recognizes_connectivity_failures() -> None:
    assert is_transient_postgres_error(OSError("connection reset"))
    assert is_transient_postgres_error(TimeoutError())


def test_is_transient_postgres_error_recognizes_retryable_psycopg_names() -> None:
    operational_error = type("OperationalError", (Exception,), {})
    assert is_transient_postgres_error(operational_error("db down"))


def test_is_transient_postgres_error_rejects_programming_failures() -> None:
    assert not is_transient_postgres_error(AttributeError("row mapping bug"))
    assert not is_transient_postgres_error(ValueError("bad filter"))


def test_quarantine_after_failure_logs_oserror_without_raising(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    notable = incoming / "bad.json"
    notable.write_text("{}", encoding="utf-8")
    config = Config(
        INCOMING_DIR=incoming,
        PROCESSED_DIR=tmp_path / "processed",
        QUARANTINE_DIR=tmp_path / "quarantine",
        REPORT_DIR=tmp_path / "reports",
        ARCHIVE_DIR=tmp_path / "archive",
    )
    logger = logging.getLogger("test_quarantine_after_failure")

    with patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.ingest.move_to_quarantine",
        side_effect=OSError("disk full"),
    ):
        with caplog.at_level(logging.ERROR, logger="test_quarantine_after_failure"):
            quarantine_after_failure(notable, config, "processing failed", logger=logger)

    assert "Failed to quarantine notable bad.json after processing error" in caplog.text
