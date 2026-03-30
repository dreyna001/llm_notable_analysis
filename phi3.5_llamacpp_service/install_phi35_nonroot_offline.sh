#!/usr/bin/env bash
# shellcheck shell=bash
# install_phi35_nonroot_offline.sh
# Offline-only, non-root installer/launcher for llama.cpp + Phi-3.5 GGUF.
set -euo pipefail
IFS=$'\n\t'

trap 'echo "ERROR: Failed at line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

# -----------------------------------------------------------------------------
# Paths and runtime settings
# -----------------------------------------------------------------------------
readonly PHI_INSTALL_DIR="${PHI_INSTALL_DIR:-$HOME/.local/share/phi35_llamacpp}"
readonly PHI_RUNTIME_SRC_DIR="${PHI_RUNTIME_SRC_DIR:-$PHI_INSTALL_DIR/runtime/llama.cpp}"
readonly PHI_RUNTIME_BUILD_DIR="${PHI_RUNTIME_BUILD_DIR:-$PHI_RUNTIME_SRC_DIR/build}"
readonly PHI_SERVER_BIN="${PHI_SERVER_BIN:-$HOME/.local/bin/llama-server}"

readonly PHI_MODEL_DIR="${PHI_MODEL_DIR:-$PHI_INSTALL_DIR/models}"
readonly PHI_MODEL_FILENAME="${PHI_MODEL_FILENAME:-Phi-3.5-mini-instruct-Q4_K_M.gguf}"
readonly PHI_MODEL_PATH="${PHI_MODEL_PATH:-$PHI_MODEL_DIR/$PHI_MODEL_FILENAME}"
readonly PHI_MODEL_SHA256="${PHI_MODEL_SHA256:-}"

readonly PHI_ENV_DIR="${PHI_ENV_DIR:-$HOME/.config/phi35_llamacpp}"
readonly PHI_ENV_FILE="${PHI_ENV_FILE:-$PHI_ENV_DIR/phi35.env}"
readonly PHI_LOG_DIR="${PHI_LOG_DIR:-$PHI_INSTALL_DIR/logs}"
readonly PHI_LOG_FILE="${PHI_LOG_FILE:-$PHI_LOG_DIR/llama-server.log}"
readonly PHI_PID_FILE="${PHI_PID_FILE:-$PHI_INSTALL_DIR/llama-server.pid}"

readonly PHI_EXPECTED_RUNTIME_COMMIT="${PHI_EXPECTED_RUNTIME_COMMIT:-149b249}"

readonly PHI_HOST="${PHI_HOST:-127.0.0.1}"
readonly PHI_PORT="${PHI_PORT:-8000}"
readonly PHI_THREADS="${PHI_THREADS:-4}"
readonly PHI_THREADS_BATCH="${PHI_THREADS_BATCH:-4}"
readonly PHI_PARALLEL="${PHI_PARALLEL:-1}"
readonly PHI_CTX_SIZE="${PHI_CTX_SIZE:-4096}"
readonly PHI_N_PREDICT="${PHI_N_PREDICT:-1024}"
readonly PHI_CACHE_TYPE_K="${PHI_CACHE_TYPE_K:-q8_0}"
readonly PHI_CACHE_TYPE_V="${PHI_CACHE_TYPE_V:-q8_0}"
readonly PHI_CONT_BATCHING="${PHI_CONT_BATCHING:-true}"
readonly PHI_MMAP="${PHI_MMAP:-true}"
readonly PHI_MLOCK="${PHI_MLOCK:-false}"
readonly PHI_EXTRA_ARGS="${PHI_EXTRA_ARGS:-}"

readonly PHI_SKIP_RUNTIME_BUILD="${PHI_SKIP_RUNTIME_BUILD:-false}"
readonly PHI_AUTO_START="${PHI_AUTO_START:-true}"
readonly PHI_STOP_EXISTING="${PHI_STOP_EXISTING:-true}"
readonly PHI_HEALTH_TIMEOUT_SECONDS="${PHI_HEALTH_TIMEOUT_SECONDS:-180}"

info() { echo "  $*"; }
warn() { echo "WARN: $*" >&2; }
err() { echo "ERROR: $*" >&2; exit 1; }

is_bool() {
    case "$1" in
        true|false) return 0 ;;
        *) return 1 ;;
    esac
}

validate_positive_int() {
    local name="$1"
    local value="$2"
    [[ "$value" =~ ^[1-9][0-9]*$ ]] || err "$name must be a positive integer (> 0) (got: $value)"
}

check_command() {
    if command -v "$1" >/dev/null 2>&1; then
        return 0
    fi
    err "Required command not found: $1. On a clean RHEL-class VM, install OS packages first (sudo once), then re-run this script. Example: sudo dnf install -y bash coreutils curl cmake make gcc gcc-c++. See phi3.5_llamacpp_service/RHEL_SOFTWARE_DEPENDENCIES.md"
}

ensure_dir() {
    local dir="$1"
    local mode="$2"
    mkdir -p "$dir" || err "Failed to create directory: $dir"
    chmod "$mode" "$dir" || true
}

validate_config() {
    is_bool "$PHI_SKIP_RUNTIME_BUILD" || err "PHI_SKIP_RUNTIME_BUILD must be true/false"
    is_bool "$PHI_AUTO_START" || err "PHI_AUTO_START must be true/false"
    is_bool "$PHI_STOP_EXISTING" || err "PHI_STOP_EXISTING must be true/false"
    is_bool "$PHI_CONT_BATCHING" || err "PHI_CONT_BATCHING must be true/false"
    is_bool "$PHI_MMAP" || err "PHI_MMAP must be true/false"
    is_bool "$PHI_MLOCK" || err "PHI_MLOCK must be true/false"

    validate_positive_int "PHI_PORT" "$PHI_PORT"
    validate_positive_int "PHI_THREADS" "$PHI_THREADS"
    validate_positive_int "PHI_THREADS_BATCH" "$PHI_THREADS_BATCH"
    validate_positive_int "PHI_PARALLEL" "$PHI_PARALLEL"
    validate_positive_int "PHI_CTX_SIZE" "$PHI_CTX_SIZE"
    validate_positive_int "PHI_N_PREDICT" "$PHI_N_PREDICT"
    validate_positive_int "PHI_HEALTH_TIMEOUT_SECONDS" "$PHI_HEALTH_TIMEOUT_SECONDS"

    [[ "$PHI_MODEL_PATH" = /* ]] || err "PHI_MODEL_PATH must be an absolute path"
    [[ "$PHI_RUNTIME_SRC_DIR" = /* ]] || err "PHI_RUNTIME_SRC_DIR must be an absolute path"
}

verify_runtime_source() {
    [[ -d "$PHI_RUNTIME_SRC_DIR" ]] || err "Missing runtime source dir: $PHI_RUNTIME_SRC_DIR"
    [[ -f "$PHI_RUNTIME_SRC_DIR/CMakeLists.txt" ]] || err "Invalid runtime source (missing CMakeLists.txt): $PHI_RUNTIME_SRC_DIR"

    if [[ -d "$PHI_RUNTIME_SRC_DIR/.git" ]] && command -v git >/dev/null 2>&1; then
        local head_commit
        head_commit="$(git -C "$PHI_RUNTIME_SRC_DIR" rev-parse --short=7 HEAD 2>/dev/null || true)"
        if [[ -n "$head_commit" ]] && [[ "$head_commit" != "${PHI_EXPECTED_RUNTIME_COMMIT:0:7}" ]]; then
            warn "Runtime source commit is $head_commit (expected ${PHI_EXPECTED_RUNTIME_COMMIT:0:7})"
        fi
    fi
}

build_runtime() {
    info "Building llama.cpp from local source (offline)..."
    cmake -S "$PHI_RUNTIME_SRC_DIR" -B "$PHI_RUNTIME_BUILD_DIR" -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release \
        || err "cmake configure failed"
    cmake --build "$PHI_RUNTIME_BUILD_DIR" -j || err "cmake build failed"
    ensure_dir "$(dirname "$PHI_SERVER_BIN")" 0755
    install -m 0755 "$PHI_RUNTIME_BUILD_DIR/bin/llama-server" "$PHI_SERVER_BIN" || err "Failed to install llama-server"
}

verify_model_file() {
    [[ -f "$PHI_MODEL_PATH" ]] || err "Missing model file: $PHI_MODEL_PATH"
    if [[ -n "$PHI_MODEL_SHA256" ]]; then
        local actual_sha
        actual_sha="$(sha256sum "$PHI_MODEL_PATH" | awk '{print $1}')"
        [[ "$actual_sha" == "$PHI_MODEL_SHA256" ]] || err "Model SHA256 mismatch. expected=$PHI_MODEL_SHA256 actual=$actual_sha"
    else
        warn "PHI_MODEL_SHA256 is empty; skipping checksum verification."
    fi
}

write_env_file() {
    ensure_dir "$PHI_ENV_DIR" 0755
    cat >"$PHI_ENV_FILE" <<EOF
# Generated by install_phi35_nonroot_offline.sh
PHI_RUNTIME_SRC_DIR=$PHI_RUNTIME_SRC_DIR
PHI_SERVER_BIN=$PHI_SERVER_BIN
PHI_MODEL_PATH=$PHI_MODEL_PATH
PHI_HOST=$PHI_HOST
PHI_PORT=$PHI_PORT
PHI_THREADS=$PHI_THREADS
PHI_THREADS_BATCH=$PHI_THREADS_BATCH
PHI_PARALLEL=$PHI_PARALLEL
PHI_CTX_SIZE=$PHI_CTX_SIZE
PHI_N_PREDICT=$PHI_N_PREDICT
PHI_CACHE_TYPE_K=$PHI_CACHE_TYPE_K
PHI_CACHE_TYPE_V=$PHI_CACHE_TYPE_V
PHI_CONT_BATCHING=$PHI_CONT_BATCHING
PHI_MMAP=$PHI_MMAP
PHI_MLOCK=$PHI_MLOCK
PHI_EXTRA_ARGS=$PHI_EXTRA_ARGS
PHI_LOG_FILE=$PHI_LOG_FILE
PHI_PID_FILE=$PHI_PID_FILE
EOF
    chmod 0644 "$PHI_ENV_FILE" || true
}

build_cmd_array() {
    local -n out_cmd_ref=$1
    out_cmd_ref=(
        "$PHI_SERVER_BIN"
        --model "$PHI_MODEL_PATH"
        --host "$PHI_HOST"
        --port "$PHI_PORT"
        --threads "$PHI_THREADS"
        --threads-batch "$PHI_THREADS_BATCH"
        --parallel "$PHI_PARALLEL"
        --ctx-size "$PHI_CTX_SIZE"
        --n-predict "$PHI_N_PREDICT"
        --cache-type-k "$PHI_CACHE_TYPE_K"
        --cache-type-v "$PHI_CACHE_TYPE_V"
        --metrics
        --no-webui
    )

    [[ "$PHI_CONT_BATCHING" == "true" ]] && out_cmd_ref+=(--cont-batching)
    [[ "$PHI_MMAP" != "true" ]] && out_cmd_ref+=(--no-mmap)
    [[ "$PHI_MLOCK" == "true" ]] && out_cmd_ref+=(--mlock)

    if [[ -n "$PHI_EXTRA_ARGS" ]]; then
        # shellcheck disable=SC2206
        local extra_args=( $PHI_EXTRA_ARGS )
        out_cmd_ref+=("${extra_args[@]}")
    fi
}

wait_for_http_200() {
    local url="$1"
    local timeout_s="$2"
    local start now
    start="$(date +%s)"
    while true; do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        now="$(date +%s)"
        if (( now - start >= timeout_s )); then
            return 1
        fi
        sleep 2
    done
}

stop_existing_if_requested() {
    [[ -f "$PHI_PID_FILE" ]] || return 0
    local pid
    pid="$(tr -d '[:space:]' <"$PHI_PID_FILE" 2>/dev/null || true)"
    [[ -n "$pid" ]] || return 0

    if kill -0 "$pid" >/dev/null 2>&1; then
        if [[ "$PHI_STOP_EXISTING" == "true" ]]; then
            info "Stopping existing llama-server process (pid=$pid)..."
            kill "$pid" || true
            sleep 2
        else
            warn "Existing process detected (pid=$pid) and PHI_STOP_EXISTING=false"
            return 1
        fi
    fi
    rm -f "$PHI_PID_FILE"
}

start_background() {
    ensure_dir "$PHI_LOG_DIR" 0755
    stop_existing_if_requested || return 0

    local -a cmd
    build_cmd_array cmd
    info "Starting llama-server in background..."
    nohup "${cmd[@]}" >"$PHI_LOG_FILE" 2>&1 &
    local pid="$!"
    echo "$pid" >"$PHI_PID_FILE"
    info "llama-server pid: $pid"

    if wait_for_http_200 "http://${PHI_HOST}:${PHI_PORT}/health" "$PHI_HEALTH_TIMEOUT_SECONDS"; then
        info "Health endpoint is ready"
    else
        warn "Health check timed out after ${PHI_HEALTH_TIMEOUT_SECONDS}s"
        warn "Inspect logs: tail -n 200 \"$PHI_LOG_FILE\""
    fi
}

print_manual_cmd() {
    # Avoid a closing-EOF heredoc here: fragile when the script is copied through
    # mail clients that drop or alter the lone "EOF" line.
    printf '%s --model "%s" --host "%s" --port "%s" --threads "%s" --threads-batch "%s" --parallel "%s" --ctx-size "%s" --n-predict "%s" --cache-type-k "%s" --cache-type-v "%s" --metrics --no-webui\n' \
        "$PHI_SERVER_BIN" "$PHI_MODEL_PATH" "$PHI_HOST" "$PHI_PORT" \
        "$PHI_THREADS" "$PHI_THREADS_BATCH" "$PHI_PARALLEL" "$PHI_CTX_SIZE" \
        "$PHI_N_PREDICT" "$PHI_CACHE_TYPE_K" "$PHI_CACHE_TYPE_V"
}

echo "=== Phi-3.5 llama.cpp install (offline, non-root) ==="
echo "Running as: $(id -un) uid=$(id -u)"
echo "Host prerequisites: cmake, make, curl, sha256sum; gcc + gcc-c++ to compile. Install with your OS package manager before this script (see RHEL_SOFTWARE_DEPENDENCIES.md)."
echo ""

validate_config
check_command cmake
check_command make
check_command curl
check_command sha256sum

echo "[1/4] Verifying local runtime source..."
verify_runtime_source

echo "[2/4] Building runtime..."
if [[ "$PHI_SKIP_RUNTIME_BUILD" == "true" ]]; then
    warn "PHI_SKIP_RUNTIME_BUILD=true; skipping compile step"
else
    build_runtime
fi
[[ -x "$PHI_SERVER_BIN" ]] || err "llama-server binary not found at $PHI_SERVER_BIN"

echo "[3/4] Verifying local model artifact..."
verify_model_file

echo "[4/4] Writing env and starting service..."
write_env_file
if [[ "$PHI_AUTO_START" == "true" ]]; then
    start_background
else
    info "PHI_AUTO_START=false; not starting service"
fi

echo ""
echo "=== complete ==="
echo "Runtime source:  $PHI_RUNTIME_SRC_DIR"
echo "Server binary:   $PHI_SERVER_BIN"
echo "Model path:      $PHI_MODEL_PATH"
echo "Env file:        $PHI_ENV_FILE"
echo "Log file:        $PHI_LOG_FILE"
echo "PID file:        $PHI_PID_FILE"
echo ""
echo "Health check:"
echo "  curl -sf http://${PHI_HOST}:${PHI_PORT}/health"
echo ""
echo "Manual foreground run:"
print_manual_cmd
