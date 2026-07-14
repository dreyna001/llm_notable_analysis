#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/local.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  ENV_FILE="$SCRIPT_DIR/local.env.example"
fi

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
if [[ -n "${PYTHON:-}" ]]; then
  python_bin="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  python_bin="python3"
else
  echo "Python 3.12 is required; set PYTHON to the interpreter path" >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$SCRIPT_DIR/docker-compose.yml" up -d --wait azurite cosmos
"$python_bin" "$SCRIPT_DIR/bootstrap_emulators.py" --env-file "$ENV_FILE"
