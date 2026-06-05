#!/usr/bin/env bash
# Create one project-wide .venv for Python backend tools and Node/npm (via nodeenv).
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
SKIP_NODE=false
SKIP_FRONTEND_INSTALL=false

usage() {
    cat <<'EOF'
Usage: bootstrap_dev_venv.sh [options]

Creates <repo>/.venv with editable installs for on-prem packages, pytest,
and Node.js (nodeenv) for the analyst portal frontend.

Options:
  --python PATH           Python interpreter used to create the venv
  --skip-node             Do not install Node.js into the venv
  --skip-frontend-install Skip npm install for analyst-portal
  -h, --help              Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python)
            PYTHON_BIN="${2:?Missing value for --python}"
            shift 2
            ;;
        --skip-node)
            SKIP_NODE=true
            shift
            ;;
        --skip-frontend-install)
            SKIP_FRONTEND_INSTALL=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
FRONTEND_DIR="$REPO_ROOT/llm_notable_analysis_onprem_systemd/frontend/analyst-portal"

echo "Repo root: $REPO_ROOT"
echo "Virtual env: $VENV_DIR"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip wheel
"$VENV_DIR/bin/pip" install \
    -e "$REPO_ROOT/onprem-llm-sdk" \
    -e "$REPO_ROOT/onprem_rag_notable_analysis" \
    -e "$REPO_ROOT/llm_notable_analysis_onprem_systemd" \
    pytest \
    nodeenv

if [[ "$SKIP_NODE" != true ]]; then
    if [[ ! -x "$VENV_DIR/bin/node" ]]; then
        echo "Installing Node.js into .venv via nodeenv..."
        export VIRTUAL_ENV="$VENV_DIR"
        export PATH="$VENV_DIR/bin:$PATH"
        "$VENV_DIR/bin/python" -m nodeenv -p --node=22.14.0
    fi
fi

if [[ "$SKIP_FRONTEND_INSTALL" != true ]]; then
    echo "Installing analyst portal frontend dependencies..."
    (
        cd "$FRONTEND_DIR"
        "$VENV_DIR/bin/npm" install
    )
fi

cat <<EOF

Done. Activate the shared dev environment:
  source "$VENV_DIR/bin/activate"

Then run, for example:
  python llm_notable_analysis_onprem_systemd/scripts/preview_portal_ui.py
  npm --prefix llm_notable_analysis_onprem_systemd/frontend/analyst-portal run dev
EOF
