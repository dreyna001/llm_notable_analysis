#!/usr/bin/env bash
# shellcheck shell=bash
# install_llamacpp.sh — standalone llama.cpp PoC installer for on-prem CPU hosts
set -euo pipefail
IFS=$'\n\t'

trap 'echo "ERROR: Failed at line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

# -----------------------------------------------------------------------------
# Constants (pinned baseline)
# -----------------------------------------------------------------------------
readonly LLAMA_SERVICE_NAME="llamacpp"
readonly LLAMA_USER="llamacpp"
readonly LLAMA_GROUP="llamacpp"

readonly LLAMA_RUNTIME_REPO="${LLAMA_RUNTIME_REPO:-https://github.com/ggml-org/llama.cpp.git}"
readonly LLAMA_RUNTIME_TAG="${LLAMA_RUNTIME_TAG:-b8457}"
readonly LLAMA_RUNTIME_COMMIT="${LLAMA_RUNTIME_COMMIT:-149b249}"

readonly LLAMA_MODEL_REPO="${LLAMA_MODEL_REPO:-Qwen/Qwen3-4B-GGUF}"
readonly LLAMA_MODEL_FILENAME="${LLAMA_MODEL_FILENAME:-Qwen3-4B-Q4_K_M.gguf}"
readonly LLAMA_MODEL_REVISION="${LLAMA_MODEL_REVISION:-a9a60d009fa7ff9606305047c2bf77ac25dbec49}"
readonly LLAMA_MODEL_SHA256="${LLAMA_MODEL_SHA256:-7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5}"
readonly LLAMA_MODEL_SIZE_BYTES="${LLAMA_MODEL_SIZE_BYTES:-2497280256}"

# -----------------------------------------------------------------------------
# Configurable paths and runtime settings
# -----------------------------------------------------------------------------
readonly LLAMA_INSTALL_DIR="${LLAMA_INSTALL_DIR:-/opt/llamacpp}"
readonly LLAMA_SRC_DIR="${LLAMA_SRC_DIR:-$LLAMA_INSTALL_DIR/src/llama.cpp}"
readonly LLAMA_MODEL_DIR="${LLAMA_MODEL_DIR:-$LLAMA_INSTALL_DIR/models}"
readonly LLAMA_MODEL_PATH="${LLAMA_MODEL_PATH:-$LLAMA_MODEL_DIR/$LLAMA_MODEL_FILENAME}"
readonly LLAMA_ENV_DIR="${LLAMA_ENV_DIR:-/etc/llamacpp}"
readonly LLAMA_ENV_FILE="${LLAMA_ENV_FILE:-$LLAMA_ENV_DIR/llamacpp.env}"
readonly LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-/usr/local/bin/llama-server}"

readonly LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
readonly LLAMA_PORT="${LLAMA_PORT:-8080}"
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
readonly LLAMA_INSTALL_DEPS="${LLAMA_INSTALL_DEPS:-true}"
readonly LLAMA_FORCE_MODEL_REDOWNLOAD="${LLAMA_FORCE_MODEL_REDOWNLOAD:-false}"
readonly LLAMA_HEALTH_TIMEOUT_SECONDS="${LLAMA_HEALTH_TIMEOUT_SECONDS:-900}"
readonly LLAMA_RESET_OVERRIDES="${LLAMA_RESET_OVERRIDES:-false}"
readonly LLAMA_SKIP_SYSTEMD="${LLAMA_SKIP_SYSTEMD:-false}"

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

check_root() {
    [[ $EUID -eq 0 ]] || err "This script must be run as root (or with sudo)."
}

check_command() {
    command -v "$1" >/dev/null 2>&1 || err "Required command not found: $1"
}

has_systemd_runtime() {
    command -v systemctl >/dev/null 2>&1 || return 1
    [[ -d /run/systemd/system ]] || return 1
    [[ -r /proc/1/comm ]] || return 1
    local init_name
    init_name="$(tr -d '\n' </proc/1/comm 2>/dev/null || true)"
    [[ "$init_name" == "systemd" ]]
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
    is_bool "$LLAMA_RESET_OVERRIDES" || err "LLAMA_RESET_OVERRIDES must be true/false"
    is_bool "$LLAMA_SKIP_SYSTEMD" || err "LLAMA_SKIP_SYSTEMD must be true/false"
    is_bool "$LLAMA_CONT_BATCHING" || err "LLAMA_CONT_BATCHING must be true/false"
    is_bool "$LLAMA_MMAP" || err "LLAMA_MMAP must be true/false"
    is_bool "$LLAMA_MLOCK" || err "LLAMA_MLOCK must be true/false"

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

create_user_if_missing() {
    if getent group "$LLAMA_GROUP" >/dev/null 2>&1; then
        :
    else
        groupadd --system "$LLAMA_GROUP" || err "Failed to create group: $LLAMA_GROUP"
        info "Created group: $LLAMA_GROUP"
    fi

    if id "$LLAMA_USER" >/dev/null 2>&1; then
        info "User exists: $LLAMA_USER"
    else
        useradd --system --gid "$LLAMA_GROUP" --shell /sbin/nologin --home-dir "$LLAMA_INSTALL_DIR" --create-home "$LLAMA_USER" \
            || err "Failed to create user: $LLAMA_USER"
        info "Created user: $LLAMA_USER"
    fi
}

ensure_dir() {
    local dir="$1"
    local owner="$2"
    local mode="$3"
    mkdir -p "$dir" || err "Failed to create directory: $dir"
    chown "$owner" "$dir" || err "Failed to chown directory: $dir"
    chmod "$mode" "$dir" || err "Failed to chmod directory: $dir"
}

strip_crlf_best_effort() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    sed -i 's/\r$//' "$file" 2>/dev/null || true
}

install_dependencies() {
    [[ "$LLAMA_INSTALL_DEPS" == "true" ]] || {
        info "LLAMA_INSTALL_DEPS=false; skipping dependency installation"
        return 0
    }

    if command -v dnf >/dev/null 2>&1; then
        info "Installing dependencies with dnf..."
        dnf install -y git cmake gcc gcc-c++ make curl ca-certificates || err "dnf dependency install failed"
    elif command -v apt-get >/dev/null 2>&1; then
        info "Installing dependencies with apt-get..."
        apt-get update -y || err "apt-get update failed"
        apt-get install -y git cmake build-essential curl ca-certificates || err "apt-get dependency install failed"
    else
        warn "No supported package manager found (dnf/apt-get). Assuming dependencies are pre-installed."
    fi
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

    mkdir -p "$(dirname "$LLAMA_MODEL_PATH")"

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
    # curl < 7.71 does not support --retry-all-errors (e.g., Ubuntu 20.04 ships 7.68).
    # Use it when available, otherwise fall back to portable retry flags.
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
    chown "$LLAMA_USER:$LLAMA_GROUP" "$LLAMA_MODEL_PATH" || true
}

write_runtime_env_file() {
    local cont_batching_flag mmap_flag mlock_flag

    cont_batching_flag=""
    [[ "$LLAMA_CONT_BATCHING" == "true" ]] && cont_batching_flag="--cont-batching"

    mmap_flag=""
    [[ "$LLAMA_MMAP" != "true" ]] && mmap_flag="--no-mmap"

    mlock_flag=""
    [[ "$LLAMA_MLOCK" == "true" ]] && mlock_flag="--mlock"

    mkdir -p "$LLAMA_ENV_DIR"
    cat >"$LLAMA_ENV_FILE" <<EOF
# Generated by install_llamacpp.sh
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
EOF
    chown root:"$LLAMA_GROUP" "$LLAMA_ENV_FILE" || true
    chmod 0640 "$LLAMA_ENV_FILE" || true
}

escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

install_unit() {
    local script_dir unit_src unit_dst esc_install
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    unit_src="$script_dir/systemd/llamacpp.service"
    unit_dst="/etc/systemd/system/${LLAMA_SERVICE_NAME}.service"

    [[ -f "$unit_src" ]] || err "Unit template missing: $unit_src"
    strip_crlf_best_effort "$unit_src"
    cp "$unit_src" "$unit_dst" || err "Failed to copy unit file"
    strip_crlf_best_effort "$unit_dst"

    esc_install="$(escape_sed_replacement "$LLAMA_INSTALL_DIR")"
    sed -i -E "s|^WorkingDirectory=.*$|WorkingDirectory=${esc_install}|" "$unit_dst"
    sed -i -E "s|^User=.*$|User=${LLAMA_USER}|" "$unit_dst"
    sed -i -E "s|^Group=.*$|Group=${LLAMA_GROUP}|" "$unit_dst"
}

handle_unit_dropins() {
    local dropin_dir="/etc/systemd/system/${LLAMA_SERVICE_NAME}.service.d"
    [[ -d "$dropin_dir" ]] || return 0

    local conf_files=("$dropin_dir"/*.conf)
    [[ -e "${conf_files[0]}" ]] || return 0

    if [[ "$LLAMA_RESET_OVERRIDES" == "true" ]]; then
        rm -f "$dropin_dir"/*.conf || err "Failed to remove unit drop-ins in $dropin_dir"
        info "Cleared existing unit drop-ins from $dropin_dir"
    else
        warn "Existing unit drop-ins detected in $dropin_dir (may override installed unit)"
        warn "Set LLAMA_RESET_OVERRIDES=true to clear them during install"
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

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
echo "=== llama.cpp PoC installation ==="
echo ""

check_root
validate_config
install_dependencies

check_command git
check_command cmake
check_command make
check_command curl
check_command sed
check_command sha256sum

echo "[1/7] Creating service account..."
create_user_if_missing

echo "[2/7] Preparing directories..."
ensure_dir "$LLAMA_INSTALL_DIR" "$LLAMA_USER:$LLAMA_GROUP" 0755
ensure_dir "$(dirname "$LLAMA_SRC_DIR")" "$LLAMA_USER:$LLAMA_GROUP" 0755
ensure_dir "$LLAMA_MODEL_DIR" "$LLAMA_USER:$LLAMA_GROUP" 0755
ensure_dir "$LLAMA_ENV_DIR" "root:$LLAMA_GROUP" 0750

echo "[3/7] Installing llama.cpp runtime..."
if [[ "$LLAMA_SKIP_RUNTIME_BUILD" == "true" ]]; then
    warn "LLAMA_SKIP_RUNTIME_BUILD=true; skipping runtime build step"
else
    sync_runtime_source
    build_runtime
fi

[[ -x "$LLAMA_SERVER_BIN" ]] || err "llama-server binary not found at $LLAMA_SERVER_BIN"

echo "[4/7] Pulling pinned model artifact..."
download_model_if_needed

echo "[5/7] Writing runtime environment..."
write_runtime_env_file

SYSTEMD_READY="false"
echo "[6/7] Installing systemd unit..."
if [[ "$LLAMA_SKIP_SYSTEMD" == "true" ]]; then
    warn "LLAMA_SKIP_SYSTEMD=true; skipping systemd unit installation"
elif has_systemd_runtime; then
    install_unit
    handle_unit_dropins
    systemctl daemon-reload || err "Failed to reload systemd"
    SYSTEMD_READY="true"
else
    warn "systemd is unavailable (PID 1 is not systemd); skipping systemd unit installation"
fi

echo "[7/7] Enabling/starting service..."
if [[ "$SYSTEMD_READY" == "true" ]]; then
    if [[ "$AUTO_START_LLAMACPP" == "true" ]]; then
        systemctl enable "$LLAMA_SERVICE_NAME" || true
        systemctl restart "$LLAMA_SERVICE_NAME" || systemctl start "$LLAMA_SERVICE_NAME" || err "Failed to start $LLAMA_SERVICE_NAME"
        if wait_for_http_200 "http://${LLAMA_HOST}:${LLAMA_PORT}/health" "$LLAMA_HEALTH_TIMEOUT_SECONDS"; then
            info "Health endpoint is ready"
        else
            warn "Health check timed out after ${LLAMA_HEALTH_TIMEOUT_SECONDS}s"
            warn "Inspect logs: sudo journalctl -u $LLAMA_SERVICE_NAME -n 200 --no-pager"
        fi
    else
        info "AUTO_START_LLAMACPP=false; install complete without starting service"
    fi
else
    info "Skipping enable/start because systemd is unavailable or disabled"
    info "To run manually in this environment:"
    info "  /usr/local/bin/llama-server --model \"$LLAMA_MODEL_PATH\" --host \"$LLAMA_HOST\" --port \"$LLAMA_PORT\" --threads \"$LLAMA_THREADS\" --threads-batch \"$LLAMA_THREADS_BATCH\" --parallel \"$LLAMA_PARALLEL\" --ctx-size \"$LLAMA_CTX_SIZE\" --n-predict \"$LLAMA_DEFAULT_MAX_TOKENS\" --cache-type-k \"$LLAMA_CACHE_TYPE_K\" --cache-type-v \"$LLAMA_CACHE_TYPE_V\" --metrics --no-webui"
fi

echo ""
echo "=== llama.cpp PoC install complete ==="
echo "Service name:           $LLAMA_SERVICE_NAME"
if [[ "$SYSTEMD_READY" == "true" ]]; then
    echo "Systemd unit:           /etc/systemd/system/${LLAMA_SERVICE_NAME}.service"
else
    echo "Systemd unit:           skipped (systemd unavailable/disabled)"
fi
echo "Runtime env file:       $LLAMA_ENV_FILE"
echo "llama-server binary:    $LLAMA_SERVER_BIN"
echo "Model path:             $LLAMA_MODEL_PATH"
echo "Pinned runtime:         $LLAMA_RUNTIME_TAG / $LLAMA_RUNTIME_COMMIT"
echo "Pinned model SHA256:    $LLAMA_MODEL_SHA256"
echo ""
echo "Useful commands:"
if [[ "$SYSTEMD_READY" == "true" ]]; then
    echo "  sudo systemctl status $LLAMA_SERVICE_NAME"
    echo "  sudo journalctl -u $LLAMA_SERVICE_NAME -f"
else
    echo "  /usr/local/bin/llama-server --model \"$LLAMA_MODEL_PATH\" --host \"$LLAMA_HOST\" --port \"$LLAMA_PORT\" --threads \"$LLAMA_THREADS\" --threads-batch \"$LLAMA_THREADS_BATCH\" --parallel \"$LLAMA_PARALLEL\" --ctx-size \"$LLAMA_CTX_SIZE\" --n-predict \"$LLAMA_DEFAULT_MAX_TOKENS\" --cache-type-k \"$LLAMA_CACHE_TYPE_K\" --cache-type-v \"$LLAMA_CACHE_TYPE_V\" --metrics --no-webui"
fi
echo "  curl -sf http://${LLAMA_HOST}:${LLAMA_PORT}/health"
echo "  curl -sf http://${LLAMA_HOST}:${LLAMA_PORT}/metrics"
