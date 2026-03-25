#!/usr/bin/env bash
# shellcheck shell=bash
# install_llamacpp_nonroot.sh — rootless llama.cpp PoC installer
set -euo pipefail
IFS=$'\n\t'

trap 'echo "ERROR: Failed at line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

# -----------------------------------------------------------------------------
# Constants (pinned baseline)
# -----------------------------------------------------------------------------
readonly LLAMA_RUNTIME_REPO="${LLAMA_RUNTIME_REPO:-https://github.com/ggml-org/llama.cpp.git}"
readonly LLAMA_RUNTIME_TAG="${LLAMA_RUNTIME_TAG:-b8457}"
readonly LLAMA_RUNTIME_COMMIT="${LLAMA_RUNTIME_COMMIT:-149b249}"

readonly LLAMA_MODEL_REPO="${LLAMA_MODEL_REPO:-Qwen/Qwen3-4B-GGUF}"
readonly LLAMA_MODEL_FILENAME="${LLAMA_MODEL_FILENAME:-Qwen3-4B-Q4_K_M.gguf}"
readonly LLAMA_MODEL_REVISION="${LLAMA_MODEL_REVISION:-a9a60d009fa7ff9606305047c2bf77ac25dbec49}"
readonly LLAMA_MODEL_SHA256="${LLAMA_MODEL_SHA256:-7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5}"
readonly LLAMA_MODEL_SIZE_BYTES="${LLAMA_MODEL_SIZE_BYTES:-2497280256}"

# -----------------------------------------------------------------------------
# Rootless paths and runtime settings
# -----------------------------------------------------------------------------
readonly LLAMA_INSTALL_DIR="${LLAMA_INSTALL_DIR:-$HOME/.local/share/llamacpp}"
readonly LLAMA_SRC_DIR="${LLAMA_SRC_DIR:-$LLAMA_INSTALL_DIR/src/llama.cpp}"
readonly LLAMA_MODEL_DIR="${LLAMA_MODEL_DIR:-$LLAMA_INSTALL_DIR/models}"
readonly LLAMA_MODEL_PATH="${LLAMA_MODEL_PATH:-$LLAMA_MODEL_DIR/$LLAMA_MODEL_FILENAME}"
readonly LLAMA_ENV_DIR="${LLAMA_ENV_DIR:-$HOME/.config/llamacpp}"
readonly LLAMA_ENV_FILE="${LLAMA_ENV_FILE:-$LLAMA_ENV_DIR/llamacpp.env}"
readonly LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$HOME/.local/bin/llama-server}"
readonly LLAMA_LOG_DIR="${LLAMA_LOG_DIR:-$LLAMA_INSTALL_DIR/logs}"
readonly LLAMA_LOG_FILE="${LLAMA_LOG_FILE:-$LLAMA_LOG_DIR/llama-server.log}"
readonly LLAMA_PID_FILE="${LLAMA_PID_FILE:-$LLAMA_INSTALL_DIR/llama-server.pid}"

readonly LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
readonly LLAMA_PORT="${LLAMA_PORT:-8000}"
readonly LLAMA_THREADS="${LLAMA_THREADS:-10}"
readonly LLAMA_THREADS_BATCH="${LLAMA_THREADS_BATCH:-12}"
readonly LLAMA_PARALLEL="${LLAMA_PARALLEL:-1}"
readonly LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-8192}"
readonly LLAMA_MAX_INPUT_TOKENS="${LLAMA_MAX_INPUT_TOKENS:-3072}"
readonly LLAMA_DEFAULT_MAX_TOKENS="${LLAMA_DEFAULT_MAX_TOKENS:-$LLAMA_CTX_SIZE}"
readonly LLAMA_HARD_MAX_TOKENS="${LLAMA_HARD_MAX_TOKENS:-$LLAMA_CTX_SIZE}"
readonly LLAMA_INFERENCE_TIMEOUT_SECONDS="${LLAMA_INFERENCE_TIMEOUT_SECONDS:-120}"
readonly LLAMA_HTTP_TIMEOUT_SECONDS="${LLAMA_HTTP_TIMEOUT_SECONDS:-180}"
readonly LLAMA_CACHE_TYPE_K="${LLAMA_CACHE_TYPE_K:-q8_0}"
readonly LLAMA_CACHE_TYPE_V="${LLAMA_CACHE_TYPE_V:-q8_0}"
readonly LLAMA_CONT_BATCHING="${LLAMA_CONT_BATCHING:-true}"
readonly LLAMA_MMAP="${LLAMA_MMAP:-true}"
readonly LLAMA_MLOCK="${LLAMA_MLOCK:-false}"
readonly LLAMA_EXTRA_ARGS="${LLAMA_EXTRA_ARGS:-}"

# Controls
readonly AUTO_START_LLAMACPP="${AUTO_START_LLAMACPP:-true}"
readonly LLAMA_SKIP_RUNTIME_BUILD="${LLAMA_SKIP_RUNTIME_BUILD:-false}"
readonly LLAMA_SKIP_MODEL_DOWNLOAD="${LLAMA_SKIP_MODEL_DOWNLOAD:-false}"
readonly LLAMA_INSTALL_DEPS="${LLAMA_INSTALL_DEPS:-false}"
readonly LLAMA_FORCE_MODEL_REDOWNLOAD="${LLAMA_FORCE_MODEL_REDOWNLOAD:-false}"
readonly LLAMA_HEALTH_TIMEOUT_SECONDS="${LLAMA_HEALTH_TIMEOUT_SECONDS:-900}"
readonly LLAMA_STOP_EXISTING="${LLAMA_STOP_EXISTING:-true}"

readonly LLAMA_MODEL_URL="https://huggingface.co/${LLAMA_MODEL_REPO}/resolve/${LLAMA_MODEL_REVISION}/${LLAMA_MODEL_FILENAME}?download=true"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
info() { echo "  $*"; }
warn() { echo "WARN: $*" >&2; }
err() { echo "ERROR: $*" >&2; exit 1; }

is_bool() {
    case "$1" in
        true|false) return 0 ;;
        *) return 1 ;;
    esac
}

check_command() {
    command -v "$1" >/dev/null 2>&1 || err "Required command not found: $1"
}

validate_positive_int() {
    local name="$1"
    local value="$2"
    [[ "$value" =~ ^[1-9][0-9]*$ ]] || err "$name must be a positive integer (> 0) (got: $value)"
}

validate_config() {
    is_bool "$AUTO_START_LLAMACPP" || err "AUTO_START_LLAMACPP must be true/false"
    is_bool "$LLAMA_SKIP_RUNTIME_BUILD" || err "LLAMA_SKIP_RUNTIME_BUILD must be true/false"
    is_bool "$LLAMA_SKIP_MODEL_DOWNLOAD" || err "LLAMA_SKIP_MODEL_DOWNLOAD must be true/false"
    is_bool "$LLAMA_INSTALL_DEPS" || err "LLAMA_INSTALL_DEPS must be true/false"
    is_bool "$LLAMA_FORCE_MODEL_REDOWNLOAD" || err "LLAMA_FORCE_MODEL_REDOWNLOAD must be true/false"
    is_bool "$LLAMA_CONT_BATCHING" || err "LLAMA_CONT_BATCHING must be true/false"
    is_bool "$LLAMA_MMAP" || err "LLAMA_MMAP must be true/false"
    is_bool "$LLAMA_MLOCK" || err "LLAMA_MLOCK must be true/false"
    is_bool "$LLAMA_STOP_EXISTING" || err "LLAMA_STOP_EXISTING must be true/false"

    validate_positive_int "LLAMA_PORT" "$LLAMA_PORT"
    validate_positive_int "LLAMA_THREADS" "$LLAMA_THREADS"
    validate_positive_int "LLAMA_THREADS_BATCH" "$LLAMA_THREADS_BATCH"
    validate_positive_int "LLAMA_PARALLEL" "$LLAMA_PARALLEL"
    validate_positive_int "LLAMA_CTX_SIZE" "$LLAMA_CTX_SIZE"
    validate_positive_int "LLAMA_MAX_INPUT_TOKENS" "$LLAMA_MAX_INPUT_TOKENS"
    validate_positive_int "LLAMA_DEFAULT_MAX_TOKENS" "$LLAMA_DEFAULT_MAX_TOKENS"
    validate_positive_int "LLAMA_HARD_MAX_TOKENS" "$LLAMA_HARD_MAX_TOKENS"
    validate_positive_int "LLAMA_INFERENCE_TIMEOUT_SECONDS" "$LLAMA_INFERENCE_TIMEOUT_SECONDS"
    validate_positive_int "LLAMA_HTTP_TIMEOUT_SECONDS" "$LLAMA_HTTP_TIMEOUT_SECONDS"
    validate_positive_int "LLAMA_HEALTH_TIMEOUT_SECONDS" "$LLAMA_HEALTH_TIMEOUT_SECONDS"

    [[ "$LLAMA_HARD_MAX_TOKENS" -ge "$LLAMA_DEFAULT_MAX_TOKENS" ]] || err "LLAMA_HARD_MAX_TOKENS must be >= LLAMA_DEFAULT_MAX_TOKENS"
    [[ "$LLAMA_DEFAULT_MAX_TOKENS" -le "$LLAMA_CTX_SIZE" ]] || err "LLAMA_DEFAULT_MAX_TOKENS must be <= LLAMA_CTX_SIZE"
    [[ "$LLAMA_HARD_MAX_TOKENS" -le "$LLAMA_CTX_SIZE" ]] || err "LLAMA_HARD_MAX_TOKENS must be <= LLAMA_CTX_SIZE"
    [[ "$LLAMA_MODEL_PATH" = /* ]] || err "LLAMA_MODEL_PATH must be an absolute path"
}

ensure_dir() {
    local dir="$1"
    local mode="$2"
    mkdir -p "$dir" || err "Failed to create directory: $dir"
    chmod "$mode" "$dir" || true
}

install_dependencies_nonroot() {
    [[ "$LLAMA_INSTALL_DEPS" == "true" ]] || return 0
    warn "LLAMA_INSTALL_DEPS=true requested, but rootless script cannot install system packages."
    warn "Install dependencies manually (git cmake make gcc/g++ curl ca-certificates) and re-run."
}

sync_runtime_source() {
    local src_parent
    src_parent="$(dirname "$LLAMA_SRC_DIR")"
    mkdir -p "$src_parent"

    if [[ -d "$LLAMA_SRC_DIR/.git" ]]; then
        info "Existing llama.cpp source found at $LLAMA_SRC_DIR"
    else
        info "Cloning llama.cpp source..."
        git clone "$LLAMA_RUNTIME_REPO" "$LLAMA_SRC_DIR" || err "Failed to clone llama.cpp"
    fi

    git -C "$LLAMA_SRC_DIR" fetch --tags --force origin || err "Failed to fetch llama.cpp updates"
    git -C "$LLAMA_SRC_DIR" cat-file -e "${LLAMA_RUNTIME_COMMIT}^{commit}" 2>/dev/null \
        || err "Pinned commit not found in repo: $LLAMA_RUNTIME_COMMIT"
    git -C "$LLAMA_SRC_DIR" checkout --force "$LLAMA_RUNTIME_COMMIT" || err "Failed to checkout pinned commit"
}

build_runtime() {
    info "Building llama.cpp from commit $LLAMA_RUNTIME_COMMIT ($LLAMA_RUNTIME_TAG)..."
    cmake -S "$LLAMA_SRC_DIR" -B "$LLAMA_SRC_DIR/build" -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release \
        || err "cmake configure failed"
    cmake --build "$LLAMA_SRC_DIR/build" -j || err "cmake build failed"
    ensure_dir "$(dirname "$LLAMA_SERVER_BIN")" 0755
    install -m 0755 "$LLAMA_SRC_DIR/build/bin/llama-server" "$LLAMA_SERVER_BIN" || err "Failed to install llama-server"
}

verify_model_file() {
    local file="$1"
    [[ -f "$file" ]] || return 1

    local actual_sha
    actual_sha="$(sha256sum "$file" | awk '{print $1}')"
    [[ "$actual_sha" == "$LLAMA_MODEL_SHA256" ]] || return 1

    local actual_size
    actual_size="$(stat -c '%s' "$file" 2>/dev/null || wc -c <"$file")"
    [[ "$actual_size" == "$LLAMA_MODEL_SIZE_BYTES" ]] || return 1

    return 0
}

download_model_if_needed() {
    [[ "$LLAMA_SKIP_MODEL_DOWNLOAD" == "true" ]] && {
        warn "LLAMA_SKIP_MODEL_DOWNLOAD=true; model download skipped"
        return 0
    }

    ensure_dir "$(dirname "$LLAMA_MODEL_PATH")" 0755

    if [[ "$LLAMA_FORCE_MODEL_REDOWNLOAD" == "true" ]]; then
        rm -f "$LLAMA_MODEL_PATH"
    fi

    if verify_model_file "$LLAMA_MODEL_PATH"; then
        info "Pinned model already present and verified: $LLAMA_MODEL_PATH"
        return 0
    fi

    info "Downloading pinned model artifact..."
    local tmp_file
    local -a curl_args
    tmp_file="${LLAMA_MODEL_PATH}.part"
    rm -f "$tmp_file"

    curl_args=(-fL --retry 3 --retry-delay 3)
    if curl --help all 2>/dev/null | grep -q -- "--retry-all-errors"; then
        curl_args+=(--retry-all-errors)
    else
        warn "curl does not support --retry-all-errors; using compatibility retry mode"
    fi

    curl "${curl_args[@]}" "$LLAMA_MODEL_URL" -o "$tmp_file" \
        || err "Model download failed: $LLAMA_MODEL_URL"
    mv "$tmp_file" "$LLAMA_MODEL_PATH" || err "Failed to finalize downloaded model file"

    verify_model_file "$LLAMA_MODEL_PATH" || err "Model verification failed (SHA256/size mismatch)"
    chmod 0644 "$LLAMA_MODEL_PATH" || true
}

write_runtime_env_file() {
    local cont_batching_flag mmap_flag mlock_flag

    cont_batching_flag=""
    [[ "$LLAMA_CONT_BATCHING" == "true" ]] && cont_batching_flag="--cont-batching"

    mmap_flag=""
    [[ "$LLAMA_MMAP" != "true" ]] && mmap_flag="--no-mmap"

    mlock_flag=""
    [[ "$LLAMA_MLOCK" == "true" ]] && mlock_flag="--mlock"

    ensure_dir "$LLAMA_ENV_DIR" 0755
    cat >"$LLAMA_ENV_FILE" <<EOF
# Generated by install_llamacpp_nonroot.sh
LLAMA_MODEL_PATH=$LLAMA_MODEL_PATH
LLAMA_HOST=$LLAMA_HOST
LLAMA_PORT=$LLAMA_PORT
LLAMA_THREADS=$LLAMA_THREADS
LLAMA_THREADS_BATCH=$LLAMA_THREADS_BATCH
LLAMA_PARALLEL=$LLAMA_PARALLEL
LLAMA_CTX_SIZE=$LLAMA_CTX_SIZE
LLAMA_MAX_INPUT_TOKENS=$LLAMA_MAX_INPUT_TOKENS
LLAMA_DEFAULT_MAX_TOKENS=$LLAMA_DEFAULT_MAX_TOKENS
LLAMA_HARD_MAX_TOKENS=$LLAMA_HARD_MAX_TOKENS
LLAMA_INFERENCE_TIMEOUT_SECONDS=$LLAMA_INFERENCE_TIMEOUT_SECONDS
LLAMA_HTTP_TIMEOUT_SECONDS=$LLAMA_HTTP_TIMEOUT_SECONDS
LLAMA_CACHE_TYPE_K=$LLAMA_CACHE_TYPE_K
LLAMA_CACHE_TYPE_V=$LLAMA_CACHE_TYPE_V
LLAMA_CONT_BATCHING_FLAG=$cont_batching_flag
LLAMA_MMAP_FLAG=$mmap_flag
LLAMA_MLOCK_FLAG=$mlock_flag
LLAMA_EXTRA_ARGS=$LLAMA_EXTRA_ARGS
LLAMA_LOG_FILE=$LLAMA_LOG_FILE
LLAMA_PID_FILE=$LLAMA_PID_FILE
EOF
    chmod 0644 "$LLAMA_ENV_FILE" || true
}

build_server_cmd_array() {
    local -n out_cmd_ref=$1
    out_cmd_ref=(
        "$LLAMA_SERVER_BIN"
        --model "$LLAMA_MODEL_PATH"
        --host "$LLAMA_HOST"
        --port "$LLAMA_PORT"
        --threads "$LLAMA_THREADS"
        --threads-batch "$LLAMA_THREADS_BATCH"
        --parallel "$LLAMA_PARALLEL"
        --ctx-size "$LLAMA_CTX_SIZE"
        --n-predict "$LLAMA_DEFAULT_MAX_TOKENS"
        --cache-type-k "$LLAMA_CACHE_TYPE_K"
        --cache-type-v "$LLAMA_CACHE_TYPE_V"
        --metrics
        --no-webui
    )
    [[ "$LLAMA_CONT_BATCHING" == "true" ]] && out_cmd_ref+=(--cont-batching)
    [[ "$LLAMA_MMAP" != "true" ]] && out_cmd_ref+=(--no-mmap)
    [[ "$LLAMA_MLOCK" == "true" ]] && out_cmd_ref+=(--mlock)
    if [[ -n "$LLAMA_EXTRA_ARGS" ]]; then
        # shellcheck disable=SC2206
        local extra_args=( $LLAMA_EXTRA_ARGS )
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

stop_existing_server_if_requested() {
    [[ -f "$LLAMA_PID_FILE" ]] || return 0
    local pid
    pid="$(tr -d '[:space:]' <"$LLAMA_PID_FILE" 2>/dev/null || true)"
    [[ -n "$pid" ]] || return 0
    if kill -0 "$pid" >/dev/null 2>&1; then
        if [[ "$LLAMA_STOP_EXISTING" == "true" ]]; then
            info "Stopping existing llama-server process (pid=$pid)..."
            kill "$pid" || true
            sleep 2
        else
            warn "Existing process detected (pid=$pid) and LLAMA_STOP_EXISTING=false"
            warn "Leaving existing process running."
            return 1
        fi
    fi
    rm -f "$LLAMA_PID_FILE"
    return 0
}

start_server_background() {
    ensure_dir "$LLAMA_LOG_DIR" 0755
    stop_existing_server_if_requested || return 0

    local -a cmd
    build_server_cmd_array cmd
    info "Starting llama-server in background..."
    nohup "${cmd[@]}" >"$LLAMA_LOG_FILE" 2>&1 &
    local pid="$!"
    echo "$pid" >"$LLAMA_PID_FILE"
    info "llama-server pid: $pid"

    if wait_for_http_200 "http://${LLAMA_HOST}:${LLAMA_PORT}/health" "$LLAMA_HEALTH_TIMEOUT_SECONDS"; then
        info "Health endpoint is ready"
    else
        warn "Health check timed out after ${LLAMA_HEALTH_TIMEOUT_SECONDS}s"
        warn "Inspect logs: tail -n 200 \"$LLAMA_LOG_FILE\""
    fi
}

print_manual_command() {
    cat <<EOF
$LLAMA_SERVER_BIN --model "$LLAMA_MODEL_PATH" --host "$LLAMA_HOST" --port "$LLAMA_PORT" --threads "$LLAMA_THREADS" --threads-batch "$LLAMA_THREADS_BATCH" --parallel "$LLAMA_PARALLEL" --ctx-size "$LLAMA_CTX_SIZE" --n-predict "$LLAMA_DEFAULT_MAX_TOKENS" --cache-type-k "$LLAMA_CACHE_TYPE_K" --cache-type-v "$LLAMA_CACHE_TYPE_V" --metrics --no-webui
EOF
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
echo "=== llama.cpp PoC installation (rootless mode) ==="
echo ""
echo "Running as user: $(id -un) (uid=$(id -u), gid=$(id -g))"
echo ""

validate_config
install_dependencies_nonroot

check_command git
check_command cmake
check_command make
check_command curl
check_command sed
check_command sha256sum

echo "[1/5] Preparing directories..."
ensure_dir "$LLAMA_INSTALL_DIR" 0755
ensure_dir "$(dirname "$LLAMA_SRC_DIR")" 0755
ensure_dir "$LLAMA_MODEL_DIR" 0755
ensure_dir "$LLAMA_LOG_DIR" 0755
ensure_dir "$(dirname "$LLAMA_SERVER_BIN")" 0755

echo "[2/5] Installing llama.cpp runtime..."
if [[ "$LLAMA_SKIP_RUNTIME_BUILD" == "true" ]]; then
    warn "LLAMA_SKIP_RUNTIME_BUILD=true; skipping runtime build step"
else
    sync_runtime_source
    build_runtime
fi

[[ -x "$LLAMA_SERVER_BIN" ]] || err "llama-server binary not found at $LLAMA_SERVER_BIN"

echo "[3/5] Pulling pinned model artifact..."
download_model_if_needed

echo "[4/5] Writing runtime environment..."
write_runtime_env_file

echo "[5/5] Starting service (rootless background mode)..."
if [[ "$AUTO_START_LLAMACPP" == "true" ]]; then
    start_server_background
else
    info "AUTO_START_LLAMACPP=false; install complete without starting service"
fi

echo ""
echo "=== llama.cpp PoC rootless install complete ==="
echo "Runtime env file:    $LLAMA_ENV_FILE"
echo "llama-server binary: $LLAMA_SERVER_BIN"
echo "Model path:          $LLAMA_MODEL_PATH"
echo "Log file:            $LLAMA_LOG_FILE"
echo "PID file:            $LLAMA_PID_FILE"
echo "Pinned runtime:      $LLAMA_RUNTIME_TAG / $LLAMA_RUNTIME_COMMIT"
echo "Pinned model SHA256: $LLAMA_MODEL_SHA256"
echo ""
echo "Useful commands:"
echo "  ps -fp \"\$(cat \"$LLAMA_PID_FILE\" 2>/dev/null)\""
echo "  tail -f \"$LLAMA_LOG_FILE\""
echo "  curl -sf http://${LLAMA_HOST}:${LLAMA_PORT}/health"
echo "  curl -sf http://${LLAMA_HOST}:${LLAMA_PORT}/metrics"
echo ""
echo "Manual foreground run:"
print_manual_command
