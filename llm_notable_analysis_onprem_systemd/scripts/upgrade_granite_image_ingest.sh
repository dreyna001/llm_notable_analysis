#!/usr/bin/env bash
# Upgrade an existing on-prem host from Mixedbread 1024-dim retrieval to Granite
# 768-dim retrieval and install image-ingest prerequisites when a bundle is provided.
#
# Does not rebuild indexes or restart services. Clears chunk rows during dimension
# migration (cases/tickets/attachments/chat/KB source files are preserved).
#
# Related: docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md
#          docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
PORTAL_ENV="${PORTAL_ENV:-/etc/notable-analyzer/portal.env}"
BUNDLE_DIR="${BUNDLE_DIR:-}"
ANALYZER_VENV="${ANALYZER_VENV:-/opt/notable-analyzer/venv}"
SKIP_PREREQ_INSTALL="${SKIP_PREREQ_INSTALL:-false}"
SKIP_MIGRATION="${SKIP_MIGRATION:-false}"
SKIP_CONFIGURE="${SKIP_CONFIGURE:-false}"
SKIP_VERIFY="${SKIP_VERIFY:-false}"

usage() {
    cat <<'EOF'
Usage: upgrade_granite_image_ingest.sh [options]

Orchestrates image-ingest prerequisite install (optional), pgvector 768 migration,
Granite env defaults, and prerequisite verification for existing hosts.

Safe order (this script):
  1. install_image_ingest_prerequisites.sh  (when --bundle-dir is set)
  2. migrate_embedding_dimensions.sh        (postgres admin; clears chunk rows)
  3. configure_us_granite_retrieval_defaults.sh
  4. verify_image_ingest_prerequisites.sh

Operator must still rebuild KB/case/closed-ticket indexes and restart services.

Options:
  --bundle-dir PATH       Offline image-ingest bundle (skips prerequisite install when omitted)
  --config-env PATH       Analyzer config.env (default: /etc/notable-analyzer/config.env)
  --portal-env PATH       Portal portal.env (default: /etc/notable-analyzer/portal.env)
  --analyzer-venv PATH    Analyzer venv (default: /opt/notable-analyzer/venv)
  --skip-prereq-install   Skip install_image_ingest_prerequisites.sh
  --skip-migration        Skip migrate_embedding_dimensions.sh
  --skip-configure        Skip configure_us_granite_retrieval_defaults.sh
  --skip-verify           Skip verify_image_ingest_prerequisites.sh
  -h, --help              Show this help

Environment overrides:
  BUNDLE_DIR, CONFIG_ENV, PORTAL_ENV, ANALYZER_VENV,
  SKIP_PREREQ_INSTALL, SKIP_MIGRATION, SKIP_CONFIGURE, SKIP_VERIFY
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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bundle-dir)
            require_arg_value "$1" "${2:-}"
            BUNDLE_DIR="$2"
            shift 2
            ;;
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
        --analyzer-venv)
            require_arg_value "$1" "${2:-}"
            ANALYZER_VENV="$2"
            shift 2
            ;;
        --skip-prereq-install)
            SKIP_PREREQ_INSTALL="true"
            shift
            ;;
        --skip-migration)
            SKIP_MIGRATION="true"
            shift
            ;;
        --skip-configure)
            SKIP_CONFIGURE="true"
            shift
            ;;
        --skip-verify)
            SKIP_VERIFY="true"
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

info "Granite + image-ingest upgrade orchestration"
info "  config.env: $CONFIG_ENV"
info "  portal.env: $PORTAL_ENV"

if [[ "$SKIP_PREREQ_INSTALL" != "true" && -n "$BUNDLE_DIR" ]]; then
    info "Step 1/4: install image-ingest prerequisites from bundle"
    bash "$SCRIPT_DIR/install_image_ingest_prerequisites.sh" \
        --bundle-dir "$BUNDLE_DIR" \
        --config-env "$CONFIG_ENV" \
        --analyzer-venv "$ANALYZER_VENV"
elif [[ "$SKIP_PREREQ_INSTALL" != "true" ]]; then
    info "Step 1/4: skipped (no --bundle-dir; run install_image_ingest_prerequisites.sh separately if needed)"
else
    info "Step 1/4: skipped (--skip-prereq-install)"
fi

if [[ "$SKIP_MIGRATION" != "true" ]]; then
    info "Step 2/4: migrate pgvector chunk tables to 768 dimensions"
    bash "$SCRIPT_DIR/migrate_embedding_dimensions.sh" \
        --config-env "$CONFIG_ENV" \
        --portal-env "$PORTAL_ENV"
else
    info "Step 2/4: skipped (--skip-migration)"
fi

if [[ "$SKIP_CONFIGURE" != "true" ]]; then
    info "Step 3/4: apply Granite retrieval env defaults"
    bash "$SCRIPT_DIR/configure_us_granite_retrieval_defaults.sh" \
        --config-env "$CONFIG_ENV" \
        --portal-env "$PORTAL_ENV"
else
    info "Step 3/4: skipped (--skip-configure)"
fi

if [[ "$SKIP_VERIFY" != "true" ]]; then
    info "Step 4/4: verify image-ingest prerequisites"
    bash "$SCRIPT_DIR/verify_image_ingest_prerequisites.sh" \
        --config-env "$CONFIG_ENV" \
        --analyzer-venv "$ANALYZER_VENV"
else
    info "Step 4/4: skipped (--skip-verify)"
fi

cat <<EOF

Upgrade orchestration complete. Rebuild indexes before serving retrieval traffic:

  sudo bash scripts/setup_postgres_rag.sh --config-env $CONFIG_ENV
  sudo bash scripts/setup_postgres_rag.sh --config-env $CONFIG_ENV --spl-query-rag
  sudo /opt/notable-analyzer/venv/bin/python scripts/rebuild_case_chunks.py --all --config-env $CONFIG_ENV
  sudo /opt/notable-analyzer/venv/bin/python scripts/rebuild_closed_ticket_chunks.py --all --config-env $CONFIG_ENV
  sudo systemctl restart notable-analyzer notable-portal

EOF
