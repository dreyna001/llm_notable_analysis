#!/usr/bin/env bash
# shellcheck shell=bash
# install_phi35_sudo.sh
# Root/sudo orchestration wrapper for phi3.5 llama.cpp setup.
#
# What it can do in one run (flag-controlled):
# 1) Install host packages (cmake/make/gcc/curl/etc)
# 2) Optionally download llama.cpp source at pinned commit
# 3) Optionally download Phi-3.5 GGUF at pinned revision
# 4) Invoke install_phi35_nonroot_offline.sh as target user
#
# Examples:
#   # Offline-style (install RPMs only + run installer with pre-staged artifacts)
#   sudo bash install_phi35_sudo.sh
#
#   # Full online pull + install in one shot
#   sudo PHI_DOWNLOAD_RUNTIME=true PHI_DOWNLOAD_MODEL=true bash install_phi35_sudo.sh
set -euo pipefail
IFS=$'\n\t'

trap 'echo "ERROR: Failed at line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -----------------------------------------------------------------------------
# Controls
# -----------------------------------------------------------------------------
PHI_INSTALL_PACKAGES="${PHI_INSTALL_PACKAGES:-true}"
PHI_DOWNLOAD_RUNTIME="${PHI_DOWNLOAD_RUNTIME:-false}"
PHI_DOWNLOAD_MODEL="${PHI_DOWNLOAD_MODEL:-false}"
PHI_RUN_INSTALLER="${PHI_RUN_INSTALLER:-true}"

# Optional package-manager override: dnf|yum|microdnf|apt-get
PHI_PACKAGE_MANAGER="${PHI_PACKAGE_MANAGER:-}"

# Target account for runtime/model paths and non-root installer execution
PHI_TARGET_USER="${PHI_TARGET_USER:-${SUDO_USER:-$(id -un)}}"
PHI_TARGET_HOME="${PHI_TARGET_HOME:-}"

readonly PHI_NONROOT_INSTALLER="${PHI_NONROOT_INSTALLER:-$SCRIPT_DIR/install_phi35_nonroot_offline.sh}"

# -----------------------------------------------------------------------------
# Pinned runtime/model sources
# -----------------------------------------------------------------------------
readonly PHI_RUNTIME_REPO="${PHI_RUNTIME_REPO:-https://github.com/ggml-org/llama.cpp.git}"
readonly PHI_EXPECTED_RUNTIME_COMMIT="${PHI_EXPECTED_RUNTIME_COMMIT:-149b249}"

readonly PHI_MODEL_FILENAME="${PHI_MODEL_FILENAME:-Phi-3.5-mini-instruct-Q4_K_M.gguf}"
readonly PHI_MODEL_REVISION="${PHI_MODEL_REVISION:-b1693692c4758ac83f0d0e65aff9b4f945f29941}"
readonly PHI_MODEL_SHA256_DEFAULT="e4165e3a71af97f1b4820da61079826d8752a2088e313af0c7d346796c38eff5"
PHI_MODEL_SHA256="${PHI_MODEL_SHA256:-$PHI_MODEL_SHA256_DEFAULT}"
readonly PHI_MODEL_URL="${PHI_MODEL_URL:-https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/$PHI_MODEL_REVISION/$PHI_MODEL_FILENAME}"

# -----------------------------------------------------------------------------
# Runtime knobs forwarded to non-root installer
# -----------------------------------------------------------------------------
PHI_SKIP_RUNTIME_BUILD="${PHI_SKIP_RUNTIME_BUILD:-false}"
PHI_AUTO_START="${PHI_AUTO_START:-true}"
PHI_STOP_EXISTING="${PHI_STOP_EXISTING:-true}"
PHI_HOST="${PHI_HOST:-127.0.0.1}"
PHI_PORT="${PHI_PORT:-8000}"
PHI_THREADS="${PHI_THREADS:-4}"
PHI_THREADS_BATCH="${PHI_THREADS_BATCH:-4}"
PHI_PARALLEL="${PHI_PARALLEL:-1}"
PHI_CTX_SIZE="${PHI_CTX_SIZE:-4096}"
PHI_N_PREDICT="${PHI_N_PREDICT:-1024}"
PHI_CACHE_TYPE_K="${PHI_CACHE_TYPE_K:-q8_0}"
PHI_CACHE_TYPE_V="${PHI_CACHE_TYPE_V:-q8_0}"
PHI_CONT_BATCHING="${PHI_CONT_BATCHING:-true}"
PHI_MMAP="${PHI_MMAP:-true}"
PHI_MLOCK="${PHI_MLOCK:-false}"
PHI_HEALTH_TIMEOUT_SECONDS="${PHI_HEALTH_TIMEOUT_SECONDS:-180}"
PHI_EXTRA_ARGS="${PHI_EXTRA_ARGS:-}"

# Paths (computed after target home is resolved)
PHI_INSTALL_DIR=""
PHI_RUNTIME_SRC_DIR=""
PHI_MODEL_DIR=""
PHI_MODEL_PATH=""

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

resolve_target_home() {
    if [[ -n "$PHI_TARGET_HOME" ]]; then
        [[ -d "$PHI_TARGET_HOME" ]] || err "PHI_TARGET_HOME does not exist: $PHI_TARGET_HOME"
        return 0
    fi

    PHI_TARGET_HOME="$(getent passwd "$PHI_TARGET_USER" | cut -d: -f6 || true)"
    [[ -n "$PHI_TARGET_HOME" ]] || err "Could not resolve home directory for PHI_TARGET_USER=$PHI_TARGET_USER"
    [[ -d "$PHI_TARGET_HOME" ]] || err "Resolved target home does not exist: $PHI_TARGET_HOME"
}

set_path_defaults() {
    PHI_INSTALL_DIR="${PHI_INSTALL_DIR:-$PHI_TARGET_HOME/.local/share/phi35_llamacpp}"
    PHI_RUNTIME_SRC_DIR="${PHI_RUNTIME_SRC_DIR:-$PHI_INSTALL_DIR/runtime/llama.cpp}"
    PHI_MODEL_DIR="${PHI_MODEL_DIR:-$PHI_INSTALL_DIR/models}"
    PHI_MODEL_PATH="${PHI_MODEL_PATH:-$PHI_MODEL_DIR/$PHI_MODEL_FILENAME}"
}

validate_config() {
    is_bool "$PHI_INSTALL_PACKAGES" || err "PHI_INSTALL_PACKAGES must be true/false"
    is_bool "$PHI_DOWNLOAD_RUNTIME" || err "PHI_DOWNLOAD_RUNTIME must be true/false"
    is_bool "$PHI_DOWNLOAD_MODEL" || err "PHI_DOWNLOAD_MODEL must be true/false"
    is_bool "$PHI_RUN_INSTALLER" || err "PHI_RUN_INSTALLER must be true/false"
    is_bool "$PHI_SKIP_RUNTIME_BUILD" || err "PHI_SKIP_RUNTIME_BUILD must be true/false"
    is_bool "$PHI_AUTO_START" || err "PHI_AUTO_START must be true/false"
    is_bool "$PHI_STOP_EXISTING" || err "PHI_STOP_EXISTING must be true/false"
    is_bool "$PHI_CONT_BATCHING" || err "PHI_CONT_BATCHING must be true/false"
    is_bool "$PHI_MMAP" || err "PHI_MMAP must be true/false"
    is_bool "$PHI_MLOCK" || err "PHI_MLOCK must be true/false"

    [[ "$PHI_RUNTIME_SRC_DIR" = /* ]] || err "PHI_RUNTIME_SRC_DIR must be an absolute path"
    [[ "$PHI_MODEL_PATH" = /* ]] || err "PHI_MODEL_PATH must be an absolute path"
}

detect_package_manager() {
    if [[ -n "$PHI_PACKAGE_MANAGER" ]]; then
        case "$PHI_PACKAGE_MANAGER" in
            dnf|yum|microdnf|apt-get) return 0 ;;
            *) err "Unsupported PHI_PACKAGE_MANAGER=$PHI_PACKAGE_MANAGER (expected dnf|yum|microdnf|apt-get)" ;;
        esac
    fi

    if command -v dnf >/dev/null 2>&1; then
        PHI_PACKAGE_MANAGER="dnf"
    elif command -v yum >/dev/null 2>&1; then
        PHI_PACKAGE_MANAGER="yum"
    elif command -v microdnf >/dev/null 2>&1; then
        PHI_PACKAGE_MANAGER="microdnf"
    elif command -v apt-get >/dev/null 2>&1; then
        PHI_PACKAGE_MANAGER="apt-get"
    else
        err "No supported package manager detected. Set PHI_INSTALL_PACKAGES=false if prerequisites are already installed."
    fi
}

install_dependencies() {
    [[ "$PHI_INSTALL_PACKAGES" == "true" ]] || {
        info "PHI_INSTALL_PACKAGES=false; skipping package installation"
        return 0
    }

    detect_package_manager
    info "Installing host prerequisites with $PHI_PACKAGE_MANAGER..."

    case "$PHI_PACKAGE_MANAGER" in
        dnf|yum|microdnf)
            "$PHI_PACKAGE_MANAGER" install -y bash coreutils curl cmake make gcc gcc-c++ ca-certificates git \
                || err "$PHI_PACKAGE_MANAGER dependency install failed"
            ;;
        apt-get)
            apt-get update -y || err "apt-get update failed"
            apt-get install -y bash coreutils curl cmake make gcc g++ ca-certificates git \
                || err "apt-get dependency install failed"
            ;;
    esac
}

ensure_parent_dirs() {
    mkdir -p "$(dirname "$PHI_RUNTIME_SRC_DIR")" "$PHI_MODEL_DIR"
}

download_runtime_if_requested() {
    [[ "$PHI_DOWNLOAD_RUNTIME" == "true" ]] || return 0

    check_command git
    if [[ -d "$PHI_RUNTIME_SRC_DIR" ]] && [[ ! -d "$PHI_RUNTIME_SRC_DIR/.git" ]]; then
        err "PHI_DOWNLOAD_RUNTIME=true but target exists and is not a git repo: $PHI_RUNTIME_SRC_DIR"
    fi

    if [[ -d "$PHI_RUNTIME_SRC_DIR/.git" ]]; then
        info "Updating existing llama.cpp repo at $PHI_RUNTIME_SRC_DIR..."
        git -C "$PHI_RUNTIME_SRC_DIR" fetch --tags --force origin || err "Failed to fetch runtime repo"
    else
        info "Cloning llama.cpp runtime source..."
        git clone "$PHI_RUNTIME_REPO" "$PHI_RUNTIME_SRC_DIR" || err "Failed to clone runtime repo"
        git -C "$PHI_RUNTIME_SRC_DIR" fetch --tags --force origin || err "Failed to fetch runtime tags"
    fi

    git -C "$PHI_RUNTIME_SRC_DIR" cat-file -e "${PHI_EXPECTED_RUNTIME_COMMIT}^{commit}" 2>/dev/null \
        || err "Pinned runtime commit not found: $PHI_EXPECTED_RUNTIME_COMMIT"
    git -C "$PHI_RUNTIME_SRC_DIR" checkout --force "$PHI_EXPECTED_RUNTIME_COMMIT" || err "Failed to checkout runtime commit"
}

verify_model_sha() {
    [[ -f "$PHI_MODEL_PATH" ]] || err "Model file missing: $PHI_MODEL_PATH"
    if [[ -z "$PHI_MODEL_SHA256" ]]; then
        warn "PHI_MODEL_SHA256 is empty; skipping model checksum validation."
        return 0
    fi
    local actual_sha
    actual_sha="$(sha256sum "$PHI_MODEL_PATH" | awk '{print $1}')"
    [[ "$actual_sha" == "$PHI_MODEL_SHA256" ]] || err "Model SHA256 mismatch. expected=$PHI_MODEL_SHA256 actual=$actual_sha"
}

download_model_if_requested() {
    [[ "$PHI_DOWNLOAD_MODEL" == "true" ]] || return 0

    check_command curl
    check_command sha256sum
    mkdir -p "$PHI_MODEL_DIR"

    local tmp_path
    tmp_path="${PHI_MODEL_PATH}.tmp"
    info "Downloading model artifact to $PHI_MODEL_PATH..."
    curl -fL --retry 3 --retry-all-errors -o "$tmp_path" "$PHI_MODEL_URL" || err "Model download failed"
    mv -f "$tmp_path" "$PHI_MODEL_PATH"
    verify_model_sha
}

chown_if_exists() {
    local path="$1"
    [[ -e "$path" ]] || return 0
    # Primary group is not always named like the user (LDAP, "users", etc.); avoid user:user.
    local grp
    grp="$(id -gn "$PHI_TARGET_USER" 2>/dev/null || true)"
    [[ -n "$grp" ]] || err "Could not resolve primary group for user: $PHI_TARGET_USER"
    chown -R "$PHI_TARGET_USER:$grp" "$path" || err "Failed to chown $path"
}

fix_ownership_for_target_user() {
    chown_if_exists "$PHI_INSTALL_DIR"
    chown_if_exists "$PHI_TARGET_HOME/.local/bin"
    chown_if_exists "$PHI_TARGET_HOME/.config/phi35_llamacpp"
}

run_nonroot_installer() {
    [[ "$PHI_RUN_INSTALLER" == "true" ]] || {
        info "PHI_RUN_INSTALLER=false; skipping install_phi35_nonroot_offline.sh handoff"
        return 0
    }

    [[ -f "$PHI_NONROOT_INSTALLER" ]] || err "Missing non-root installer: $PHI_NONROOT_INSTALLER"
    chmod 0755 "$PHI_NONROOT_INSTALLER" || true

    local -a env_args=(
        "HOME=$PHI_TARGET_HOME"
        "PHI_INSTALL_DIR=$PHI_INSTALL_DIR"
        "PHI_RUNTIME_SRC_DIR=$PHI_RUNTIME_SRC_DIR"
        "PHI_MODEL_PATH=$PHI_MODEL_PATH"
        "PHI_MODEL_SHA256=$PHI_MODEL_SHA256"
        "PHI_EXPECTED_RUNTIME_COMMIT=$PHI_EXPECTED_RUNTIME_COMMIT"
        "PHI_SKIP_RUNTIME_BUILD=$PHI_SKIP_RUNTIME_BUILD"
        "PHI_AUTO_START=$PHI_AUTO_START"
        "PHI_STOP_EXISTING=$PHI_STOP_EXISTING"
        "PHI_HOST=$PHI_HOST"
        "PHI_PORT=$PHI_PORT"
        "PHI_THREADS=$PHI_THREADS"
        "PHI_THREADS_BATCH=$PHI_THREADS_BATCH"
        "PHI_PARALLEL=$PHI_PARALLEL"
        "PHI_CTX_SIZE=$PHI_CTX_SIZE"
        "PHI_N_PREDICT=$PHI_N_PREDICT"
        "PHI_CACHE_TYPE_K=$PHI_CACHE_TYPE_K"
        "PHI_CACHE_TYPE_V=$PHI_CACHE_TYPE_V"
        "PHI_CONT_BATCHING=$PHI_CONT_BATCHING"
        "PHI_MMAP=$PHI_MMAP"
        "PHI_MLOCK=$PHI_MLOCK"
        "PHI_HEALTH_TIMEOUT_SECONDS=$PHI_HEALTH_TIMEOUT_SECONDS"
        "PHI_EXTRA_ARGS=$PHI_EXTRA_ARGS"
    )

    info "Running non-root installer as user: $PHI_TARGET_USER"
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$PHI_TARGET_USER" -- env "${env_args[@]}" bash "$PHI_NONROOT_INSTALLER"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -u "$PHI_TARGET_USER" -H env "${env_args[@]}" bash "$PHI_NONROOT_INSTALLER"
    else
        err "Neither runuser nor sudo is available to execute installer as target user."
    fi
}

echo "=== Phi-3.5 sudo installer wrapper ==="
echo "Running as: $(id -un) uid=$(id -u)"
echo "Target user: $PHI_TARGET_USER"
echo ""

check_root
resolve_target_home
set_path_defaults
validate_config
ensure_parent_dirs
install_dependencies
download_runtime_if_requested
download_model_if_requested
fix_ownership_for_target_user
run_nonroot_installer

echo ""
echo "=== complete ==="
echo "Target user:        $PHI_TARGET_USER"
echo "Target home:        $PHI_TARGET_HOME"
echo "Runtime source dir: $PHI_RUNTIME_SRC_DIR"
echo "Model path:         $PHI_MODEL_PATH"
echo "Downloads used:     runtime=$PHI_DOWNLOAD_RUNTIME model=$PHI_DOWNLOAD_MODEL"
echo ""
echo "Tip:"
echo "  sudo PHI_DOWNLOAD_RUNTIME=true PHI_DOWNLOAD_MODEL=true bash \"$SCRIPT_DIR/install_phi35_sudo.sh\""
