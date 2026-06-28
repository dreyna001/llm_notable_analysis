#!/usr/bin/env bash
# Prepare PostgreSQL for the analyst portal case archive schema.
set -euo pipefail
IFS=$'\n\t'

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
PORTAL_ENV="${PORTAL_ENV:-/etc/notable-analyzer/portal.env}"
SCHEMA_SQL="${SCHEMA_SQL:-}"
POSTGRES_ADMIN_USER="${POSTGRES_ADMIN_USER:-postgres}"
POSTGRES_ADMIN_DB="${POSTGRES_ADMIN_DB:-postgres}"
SKIP_DB_SETUP="${SKIP_DB_SETUP:-false}"

usage() {
    cat <<'EOF'
Usage: setup_postgres_case_archive.sh [options]

Options:
  --config-env PATH   Analyzer config.env path (CASE_POSTGRES_* for analyzer role)
  --portal-env PATH   Portal portal.env path (CASE_POSTGRES_* for portal role)
  --schema-sql PATH   Override deploy/postgres/notable_cases_schema.sql
  --skip-db-setup     Print planned actions only (reserved; currently no-op ingest)
  -h, --help          Show this help

Environment overrides:
  CONFIG_ENV, PORTAL_ENV, SCHEMA_SQL, POSTGRES_ADMIN_USER, POSTGRES_ADMIN_DB,
  SKIP_DB_SETUP
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
        --portal-env)
            require_arg_value "$1" "${2:-}"
            PORTAL_ENV="$2"
            shift 2
            ;;
        --schema-sql)
            require_arg_value "$1" "${2:-}"
            SCHEMA_SQL="$2"
            shift 2
            ;;
        --skip-db-setup)
            SKIP_DB_SETUP="true"
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
[[ -f "$PORTAL_ENV" ]] || err "Missing portal env file: $PORTAL_ENV"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
if [[ -z "$SCHEMA_SQL" ]]; then
    SCHEMA_SQL="$repo_dir/deploy/postgres/notable_cases_schema.sql"
fi
[[ -f "$SCHEMA_SQL" ]] || err "Missing schema SQL: $SCHEMA_SQL"

tmpdir="$(mktemp -d)"
cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT

generate_sql() {
    python3 - "$CONFIG_ENV" "$PORTAL_ENV" "$tmpdir/admin.sql" "$tmpdir/grants.sql" "$tmpdir/meta.env" <<'PY'
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

config_path = Path(sys.argv[1])
portal_path = Path(sys.argv[2])
admin_sql_path = Path(sys.argv[3])
grants_sql_path = Path(sys.argv[4])
meta_path = Path(sys.argv[5])


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise SystemExit(f"Invalid env line {line_number} in {path}: {exc}") from exc
        if not tokens:
            continue
        if tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise SystemExit(
                f"Invalid env line {line_number} in {path}: expected KEY=VALUE."
            )
        key, value = tokens[0].split("=", 1)
        if not key.isidentifier():
            raise SystemExit(f"Invalid env line {line_number} in {path}: invalid key {key!r}.")
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


def parse_dsn(dsn: str, label: str) -> tuple[str, str, str]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise SystemExit(f"{label} must use postgresql:// or postgres://.")
    database = require_simple_identifier(
        unquote((parsed.path or "").lstrip("/")),
        f"{label} database",
    )
    role = require_simple_identifier(
        unquote(parsed.username or ""),
        f"{label} username",
    )
    password = unquote(parsed.password) if parsed.password else ""
    return database, role, password


config = parse_env(config_path)
portal = parse_env(portal_path)
schema = require_simple_identifier(
    config.get("CASE_POSTGRES_SCHEMA", "notable_cases"),
    "CASE_POSTGRES_SCHEMA",
)
analyzer_dsn = config.get(
    "CASE_POSTGRES_DSN",
    "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
)
portal_dsn = portal.get(
    "CASE_POSTGRES_DSN",
    "postgresql://notable_portal@127.0.0.1:5432/notable_rag",
)

database, analyzer_role, analyzer_password = parse_dsn(analyzer_dsn, "CASE_POSTGRES_DSN")
portal_database, portal_role, portal_password = parse_dsn(
    portal_dsn,
    "portal CASE_POSTGRES_DSN",
)
if portal_database != database:
    raise SystemExit(
        "Analyzer and portal CASE_POSTGRES_DSN must use the same database name. "
        f"Found analyzer={database!r}, portal={portal_database!r}."
    )

schema_ident = quote_ident(schema)
analyzer_ident = quote_ident(analyzer_role)
portal_ident = quote_ident(portal_role)
database_ident = quote_ident(database)

admin_statements = [
    "DO $$",
    "BEGIN",
    f"    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {quote_literal(analyzer_role)}) THEN",
    f"        CREATE ROLE {analyzer_ident} LOGIN;",
    "    END IF;",
    "END",
    "$$;",
]
if analyzer_password:
    admin_statements.append(
        f"ALTER ROLE {analyzer_ident} PASSWORD {quote_literal(analyzer_password)};"
    )

admin_statements.extend(
    [
        "DO $$",
        "BEGIN",
        f"    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {quote_literal(portal_role)}) THEN",
        f"        CREATE ROLE {portal_ident} LOGIN;",
        "    END IF;",
        "END",
        "$$;",
    ]
)
if portal_password:
    admin_statements.append(
        f"ALTER ROLE {portal_ident} PASSWORD {quote_literal(portal_password)};"
    )

admin_statements.extend(
    [
        "SELECT 'CREATE DATABASE ' || quote_ident(datname) || ' OWNER ' || quote_ident(owner_name)",
        f"FROM (SELECT {quote_literal(database)} AS datname, {quote_literal(analyzer_role)} AS owner_name) values_to_create",
        f"WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = {quote_literal(database)})",
        "\\gexec",
        f"GRANT CONNECT ON DATABASE {database_ident} TO {portal_ident};",
    ]
)

grant_statements = [
    f"GRANT USAGE ON SCHEMA {schema_ident} TO {portal_ident};",
    f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema_ident} TO {portal_ident};",
    f"GRANT INSERT, UPDATE, DELETE ON {schema_ident}.chat_sessions TO {portal_ident};",
    f"GRANT INSERT, DELETE ON {schema_ident}.chat_messages TO {portal_ident};",
    f"ALTER DEFAULT PRIVILEGES FOR ROLE {analyzer_ident} IN SCHEMA {schema_ident} "
    f"GRANT SELECT ON TABLES TO {portal_ident};",
]

admin_sql_path.write_text("\n".join(admin_statements) + "\n", encoding="utf-8")
grants_sql_path.write_text("\n".join(grant_statements) + "\n", encoding="utf-8")
meta_path.write_text(
    f"CASE_DATABASE={shlex.quote(database)}\n"
    f"ANALYZER_ROLE={shlex.quote(analyzer_role)}\n",
    encoding="utf-8",
)
for path in (admin_sql_path, grants_sql_path, meta_path):
    path.chmod(0o600)
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

if [[ "$SKIP_DB_SETUP" == "true" ]]; then
    info "SKIP_DB_SETUP=true; skipping PostgreSQL case archive setup"
    exit 0
fi

require_command psql
if [[ "$(id -un)" != "$POSTGRES_ADMIN_USER" ]]; then
    require_command sudo
fi

generate_sql
# shellcheck disable=SC1091
source "$tmpdir/meta.env"

info "Creating PostgreSQL roles/database for case archive if needed"
run_psql_as_admin "$POSTGRES_ADMIN_DB" "$tmpdir/admin.sql"
info "Applying case archive schema: $SCHEMA_SQL"
run_psql_as_admin "$CASE_DATABASE" "$SCHEMA_SQL"

DISPOSITIONS_SCHEMA_SQL="$repo_dir/deploy/postgres/dispositions_schema.sql"
[[ -f "$DISPOSITIONS_SCHEMA_SQL" ]] || err "Missing disposition schema SQL: $DISPOSITIONS_SCHEMA_SQL"
info "Applying disposition schema: $DISPOSITIONS_SCHEMA_SQL"
run_psql_as_admin "$CASE_DATABASE" "$DISPOSITIONS_SCHEMA_SQL"

disposition_grants_sql="$tmpdir/disposition_grants.sql"
cat > "$disposition_grants_sql" <<EOF
GRANT USAGE ON SCHEMA notable_dispositions TO "${ANALYZER_ROLE}";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA notable_dispositions TO "${ANALYZER_ROLE}";
ALTER DEFAULT PRIVILEGES IN SCHEMA notable_dispositions
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "${ANALYZER_ROLE}";
EOF
info "Granting analyzer role access to disposition schema"
run_psql_as_admin "$CASE_DATABASE" "$disposition_grants_sql"

info "Granting read-only portal role access to case archive tables"
run_psql_as_admin "$CASE_DATABASE" "$tmpdir/grants.sql"

info "PostgreSQL case archive setup complete"
