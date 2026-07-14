#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

export RUN_LOCAL_AZURE_PARITY="${RUN_LOCAL_AZURE_PARITY:-1}"
if [[ -z "${AZURITE_CONNECTION_STRING:-}" ]]; then
  export AZURITE_CONNECTION_STRING="UseDevelopmentStorage=true"
fi

if [[ -n "${PYTHON:-}" ]]; then
  python_bin="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  python_bin="python3"
else
  python_bin="python"
fi

"$python_bin" -m pytest -m integration tests/integration/test_local_azure_parity.py "$@"
