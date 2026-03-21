#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "$TEST_DIR/.." && pwd)"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_file() {
    local path="$1"
    [[ -f "$path" ]] || fail "Missing required file: $path"
}

require_contains() {
    local path="$1"
    local pattern="$2"
    if ! grep -Eq "$pattern" "$path"; then
        fail "Expected pattern '$pattern' not found in $path"
    fi
}

echo "[1/5] Checking required package files..."
require_file "$PKG_DIR/install_llamacpp.sh"
require_file "$PKG_DIR/systemd/llamacpp.service"
require_file "$PKG_DIR/config/llamacpp.env.example"
require_file "$PKG_DIR/README.md"
require_file "$PKG_DIR/docs/TROUBLESHOOTING.md"

echo "[2/5] Validating installer shell syntax..."
bash -n "$PKG_DIR/install_llamacpp.sh"

echo "[3/5] Validating unit template essentials..."
require_contains "$PKG_DIR/systemd/llamacpp.service" "^EnvironmentFile=-/etc/llamacpp/llamacpp\\.env$"
require_contains "$PKG_DIR/systemd/llamacpp.service" "llama-server"
require_contains "$PKG_DIR/systemd/llamacpp.service" "--metrics"
require_contains "$PKG_DIR/systemd/llamacpp.service" "--no-webui"

echo "[4/5] Validating env example keys..."
require_contains "$PKG_DIR/config/llamacpp.env.example" "^LLAMA_MODEL_PATH="
require_contains "$PKG_DIR/config/llamacpp.env.example" "^LLAMA_HOST="
require_contains "$PKG_DIR/config/llamacpp.env.example" "^LLAMA_PORT="
require_contains "$PKG_DIR/config/llamacpp.env.example" "^LLAMA_THREADS="
require_contains "$PKG_DIR/config/llamacpp.env.example" "^LLAMA_CTX_SIZE="
require_contains "$PKG_DIR/config/llamacpp.env.example" "^LLAMA_DEFAULT_MAX_TOKENS="

echo "[5/5] Validating pinned baseline values in installer..."
require_contains "$PKG_DIR/install_llamacpp.sh" "LLAMA_RUNTIME_TAG=.*b8457"
require_contains "$PKG_DIR/install_llamacpp.sh" "LLAMA_RUNTIME_COMMIT=.*149b249"
require_contains "$PKG_DIR/install_llamacpp.sh" "LLAMA_MODEL_SHA256=.*7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"

echo "Static validation checks passed."
