#!/usr/bin/env bash
# Reset mutable on-prem application data while preserving the installed stack.
#
# Clears:
#   - all tables in CASE_POSTGRES_SCHEMA (cases, derived case chunks, chats)
#   - all tables in notable_dispositions when that optional schema exists
#   - files and other non-directory entries under configured incoming,
#     processed, quarantine, reports, archive, and side-effect idempotency
#     directories
#
# Preserves:
#   - PostgreSQL RAG schemas, including RAG_POSTGRES_SCHEMA/notable_rag
#   - SQLite/FAISS RAG indexes and all knowledge-base source/index directories
#   - models, caches, code, virtual environments, systemd/nginx configuration,
#     TLS material, Basic Auth credentials, and analyzer/portal env files
#   - browser-local portal storage (clear site data separately when required)
#   - runtime directory trees, including archive/processed, archive/quarantine,
#     and archive/reports
#
# Safety:
#   - dry-run is the default
#   - --execute and an exact confirmation are required for deletion
#   - a timestamped backup is created unless --skip-backup is explicit
#   - configured paths are parsed without sourcing config.env
#   - broad, relative, and overlapping reset directories are rejected
#   - only INCOMING_DIR may be a symlink, and its resolved target must match the
#     supported SFTP incoming path
set -euo pipefail
IFS=$'\n\t'

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
BACKUP_ROOT="${BACKUP_ROOT:-/root/notable-reset-backups}"
EXPECTED_INCOMING_SYMLINK_TARGET="${EXPECTED_INCOMING_SYMLINK_TARGET:-/var/sftp/soar/incoming}"
EXECUTE=false
ASSUME_YES=false
SKIP_BACKUP=false
SERVICES_STOPPED=false
declare -A WAS_ACTIVE=()

usage() {
    cat <<'EOF'
Usage: reset_onprem_app_data.sh [options]

Preview the reset plan (default):
  sudo bash scripts/reset_onprem_app_data.sh

Execute with an interactive confirmation and backup:
  sudo bash scripts/reset_onprem_app_data.sh --execute

Options:
  --config-env PATH  Analyzer config file (default: /etc/notable-analyzer/config.env)
  --backup-root PATH Backup parent directory (default: /root/notable-reset-backups)
  --execute          Perform the reset; without this option, only print the plan
  --yes              Skip the interactive prompt; valid only with --execute
  --skip-backup      Execute without a recovery backup; valid only with --execute
  -h, --help         Show this help

The reset preserves RAG PostgreSQL schemas, SQLite/FAISS indexes, knowledge-base
content, models, caches, code, configuration, credentials, and TLS material.

Environment override for an approved non-default SFTP layout:
  EXPECTED_INCOMING_SYMLINK_TARGET
EOF
}

err() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "  $*"
}

require_arg_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || err "Missing value for $option"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || err "Missing required command: $1"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config-env)
            require_arg_value "$1" "${2:-}"
            CONFIG_ENV="$2"
            shift 2
            ;;
        --backup-root)
            require_arg_value "$1" "${2:-}"
            BACKUP_ROOT="$2"
            shift 2
            ;;
        --execute)
            EXECUTE=true
            shift
            ;;
        --yes)
            ASSUME_YES=true
            shift
            ;;
        --skip-backup)
            SKIP_BACKUP=true
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

if [[ "$EXECUTE" != "true" && "$ASSUME_YES" == "true" ]]; then
    err "--yes requires --execute"
fi
if [[ "$EXECUTE" != "true" && "$SKIP_BACKUP" == "true" ]]; then
    err "--skip-backup requires --execute"
fi

require_command python3
[[ -f "$CONFIG_ENV" ]] || err "Missing config file: $CONFIG_ENV"

tmpdir="$(mktemp -d)"

restore_services() {
    local unit
    local failed=0
    local restart_order=(
        notable-analyzer.service
        notable-portal.service
        notable-disposition-sync.service
        notable-closed-ticket-sync.service
        notable-retention.service
        notable-disposition-sync.timer
        notable-closed-ticket-sync.timer
        notable-retention.timer
    )

    if [[ "$SERVICES_STOPPED" != "true" ]]; then
        return 0
    fi

    for unit in "${restart_order[@]}"; do
        if [[ "${WAS_ACTIVE[$unit]:-false}" == "true" ]]; then
            info "Restarting $unit"
            if ! systemctl start "$unit"; then
                echo "ERROR: Failed to restart $unit" >&2
                failed=1
            fi
        fi
    done
    SERVICES_STOPPED=false
    return "$failed"
}

cleanup() {
    local exit_status=$?
    if [[ "$SERVICES_STOPPED" == "true" ]]; then
        restore_services || exit_status=1
    fi
    rm -rf -- "$tmpdir"
    exit "$exit_status"
}
trap cleanup EXIT

python3 - \
    "$CONFIG_ENV" \
    "$EXPECTED_INCOMING_SYMLINK_TARGET" \
    "$tmpdir/reset-values" <<'PY'
import os
import re
import shlex
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

config_path = Path(sys.argv[1])
expected_incoming_target_raw = sys.argv[2]
output_path = Path(sys.argv[3])


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise SystemExit(
                f"Invalid env line {line_number} in {path}: {exc}"
            ) from exc
        if tokens and tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise SystemExit(
                f"Invalid env line {line_number} in {path}: expected KEY=VALUE."
            )
        key, value = tokens[0].split("=", 1)
        if not key.isidentifier():
            raise SystemExit(
                f"Invalid env line {line_number} in {path}: invalid key {key!r}."
            )
        values[key] = value
    return values


def simple_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value or ""):
        raise SystemExit(f"{label} must be a simple PostgreSQL identifier.")
    return value


def database_from_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise SystemExit(
            "CASE_POSTGRES_DSN must use postgresql:// or postgres://."
        )
    return simple_identifier(
        unquote((parsed.path or "").lstrip("/")),
        "CASE_POSTGRES_DSN database",
    )


blocked_paths = {
    "/",
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/home",
    "/opt",
    "/proc",
    "/root",
    "/run",
    "/srv",
    "/sys",
    "/tmp",
    "/usr",
    "/var",
    "/var/notables",
}


def validate_reset_path(value: str, label: str) -> str:
    if "\x00" in value or "\n" in value:
        raise SystemExit(f"{label} contains an invalid character.")
    path = PurePosixPath(value)
    if not path.is_absolute():
        raise SystemExit(f"{label} must be an absolute path.")
    if ".." in path.parts:
        raise SystemExit(f"{label} must not contain '..'.")
    normalized = os.path.normpath(value)
    if normalized in blocked_paths or len(PurePosixPath(normalized).parts) < 3:
        raise SystemExit(f"{label} is too broad to reset safely: {normalized}")
    return normalized


expected_incoming_target = validate_reset_path(
    expected_incoming_target_raw,
    "EXPECTED_INCOMING_SYMLINK_TARGET",
)


def reset_path(value: str, label: str) -> str:
    normalized = validate_reset_path(value, label)
    if not os.path.islink(normalized):
        return normalized
    if label != "INCOMING_DIR":
        raise SystemExit(f"{label} must not be a symlink: {normalized}")
    resolved = os.path.realpath(normalized)
    if resolved != expected_incoming_target:
        raise SystemExit(
            "INCOMING_DIR symlink target does not match the approved target: "
            f"resolved={resolved}, expected={expected_incoming_target}"
        )
    if not os.path.isdir(resolved):
        raise SystemExit(
            f"INCOMING_DIR symlink target is not an existing directory: {resolved}"
        )
    return validate_reset_path(resolved, "INCOMING_DIR resolved target")


def protected_path(value: str, label: str) -> str:
    if "\x00" in value or "\n" in value:
        raise SystemExit(f"{label} contains an invalid character.")
    path = PurePosixPath(value)
    if not path.is_absolute():
        raise SystemExit(f"{label} must be an absolute path.")
    if ".." in path.parts:
        raise SystemExit(f"{label} must not contain '..'.")
    return os.path.normpath(value)


config = parse_env(config_path)
database = database_from_dsn(
    config.get(
        "CASE_POSTGRES_DSN",
        "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
    )
)
case_schema = simple_identifier(
    config.get("CASE_POSTGRES_SCHEMA", "notable_cases"),
    "CASE_POSTGRES_SCHEMA",
)
rag_schema = simple_identifier(
    config.get("RAG_POSTGRES_SCHEMA", "notable_rag"),
    "RAG_POSTGRES_SCHEMA",
)
if rag_schema in {case_schema, "notable_dispositions"}:
    raise SystemExit(
        "RAG_POSTGRES_SCHEMA must be separate from reset application schemas."
    )

path_items = [
    ("INCOMING_DIR", config.get("INCOMING_DIR", "/var/notables/incoming")),
    ("PROCESSED_DIR", config.get("PROCESSED_DIR", "/var/notables/processed")),
    ("QUARANTINE_DIR", config.get("QUARANTINE_DIR", "/var/notables/quarantine")),
    ("REPORT_DIR", config.get("REPORT_DIR", "/var/notables/reports")),
    ("ARCHIVE_DIR", config.get("ARCHIVE_DIR", "/var/notables/archive")),
    (
        "SIDE_EFFECT_IDEMPOTENCY_DIR",
        config.get("SIDE_EFFECT_IDEMPOTENCY_DIR", "/var/notables/idempotency"),
    ),
]
validated_paths = [(key, reset_path(value, key)) for key, value in path_items]
protected_items = [
    (
        "RAG_SQLITE_PATH",
        config.get(
            "RAG_SQLITE_PATH",
            "/opt/llm-notable-analysis/knowledge_base/index/kb.sqlite3",
        ),
    ),
    (
        "RAG_FAISS_PATH",
        config.get(
            "RAG_FAISS_PATH",
            "/opt/llm-notable-analysis/knowledge_base/index/kb.faiss",
        ),
    ),
    (
        "SPL_QUERY_RAG_SOURCE_DIR",
        config.get(
            "SPL_QUERY_RAG_SOURCE_DIR",
            "/opt/llm-notable-analysis/knowledge_base/spl_query_source_docs",
        ),
    ),
    (
        "SPL_QUERY_RAG_INDEX_DIR",
        config.get(
            "SPL_QUERY_RAG_INDEX_DIR",
            "/opt/llm-notable-analysis/knowledge_base/spl_query_index",
        ),
    ),
    (
        "ELASTICSEARCH_GROUNDING_SOURCE_DIR",
        config.get(
            "ELASTICSEARCH_GROUNDING_SOURCE_DIR",
            "/opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs",
        ),
    ),
]
protected_paths = [
    (key, protected_path(value, key)) for key, value in protected_items
]

for index, (left_key, left_path) in enumerate(validated_paths):
    left = PurePosixPath(left_path)
    for right_key, right_path in validated_paths[index + 1 :]:
        right = PurePosixPath(right_path)
        if left == right or left in right.parents or right in left.parents:
            raise SystemExit(
                "Reset directories must be distinct and non-overlapping: "
                f"{left_key}={left_path}, {right_key}={right_path}"
            )

for reset_key, reset_value in validated_paths:
    reset = PurePosixPath(reset_value)
    for protected_key, protected_value in protected_paths:
        protected = PurePosixPath(protected_value)
        if (
            reset == protected
            or reset in protected.parents
            or protected in reset.parents
        ):
            raise SystemExit(
                "A protected RAG path overlaps a reset directory: "
                f"{reset_key}={reset_value}, "
                f"{protected_key}={protected_value}"
            )

values = [database, case_schema, rag_schema]
values.extend(f"{key}={value}" for key, value in validated_paths)
values.extend(f"{key}={value}" for key, value in protected_paths)
with output_path.open("wb") as output:
    for value in values:
        output.write(value.encode("utf-8"))
        output.write(b"\0")
PY

mapfile -d '' -t reset_values < "$tmpdir/reset-values"
[[ "${#reset_values[@]}" -eq 14 ]] || err "Failed to parse reset configuration"

CASE_DATABASE="${reset_values[0]}"
CASE_SCHEMA="${reset_values[1]}"
RAG_SCHEMA="${reset_values[2]}"
declare -a RESET_LABELS=()
declare -a RESET_DIRS=()
declare -a PROTECTED_RAG_LABELS=()
declare -a PROTECTED_RAG_PATHS=()

for entry in "${reset_values[@]:3:6}"; do
    RESET_LABELS+=("${entry%%=*}")
    RESET_DIRS+=("${entry#*=}")
done
for entry in "${reset_values[@]:9:5}"; do
    PROTECTED_RAG_LABELS+=("${entry%%=*}")
    PROTECTED_RAG_PATHS+=("${entry#*=}")
done

print_plan() {
    local index
    echo "On-prem application data reset plan"
    info "Mode: $([[ "$EXECUTE" == "true" ]] && echo execute || echo dry-run)"
    info "PostgreSQL database: $CASE_DATABASE"
    info "Clear all tables in schema: $CASE_SCHEMA"
    info "Clear all tables in optional schema: notable_dispositions"
    for index in "${!RESET_DIRS[@]}"; do
        info "Clear ${RESET_LABELS[$index]} contents: ${RESET_DIRS[$index]}"
    done
    info "Preserve PostgreSQL RAG schema: $RAG_SCHEMA"
    for index in "${!PROTECTED_RAG_PATHS[@]}"; do
        info "Preserve ${PROTECTED_RAG_LABELS[$index]}: ${PROTECTED_RAG_PATHS[$index]}"
    done
    info "Preserve models, caches, code, config, credentials, and TLS"
    info "Browser-local portal storage is not changed"
    if [[ "$SKIP_BACKUP" == "true" ]]; then
        info "Backup: skipped by explicit request"
    else
        info "Backup root: $BACKUP_ROOT"
    fi
}

print_plan

if [[ "$EXECUTE" != "true" ]]; then
    echo
    info "Dry-run only; no data was changed. Add --execute to perform the reset."
    exit 0
fi

[[ "$EUID" -eq 0 ]] || err "--execute must run as root"
require_command systemctl
require_command runuser
require_command psql
require_command find
if [[ "$SKIP_BACKUP" != "true" ]]; then
    require_command pg_dump
    require_command tar
fi

[[ "$BACKUP_ROOT" == /* ]] || err "--backup-root must be an absolute path"
case "$BACKUP_ROOT" in
    /|/bin|/boot|/dev|/etc|/home|/opt|/proc|/root|/run|/srv|/sys|/tmp|/usr|/var|/var/notables)
        err "--backup-root is too broad: $BACKUP_ROOT"
        ;;
esac
if [[ -L "$BACKUP_ROOT" ]]; then
    err "--backup-root must not be a symlink: $BACKUP_ROOT"
fi

for reset_dir in "${RESET_DIRS[@]}"; do
    case "$BACKUP_ROOT/" in
        "$reset_dir/"*)
            err "--backup-root must not be inside a reset directory: $BACKUP_ROOT"
            ;;
    esac
done

case_table_count="$(
    runuser -u postgres -- psql \
        --dbname "$CASE_DATABASE" \
        --tuples-only \
        --no-align \
        --set ON_ERROR_STOP=1 \
        --command "SELECT count(*) FROM pg_tables WHERE schemaname = '$CASE_SCHEMA';"
)"
[[ "$case_table_count" =~ ^[1-9][0-9]*$ ]] || \
    err "No tables found in application schema $CASE_SCHEMA on $CASE_DATABASE"

if [[ "$ASSUME_YES" != "true" ]]; then
    echo
    echo "This permanently clears the listed server-side application data."
    read -r -p "Type RESET ONPREM APP DATA to continue: " confirmation
    [[ "$confirmation" == "RESET ONPREM APP DATA" ]] || err "Confirmation did not match"
fi

stop_order=(
    notable-retention.timer
    notable-disposition-sync.timer
    notable-closed-ticket-sync.timer
    notable-retention.service
    notable-disposition-sync.service
    notable-closed-ticket-sync.service
    notable-portal.service
    notable-analyzer.service
)

SERVICES_STOPPED=true
for unit in "${stop_order[@]}"; do
    load_state="$(systemctl show "$unit" --property LoadState --value 2>/dev/null || true)"
    if [[ -n "$load_state" && "$load_state" != "not-found" ]]; then
        if systemctl is-active --quiet "$unit"; then
            WAS_ACTIVE["$unit"]=true
            info "Stopping $unit"
            systemctl stop "$unit"
        else
            WAS_ACTIVE["$unit"]=false
        fi
    fi
done

if [[ "$SKIP_BACKUP" != "true" ]]; then
    reset_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    backup_dir="$BACKUP_ROOT/$reset_stamp"
    install -d -m 0700 "$backup_dir"

    schema_args=("--schema=$CASE_SCHEMA")
    disposition_exists="$(
        runuser -u postgres -- psql \
            --dbname "$CASE_DATABASE" \
            --tuples-only \
            --no-align \
            --set ON_ERROR_STOP=1 \
            --command "SELECT CASE WHEN to_regnamespace('notable_dispositions') IS NULL THEN 'false' ELSE 'true' END;"
    )"
    if [[ "$disposition_exists" == "true" ]]; then
        schema_args+=("--schema=notable_dispositions")
    fi
    closed_ticket_exists="$(
        runuser -u postgres -- psql \
            --dbname "$CASE_DATABASE" \
            --tuples-only \
            --no-align \
            --set ON_ERROR_STOP=1 \
            --command "SELECT CASE WHEN to_regnamespace('notable_closed_tickets') IS NULL THEN 'false' ELSE 'true' END;"
    )"
    if [[ "$closed_ticket_exists" == "true" ]]; then
        schema_args+=("--schema=notable_closed_tickets")
    fi

    info "Backing up PostgreSQL app data to $backup_dir/postgres-app-data.sql"
    runuser -u postgres -- pg_dump \
        --dbname "$CASE_DATABASE" \
        --data-only \
        "${schema_args[@]}" \
        > "$backup_dir/postgres-app-data.sql"
    chmod 0600 "$backup_dir/postgres-app-data.sql"

    existing_relative_dirs=()
    for reset_dir in "${RESET_DIRS[@]}"; do
        if [[ -d "$reset_dir" ]]; then
            existing_relative_dirs+=("${reset_dir#/}")
        fi
    done
    if [[ "${#existing_relative_dirs[@]}" -gt 0 ]]; then
        info "Backing up runtime directories to $backup_dir/runtime-data.tar.gz"
        tar --create --gzip \
            --file "$backup_dir/runtime-data.tar.gz" \
            --directory / \
            -- "${existing_relative_dirs[@]}"
        chmod 0600 "$backup_dir/runtime-data.tar.gz"
    fi

    {
        printf 'created_at_utc=%s\n' "$reset_stamp"
        printf 'database=%s\n' "$CASE_DATABASE"
        printf 'case_schema=%s\n' "$CASE_SCHEMA"
        printf 'rag_preserved=true\n'
        printf 'config_env=%s\n' "$CONFIG_ENV"
        printf '%s\n' "${reset_values[@]:3:6}"
        printf 'rag_schema=%s\n' "$RAG_SCHEMA"
        printf '%s\n' "${reset_values[@]:9:5}"
    } > "$backup_dir/reset-manifest.txt"
    chmod 0600 "$backup_dir/reset-manifest.txt"
fi

for reset_dir in "${RESET_DIRS[@]}"; do
    if [[ -d "$reset_dir" ]]; then
        info "Clearing files under $reset_dir while preserving directories"
        find "$reset_dir" -xdev -mindepth 1 ! -type d -delete
    else
        info "Directory does not exist; skipping $reset_dir"
    fi
done

info "Clearing PostgreSQL application schemas"
runuser -u postgres -- psql \
    --dbname "$CASE_DATABASE" \
    --set ON_ERROR_STOP=1 \
    --set case_schema="$CASE_SCHEMA" <<'SQL'
BEGIN;
SELECT format('TRUNCATE TABLE %I.%I RESTART IDENTITY CASCADE;', schemaname, tablename)
FROM pg_tables
WHERE schemaname IN (:'case_schema', 'notable_dispositions', 'notable_closed_tickets')
ORDER BY schemaname, tablename
\gexec
COMMIT;
SQL

restore_services || err "Application data reset completed, but one or more services failed to restart"

echo
info "On-prem application data reset completed."
if [[ "$SKIP_BACKUP" != "true" ]]; then
    info "Recovery backup: $backup_dir"
fi
info "RAG indexes and knowledge-base data were preserved."
