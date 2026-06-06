#!/usr/bin/env bash
# Run analyst portal Playwright E2E tests using npm from the shared repo .venv.
set -euo pipefail

INSTALL_BROWSERS=false
PLAYWRIGHT_ARGS=()

usage() {
    cat <<'EOF'
Usage: dev_portal_e2e.sh [--install-browsers] [-- playwright-args...]

Runs Playwright E2E against the deployed portal using npm from <repo>/.venv.
Bootstrap the repo venv on this machine first (do not reuse a Windows .venv):

  bash scripts/bootstrap_dev_venv.sh
  source .venv/bin/activate

Environment (optional):
  PORTAL_E2E_BASE_URL      default https://127.0.0.1:8443
  PORTAL_E2E_USER          nginx basic-auth user
  PORTAL_E2E_PASSWORD      nginx basic-auth password
  PORTAL_E2E_CASE_ID       archived sample case id
  PORTAL_E2E_CHAT          set false to skip LLM chat steps
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-browsers)
            INSTALL_BROWSERS=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            PLAYWRIGHT_ARGS=("$@")
            break
            ;;
        *)
            PLAYWRIGHT_ARGS+=("$1")
            shift
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
NPM_BIN="$VENV_DIR/bin/npm"
NODE_BIN="$VENV_DIR/bin/node"
FRONTEND_DIR="$REPO_ROOT/llm_notable_analysis_onprem_systemd/frontend/analyst-portal"
PLAYWRIGHT_PKG="$FRONTEND_DIR/node_modules/@playwright/test/package.json"

if [[ ! -x "$NPM_BIN" ]]; then
    echo "Missing $NPM_BIN. Run: bash scripts/bootstrap_dev_venv.sh" >&2
    exit 1
fi
if [[ ! -x "$NODE_BIN" ]]; then
    echo "Missing $NODE_BIN. Re-run bootstrap without --skip-node." >&2
    exit 1
fi
if [[ ! -f "$PLAYWRIGHT_PKG" ]]; then
    echo "@playwright/test is not installed. Run: bash scripts/bootstrap_dev_venv.sh" >&2
    exit 1
fi

export VIRTUAL_ENV="$VENV_DIR"
export PATH="$VENV_DIR/bin:$PATH"

cd "$FRONTEND_DIR"
echo "Using npm: $NPM_BIN"
echo "Using node: $NODE_BIN"

if [[ "$INSTALL_BROWSERS" == true ]]; then
    echo "Installing Playwright Chromium via repo .venv npm..."
    "$NPM_BIN" run install:e2e-browsers
fi

if ((${#PLAYWRIGHT_ARGS[@]})); then
    exec "$NPM_BIN" exec playwright test "${PLAYWRIGHT_ARGS[@]}"
fi
exec "$NPM_BIN" run test:e2e
