#!/usr/bin/env bash
# shellcheck shell=bash
# install_phi35_sudo.sh
# Root/sudo orchestration wrapper for phi3.5 llama.cpp setup.
#
# What it can do in one run (flag-controlled):
# 1) Install host packages (cmake/make/gcc/curl/etc)
# 2) Optionally download llama.cpp source at pinned commit
# 3) Optionally download Phi-3.5 GGUF at pinned revision
# 4) Invoke install_phi35_nonroot_offline.sh as target user (or as root if PHI_RUN_INSTALLER_AS_ROOT=true)
# 5) Optionally install/manage a systemd unit for llama.cpp service
#
# Examples:
#   # Offline-style (install RPMs only + run installer with pre-staged artifacts)
#   sudo bash install_phi35_sudo.sh
#
#   # Full online pull + install in one shot
#   sudo PHI_DOWNLOAD_RUNTIME=true PHI_DOWNLOAD_MODEL=true bash install_phi35_sudo.sh
#
#   # Run inner build/launcher as root (install under /root/.local/... unless PHI_TARGET_HOME is set)
#   sudo PHI_RUN_INSTALLER_AS_ROOT=true bash install_phi35_sudo.sh
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
# If true: run install_phi35_nonroot_offline.sh as root (no runuser/sudo -u); use root's home unless PHI_TARGET_HOME is set
PHI_RUN_INSTALLER_AS_ROOT="${PHI_RUN_INSTALLER_AS_ROOT:-false}"
PHI_INSTALL_SYSTEMD_UNIT="${PHI_INSTALL_SYSTEMD_UNIT:-auto}"  # auto|true|false
PHI_AUTO_START_SYSTEMD="${PHI_AUTO_START_SYSTEMD:-true}"
PHI_SYSTEMD_UNIT_NAME="${PHI_SYSTEMD_UNIT_NAME:-llama-phi35.service}"
readonly PHI_SYSTEMD_UNIT_TEMPLATE="${PHI_SYSTEMD_UNIT_TEMPLATE:-$SCRIPT_DIR/llama-phi35.service}"

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
PHI_RUNTIME_LIB_DIR="${PHI_RUNTIME_LIB_DIR:-}"
PHI_REWRITE_RPATH="${PHI_REWRITE_RPATH:-true}"


# Paths (computed after target home is resolved)
PHI_INSTALL_DIR=""
PHI_RUNTIME_SRC_DIR=""
PHI_RUNTIME_BUILD_DIR=""
PHI_MODEL_DIR=""
PHI_MODEL_PATH=""
PHI_SERVER_BIN=""
PHI_SYSTEMD_ENV_FILE=""
PHI_TARGET_GROUP=""
PHI_INSTALL_SYSTEMD_EFFECTIVE="false"
PHI_AUTO_START_INNER="$PHI_AUTO_START"

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

is_systemd_runtime() {
    [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1
}

# When the inner installer runs as root, install under root's home unless PHI_TARGET_HOME is already set.
apply_installer_as_root_mode() {
    [[ "$PHI_RUN_INSTALLER_AS_ROOT" == "true" ]] || return 0
    PHI_TARGET_USER="root"
    if [[ -z "$PHI_TARGET_HOME" ]]; then
        PHI_TARGET_HOME="$(getent passwd root | cut -d: -f6 || true)"
        [[ -n "$PHI_TARGET_HOME" ]] || PHI_TARGET_HOME="/root"
    fi
    [[ -d "$PHI_TARGET_HOME" ]] || err "PHI_TARGET_HOME does not exist: $PHI_TARGET_HOME"
    info "PHI_RUN_INSTALLER_AS_ROOT=true: using HOME=$PHI_TARGET_HOME (root-owned install)"
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

resolve_target_group() {
    PHI_TARGET_GROUP="$(id -gn "$PHI_TARGET_USER" 2>/dev/null || true)"
    [[ -n "$PHI_TARGET_GROUP" ]] || err "Could not resolve primary group for PHI_TARGET_USER=$PHI_TARGET_USER"
}

set_path_defaults() {
    PHI_INSTALL_DIR="${PHI_INSTALL_DIR:-$PHI_TARGET_HOME/.local/share/phi35_llamacpp}"
    PHI_RUNTIME_SRC_DIR="${PHI_RUNTIME_SRC_DIR:-$PHI_INSTALL_DIR/runtime/llama.cpp}"
    PHI_RUNTIME_BUILD_DIR="${PHI_RUNTIME_BUILD_DIR:-$PHI_RUNTIME_SRC_DIR/build}"
    PHI_MODEL_DIR="${PHI_MODEL_DIR:-$PHI_INSTALL_DIR/models}"
    PHI_MODEL_PATH="${PHI_MODEL_PATH:-$PHI_MODEL_DIR/$PHI_MODEL_FILENAME}"
    # Colocate the installed server binary with PHI_INSTALL_DIR (not ~/.local/bin) unless overridden.
    PHI_SERVER_BIN="${PHI_SERVER_BIN:-$PHI_INSTALL_DIR/bin/llama-server}"
    PHI_RUNTIME_LIB_DIR="${PHI_RUNTIME_LIB_DIR:-$(dirname "$PHI_SERVER_BIN")}"
    PHI_SYSTEMD_ENV_FILE="${PHI_SYSTEMD_ENV_FILE:-$PHI_TARGET_HOME/.config/phi35_llamacpp/phi35.env}"
}

validate_config() {
    is_bool "$PHI_INSTALL_PACKAGES" || err "PHI_INSTALL_PACKAGES must be true/false"
    is_bool "$PHI_DOWNLOAD_RUNTIME" || err "PHI_DOWNLOAD_RUNTIME must be true/false"
    is_bool "$PHI_DOWNLOAD_MODEL" || err "PHI_DOWNLOAD_MODEL must be true/false"
    is_bool "$PHI_RUN_INSTALLER" || err "PHI_RUN_INSTALLER must be true/false"
    is_bool "$PHI_RUN_INSTALLER_AS_ROOT" || err "PHI_RUN_INSTALLER_AS_ROOT must be true/false"
    is_bool "$PHI_SKIP_RUNTIME_BUILD" || err "PHI_SKIP_RUNTIME_BUILD must be true/false"
    is_bool "$PHI_AUTO_START" || err "PHI_AUTO_START must be true/false"
    is_bool "$PHI_STOP_EXISTING" || err "PHI_STOP_EXISTING must be true/false"
    is_bool "$PHI_CONT_BATCHING" || err "PHI_CONT_BATCHING must be true/false"
    is_bool "$PHI_MMAP" || err "PHI_MMAP must be true/false"
    is_bool "$PHI_MLOCK" || err "PHI_MLOCK must be true/false"
    is_bool "$PHI_REWRITE_RPATH" || err "PHI_REWRITE_RPATH must be true/false"
    is_bool "$PHI_AUTO_START_SYSTEMD" || err "PHI_AUTO_START_SYSTEMD must be true/false"

    case "$PHI_INSTALL_SYSTEMD_UNIT" in
        auto|true|false) ;;
        *) err "PHI_INSTALL_SYSTEMD_UNIT must be one of: auto, true, false" ;;
    esac

    [[ "$PHI_RUNTIME_SRC_DIR" = /* ]] || err "PHI_RUNTIME_SRC_DIR must be an absolute path"
    [[ "$PHI_RUNTIME_BUILD_DIR" = /* ]] || err "PHI_RUNTIME_BUILD_DIR must be an absolute path"
    [[ "$PHI_MODEL_PATH" = /* ]] || err "PHI_MODEL_PATH must be an absolute path"
    [[ "$PHI_SERVER_BIN" = /* ]] || err "PHI_SERVER_BIN must be an absolute path"
    [[ "$PHI_RUNTIME_LIB_DIR" = /* ]] || err "PHI_RUNTIME_LIB_DIR must be an absolute path"
    [[ "$PHI_SYSTEMD_ENV_FILE" = /* ]] || err "PHI_SYSTEMD_ENV_FILE must be an absolute path"
}

decide_systemd_install() {
    case "$PHI_INSTALL_SYSTEMD_UNIT" in
        auto)
            if is_systemd_runtime; then
                PHI_INSTALL_SYSTEMD_EFFECTIVE="true"
            else
                PHI_INSTALL_SYSTEMD_EFFECTIVE="false"
            fi
            ;;
        true)
            is_systemd_runtime || err "PHI_INSTALL_SYSTEMD_UNIT=true but systemd runtime is unavailable"
            PHI_INSTALL_SYSTEMD_EFFECTIVE="true"
            ;;
        false)
            PHI_INSTALL_SYSTEMD_EFFECTIVE="false"
            ;;
    esac

    # Avoid duplicate processes: when systemd service management is enabled,
    # do not also auto-start via nohup in the non-root installer.
    PHI_AUTO_START_INNER="$PHI_AUTO_START"
    if [[ "$PHI_INSTALL_SYSTEMD_EFFECTIVE" == "true" ]] && [[ "$PHI_AUTO_START" == "true" ]]; then
        PHI_AUTO_START_INNER="false"
        info "Systemd unit enabled; forcing inner PHI_AUTO_START=false to avoid duplicate llama-server processes"
    fi
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
    chmod 0644 "$PHI_MODEL_PATH" || true
    verify_model_sha
}

chown_if_exists() {
    local path="$1"
    [[ -e "$path" ]] || return 0
    chown -R "$PHI_TARGET_USER:$PHI_TARGET_GROUP" "$path" || err "Failed to chown $path"
}

fix_ownership_for_target_user() {
    if [[ "$PHI_RUN_INSTALLER_AS_ROOT" == "true" ]]; then
        info "PHI_RUN_INSTALLER_AS_ROOT=true; skipping chown (install tree stays root-owned)"
        return 0
    fi
    chown_if_exists "$PHI_INSTALL_DIR"
    chown_if_exists "$PHI_MODEL_PATH"
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
        "PHI_RUNTIME_BUILD_DIR=$PHI_RUNTIME_BUILD_DIR"
        "PHI_SERVER_BIN=$PHI_SERVER_BIN"
        "PHI_RUNTIME_LIB_DIR=$PHI_RUNTIME_LIB_DIR"
        "PHI_MODEL_PATH=$PHI_MODEL_PATH"
        "PHI_MODEL_SHA256=$PHI_MODEL_SHA256"
        "PHI_EXPECTED_RUNTIME_COMMIT=$PHI_EXPECTED_RUNTIME_COMMIT"
        "PHI_SKIP_RUNTIME_BUILD=$PHI_SKIP_RUNTIME_BUILD"
        "PHI_AUTO_START=$PHI_AUTO_START_INNER"
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
        "PHI_REWRITE_RPATH=$PHI_REWRITE_RPATH"
        "PHI_ENV_FILE=$PHI_SYSTEMD_ENV_FILE"
    )

    if [[ "$PHI_RUN_INSTALLER_AS_ROOT" == "true" ]]; then
        info "Running installer as root (PHI_RUN_INSTALLER_AS_ROOT=true)"
        env "${env_args[@]}" bash "$PHI_NONROOT_INSTALLER"
        return 0
    fi

    info "Running non-root installer as user: $PHI_TARGET_USER"
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$PHI_TARGET_USER" -- env "${env_args[@]}" bash "$PHI_NONROOT_INSTALLER"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -u "$PHI_TARGET_USER" -H env "${env_args[@]}" bash "$PHI_NONROOT_INSTALLER"
    else
        err "Neither runuser nor sudo is available to execute installer as target user."
    fi
}

build_systemd_execstart() {
    local -n out_ref=$1
    local -a cmd=(
        /usr/bin/env
        "LD_LIBRARY_PATH=$PHI_RUNTIME_LIB_DIR"
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
    [[ "$PHI_CONT_BATCHING" == "true" ]] && cmd+=(--cont-batching)
    [[ "$PHI_MMAP" != "true" ]] && cmd+=(--no-mmap)
    [[ "$PHI_MLOCK" == "true" ]] && cmd+=(--mlock)
    if [[ -n "$PHI_EXTRA_ARGS" ]]; then
        # shellcheck disable=SC2206
        local extra_args=( $PHI_EXTRA_ARGS )
        cmd+=("${extra_args[@]}")
    fi

    out_ref=""
    local token
    for token in "${cmd[@]}"; do
        if [[ -n "$out_ref" ]]; then
            out_ref+=" "
        fi
        out_ref+="$token"
    done
}

install_systemd_unit_if_requested() {
    [[ "$PHI_INSTALL_SYSTEMD_EFFECTIVE" == "true" ]] || {
        info "Systemd unit install skipped (PHI_INSTALL_SYSTEMD_UNIT=$PHI_INSTALL_SYSTEMD_UNIT)"
        return 0
    }

    [[ -f "$PHI_SYSTEMD_UNIT_TEMPLATE" ]] || err "Missing systemd unit template: $PHI_SYSTEMD_UNIT_TEMPLATE"

    local unit_dst="/etc/systemd/system/$PHI_SYSTEMD_UNIT_NAME"
    cp "$PHI_SYSTEMD_UNIT_TEMPLATE" "$unit_dst" || err "Failed to copy systemd unit to $unit_dst"

    local exec_start_line
    build_systemd_execstart exec_start_line

    sed -i -E "s|^User=.*$|User=$PHI_TARGET_USER|" "$unit_dst" || err "Failed to patch User in $unit_dst"
    sed -i -E "s|^Group=.*$|Group=$PHI_TARGET_GROUP|" "$unit_dst" || err "Failed to patch Group in $unit_dst"
    sed -i -E "s|^WorkingDirectory=.*$|WorkingDirectory=$PHI_INSTALL_DIR|" "$unit_dst" || err "Failed to patch WorkingDirectory in $unit_dst"
    sed -i -E "s|^EnvironmentFile=.*$|EnvironmentFile=-$PHI_SYSTEMD_ENV_FILE|" "$unit_dst" || err "Failed to patch EnvironmentFile in $unit_dst"
    sed -i -E "s|^ExecStart=.*$|ExecStart=$exec_start_line|" "$unit_dst" || err "Failed to patch ExecStart in $unit_dst"
    sed -i -E "s|^SyslogIdentifier=.*$|SyslogIdentifier=${PHI_SYSTEMD_UNIT_NAME%.service}|" "$unit_dst" || err "Failed to patch SyslogIdentifier in $unit_dst"

    systemctl daemon-reload || err "Failed to reload systemd"
    systemctl enable "$PHI_SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true

    if [[ "$PHI_AUTO_START_SYSTEMD" == "true" ]]; then
        systemctl restart "$PHI_SYSTEMD_UNIT_NAME" 2>/dev/null || \
        systemctl start "$PHI_SYSTEMD_UNIT_NAME" 2>/dev/null || \
        err "Failed to start/restart $PHI_SYSTEMD_UNIT_NAME"
        info "Installed + started systemd unit: $PHI_SYSTEMD_UNIT_NAME"
    else
        info "Installed systemd unit (not started): $PHI_SYSTEMD_UNIT_NAME"
    fi
}

echo "=== Phi-3.5 sudo installer wrapper ==="
echo "Running as: $(id -un) uid=$(id -u)"
echo "Installer as root: $PHI_RUN_INSTALLER_AS_ROOT"
echo ""

check_root
apply_installer_as_root_mode
resolve_target_home
resolve_target_group
set_path_defaults

echo "Target user: $PHI_TARGET_USER"
echo "Target home: $PHI_TARGET_HOME"
echo "Runtime build dir: $PHI_RUNTIME_BUILD_DIR"
echo "Server binary: $PHI_SERVER_BIN"
echo "Runtime lib dir: $PHI_RUNTIME_LIB_DIR"
echo ""

validate_config
decide_systemd_install
ensure_parent_dirs
install_dependencies
download_runtime_if_requested
download_model_if_requested
fix_ownership_for_target_user
run_nonroot_installer
install_systemd_unit_if_requested

echo ""
echo "=== complete ==="
echo "Target user:        $PHI_TARGET_USER"
echo "Target home:        $PHI_TARGET_HOME"
echo "Runtime source dir: $PHI_RUNTIME_SRC_DIR"
echo "Runtime build dir:  $PHI_RUNTIME_BUILD_DIR"
echo "Runtime lib dir:    $PHI_RUNTIME_LIB_DIR"
echo "Model path:         $PHI_MODEL_PATH"
echo "Downloads used:     runtime=$PHI_DOWNLOAD_RUNTIME model=$PHI_DOWNLOAD_MODEL"
echo "Systemd managed:    $PHI_INSTALL_SYSTEMD_EFFECTIVE (mode=$PHI_INSTALL_SYSTEMD_UNIT)"
echo "Systemd unit:       $PHI_SYSTEMD_UNIT_NAME"
echo ""
echo "Tip:"
echo "  sudo PHI_DOWNLOAD_RUNTIME=true PHI_DOWNLOAD_MODEL=true bash \"$SCRIPT_DIR/install_phi35_sudo.sh\""
echo "  sudo PHI_RUN_INSTALLER_AS_ROOT=true bash \"$SCRIPT_DIR/install_phi35_sudo.sh\"   # build/run under root home (default /root)"
