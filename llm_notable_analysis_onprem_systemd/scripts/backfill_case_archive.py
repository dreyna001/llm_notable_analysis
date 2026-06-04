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
from typing import Iterable

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if PROJECT_SRC.exists() and str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    CaseArchiveRecord,
    write_case_record_with_retries,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config, load_config

_BACKFILL_HASH_PREFIX = 16


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


def _iter_markdown_reports(report_dir: Path) -> Iterable[Path]:
    """Yield markdown report files in stable path order."""
    if not report_dir.exists():
        return []
    return sorted(path for path in report_dir.rglob("*.md") if path.is_file())


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
) -> CaseArchiveRecord:
    """Build a markdown-only legacy summary case archive record."""
    root = root or config.REPORT_DIR
    text = report_path.read_text(encoding="utf-8", errors="replace")
    stat = report_path.stat()
    processed_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    case_id = build_backfill_case_id(report_path, text, root=root)
    title = _first_heading(text)
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
            "legacy_markdown_only": True,
        },
        alert_payload={
            "input_type": "markdown_report",
            "title": title,
            "text": text,
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
) -> dict[str, object]:
    """Report which markdown files would be imported without writing rows."""
    root = report_dir or config.REPORT_DIR
    reports = list(_iter_markdown_reports(root))
    records = [
        build_legacy_case_record(config=config, report_path=path, root=root)
        for path in reports
    ]
    return {
        "dry_run": 1,
        "reports_found": len(reports),
        "cases": len(records),
        "case_ids": [record.case_id for record in records],
    }


def execute_backfill(
    *,
    config: Config,
    report_dir: Path | None = None,
) -> dict[str, object]:
    """Import markdown reports as idempotent legacy summary cases."""
    root = report_dir or config.REPORT_DIR
    imported = 0
    case_ids: list[str] = []
    for report_path in _iter_markdown_reports(root):
        record = build_legacy_case_record(
            config=config,
            report_path=report_path,
            root=root,
        )
        write_case_record_with_retries(record=record, config=config)
        imported += 1
        case_ids.append(record.case_id)
    return {
        "dry_run": 0,
        "reports_found": imported,
        "cases": imported,
        "case_ids": case_ids,
    }


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
        "--config-env",
        type=Path,
        help="Optional config.env file to read before loading environment config.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the markdown report backfill command."""
    args = _parse_args(argv)
    if args.config_env is not None:
        _load_config_env(args.config_env)
    config = load_config()
    report_dir = args.report_dir or config.REPORT_DIR
    result = (
        dry_run_backfill(config=config, report_dir=report_dir)
        if args.dry_run
        else execute_backfill(config=config, report_dir=report_dir)
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
