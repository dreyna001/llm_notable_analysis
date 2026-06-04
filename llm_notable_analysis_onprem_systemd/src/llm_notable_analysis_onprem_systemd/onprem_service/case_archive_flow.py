"""Shared analyzer-to-case-archive orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .case_search import (
    CaseChunkWriteError,
    mark_case_retrieval_status,
    store_case_chunks,
)
from .case_store import (
    CaseArchiveConflictError,
    CaseArchiveWriteError,
    build_native_case_id,
    write_case_archive_record,
)
from .config import Config


def archive_case_for_portal(
    *,
    config: Config,
    logger: logging.Logger,
    source_filename: str,
    finding_id: str,
    alert_payload: Any,
    analysis: dict[str, Any],
    report_md_path: Path | str | None,
    report_html_path: Path | str | None,
) -> bool:
    """Archive a completed analysis and index chunks without failing ingest.

    Returns True when the case row and chunks are stored. Operational archive or
    chunk failures are logged and return False so the already completed analysis
    can still move to processed. Unrelated identity collisions remain hard
    failures because they indicate a deterministic-id safety violation.
    """
    case_id = build_native_case_id(alert_payload, source_filename)
    try:
        case_record = write_case_archive_record(
            config=config,
            case_id=case_id,
            finding_id=finding_id,
            source_filename=source_filename,
            alert_payload=alert_payload,
            analysis=analysis,
            report_md_path=report_md_path,
            report_html_path=report_html_path,
        )
    except CaseArchiveConflictError:
        raise
    except CaseArchiveWriteError:
        logger.exception("Case archive write failed; continuing ingest: %s", case_id)
        return False

    try:
        chunk_count = store_case_chunks(record=case_record, config=config)
    except CaseChunkWriteError:
        try:
            mark_case_retrieval_status(
                config=config,
                case_id=case_id,
                status="failed",
            )
        except CaseChunkWriteError:
            logger.exception("Failed to mark case retrieval failure: %s", case_id)
        logger.exception("Case retrieval chunk indexing failed: %s", case_id)
        return False

    logger.info("Archived case to Postgres: %s", case_id)
    logger.info("Stored %s case retrieval chunks: %s", chunk_count, case_id)
    return True
