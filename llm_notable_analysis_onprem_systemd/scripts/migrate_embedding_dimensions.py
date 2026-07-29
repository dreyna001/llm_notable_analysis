#!/usr/bin/env python3
"""Idempotent pgvector dimension migration for on-prem chunk tables.

Clears chunk rows only; preserves cases, tickets, attachments, chat, and source files.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
DEFAULT_GRANITE_TARGET_DIMENSION = 768
_SUPPORTED_TARGET_DIMENSIONS = frozenset({DEFAULT_GRANITE_TARGET_DIMENSION})

ExecuteFn = Callable[[str, str], tuple[int, str, str]]


@dataclass(frozen=True)
class ChunkTableSpec:
    """One embedding chunk table to migrate."""

    label: str
    dsn: str
    schema: str
    table: str
    vector_index_names: tuple[str, ...]
    post_alter_sql: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableInspection:
    """Observed pgvector column state."""

    exists: bool
    type_text: str | None


@dataclass(frozen=True)
class MigrationAction:
    """Planned work for one chunk table."""

    spec: ChunkTableSpec
    inspection: TableInspection
    skipped: bool
    skip_reason: str = ""


def parse_config_env(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from config.env without sourcing shell."""
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(f"Invalid config.env line {line_number}: {exc}") from exc
        if not tokens:
            continue
        if tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise ValueError(
                f"Invalid config.env line {line_number}: expected KEY=VALUE."
            )
        key, value = tokens[0].split("=", 1)
        if not key.isidentifier():
            raise ValueError(f"Invalid config.env line {line_number}: invalid key {key!r}.")
        values[key] = value
    return values


def merge_config_values(*sources: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for source in sources:
        merged.update(source)
    return merged


def require_simple_identifier(value: str, label: str) -> str:
    normalized = (value or "").strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{label} must be a simple PostgreSQL identifier.")
    return normalized


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def mask_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    if not parsed.password:
        return dsn
    safe_netloc = parsed.netloc.replace(parsed.password, "***", 1)
    return parsed._replace(netloc=safe_netloc).geturl()


def vector_type_text(dimension: int) -> str:
    return f"vector({int(dimension)})"


def parse_vector_dimension(type_text: str | None) -> int | None:
    if not type_text:
        return None
    match = re.fullmatch(r"vector\((\d+)\)", type_text.strip().lower())
    if not match:
        return None
    return int(match.group(1))


def build_rag_index_name(schema: str, table: str, suffix: str) -> str:
    import hashlib

    require_simple_identifier(suffix, "index suffix")
    source = f"{schema}.{table}.{suffix}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"rag_{digest}_{suffix}"


def build_chunk_table_specs(config: dict[str, str]) -> list[ChunkTableSpec]:
    rag_dsn = config.get(
        "RAG_POSTGRES_DSN", "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag"
    )
    case_dsn = config.get("CASE_POSTGRES_DSN", rag_dsn)
    rag_schema = require_simple_identifier(
        config.get("RAG_POSTGRES_SCHEMA", "notable_rag"), "RAG_POSTGRES_SCHEMA"
    )
    case_schema = require_simple_identifier(
        config.get("CASE_POSTGRES_SCHEMA", "notable_cases"), "CASE_POSTGRES_SCHEMA"
    )
    closed_schema = require_simple_identifier(
        config.get("CLOSED_TICKET_POSTGRES_SCHEMA", "notable_closed_tickets"),
        "CLOSED_TICKET_POSTGRES_SCHEMA",
    )
    kb_table = require_simple_identifier(
        config.get("RAG_POSTGRES_CHUNKS_TABLE", "kb_chunks"), "RAG_POSTGRES_CHUNKS_TABLE"
    )
    spl_table = require_simple_identifier(
        config.get("SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE", "spl_query_chunks"),
        "SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE",
    )
    elastic_table = require_simple_identifier(
        config.get(
            "ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE", "elasticsearch_query_chunks"
        ),
        "ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE",
    )

    specs = [
        ChunkTableSpec(
            label="general_kb",
            dsn=rag_dsn,
            schema=rag_schema,
            table=kb_table,
            vector_index_names=(
                build_rag_index_name(rag_schema, kb_table, "embedding_hnsw_idx"),
            ),
        ),
        ChunkTableSpec(
            label="spl_query",
            dsn=rag_dsn,
            schema=rag_schema,
            table=spl_table,
            vector_index_names=(
                build_rag_index_name(rag_schema, spl_table, "embedding_hnsw_idx"),
            ),
        ),
        ChunkTableSpec(
            label="elasticsearch_query",
            dsn=rag_dsn,
            schema=rag_schema,
            table=elastic_table,
            vector_index_names=(
                build_rag_index_name(rag_schema, elastic_table, "embedding_hnsw_idx"),
            ),
        ),
        ChunkTableSpec(
            label="case_chunks",
            dsn=case_dsn,
            schema=case_schema,
            table="case_chunks",
            vector_index_names=("case_chunks_embedding_hnsw_idx",),
            post_alter_sql=(
                f"UPDATE {quote_ident(case_schema)}.cases "
                "SET retrieval_status = 'pending' "
                "WHERE retrieval_status = 'ready';",
            ),
        ),
        ChunkTableSpec(
            label="closed_ticket_chunks",
            dsn=case_dsn,
            schema=closed_schema,
            table="ticket_chunks",
            vector_index_names=("ticket_chunks_embedding_hnsw_idx",),
            post_alter_sql=(
                f"UPDATE {quote_ident(closed_schema)}.servicenow_tickets "
                "SET index_status = 'pending' "
                "WHERE index_status = 'ready';",
            ),
        ),
    ]
    return specs


def inspect_table(
    execute: ExecuteFn,
    dsn: str,
    schema: str,
    table: str,
) -> TableInspection:
    query = (
        "SELECT EXISTS ("
        f"  SELECT 1 FROM information_schema.tables "
        f"  WHERE table_schema = '{schema}' AND table_name = '{table}'"
        ") AS table_exists, ("
        "  SELECT format_type(a.atttypid, a.atttypmod) "
        "  FROM pg_attribute a "
        "  JOIN pg_class c ON a.attrelid = c.oid "
        "  JOIN pg_namespace n ON c.relnamespace = n.oid "
        f"  WHERE n.nspname = '{schema}' AND c.relname = '{table}' "
        "    AND a.attname = 'embedding' AND NOT a.attisdropped"
        ") AS embedding_type;"
    )
    code, stdout, stderr = execute(dsn, query)
    if code != 0:
        raise RuntimeError(
            f"Failed inspecting {schema}.{table} on {mask_dsn(dsn)}: {stderr or stdout}"
        )
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return TableInspection(exists=False, type_text=None)
    parts = [part.strip() for part in lines[-1].split("|")]
    if len(parts) != 2:
        raise RuntimeError(
            f"Unexpected inspection output for {schema}.{table}: {stdout!r}"
        )
    exists = parts[0].lower() in {"t", "true"}
    type_text = parts[1] if parts[1] else None
    return TableInspection(exists=exists, type_text=type_text)


def plan_migration(
    specs: Sequence[ChunkTableSpec],
    *,
    target_dim: int,
    execute: ExecuteFn,
) -> list[MigrationAction]:
    if target_dim not in _SUPPORTED_TARGET_DIMENSIONS:
        raise ValueError(
            f"Unsupported --target-dim {target_dim}; supported: "
            f"{sorted(_SUPPORTED_TARGET_DIMENSIONS)}"
        )
    target_type = vector_type_text(target_dim)
    actions: list[MigrationAction] = []
    for spec in specs:
        inspection = inspect_table(execute, spec.dsn, spec.schema, spec.table)
        if not inspection.exists:
            actions.append(
                MigrationAction(
                    spec=spec,
                    inspection=inspection,
                    skipped=True,
                    skip_reason="table absent",
                )
            )
            continue
        current_dim = parse_vector_dimension(inspection.type_text)
        if current_dim == target_dim:
            actions.append(
                MigrationAction(
                    spec=spec,
                    inspection=inspection,
                    skipped=True,
                    skip_reason=f"already {target_type}",
                )
            )
            continue
        if inspection.type_text and current_dim is None:
            raise RuntimeError(
                f"{spec.schema}.{spec.table} embedding column type "
                f"{inspection.type_text!r} is not pgvector"
            )
        actions.append(
            MigrationAction(spec=spec, inspection=inspection, skipped=False)
        )
    return actions


def build_table_migration_sql(spec: ChunkTableSpec, target_dim: int) -> str:
    schema = quote_ident(spec.schema)
    table = quote_ident(spec.table)
    qualified = f"{schema}.{table}"
    target_type = vector_type_text(target_dim)
    statements = ["BEGIN;"]
    for index_name in spec.vector_index_names:
        statements.append(
            f"DROP INDEX IF EXISTS {schema}.{quote_ident(index_name)};"
        )
    statements.append(f"DELETE FROM {qualified};")
    statements.append(
        f"ALTER TABLE {qualified} ALTER COLUMN embedding TYPE {target_type};"
    )
    statements.append(
        f"CREATE INDEX IF NOT EXISTS {quote_ident(spec.vector_index_names[0])} "
        f"ON {qualified} USING hnsw (embedding vector_cosine_ops);"
    )
    statements.extend(spec.post_alter_sql)
    statements.append("COMMIT;")
    return "\n".join(statements)


def rebuild_commands(config: dict[str, str]) -> list[str]:
    config_env = config.get("_CONFIG_ENV_PATH", "/etc/notable-analyzer/config.env")
    return [
        f"scripts/setup_postgres_rag.sh --config-env {config_env}",
        (
            f"scripts/setup_postgres_rag.sh --config-env {config_env} "
            "--spl-query-rag"
        ),
        (
            f"python3 scripts/rebuild_case_chunks.py --all --config-env {config_env}"
        ),
        (
            f"python3 scripts/rebuild_closed_ticket_chunks.py --all "
            f"--config-env {config_env}"
        ),
        "sudo systemctl restart notable-analyzer notable-portal",
    ]


def default_execute(dsn: str, sql: str) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout, completed.stderr


def run_migration(
    *,
    config_env: Path,
    portal_env: Path | None,
    target_dim: int,
    dry_run: bool,
    execute: ExecuteFn | None = None,
) -> int:
    execute_fn = execute or default_execute
    config = parse_config_env(config_env)
    config["_CONFIG_ENV_PATH"] = str(config_env)
    if portal_env is not None and portal_env.exists():
        config = merge_config_values(parse_config_env(portal_env), config)
    specs = build_chunk_table_specs(config)
    actions = plan_migration(specs, target_dim=target_dim, execute=execute_fn)

    print(f"Target embedding dimension: {target_dim}")
    for action in actions:
        spec = action.spec
        location = f"{spec.schema}.{spec.table} ({spec.label})"
        if action.skipped:
            print(f"SKIP {location}: {action.skip_reason}")
            continue
        current = action.inspection.type_text or "unknown"
        print(
            f"MIGRATE {location}: {current} -> {vector_type_text(target_dim)} "
            f"via {mask_dsn(spec.dsn)}"
        )
        sql = build_table_migration_sql(spec, target_dim)
        if dry_run:
            print("--- dry-run SQL ---")
            print(sql)
            print("--- end dry-run SQL ---")
            continue
        code, stdout, stderr = execute_fn(spec.dsn, sql)
        if code != 0:
            raise RuntimeError(
                f"Migration failed for {location} on {mask_dsn(spec.dsn)}: "
                f"{stderr or stdout}"
            )
        if stdout.strip():
            print(stdout.strip())

    print("\nNext rebuild steps:")
    for command in rebuild_commands(config):
        print(command)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate on-prem pgvector chunk tables to Granite 768 dimensions."
    )
    parser.add_argument(
        "--config-env",
        default="/etc/notable-analyzer/config.env",
        help="Analyzer config.env path",
    )
    parser.add_argument(
        "--portal-env",
        default="",
        help="Optional portal.env path for supplemental config keys",
    )
    parser.add_argument(
        "--target-dim",
        type=int,
        default=None,
        help=(
            "Target vector dimension "
            f"(default: {DEFAULT_GRANITE_TARGET_DIMENSION} for Granite migration)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned SQL without modifying databases",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config_env = Path(args.config_env)
    if not config_env.is_file():
        parser.error(f"Missing config file: {config_env}")

    portal_env = Path(args.portal_env) if args.portal_env else None
    target_dim = args.target_dim if args.target_dim is not None else DEFAULT_GRANITE_TARGET_DIMENSION

    try:
        return run_migration(
            config_env=config_env,
            portal_env=portal_env,
            target_dim=target_dim,
            dry_run=bool(args.dry_run),
        )
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
