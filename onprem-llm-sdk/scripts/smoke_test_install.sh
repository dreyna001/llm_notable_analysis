#!/usr/bin/env bash
# Smoke test for post-install validation.
# Usage:
#   bash scripts/smoke_test_install.sh [VENV_DIR]
# Optional:
#   RUN_ENDPOINT_CHECK=true bash scripts/smoke_test_install.sh
set -euo pipefail

VENV_DIR="${1:-/opt/venvs/myapp}"
RUN_ENDPOINT_CHECK="${RUN_ENDPOINT_CHECK:-false}"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "ERROR: Virtual environment not found: $VENV_DIR"
  exit 1
fi

source "$VENV_DIR/bin/activate"
python - <<'PY'
import onprem_llm_sdk
print("SDK version:", onprem_llm_sdk.__version__)
PY

if [[ "$RUN_ENDPOINT_CHECK" == "true" ]]; then
  if command -v curl >/dev/null 2>&1; then
    curl -sSf http://127.0.0.1:8000/health >/dev/null
    echo "vLLM health check passed."
  else
    echo "WARN: curl not found, skipping endpoint check."
  fi
fi

echo "Smoke test completed."

