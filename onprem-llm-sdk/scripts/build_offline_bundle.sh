#!/usr/bin/env bash
# Build a self-contained air-gapped SDK bundle.
# Usage:
#   bash scripts/build_offline_bundle.sh
# Optional:
#   PYTHON_BIN=python3.12 bash scripts/build_offline_bundle.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

cd "$ROOT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python interpreter not found: $PYTHON_BIN"
  exit 1
fi

rm -rf dist build bundle .build-venv .lock-venv
mkdir -p bundle/wheels

"$PYTHON_BIN" -m venv .build-venv
source .build-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install build wheel
python -m build
python -m pip wheel . -w bundle/wheels
cp dist/* bundle/wheels/

VERSION="$(PYTHONPATH=src python -c 'import onprem_llm_sdk; print(onprem_llm_sdk.__version__)')"
echo "$VERSION" > bundle/VERSION

cat > bundle/INSTALL.md <<EOF
# Offline install quick steps

cd /opt/artifacts/onprem_llm_sdk
sha256sum -c SHA256SUMS
python3.12 -m venv /opt/venvs/myapp
source /opt/venvs/myapp/bin/activate
python -m pip install --no-index --find-links /opt/artifacts/onprem_llm_sdk/wheels -r /opt/artifacts/onprem_llm_sdk/requirements-lock.txt
python -c "import onprem_llm_sdk; print(onprem_llm_sdk.__version__)"
EOF

deactivate

"$PYTHON_BIN" -m venv .lock-venv
source .lock-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --no-index --find-links bundle/wheels "onprem-llm-sdk==$VERSION"
python - <<'PY' > bundle/requirements-lock.txt
import subprocess

freeze = subprocess.check_output(["python", "-m", "pip", "freeze"], text=True).splitlines()
for line in freeze:
    if line.lower().startswith(("pip==", "setuptools==", "wheel==")):
        continue
    if line.strip():
        print(line)
PY
deactivate

(
  cd bundle
  sha256sum wheels/* requirements-lock.txt VERSION INSTALL.md > SHA256SUMS
  tar -czf "onprem_llm_sdk_bundle_${VERSION}.tar.gz" wheels requirements-lock.txt SHA256SUMS VERSION INSTALL.md
)

echo "Created bundle: $ROOT_DIR/bundle/onprem_llm_sdk_bundle_${VERSION}.tar.gz"

