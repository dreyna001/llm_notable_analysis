#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="${1:-/opt/artifacts/onprem_llm_sdk}"
VENV_DIR="${2:-/opt/venvs/myapp}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "ERROR: Bundle directory does not exist: $BUNDLE_DIR"
  exit 1
fi

if [[ ! -f "$BUNDLE_DIR/SHA256SUMS" ]]; then
  echo "ERROR: Missing SHA256SUMS in bundle directory"
  exit 1
fi

if [[ ! -d "$BUNDLE_DIR/wheels" ]]; then
  echo "ERROR: Missing wheels directory in bundle"
  exit 1
fi

VERSION="${3:-}"
if [[ -z "$VERSION" ]]; then
  if [[ -f "$BUNDLE_DIR/VERSION" ]]; then
    VERSION="$(cat "$BUNDLE_DIR/VERSION")"
  else
    echo "ERROR: VERSION file missing and version argument not supplied"
    exit 1
  fi
fi

cd "$BUNDLE_DIR"
sha256sum -c SHA256SUMS

"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

if [[ -f "$BUNDLE_DIR/requirements-lock.txt" ]]; then
  python -m pip install --no-index --find-links "$BUNDLE_DIR/wheels" -r "$BUNDLE_DIR/requirements-lock.txt"
else
  python -m pip install --no-index --find-links "$BUNDLE_DIR/wheels" "onprem-llm-sdk==$VERSION"
fi

python -m pip install --no-index --find-links "$BUNDLE_DIR/wheels" "onprem-llm-sdk==$VERSION"
python -c "import onprem_llm_sdk; print(onprem_llm_sdk.__version__)"

echo "Installed onprem-llm-sdk==$VERSION into $VENV_DIR"

