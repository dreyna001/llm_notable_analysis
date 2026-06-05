#!/usr/bin/env python3
"""Backfill legacy markdown reports into the Postgres case archive."""

# Tests and operator execution add the local src layout dynamically.
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if PROJECT_SRC.exists() and str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    CaseArchiveRecord,
    write_case_record_with_retries,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config, load_config

_BACKFILL_HASH_PREFIX = 16
_DEFAULT_BATCH_SIZE = 100
_MAX_BACKFILL_TEXT_EXCERPT_CHARS = 12000


def _result(
    *,
    dry_run: int,
    reports_found: int,
    cases: int,
    case_ids: list[str] | None = None,
    skipped: list[dict[str, str]] | None = None,
    failures: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Build the stable JSON result shape emitted by the operator command."""
    return {
        "dry_run": dry_run,
        "reports_found": reports_found,
        "cases": cases,
        "case_ids": case_ids or [],
        "skipped": skipped or [],
        "failures": failures or [],
    }


def _skip(path: Path, reason: str) -> dict[str, str]:
    """Return a serializable skipped-file record."""
    return {"path": str(path), "reason": reason}


def _validate_positive_int(value: int, name: str) -> int:
    """Validate a positive integer CLI/runtime bound."""
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{name} must be greater than zero.")
    return parsed


def _load_config_env(path: Path) -> None:
    """Load simple KEY=VALUE pairs into the process environment."""
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(f"Invalid config line {line_number}: {exc}") from exc
        if tokens and tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise ValueError(
                f"Invalid config line {line_number}: expected KEY=VALUE."
            )
        key, value = tokens[0].split("=", 1)
        key = key.strip()
        if not key.isidentifier():
            raise ValueError(f"Invalid config line {line_number}: invalid key {key!r}.")
        if key in os.environ:
            continue
        os.environ[key] = value


def _walk_markdown_reports(report_dir: Path) -> Iterable[Path]:
    """Yield markdown report paths in stable directory order without following dirs."""
    for current_dir, dirnames, filenames in os.walk(report_dir):
        dirnames[:] = sorted(dirnames)
        for filename in sorted(filenames):
            if filename.endswith(".md"):
                yield Path(current_dir) / filename


def _report_dir_problem(report_dir: Path) -> str | None:
    """Return a report-dir validation problem, if any."""
    if not report_dir.exists():
        return "report_dir_missing"
    if not report_dir.is_dir():
        return "report_dir_not_directory"
    return None


def _is_relative_to(path: Path, root: Path) -> bool:
    """Return True when path is under root after resolution."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_report_path(
    report_path: Path,
    *,
    root: Path,
    max_file_bytes: int,
) -> None:
    """Reject unsafe or oversized report paths before reading content."""
    if report_path.is_symlink():
        raise ValueError("symlinked reports are not supported")
    root_resolved = root.resolve(strict=True)
    resolved = report_path.resolve(strict=True)
    if not _is_relative_to(resolved, root_resolved):
        raise ValueError("report path must remain under report_dir")
    if not report_path.is_file():
        raise ValueError("report path is not a file")
    size = report_path.stat().st_size
    if size > max_file_bytes:
        raise ValueError(
            f"report exceeds max file size: {size} > {max_file_bytes} bytes"
        )


def _scan_markdown_reports(
    report_dir: Path,
    *,
    batch_size: int,
    max_file_bytes: int,
) -> tuple[list[Path], list[dict[str, str]]]:
    """Return importable markdown reports plus skipped-path diagnostics."""
    batch_limit = _validate_positive_int(batch_size, "batch_size")
    max_bytes = _validate_positive_int(max_file_bytes, "max_file_bytes")
    problem = _report_dir_problem(report_dir)
    if problem is not None:
        raise ValueError(problem)

    reports: list[Path] = []
    skipped: list[dict[str, str]] = []
    for report_path in _walk_markdown_reports(report_dir):
        if len(reports) >= batch_limit:
            skipped.append(_skip(report_dir, "batch_size_limit_reached"))
            break
        try:
            _validate_report_path(
                report_path,
                root=report_dir,
                max_file_bytes=max_bytes,
            )
        except (OSError, ValueError) as exc:
            skipped.append(_skip(report_path, str(exc)))
            continue
        reports.append(report_path)
    return reports, skipped


def _report_hash(report_path: Path, text: str, *, root: Path) -> str:
    """Return the stable backfill hash for one report path and content."""
    try:
        relative = report_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = report_path.name
    digest = hashlib.sha256(
        (relative + "\n" + text).encode("utf-8", errors="replace")
    ).hexdigest()
    return digest[:_BACKFILL_HASH_PREFIX]


def build_backfill_case_id(report_path: Path, text: str, *, root: Path) -> str:
    """Build an idempotent legacy case id using the backfill:<sha256-prefix> rule."""
    return f"backfill:{_report_hash(report_path, text, root=root)}"


def _first_heading(text: str) -> str | None:
    """Extract the first markdown heading as a search-name hint."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("#"):
            continue
        title = line.lstrip("#").strip()
        if title:
            return title[:512]
    return None


def build_legacy_case_record(
    *,
    config: Config,
    report_path: Path,
    root: Path | None = None,
    max_file_bytes: int | None = None,
) -> CaseArchiveRecord:
    """Build a markdown-only legacy summary case archive record."""
    root = root or config.REPORT_DIR
    max_bytes = max_file_bytes or int(config.MAX_INPUT_FILE_BYTES)
    _validate_report_path(report_path, root=root, max_file_bytes=max_bytes)
    text = report_path.read_text(encoding="utf-8", errors="replace")
    stat = report_path.stat()
    processed_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    case_id = build_backfill_case_id(report_path, text, root=root)
    title = _first_heading(text)
    content_sha256 = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return CaseArchiveRecord(
        case_id=case_id,
        finding_id=case_id,
        source_filename=report_path.name,
        processed_at=processed_at,
        expires_at=processed_at + timedelta(days=config.CASE_RETENTION_DAYS),
        correlation_id=case_id,
        capability_snapshot={
            "capability_profiles": config.CAPABILITY_PROFILES,
            "backfill_source": "markdown_report",
            "case_schema_version": config.CASE_SCHEMA_VERSION,
            "analysis_schema_version": config.CASE_ANALYSIS_SCHEMA_VERSION,
        },
        archive_metadata={
            "backfill_source_path": str(report_path),
            "backfill_hash_prefix": case_id.removeprefix("backfill:"),
            "content_sha256": content_sha256,
            "source_size_bytes": stat.st_size,
            "legacy_markdown_only": True,
        },
        alert_payload={
            "input_type": "markdown_report",
            "title": title,
            "text_excerpt": text[:_MAX_BACKFILL_TEXT_EXCERPT_CHARS],
            "text_truncated": len(text) > _MAX_BACKFILL_TEXT_EXCERPT_CHARS,
        },
        analysis=None,
        case_schema_version=config.CASE_SCHEMA_VERSION,
        analysis_schema_version=config.CASE_ANALYSIS_SCHEMA_VERSION,
        verdict=None,
        confidence=None,
        search_name=title,
        risk_score=None,
        report_md_path=str(report_path),
        report_html_path=None,
        retrieval_status="not_indexed",
        backfill_status="legacy_summary",
        source_completeness="markdown_only",
    )


def dry_run_backfill(
    *,
    config: Config,
    report_dir: Path | None = None,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    max_file_bytes: int | None = None,
) -> dict[str, object]:
    """Report which markdown files would be imported without writing rows."""
    root = report_dir or config.REPORT_DIR
    max_bytes = max_file_bytes or int(config.MAX_INPUT_FILE_BYTES)
    problem = _report_dir_problem(root)
    if problem is not None:
        return _result(
            dry_run=1,
            reports_found=0,
            cases=0,
            skipped=[_skip(root, problem)],
        )
    reports, skipped = _scan_markdown_reports(
        root,
        batch_size=batch_size,
        max_file_bytes=max_bytes,
    )
    records = [
        build_legacy_case_record(
            config=config,
            report_path=path,
            root=root,
            max_file_bytes=max_bytes,
        )
        for path in reports
    ]
    return _result(
        dry_run=1,
        reports_found=len(reports),
        cases=len(records),
        case_ids=[record.case_id for record in records],
        skipped=skipped,
    )


def execute_backfill(
    *,
    config: Config,
    report_dir: Path | None = None,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    max_file_bytes: int | None = None,
) -> dict[str, object]:
    """Import markdown reports as idempotent legacy summary cases."""
    if not bool(config.CASE_ARCHIVE_ENABLED):
        raise ValueError("CASE_ARCHIVE_ENABLED must be true to execute backfill.")
    root = report_dir or config.REPORT_DIR
    max_bytes = max_file_bytes or int(config.MAX_INPUT_FILE_BYTES)
    reports, skipped = _scan_markdown_reports(
        root,
        batch_size=batch_size,
        max_file_bytes=max_bytes,
    )
    imported = 0
    case_ids: list[str] = []
    failures: list[dict[str, str]] = []
    for report_path in reports:
        try:
            record = build_legacy_case_record(
                config=config,
                report_path=report_path,
                root=root,
                max_file_bytes=max_bytes,
            )
            write_case_record_with_retries(record=record, config=config)
        except Exception as exc:
            failures.append(_skip(report_path, str(exc)))
            continue
        imported += 1
        case_ids.append(record.case_id)
    return _result(
        dry_run=0,
        reports_found=len(reports),
        cases=imported,
        case_ids=case_ids,
        skipped=skipped,
        failures=failures,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse operator CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Backfill legacy markdown reports into the case archive.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        help="Markdown report directory to scan; defaults to REPORT_DIR.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report importable files without writing Postgres rows.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        help="Maximum markdown reports to import or preview in one run.",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        help="Maximum markdown report size; defaults to MAX_INPUT_FILE_BYTES.",
    )
    parser.add_argument(
        "--config-env",
        type=Path,
        help="Config env file to read before loading config; required for execute.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the markdown report backfill command."""
    args = _parse_args(argv)
    if not args.dry_run and args.config_env is None:
        raise ValueError("--config-env is required when executing backfill.")
    if args.config_env is not None:
        _load_config_env(args.config_env)
    config = load_config()
    report_dir = args.report_dir or config.REPORT_DIR
    kwargs: dict[str, Any] = {
        "config": config,
        "report_dir": report_dir,
        "batch_size": args.batch_size,
        "max_file_bytes": args.max_file_bytes,
    }
    result = (
        dry_run_backfill(**kwargs)
        if args.dry_run
        else execute_backfill(**kwargs)
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 1 if result.get("failures") else 0


if __name__ == "__main__":
    sys.exit(main())
