#!/usr/bin/env python3
"""Rebuild Postgres closed-ticket chunks for hybrid retrieval."""

# Tests and operator execution add the local src layout dynamically.
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if PROJECT_SRC.exists() and str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_index import (
    dry_run_closed_ticket_chunk_rebuild,
    rebuild_closed_ticket_chunks,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import load_config


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse operator CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Rebuild ticket_chunks rows from stored closed-ticket records.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--ticket-id", help="Rebuild one ticket_id.")
    target.add_argument("--all", action="store_true", help="Rebuild all retained tickets.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of ticket rows to fetch per rebuild page when using --all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build chunks and report counts without deleting or inserting rows.",
    )
    parser.add_argument(
        "--config-env",
        type=Path,
        help="Optional config.env file to read before loading environment config.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the closed-ticket chunk rebuild command."""
    args = _parse_args(argv)
    if args.batch_size < 1:
        raise ValueError("--batch-size must be greater than zero")
    if not args.dry_run and args.config_env is None:
        raise ValueError("--config-env is required when executing chunk rebuild.")
    if args.config_env is not None:
        _load_config_env(args.config_env)

    config = load_config()
    if not args.dry_run and not bool(getattr(config, "CLOSED_TICKET_RAG_ENABLED", False)):
        raise ValueError(
            "CLOSED_TICKET_RAG_ENABLED must be true to execute closed-ticket rebuild."
        )
    ticket_id = args.ticket_id if not args.all else None
    if args.dry_run:
        result = dry_run_closed_ticket_chunk_rebuild(
            config=config,
            ticket_id=ticket_id,
            batch_size=args.batch_size,
        )
        result["dry_run"] = 1
    else:
        result = rebuild_closed_ticket_chunks(
            config=config,
            ticket_id=ticket_id,
            batch_size=args.batch_size,
        )
        result["dry_run"] = 0
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
