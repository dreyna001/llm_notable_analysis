#!/usr/bin/env bash
# Prepare the local PostgreSQL RAG backend and run config-bound corpus ingestion.
set -euo pipefail
IFS=$'\n\t'

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
ANALYZER_PYTHON="${ANALYZER_PYTHON:-/opt/notable-analyzer/venv/bin/python}"
SOURCE_DIR="${SOURCE_DIR:-/opt/llm-notable-analysis/knowledge_base/source_docs}"
INDEX_DIR="${INDEX_DIR:-/opt/llm-notable-analysis/knowledge_base/index}"
POSTGRES_ADMIN_USER="${POSTGRES_ADMIN_USER:-postgres}"
POSTGRES_ADMIN_DB="${POSTGRES_ADMIN_DB:-postgres}"
SKIP_DB_SETUP="${SKIP_DB_SETUP:-false}"
SKIP_INGEST="${SKIP_INGEST:-false}"

usage() {
    cat <<'EOF'
Usage: setup_postgres_rag.sh [options]

Options:
  --config-env PATH       Analyzer config.env path
  --source-dir PATH       Knowledge-base source docs directory
  --index-dir PATH        Ingest artifact output directory
  --analyzer-python PATH  Analyzer venv Python
  --skip-db-setup         Only run corpus ingest
  --skip-ingest           Only create database/schema/extension
  -h, --help              Show this help

Environment overrides:
  CONFIG_ENV, SOURCE_DIR, INDEX_DIR, ANALYZER_PYTHON,
  POSTGRES_ADMIN_USER, POSTGRES_ADMIN_DB, SKIP_DB_SETUP, SKIP_INGEST
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
        --config-env)
            require_arg_value "$1" "${2:-}"
            CONFIG_ENV="$2"
            shift 2
            ;;
        --source-dir)
            require_arg_value "$1" "${2:-}"
            SOURCE_DIR="$2"
            shift 2
            ;;
        --index-dir)
            require_arg_value "$1" "${2:-}"
            INDEX_DIR="$2"
            shift 2
            ;;
        --analyzer-python)
            require_arg_value "$1" "${2:-}"
            ANALYZER_PYTHON="$2"
            shift 2
            ;;
        --skip-db-setup)
            SKIP_DB_SETUP="true"
            shift
            ;;
        --skip-ingest)
            SKIP_INGEST="true"
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

[[ -f "$CONFIG_ENV" ]] || err "Missing config file: $CONFIG_ENV"
[[ -x "$ANALYZER_PYTHON" ]] || err "Analyzer Python is not executable: $ANALYZER_PYTHON"

tmpdir="$(mktemp -d)"
cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT

generate_sql() {
    "$ANALYZER_PYTHON" - "$CONFIG_ENV" "$tmpdir/admin.sql" "$tmpdir/schema.sql" "$tmpdir/meta.env" <<'PY'
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

config_path = Path(sys.argv[1])
admin_sql_path = Path(sys.argv[2])
schema_sql_path = Path(sys.argv[3])
meta_path = Path(sys.argv[4])


def parse_config_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise SystemExit(f"Invalid config.env line {line_number}: {exc}") from exc
        if not tokens:
            continue
        if tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise SystemExit(f"Invalid config.env line {line_number}: expected KEY=VALUE.")
        key, value = tokens[0].split("=", 1)
        if not key.isidentifier():
            raise SystemExit(f"Invalid config.env line {line_number}: invalid key {key!r}.")
        values[key] = value
    return values


def require_simple_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value or ""):
        raise SystemExit(f"{label} must be a simple PostgreSQL identifier.")
    return value


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


config = parse_config_env(config_path)
dsn = config.get("RAG_POSTGRES_DSN", "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag")
schema = require_simple_identifier(config.get("RAG_POSTGRES_SCHEMA", "notable_rag"), "RAG_POSTGRES_SCHEMA")
parsed = urlparse(dsn)
if parsed.scheme not in {"postgresql", "postgres"}:
    raise SystemExit("RAG_POSTGRES_DSN must use postgresql:// or postgres://.")
database = require_simple_identifier(unquote((parsed.path or "").lstrip("/")), "RAG_POSTGRES_DSN database")
role = require_simple_identifier(unquote(parsed.username or ""), "RAG_POSTGRES_DSN username")
password = unquote(parsed.password) if parsed.password else ""

role_ident = quote_ident(role)
database_ident = quote_ident(database)
schema_ident = quote_ident(schema)

admin_statements = [
    "DO $$",
    "BEGIN",
    f"    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {quote_literal(role)}) THEN",
    f"        CREATE ROLE {role_ident} LOGIN;",
    "    END IF;",
    "END",
    "$$;",
]
if password:
    admin_statements.append(f"ALTER ROLE {role_ident} PASSWORD {quote_literal(password)};")
admin_statements.extend(
    [
        "SELECT 'CREATE DATABASE ' || quote_ident(datname) || ' OWNER ' || quote_ident(owner_name)",
        f"FROM (SELECT {quote_literal(database)} AS datname, {quote_literal(role)} AS owner_name) values_to_create",
        f"WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = {quote_literal(database)})",
        "\\gexec",
    ]
)

schema_statements = [
    "CREATE EXTENSION IF NOT EXISTS vector;",
    f"CREATE SCHEMA IF NOT EXISTS {schema_ident} AUTHORIZATION {role_ident};",
    f"GRANT USAGE, CREATE ON SCHEMA {schema_ident} TO {role_ident};",
]

admin_sql_path.write_text("\n".join(admin_statements) + "\n", encoding="utf-8")
schema_sql_path.write_text("\n".join(schema_statements) + "\n", encoding="utf-8")
meta_path.write_text(f"RAG_DATABASE={shlex.quote(database)}\n", encoding="utf-8")
admin_sql_path.chmod(0o600)
schema_sql_path.chmod(0o600)
meta_path.chmod(0o600)
PY
}

run_psql_as_admin() {
    local database="$1"
    local file="$2"
    if [[ "$(id -un)" == "$POSTGRES_ADMIN_USER" ]]; then
        psql -v ON_ERROR_STOP=1 -d "$database" < "$file"
    else
        sudo -u "$POSTGRES_ADMIN_USER" psql -v ON_ERROR_STOP=1 -d "$database" < "$file"
    fi
}

if [[ "$SKIP_DB_SETUP" != "true" ]]; then
    require_command psql
    if [[ "$(id -un)" != "$POSTGRES_ADMIN_USER" ]]; then
        require_command sudo
    fi
    generate_sql
    # shellcheck disable=SC1091
    source "$tmpdir/meta.env"
    info "Creating PostgreSQL role/database if needed"
    run_psql_as_admin "$POSTGRES_ADMIN_DB" "$tmpdir/admin.sql"
    info "Creating pgvector extension and configured schema"
    run_psql_as_admin "$RAG_DATABASE" "$tmpdir/schema.sql"
else
    info "SKIP_DB_SETUP=true; skipping database/schema setup"
fi

if [[ "$SKIP_INGEST" != "true" ]]; then
    mkdir -p "$SOURCE_DIR" "$INDEX_DIR"
    info "Running Postgres RAG corpus ingest from $SOURCE_DIR"
    ingest_args=(
        --config-env "$CONFIG_ENV"
        --backend postgres
        --source-dir "$SOURCE_DIR"
        --index-dir "$INDEX_DIR"
    )
    "$ANALYZER_PYTHON" -m onprem_rag_notable_analysis.future.corpus_ingest \
        "${ingest_args[@]}"
else
    info "SKIP_INGEST=true; skipping corpus ingest"
fi

info "PostgreSQL RAG setup complete"
