#!/usr/bin/env bash
# Docker-backed validation smoke for PostgreSQL + pgvector RAG ingest/retrieval.
# Production uses the configured host PostgreSQL/pgvector service; Docker is
# only used here to provide a disposable database for release validation.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="$(cd "$REPO_DIR/.." && pwd)"

DOCKER_IMAGE="${DOCKER_IMAGE:-pgvector/pgvector:pg16}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
CONTAINER_NAME="${CONTAINER_NAME:-notable-rag-pgvector-smoke-$$}"
POSTGRES_PORT="${POSTGRES_PORT:-55432}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_DB="${POSTGRES_DB:-notable_rag}"
KEEP_CONTAINER="${KEEP_CONTAINER:-false}"
SMOKE_SCHEMA="${SMOKE_SCHEMA:-notable_rag_smoke}"
SMOKE_TABLE="${SMOKE_TABLE:-kb_chunks}"
STATEMENT_TIMEOUT_MS="${STATEMENT_TIMEOUT_MS:-5000}"
ANALYZER_PYTHON="${ANALYZER_PYTHON:-}"

usage() {
    cat <<'EOF'
Usage: smoke_postgres_rag.sh [options]

Starts a disposable pgvector Postgres container, creates a smoke schema/table,
inserts sample KB chunks, and verifies retrieval context through project code.
This is a validation harness, not a production runtime dependency.

Options:
  --python PATH      Python interpreter to use
  --port PORT        Host port for disposable Postgres (default: 55432)
  --keep-container   Leave container running for debugging
  -h, --help         Show this help

Environment overrides:
  DOCKER_BIN, DOCKER_IMAGE, CONTAINER_NAME, POSTGRES_PORT, POSTGRES_PASSWORD, POSTGRES_DB,
  KEEP_CONTAINER, SMOKE_SCHEMA, SMOKE_TABLE, STATEMENT_TIMEOUT_MS,
  ANALYZER_PYTHON
EOF
}

err() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "  $*"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || err "Missing required command: $1"
}

require_arg_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || err "Missing value for $option"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python)
            require_arg_value "$1" "${2:-}"
            ANALYZER_PYTHON="$2"
            shift 2
            ;;
        --port)
            require_arg_value "$1" "${2:-}"
            POSTGRES_PORT="$2"
            shift 2
            ;;
        --keep-container)
            KEEP_CONTAINER="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            err "Unknown argument: $1"
            ;;
    esac
done

require_command "$DOCKER_BIN"
if ! "$DOCKER_BIN" version >/dev/null 2>&1; then
    err "Docker is installed but not reachable. Start Docker Desktop and enable WSL integration for this distro, or set DOCKER_BIN to a working Docker CLI."
fi

if [[ -z "$ANALYZER_PYTHON" ]]; then
    if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
        ANALYZER_PYTHON="$REPO_DIR/.venv/bin/python"
    else
        ANALYZER_PYTHON="/opt/notable-analyzer/venv/bin/python"
    fi
fi
[[ -x "$ANALYZER_PYTHON" ]] || err "Python interpreter is not executable: $ANALYZER_PYTHON"

if [[ -z "$POSTGRES_PASSWORD" ]]; then
    POSTGRES_PASSWORD="$("$ANALYZER_PYTHON" - <<'PY'
import secrets

print(secrets.token_urlsafe(24))
PY
)"
fi

cleanup() {
    if [[ "$KEEP_CONTAINER" != "true" ]]; then
        "$DOCKER_BIN" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

if "$DOCKER_BIN" ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    err "Container already exists: $CONTAINER_NAME"
fi

info "Starting disposable pgvector container $CONTAINER_NAME on 127.0.0.1:$POSTGRES_PORT"
"$DOCKER_BIN" run -d --rm \
    --name "$CONTAINER_NAME" \
    -e "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
    -e "POSTGRES_DB=$POSTGRES_DB" \
    -p "127.0.0.1:$POSTGRES_PORT:5432" \
    "$DOCKER_IMAGE" >/dev/null

# Wait until initdb/entrypoint finish and `POSTGRES_DB` exists. Using
# `pg_isready -d "$POSTGRES_DB"` alone can race the official image's init
# restart cycle; connecting with `psql` matches when the smoke DSN will work.
for _attempt in $(seq 1 120); do
    if "$DOCKER_BIN" exec "$CONTAINER_NAME" \
        psql -v ON_ERROR_STOP=1 -U postgres -d "$POSTGRES_DB" -c "SELECT 1" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! "$DOCKER_BIN" exec "$CONTAINER_NAME" \
    psql -v ON_ERROR_STOP=1 -U postgres -d "$POSTGRES_DB" -c "SELECT 1" >/dev/null 2>&1; then
    "$DOCKER_BIN" logs "$CONTAINER_NAME" --tail 80 >&2 || true
    err "Postgres did not become ready."
fi

export PYTHONPATH="$WORKSPACE_DIR:${PYTHONPATH:-}"
export SMOKE_DSN="postgresql://postgres:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"
export SMOKE_SCHEMA
export SMOKE_TABLE
export STATEMENT_TIMEOUT_MS

info "Running live ingest and retrieval smoke"
"$ANALYZER_PYTHON" - <<'PY'
from __future__ import annotations

import os
import re

import psycopg

from onprem_rag_notable_analysis.future.chunking import ChunkRecord
from onprem_rag_notable_analysis.future.postgres_ingest import build_postgres_index
from onprem_rag_notable_analysis.future.postgres_retrieval import PostgresRAGContextProvider
from onprem_rag_notable_analysis.future.rag_config import RAGConfig


class SmokeEmbeddingModel:
    """Small deterministic embedding model for DB-path validation."""

    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "powershell" in lowered or "encodedcommand" in lowered:
                vectors.append([1.0, 0.0, 0.0])
            elif "authentication" in lowered:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


dsn = os.environ["SMOKE_DSN"]
schema = os.environ["SMOKE_SCHEMA"]
table = os.environ["SMOKE_TABLE"]
timeout_ms = int(os.environ["STATEMENT_TIMEOUT_MS"])
identifier_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
if not identifier_re.fullmatch(schema):
    raise SystemExit("SMOKE_SCHEMA must be a simple PostgreSQL identifier.")
if not identifier_re.fullmatch(table):
    raise SystemExit("SMOKE_TABLE must be a simple PostgreSQL identifier.")

chunks = [
    ChunkRecord(
        doc_id="soc-sop",
        chunk_id="soc-sop::powershell",
        title="SOC SOP",
        section_path="PowerShell",
        source_file="soc_sop.txt",
        text="PowerShell encodedcommand triage procedure for analyst review.",
    ),
    ChunkRecord(
        doc_id="soc-sop",
        chunk_id="soc-sop::authentication",
        title="SOC SOP",
        section_path="Authentication",
        source_file="soc_sop.txt",
        text="Authentication lockout triage steps for identity alerts.",
    ),
]

inserted = build_postgres_index(
    chunks=chunks,
    postgres_dsn=dsn,
    postgres_schema=schema,
    postgres_chunks_table=table,
    postgres_fts_config="english",
    vector_dimensions=3,
    embedding_model_name="smoke-embedding",
    embedding_batch_size=2,
    postgres_statement_timeout_ms=timeout_ms,
    ensure_schema=True,
    embedding_model=SmokeEmbeddingModel(),
)

with psycopg.connect(dsn, connect_timeout=5) as conn:
    extension = conn.execute(
        "SELECT extname FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()[0]
    row_count = conn.execute(
        f'SELECT count(*) FROM "{schema}"."{table}"'
    ).fetchone()[0]

provider = PostgresRAGContextProvider(
    RAGConfig(
        enabled=True,
        backend="postgres",
        postgres_dsn=dsn,
        postgres_schema=schema,
        postgres_chunks_table=table,
        postgres_fts_config="english",
        postgres_statement_timeout_ms=timeout_ms,
        vector_dimensions=3,
        max_snippets_120b=2,
        context_budget_chars_120b=1200,
    ),
    embedding_model=SmokeEmbeddingModel(),
)
context = provider.build_context(
    alert_text="PowerShell EncodedCommand alert from 10.0.0.1",
    llm_model_name="gemma-4-31B-it",
)

assert extension == "vector", extension
assert inserted == 2, inserted
assert row_count == 2, row_count
assert "SOC_OPERATIONAL_CONTEXT" in context, context
assert "PowerShell encodedcommand triage procedure" in context, context

print("extension=vector")
print("inserted=2")
print("row_count=2")
print("context=ok")
PY

info "Postgres RAG smoke passed."
