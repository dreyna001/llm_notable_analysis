#!/usr/bin/env bash
# Create one project-wide .venv for Python backend tools and Node/npm (via nodeenv).
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-}"
PYTHON_BIN_EXPLICIT=false
if [[ -n "$PYTHON_BIN" ]]; then
    PYTHON_BIN_EXPLICIT=true
fi
INSTALL_PYTHON=false
SKIP_NODE=false
SKIP_FRONTEND_INSTALL=false
SKIP_PLAYWRIGHT_INSTALL=false

usage() {
    cat <<'EOF'
Usage: bootstrap_dev_venv.sh [options]

Creates <repo>/.venv with editable installs for on-prem packages, pytest,
and Node.js (nodeenv) for the analyst portal frontend.

Requires Python 3.12+. By default the script prefers python3.12 on PATH.

Options:
  --python PATH           Python interpreter used to create the venv
  --install-python        Install Python 3.12 via install_python312.sh (Linux + sudo)
  --skip-node             Do not install Node.js into the venv
  --skip-frontend-install Skip npm install for analyst-portal
  --skip-playwright-install Skip Playwright Chromium download (after npm install)
  -h, --help              Show this help
EOF
}

print_python312_hints() {
    cat <<'EOF'
Python 3.12+ is required but was not found.

Install it manually, or re-run with --install-python on a supported Linux VM:

  bash scripts/install_python312.sh
  bash scripts/bootstrap_dev_venv.sh --python python3.12

Ubuntu 24.04 / Debian 12:
  sudo apt update
  sudo apt install -y python3.12 python3.12-venv python3.12-dev

Ubuntu 22.04:
  sudo apt update
  sudo apt install -y software-properties-common
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt update
  sudo apt install -y python3.12 python3.12-venv python3.12-dev

RHEL 9 / Rocky 9 / Alma 9 / Fedora:
  sudo dnf install -y python3.12 python3.12-devel
EOF
}

resolve_default_python_bin() {
    if command -v python3.12 >/dev/null 2>&1; then
        echo "python3.12"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        echo "python3"
        return 0
    fi
    echo "python3.12"
}

python_version_ok() {
    local bin="$1"
    local version major minor
    version="$("$bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    IFS=. read -r major minor <<< "$version"
    if (( major < 3 || (major == 3 && minor < 12) )); then
        echo "Python 3.12+ required; found Python $version from: $bin" >&2
        return 1
    fi
    return 0
}

python_bin_ready() {
    command -v "$PYTHON_BIN" >/dev/null 2>&1 && python_version_ok "$PYTHON_BIN"
}

ensure_python_bin() {
    if [[ -z "$PYTHON_BIN" ]]; then
        PYTHON_BIN="$(resolve_default_python_bin)"
    fi

    if [[ "$INSTALL_PYTHON" == true ]] && ! python_bin_ready; then
        bash "$SCRIPT_DIR/install_python312.sh"
        PYTHON_BIN="python3.12"
    fi

    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        echo "Python interpreter not found: $PYTHON_BIN" >&2
        print_python312_hints >&2
        exit 1
    fi

    if ! python_version_ok "$PYTHON_BIN"; then
        print_python312_hints >&2
        exit 1
    fi

    if ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
        echo "The venv module is unavailable for: $PYTHON_BIN" >&2
        echo "On Debian/Ubuntu install python3.12-venv." >&2
        echo "On RHEL/Fedora install python3.12-devel." >&2
        exit 1
    fi

    echo "Using Python: $("$PYTHON_BIN" --version) ($PYTHON_BIN)"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python)
            PYTHON_BIN="${2:?Missing value for --python}"
            PYTHON_BIN_EXPLICIT=true
            shift 2
            ;;
        --install-python)
            INSTALL_PYTHON=true
            shift
            ;;
        --skip-node)
            SKIP_NODE=true
            shift
            ;;
        --skip-frontend-install)
            SKIP_FRONTEND_INSTALL=true
            shift
            ;;
        --skip-playwright-install)
            SKIP_PLAYWRIGHT_INSTALL=true
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

ensure_python_bin

if [[ -x "$VENV_DIR/bin/python" ]] && ! "$VENV_DIR/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
    echo "Removing stale .venv (Python < 3.12); recreating with $PYTHON_BIN..."
    rm -rf "$VENV_DIR"
fi

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
        export VIRTUAL_ENV="$VENV_DIR"
        export PATH="$VENV_DIR/bin:$PATH"
        cd "$FRONTEND_DIR"
        "$VENV_DIR/bin/npm" install
        if [[ "$SKIP_PLAYWRIGHT_INSTALL" != true ]]; then
            echo "Installing Playwright Chromium for portal E2E tests..."
            "$VENV_DIR/bin/npm" run install:e2e-browsers
        fi
    )
fi

cat <<EOF

Done. Activate the shared dev environment:
  source "$VENV_DIR/bin/activate"

Then run, for example:
  python llm_notable_analysis_onprem_systemd/scripts/preview_portal_ui.py
  bash scripts/dev_portal_e2e.sh

Portal E2E on a Linux VM (after git sync; bootstrap a fresh .venv on the VM):
  bash scripts/bootstrap_dev_venv.sh
  source .venv/bin/activate
  PORTAL_E2E_BASE_URL=https://127.0.0.1:8443 bash scripts/dev_portal_e2e.sh
EOF
