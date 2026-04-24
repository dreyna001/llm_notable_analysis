#!/usr/bin/env bash
# shellcheck shell=bash
# install_vllm.sh — standalone vLLM installer for on-prem hosts (RHEL family)
set -euo pipefail
IFS=$'\n\t'

trap 'echo "ERROR: Failed at line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
readonly VLLM_MODEL_PATH="${VLLM_MODEL_PATH:-/opt/models/gemma-4-31B-it}"
readonly VLLM_INSTALL_DIR="${VLLM_INSTALL_DIR:-/opt/vllm}"
readonly VLLM_VENV_DIR="${VLLM_VENV_DIR:-$VLLM_INSTALL_DIR/venv}"
readonly VLLM_PIP_SPEC="${VLLM_PIP_SPEC:-vllm==0.14.1}"
readonly VLLM_PYTHON_BIN="${VLLM_PYTHON_BIN:-python3.12}"
readonly VLLM_USER="${VLLM_USER:-vllm}"
readonly VLLM_GROUP="${VLLM_GROUP:-$VLLM_USER}"
readonly VLLM_SERVICE_NAME="vllm"
readonly VLLM_SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-gemma-4-31B-it}"
readonly VLLM_HOST="${VLLM_HOST:-127.0.0.1}"
readonly VLLM_PORT="${VLLM_PORT:-8000}"
readonly VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.9}"

# Controls
readonly AUTO_START_VLLM="${AUTO_START_VLLM:-true}"
readonly VLLM_HEALTH_TIMEOUT_SECONDS="${VLLM_HEALTH_TIMEOUT_SECONDS:-420}"
readonly VLLM_SKIP_INSTALL="${VLLM_SKIP_INSTALL:-false}"
readonly VLLM_RESET_OVERRIDES="${VLLM_RESET_OVERRIDES:-false}"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
info() { echo "  $*"; }
warn() { echo "WARN: $*" >&2; }
err() { echo "ERROR: $*" >&2; exit 1; }

check_root() {
    [[ $EUID -eq 0 ]] || err "This script must be run as root (or with sudo)."
}

check_command() {
    command -v "$1" >/dev/null 2>&1 || err "Required command not found: $1"
}

check_python_interpreter() {
    local pybin="$1"
    check_command "$pybin"
    "$pybin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' >/dev/null 2>&1 \
        || err "Python interpreter not usable: $pybin"
}

check_python_version() {
    local pybin="$1"
    local ver major minor
    ver="$("$pybin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    major="${ver%%.*}"
    minor="${ver##*.}"
    if [[ "$major" -lt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -lt 10 ]]; }; then
        err "vLLM requires Python 3.10+ (found $ver at $pybin)"
    fi
    if [[ "$major" -eq 3 && "$minor" -ge 13 ]]; then
        warn "Detected Python $ver. If vLLM fails, pin to python3.12."
    fi
    info "Python version OK: $ver ($pybin)"
}

create_user_if_missing() {
    local user="$1"
    local group="$2"
    local home="$3"

    if getent group "$group" >/dev/null 2>&1; then
        :
    else
        groupadd --system "$group" || err "Failed to create group: $group"
        info "Created group: $group"
    fi

    if id "$user" >/dev/null 2>&1; then
        info "User exists: $user"
    else
        useradd --system --gid "$group" --shell /sbin/nologin --home-dir "$home" --create-home "$user" \
            || err "Failed to create user: $user"
        info "Created user: $user"
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

escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

strip_crlf_best_effort() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    sed -i 's/\r$//' "$file" 2>/dev/null || true
}

patch_vllm_unit() {
    local unit_file="$1"
    [[ -f "$unit_file" ]] || err "vLLM unit file not found: $unit_file"

    local vllm_python="$VLLM_VENV_DIR/bin/python"
    local esc_install esc_python esc_model esc_served esc_host esc_port esc_gpu
    esc_install="$(escape_sed_replacement "$VLLM_INSTALL_DIR")"
    esc_python="$(escape_sed_replacement "$vllm_python")"
    esc_model="$(escape_sed_replacement "$VLLM_MODEL_PATH")"
    esc_served="$(escape_sed_replacement "$VLLM_SERVED_MODEL_NAME")"
    esc_host="$(escape_sed_replacement "$VLLM_HOST")"
    esc_port="$(escape_sed_replacement "$VLLM_PORT")"
    esc_gpu="$(escape_sed_replacement "$VLLM_GPU_MEMORY_UTILIZATION")"

    sed -i -E "s|^User=.*$|User=${VLLM_USER}|" "$unit_file"
    sed -i -E "s|^Group=.*$|Group=${VLLM_GROUP}|" "$unit_file"
    sed -i -E "s|^WorkingDirectory=.*$|WorkingDirectory=${esc_install}|" "$unit_file"
    sed -i -E "s|^ExecStart=.*-m vllm\\.entrypoints\\.openai\\.api_server[[:space:]]*\\\\$|ExecStart=${esc_python} -m vllm.entrypoints.openai.api_server \\\\|" "$unit_file"
    sed -i -E "s|^([[:space:]]*--model[[:space:]]+).*$|\\1${esc_model} \\\\|" "$unit_file"
    sed -i -E "s|^([[:space:]]*--served-model-name[[:space:]]+).*$|\\1${esc_served} \\\\|" "$unit_file"
    sed -i -E "s|^([[:space:]]*--host[[:space:]]+).*$|\\1${esc_host} \\\\|" "$unit_file"
    sed -i -E "s|^([[:space:]]*--port[[:space:]]+).*$|\\1${esc_port} \\\\|" "$unit_file"
    sed -i -E "s|^([[:space:]]*--gpu-memory-utilization[[:space:]]+).*$|\\1${esc_gpu} \\\\|" "$unit_file"
}

handle_vllm_overrides() {
    local dropin_dir="/etc/systemd/system/vllm.service.d"
    if [[ ! -d "$dropin_dir" ]]; then
        return 0
    fi
    local conf_files=("$dropin_dir"/*.conf)
    if [[ ! -e "${conf_files[0]}" ]]; then
        return 0
    fi
    if [[ "$VLLM_RESET_OVERRIDES" == "true" ]]; then
        rm -f "$dropin_dir"/*.conf || err "Failed to remove vLLM drop-ins in $dropin_dir"
        info "Cleared existing vLLM drop-ins from $dropin_dir"
    else
        warn "Existing vLLM drop-ins detected in $dropin_dir (may override installed unit)"
        warn "Set VLLM_RESET_OVERRIDES=true to clear them during install"
    fi
}

wait_for_http_200() {
    local url="$1"
    local timeout_s="$2"
    local start now
    start="$(date +%s)"
    while true; do
        if command -v curl >/dev/null 2>&1 && curl -fsS "$url" >/dev/null 2>&1; then
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
echo "=== vLLM-only installation ==="
echo ""

check_root
check_command systemctl
check_command sed
check_command pip3
check_python_interpreter "$VLLM_PYTHON_BIN"
check_python_version "$VLLM_PYTHON_BIN"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="$SCRIPT_DIR/systemd/vllm.service"
[[ -f "$UNIT_SRC" ]] || err "Missing required unit file: $UNIT_SRC"

echo "[1/5] Creating vLLM service account..."
create_user_if_missing "$VLLM_USER" "$VLLM_GROUP" "$VLLM_INSTALL_DIR"

echo "[2/5] Preparing directories..."
ensure_dir "$VLLM_INSTALL_DIR" "$VLLM_USER:$VLLM_GROUP" 755
mkdir -p "$(dirname "$VLLM_MODEL_PATH")" "$VLLM_MODEL_PATH" || err "Failed to create model directories"
chmod 755 "$(dirname "$VLLM_MODEL_PATH")" "$VLLM_MODEL_PATH" || true
if [[ -n "${SUDO_USER:-}" ]]; then
    chown -R "${SUDO_USER}:${SUDO_USER}" "$(dirname "$VLLM_MODEL_PATH")" 2>/dev/null || true
fi
chmod -R a+rX "$VLLM_MODEL_PATH" 2>/dev/null || true

echo "[3/5] Installing vLLM runtime..."
if [[ "$VLLM_SKIP_INSTALL" == "true" ]]; then
    warn "VLLM_SKIP_INSTALL=true; skipping vLLM pip install step"
else
    if [[ -d "$VLLM_VENV_DIR" ]]; then
        info "vLLM venv exists at $VLLM_VENV_DIR"
    else
        "$VLLM_PYTHON_BIN" -m venv "$VLLM_VENV_DIR" || err "Failed to create vLLM venv"
        info "Created vLLM venv at $VLLM_VENV_DIR"
    fi

    "$VLLM_VENV_DIR/bin/pip" install --upgrade pip --quiet || err "Failed to upgrade pip in vLLM venv"
    "$VLLM_VENV_DIR/bin/pip" install "$VLLM_PIP_SPEC" --quiet || err "Failed to install vLLM ($VLLM_PIP_SPEC)"
    chown -R "$VLLM_USER:$VLLM_GROUP" "$VLLM_VENV_DIR"
    sudo -u "$VLLM_USER" "$VLLM_VENV_DIR/bin/python" -c 'import vllm; print(getattr(vllm, "__version__", "unknown"))' \
        || err "vLLM import test failed from venv"
fi

echo "[4/5] Installing systemd vLLM unit..."
strip_crlf_best_effort "$UNIT_SRC"
cp "$UNIT_SRC" /etc/systemd/system/vllm.service || err "Failed to copy vllm.service"
strip_crlf_best_effort /etc/systemd/system/vllm.service
patch_vllm_unit /etc/systemd/system/vllm.service
handle_vllm_overrides
systemctl daemon-reload || err "Failed to reload systemd"

echo "[5/5] Enabling/starting vLLM..."
if [[ "$AUTO_START_VLLM" == "true" ]]; then
    if [[ ! -f "$VLLM_MODEL_PATH/config.json" ]]; then
        warn "Model not found at $VLLM_MODEL_PATH/config.json; skipping auto-start"
        warn "Copy model weights first, then run: sudo systemctl enable --now $VLLM_SERVICE_NAME"
    else
        systemctl enable "$VLLM_SERVICE_NAME" || true
        systemctl restart "$VLLM_SERVICE_NAME" || systemctl start "$VLLM_SERVICE_NAME" || err "Failed to start vLLM service"
        if wait_for_http_200 "http://127.0.0.1:${VLLM_PORT}/health" "$VLLM_HEALTH_TIMEOUT_SECONDS"; then
            info "vLLM health endpoint is ready"
        else
            warn "vLLM health check timed out after ${VLLM_HEALTH_TIMEOUT_SECONDS}s"
            warn "Inspect logs: sudo journalctl -u $VLLM_SERVICE_NAME -n 200 --no-pager"
        fi
    fi
else
    info "AUTO_START_VLLM=false; install complete without starting service"
fi

echo ""
echo "=== vLLM-only install complete ==="
echo "Installed unit: /etc/systemd/system/vllm.service"
echo "vLLM venv path: $VLLM_VENV_DIR"
echo "Model path:     $VLLM_MODEL_PATH"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status $VLLM_SERVICE_NAME"
echo "  sudo journalctl -u $VLLM_SERVICE_NAME -f"
echo "  curl -sf http://127.0.0.1:${VLLM_PORT}/health"
echo ""
echo "Optional flags:"
echo "  sudo VLLM_SKIP_INSTALL=true bash install_vllm.sh"
echo "  sudo VLLM_PIP_SPEC='/mnt/media/wheels/vllm-0.14.1-*.whl' bash install_vllm.sh"
echo "  sudo VLLM_INSTALL_DIR=/opt/vllm312 VLLM_VENV_DIR=/opt/vllm312/venv bash install_vllm.sh"
echo "  sudo VLLM_MODEL_PATH=/opt/models/gemma-4-31B-it VLLM_GPU_MEMORY_UTILIZATION=0.9 bash install_vllm.sh"

