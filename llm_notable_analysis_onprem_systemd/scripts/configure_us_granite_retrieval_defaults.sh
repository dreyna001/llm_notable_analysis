#!/usr/bin/env bash
# Upsert IBM Granite retrieval defaults in analyzer config.env and portal.env.
# Requires pgvector chunk columns to already match the Granite 768 contract.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
PORTAL_ENV="${PORTAL_ENV:-/etc/notable-analyzer/portal.env}"
FORCE=false

EMBED_MODEL="ibm-granite/granite-embedding-english-r2"
RERANK_MODEL="ibm-granite/granite-embedding-reranker-english-r2"
VECTOR_DIMENSIONS="768"

usage() {
    cat <<'EOF'
Usage: configure_us_granite_retrieval_defaults.sh [options]

Upserts Granite retrieval defaults in analyzer config.env and portal.env:
  RAG_EMBEDDING_MODEL=ibm-granite/granite-embedding-english-r2
  RAG_RERANK_MODEL=ibm-granite/granite-embedding-reranker-english-r2
  RAG_VECTOR_DIMENSIONS=768
  CASE_QA_VECTOR_DIMENSIONS=768

Safe order (required unless --force):
  1. scripts/migrate_embedding_dimensions.sh --config-env PATH [--portal-env PATH]
  2. scripts/configure_us_granite_retrieval_defaults.sh --config-env PATH --portal-env PATH
  3. Run rebuild commands printed by step 1, then restart services

Options:
  --config-env PATH   Analyzer config.env (default: /etc/notable-analyzer/config.env)
  --portal-env PATH   Portal portal.env (default: /etc/notable-analyzer/portal.env)
  --force             Apply env defaults even when pgvector columns are not yet 768
  -h, --help          Show this help
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

upsert_env_value() {
    local file="$1"
    local key="$2"
    local value="$3"
    python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
new_line = f"{key}={value}"

if path.exists():
    lines = path.read_text(encoding="utf-8").splitlines()
else:
    lines = []

found = False
out = []
for line in lines:
    if line.startswith(f"{key}="):
        if not found:
            out.append(new_line)
            found = True
        continue
    out.append(line)

if not found:
    out.append(new_line)

path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
PY
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
        --force)
            FORCE=true
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
command -v python3 >/dev/null 2>&1 || err "Missing required command: python3"

if [[ "$FORCE" != "true" ]]; then
    if ! python3 "$SCRIPT_DIR/migrate_embedding_dimensions.py" \
        --config-env "$CONFIG_ENV" \
        --portal-env "$PORTAL_ENV" \
        --target-dim "$VECTOR_DIMENSIONS" \
        --dry-run >/dev/null 2>&1; then
        err "Unable to inspect pgvector schema. Fix database connectivity first."
    fi

    pending_migration="$(
        python3 - "$CONFIG_ENV" "$PORTAL_ENV" "$SCRIPT_DIR/migrate_embedding_dimensions.py" <<'PY'
import subprocess
import sys
from pathlib import Path

config_env = Path(sys.argv[1])
portal_env = Path(sys.argv[2])
script = Path(sys.argv[3])
completed = subprocess.run(
    [
        "python3",
        str(script),
        "--config-env",
        str(config_env),
        "--portal-env",
        str(portal_env),
        "--target-dim",
        "768",
        "--dry-run",
    ],
    check=False,
    capture_output=True,
    text=True,
)
output = completed.stdout + completed.stderr
if completed.returncode != 0:
    print("inspect_failed")
    raise SystemExit(0)
if "MIGRATE " in output:
    print("needs_migration")
else:
    print("ready")
PY
    )"

    if [[ "$pending_migration" == "inspect_failed" ]]; then
        err "Unable to inspect pgvector schema. Fix database connectivity first."
    fi
    if [[ "$pending_migration" == "needs_migration" ]]; then
        cat <<EOF >&2
ERROR: Postgres pgvector chunk columns are not yet migrated to vector(768).

Run migration first:
  scripts/migrate_embedding_dimensions.sh --config-env $CONFIG_ENV --portal-env $PORTAL_ENV

Then rerun this script. Use --force only when you accept a broken retrieval state.
EOF
        exit 1
    fi
fi

upsert_keys() {
    local file="$1"
    upsert_env_value "$file" "RAG_EMBEDDING_MODEL" "$EMBED_MODEL"
    upsert_env_value "$file" "RAG_RERANK_MODEL" "$RERANK_MODEL"
    upsert_env_value "$file" "RAG_VECTOR_DIMENSIONS" "$VECTOR_DIMENSIONS"
    upsert_env_value "$file" "CASE_QA_EMBEDDING_MODEL" "$EMBED_MODEL"
    upsert_env_value "$file" "CASE_QA_VECTOR_DIMENSIONS" "$VECTOR_DIMENSIONS"
}

upsert_keys "$CONFIG_ENV"
upsert_keys "$PORTAL_ENV"

info "Updated Granite retrieval defaults in:"
info "  $CONFIG_ENV"
info "  $PORTAL_ENV"

cat <<EOF >&2

Granite env defaults applied. Before enabling retrieval or portal Q&A:
  1. Rebuild KB lanes: scripts/setup_postgres_rag.sh --config-env $CONFIG_ENV
  2. Rebuild case chunks: /opt/notable-analyzer/venv/bin/python scripts/rebuild_case_chunks.py --all --config-env $CONFIG_ENV
  3. Rebuild closed-ticket chunks when enabled:
     /opt/notable-analyzer/venv/bin/python scripts/rebuild_closed_ticket_chunks.py --all --config-env $CONFIG_ENV
  4. Restart services: sudo systemctl restart notable-analyzer notable-portal

EOF

info "Restart services after rebuild: sudo systemctl restart notable-analyzer notable-portal"
