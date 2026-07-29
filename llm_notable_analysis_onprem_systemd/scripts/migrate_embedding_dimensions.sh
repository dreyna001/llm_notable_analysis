#!/usr/bin/env bash
# Idempotent pgvector dimension migration for on-prem chunk tables.
# Clears chunk rows only; preserves cases, tickets, attachments, chat, and source files.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
PORTAL_ENV="${PORTAL_ENV:-}"
TARGET_DIM=""
DRY_RUN=false

usage() {
    cat <<'EOF'
Usage: migrate_embedding_dimensions.sh [options]

Migrate on-prem pgvector chunk tables from Mixedbread 1024-dim embeddings to
IBM Granite 768-dim embeddings. Source records (cases, tickets, attachments,
chat, KB files) are preserved; only chunk rows are cleared.

Options:
  --config-env PATH   Analyzer config.env (default: /etc/notable-analyzer/config.env)
  --portal-env PATH   Optional portal.env for supplemental config keys
  --target-dim N      Target vector dimension (default: RAG_VECTOR_DIMENSIONS or 768)
  --dry-run           Print planned SQL without modifying databases
  -h, --help          Show this help

Safe order with Granite env defaults:
  1. scripts/migrate_embedding_dimensions.sh --config-env /etc/notable-analyzer/config.env
  2. scripts/configure_us_granite_retrieval_defaults.sh
  3. Rebuild commands printed at the end of step 1
EOF
}

err() {
    echo "ERROR: $*" >&2
    exit 1
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
        --target-dim)
            require_arg_value "$1" "${2:-}"
            TARGET_DIM="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
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
command -v python3 >/dev/null 2>&1 || err "Missing required command: python3"
command -v psql >/dev/null 2>&1 || err "Missing required command: psql"

args=(python3 "$SCRIPT_DIR/migrate_embedding_dimensions.py" --config-env "$CONFIG_ENV")
if [[ -n "$PORTAL_ENV" ]]; then
    args+=(--portal-env "$PORTAL_ENV")
fi
if [[ -n "$TARGET_DIM" ]]; then
    args+=(--target-dim "$TARGET_DIM")
fi
if [[ "$DRY_RUN" == "true" ]]; then
    args+=(--dry-run)
fi

exec "${args[@]}"
