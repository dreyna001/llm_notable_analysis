#!/usr/bin/env bash
# shellcheck shell=bash
# install.sh — On-prem Notable Analyzer installation script for RHEL
# Run as root or with sudo
set -euo pipefail
IFS=$'\n\t'

trap 'err "Failed at line ${LINENO}: ${BASH_COMMAND}"' ERR

#------------------------------------------------------------------------------
# Configuration (edit as needed)
#------------------------------------------------------------------------------
readonly INSTALL_DIR="/opt/notable-analyzer"
readonly CONFIG_DIR="/etc/notable-analyzer"
readonly DATA_DIR="/var/notables"
readonly SFTP_CHROOT="/var/sftp/soar"
readonly VLLM_MODEL_PATH="/opt/models/gpt-oss-20b"
readonly VLLM_INSTALL_DIR="/opt/vllm"
readonly VLLM_VENV_DIR="/opt/vllm/venv"

# Python interpreter selection (pinning / reproducibility)
#
# For regulated environments, prefer pinning vLLM to a specific Python (commonly 3.11).
# Example:
#   sudo ANALYZER_PYTHON_BIN=python3.11 VLLM_PYTHON_BIN=python3.11 bash install.sh
#
# If these are set and missing/unusable, the installer will fail early.
readonly ANALYZER_PYTHON_BIN="${ANALYZER_PYTHON_BIN:-python3}"
readonly VLLM_PYTHON_BIN="${VLLM_PYTHON_BIN:-python3}"

# Users
readonly SVC_USER="notable-analyzer"
readonly VLLM_USER="vllm"
readonly SFTP_USER="soar-uploader"

# Minimum Python version
readonly MIN_PYTHON_MAJOR=3
readonly MIN_PYTHON_MINOR=10

#------------------------------------------------------------------------------
# Helper functions
#------------------------------------------------------------------------------
err() { echo "ERROR: $*" >&2; exit 1; }
warn() { echo "WARN: $*" >&2; }
info() { echo "  $*"; }

strip_crlf_in_file_best_effort() {
    # Best-effort: strip Windows CRLF from a file if present; never fail install.
    local file="$1"
    if [[ -f "$file" ]]; then
        sed -i 's/\r$//' "$file" 2>/dev/null || true
    fi
}

download_model_best_effort() {
    # Optional: download model weights non-interactively via Hugging Face Hub.
    #
    # Enable with:
    #   sudo MODEL_DOWNLOAD=true HF_TOKEN=... bash install.sh
    #
    # Optional:
    #   MODEL_REPO=openai/gpt-oss-20b   (default)
    #
    # Never fails the installer; logs warnings on failure.
    local model_repo="${MODEL_REPO:-openai/gpt-oss-20b}"
    local model_dir="$VLLM_MODEL_PATH"
    local token="${HF_TOKEN:-${HUGGINGFACE_TOKEN:-}}"

    if [[ "${MODEL_DOWNLOAD:-false}" != "true" ]]; then
        return 0
    fi

    if [[ -z "$token" ]]; then
        warn "MODEL_DOWNLOAD=true but HF_TOKEN/HUGGINGFACE_TOKEN not set; skipping model download"
        return 0
    fi

    info "MODEL_DOWNLOAD=true: attempting to download model '$model_repo' into $model_dir (best-effort)"

    # Use the analyzer venv as a stable tool environment for downloads.
    if [[ ! -x "$INSTALL_DIR/venv/bin/python" ]]; then
        warn "Analyzer venv not found at $INSTALL_DIR/venv; skipping model download"
        return 0
    fi

    "$INSTALL_DIR/venv/bin/pip" install --quiet "huggingface_hub>=0.23.0" \
        || { warn "Failed to install huggingface_hub; skipping model download"; return 0; }

    mkdir -p "$model_dir" 2>/dev/null || true

    # Snapshot download into the target directory; avoids git-lfs.
    "$INSTALL_DIR/venv/bin/python" - << 'PY' || true
import os
from huggingface_hub import snapshot_download

repo_id = os.environ.get("MODEL_REPO", "openai/gpt-oss-20b")
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
local_dir = os.environ.get("VLLM_MODEL_PATH", "/opt/models/gpt-oss-20b")

snapshot_download(
    repo_id=repo_id,
    local_dir=local_dir,
    local_dir_use_symlinks=False,
    token=token,
    resume_download=True,
)
print(f"Downloaded {repo_id} to {local_dir}")
PY

    if [[ -f "$model_dir/config.json" ]]; then
        info "Model download appears complete (found: $model_dir/config.json)"
    else
        warn "Model download step did not produce $model_dir/config.json (continuing)"
    fi
}

wait_for_http_200_best_effort() {
    # Best-effort health poll. Never fails install.
    # Usage: wait_for_http_200_best_effort "http://127.0.0.1:8000/health" 180
    local url="$1"
    local timeout_s="${2:-120}"

    local start
    start="$(date +%s)"

    while true; do
        if command -v curl &>/dev/null; then
            if curl -fsS "$url" &>/dev/null; then
                return 0
            fi
        else
            # Fallback to Python if curl is not installed
            python3 - <<PY >/dev/null 2>&1 || true
import sys, urllib.request
try:
    urllib.request.urlopen("$url", timeout=2).read()
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
            if [[ $? -eq 0 ]]; then
                return 0
            fi
        fi

        local now
        now="$(date +%s)"
        if (( now - start >= timeout_s )); then
            return 1
        fi
        sleep 2
    done
}

check_root() {
    [[ $EUID -eq 0 ]] || err "This script must be run as root (or sudo)"
}

check_command() {
    command -v "$1" &>/dev/null || err "Required command not found: $1. Install it first."
}

check_python_interpreter() {
    local pybin="$1"
    check_command "$pybin"
    "$pybin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' >/dev/null 2>&1 \
        || err "Python interpreter not usable: $pybin"
}

check_python_version() {
    local ver
    ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null) \
        || err "python3 not found or broken"
    
    local major minor
    major="${ver%%.*}"
    minor="${ver##*.}"
    
    if [[ "$major" -lt "$MIN_PYTHON_MAJOR" ]] || \
       { [[ "$major" -eq "$MIN_PYTHON_MAJOR" ]] && [[ "$minor" -lt "$MIN_PYTHON_MINOR" ]]; }; then
        err "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+ required (found $ver)"
    fi
    info "Python version: $ver"

    # vLLM compatibility varies by platform/Python; warn early if we're on a very new Python.
    # (Do not fail install: some environments ship newer Pythons by default.)
    if [[ "$major" -eq 3 && "$minor" -ge 12 ]]; then
        warn "Detected Python $ver. If vLLM fails to start, try using Python 3.10/3.11 for the vLLM venv."
    fi
}

create_user_if_missing() {
    local user="$1" home="$2"
    if id "$user" &>/dev/null; then
        info "User exists: $user"
    else
        useradd --system --shell /sbin/nologin --home-dir "$home" --create-home "$user" \
            || err "Failed to create user: $user"
        info "Created user: $user"
    fi
}

ensure_dir() {
    local dir="$1" owner="$2" mode="$3"
    mkdir -p "$dir" || err "Failed to create directory: $dir"
    chown "$owner" "$dir" || err "Failed to set owner on: $dir"
    chmod "$mode" "$dir" || err "Failed to set permissions on: $dir"
}

#------------------------------------------------------------------------------
# Preflight checks
#------------------------------------------------------------------------------
echo "=== On-prem Notable Analyzer Installation ==="
echo ""

check_root
check_command python3
check_command pip3
check_command systemctl
check_python_interpreter "$ANALYZER_PYTHON_BIN"
check_python_interpreter "$VLLM_PYTHON_BIN"
check_python_version

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Verify required files exist
for f in requirements.txt config.env.example; do
    [[ -f "$SCRIPT_DIR/$f" ]] || err "Missing required file: $SCRIPT_DIR/$f"
done
[[ -d "$SCRIPT_DIR/onprem_service" ]] || err "Missing directory: $SCRIPT_DIR/onprem_service"
[[ -d "$SCRIPT_DIR/systemd" ]] || err "Missing directory: $SCRIPT_DIR/systemd"

echo ""

#------------------------------------------------------------------------------
# 1. Create system users
#------------------------------------------------------------------------------
echo "[1/8] Creating system users..."

create_user_if_missing "$SVC_USER" "$INSTALL_DIR"
create_user_if_missing "$VLLM_USER" "/opt/vllm"
create_user_if_missing "$SFTP_USER" "$SFTP_CHROOT"

# Add SFTP user to service group for shared write access
if ! groups "$SFTP_USER" | grep -q "$SVC_USER"; then
    usermod -aG "$SVC_USER" "$SFTP_USER" \
        || warn "Could not add $SFTP_USER to group $SVC_USER"
    info "Added $SFTP_USER to group $SVC_USER"
fi

#------------------------------------------------------------------------------
# 2. Create directories
#------------------------------------------------------------------------------
echo "[2/8] Creating directories..."

# Application directories
ensure_dir "$INSTALL_DIR" "$SVC_USER:$SVC_USER" 755
ensure_dir "$CONFIG_DIR" "$SVC_USER:$SVC_USER" 750

# Data directories (service user owns)
for subdir in processed quarantine reports; do
    ensure_dir "$DATA_DIR/$subdir" "$SVC_USER:$SVC_USER" 750
done

# Archive subdirs
for subdir in processed quarantine reports; do
    ensure_dir "$DATA_DIR/archive/$subdir" "$SVC_USER:$SVC_USER" 750
done

# SFTP chroot structure (root must own chroot parent for sshd)
ensure_dir "$SFTP_CHROOT" "root:root" 755
ensure_dir "$SFTP_CHROOT/incoming" "$SFTP_USER:$SVC_USER" 775

# Symlink main incoming to SFTP incoming
if [[ -L "$DATA_DIR/incoming" ]]; then
    info "Symlink exists: $DATA_DIR/incoming"
elif [[ -d "$DATA_DIR/incoming" ]]; then
    if [[ -z "$(ls -A "$DATA_DIR/incoming" 2>/dev/null)" ]]; then
        rmdir "$DATA_DIR/incoming"
        ln -s "$SFTP_CHROOT/incoming" "$DATA_DIR/incoming"
        info "Created symlink: $DATA_DIR/incoming -> $SFTP_CHROOT/incoming"
    else
        warn "$DATA_DIR/incoming exists and is not empty; skipping symlink"
    fi
else
    ln -s "$SFTP_CHROOT/incoming" "$DATA_DIR/incoming"
    info "Created symlink: $DATA_DIR/incoming -> $SFTP_CHROOT/incoming"
fi

# Model directory (best-effort; do not fail install if this can't be created/chowned)
#
# We intentionally store model weights outside the repo at a stable system path:
#   /opt/models/gpt-oss-20b
#
# This matches the default `vllm.service` --model argument.
echo ""
echo "[2b] Preparing model directory (best-effort)..."
mkdir -p "$(dirname "$VLLM_MODEL_PATH")" "$VLLM_MODEL_PATH" 2>/dev/null || warn "Could not create /opt/models directory (you may need to create it manually)"

# Ensure the vLLM service user can read the model directory (best-effort).
# Keep ownership flexible: downloads are often done as the interactive admin user,
# but the vLLM systemd service runs as `vllm`.
chmod 755 "$(dirname "$VLLM_MODEL_PATH")" "$VLLM_MODEL_PATH" 2>/dev/null || true

# If invoked via sudo, chown to the real user to make it easy to download weights.
_owner_user="${SUDO_USER:-}"
if [[ -n "$_owner_user" ]]; then
    chown -R "${_owner_user}:${_owner_user}" "$(dirname "$VLLM_MODEL_PATH")" 2>/dev/null || warn "Could not chown /opt/models to ${_owner_user} (continuing)"
else
    info "SUDO_USER not set; leaving /opt/models ownership unchanged"
fi

# Regardless of ownership, ensure the vLLM service user will be able to read files (if present).
chmod -R a+rX "$VLLM_MODEL_PATH" 2>/dev/null || true

#------------------------------------------------------------------------------
# 3. Handle SELinux (RHEL)
#------------------------------------------------------------------------------
echo "[3/8] Configuring SELinux (if enabled)..."

if command -v getenforce &>/dev/null && [[ "$(getenforce 2>/dev/null)" != "Disabled" ]]; then
    # Allow sshd to read user content in chroot
    if command -v setsebool &>/dev/null; then
        setsebool -P ssh_chroot_rw_homedirs on 2>/dev/null || warn "Could not set ssh_chroot_rw_homedirs"
    fi
    # Label SFTP chroot
    if command -v semanage &>/dev/null && command -v restorecon &>/dev/null; then
        semanage fcontext -a -t ssh_home_t "$SFTP_CHROOT(/.*)?" 2>/dev/null || true
        restorecon -Rv "$SFTP_CHROOT" 2>/dev/null || true
        info "SELinux context applied to $SFTP_CHROOT"
    else
        warn "semanage/restorecon not found; SELinux labels may need manual fix"
    fi
else
    info "SELinux disabled or not present; skipping"
fi

#------------------------------------------------------------------------------
# 4. Copy application code
#------------------------------------------------------------------------------
echo "[4/8] Copying application code..."

cp -r "$SCRIPT_DIR/onprem_service" "$INSTALL_DIR/" \
    || err "Failed to copy onprem_service to $INSTALL_DIR"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/" \
    || err "Failed to copy requirements.txt"

chown -R "$SVC_USER:$SVC_USER" "$INSTALL_DIR"
info "Code installed at $INSTALL_DIR/onprem_service"

#------------------------------------------------------------------------------
# 5. Create Python virtual environment
#------------------------------------------------------------------------------
echo "[5/8] Creating Python virtual environment..."

if [[ -d "$INSTALL_DIR/venv" ]]; then
    info "Venv exists; upgrading dependencies..."
else
    "$ANALYZER_PYTHON_BIN" -m venv "$INSTALL_DIR/venv" \
        || err "Failed to create virtual environment"
    info "Created venv at $INSTALL_DIR/venv"
fi

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet \
    || err "Failed to upgrade pip"
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet \
    || err "Failed to install requirements"

chown -R "$SVC_USER:$SVC_USER" "$INSTALL_DIR/venv"
info "Dependencies installed"

# Optional model download (best-effort)
export VLLM_MODEL_PATH
download_model_best_effort

#------------------------------------------------------------------------------
# 5b. Create vLLM virtual environment (optional but recommended)
#------------------------------------------------------------------------------
echo ""
echo "[5b] Creating vLLM virtual environment (optional)..."

# Allow skipping vLLM install (useful for air-gapped environments where vLLM is pre-installed)
# Example:
#   sudo VLLM_SKIP_INSTALL=true bash install.sh
if [[ "${VLLM_SKIP_INSTALL:-false}" == "true" ]]; then
    warn "VLLM_SKIP_INSTALL=true; skipping vLLM venv creation and vLLM installation"
else
    ensure_dir "$VLLM_INSTALL_DIR" "$VLLM_USER:$VLLM_USER" 755

    if [[ -d "$VLLM_VENV_DIR" ]]; then
        info "vLLM venv exists; upgrading dependencies..."
    else
        "$VLLM_PYTHON_BIN" -m venv "$VLLM_VENV_DIR" \
            || err "Failed to create vLLM virtual environment at $VLLM_VENV_DIR"
        info "Created vLLM venv at $VLLM_VENV_DIR"
    fi

    "$VLLM_VENV_DIR/bin/pip" install --upgrade pip --quiet \
        || err "Failed to upgrade pip in vLLM venv"

    # NOTE: vLLM requires a compatible GPU driver/runtime (typically NVIDIA CUDA).
    # On a fresh host, install GPU drivers BEFORE starting the vllm.service.
    "$VLLM_VENV_DIR/bin/pip" install vllm --quiet \
        || err "Failed to install vLLM (pip install vllm). Ensure GPU drivers/toolkit are installed."

    chown -R "$VLLM_USER:$VLLM_USER" "$VLLM_VENV_DIR"
    info "vLLM installed in $VLLM_VENV_DIR"

    # Best-effort smoke checks (never fail install)
    if sudo -u "$VLLM_USER" "$VLLM_VENV_DIR/bin/python" -c 'import vllm; print(getattr(vllm, "__version__", "unknown"))' &>/dev/null; then
        info "vLLM import smoke-test OK"
    else
        warn "vLLM import smoke-test failed (continuing). If vllm.service fails, review journal logs."
    fi

    if [[ "${VLLM_SMOKE_TEST:-false}" == "true" ]]; then
        info "VLLM_SMOKE_TEST=true: running additional best-effort checks..."
        command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null || warn "nvidia-smi not available (GPU drivers may be missing)"
        [[ -f "$VLLM_MODEL_PATH/config.json" ]] || warn "Model not detected at $VLLM_MODEL_PATH (download weights before starting vLLM)"
    fi
fi

#------------------------------------------------------------------------------
# 6. Install configuration
#------------------------------------------------------------------------------
echo "[6/8] Installing configuration..."

if [[ -f "$CONFIG_DIR/config.env" ]]; then
    info "Config exists: $CONFIG_DIR/config.env (not overwritten)"
else
    cp "$SCRIPT_DIR/config.env.example" "$CONFIG_DIR/config.env" \
        || err "Failed to copy config.env.example"
    chown "$SVC_USER:$SVC_USER" "$CONFIG_DIR/config.env"
    chmod 600 "$CONFIG_DIR/config.env"
    info "Config installed: $CONFIG_DIR/config.env"
    warn "EDIT THIS FILE before starting the service"
fi

#------------------------------------------------------------------------------
# 7. Install systemd units
#------------------------------------------------------------------------------
echo "[7/8] Installing systemd units..."

# If you want to "comment out" systemd unit installation without deleting code:
#   sudo INSTALL_SYSTEMD_UNITS=false bash install.sh
if [[ "${INSTALL_SYSTEMD_UNITS:-true}" == "true" ]]; then
    # Default units (stable baseline)
    units=(
        notable-analyzer.service
        vllm.service
        notable-retention.service
        notable-retention.timer
    )

    # Optional: install the freeform (paragraphs-only) analyzer as an additional unit.
    # This avoids modifying/replacing the baseline unit and removes "remember to change it back" risk.
    # Enable with:
    #   sudo INSTALL_FREEFORM_SERVICE=true bash install.sh
    if [[ "${INSTALL_FREEFORM_SERVICE:-false}" == "true" ]]; then
        units+=(notable-analyzer-freeform.service)
    fi

    for unit in "${units[@]}"; do
        src="$SCRIPT_DIR/systemd/$unit"
        [[ -f "$src" ]] || err "Missing systemd unit: $src"
        # Prevent subtle failures when unit files were edited on Windows.
        strip_crlf_in_file_best_effort "$src"
        cp "$src" /etc/systemd/system/ || err "Failed to copy $unit"
        strip_crlf_in_file_best_effort "/etc/systemd/system/$unit"
        info "Installed: $unit"
    done

    systemctl daemon-reload || err "Failed to reload systemd"
else
    warn "INSTALL_SYSTEMD_UNITS=false; skipping systemd unit installation and daemon-reload"
fi

#------------------------------------------------------------------------------
# 8. Configure SFTP chroot in sshd_config
#------------------------------------------------------------------------------
echo "[8/8] Configuring SFTP chroot..."

SSHD_CONFIG="/etc/ssh/sshd_config"
SFTP_MARKER="# Notable Analyzer SFTP Config"

if grep -q "$SFTP_MARKER" "$SSHD_CONFIG" 2>/dev/null; then
    info "SFTP config already present in $SSHD_CONFIG"
else
    cat >> "$SSHD_CONFIG" << EOF

$SFTP_MARKER
Match User $SFTP_USER
    ChrootDirectory $SFTP_CHROOT
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no
    PasswordAuthentication no
EOF
    info "Appended SFTP Match block to $SSHD_CONFIG"
fi

# Create .ssh directory for authorized_keys
SSH_DIR="$SFTP_CHROOT/.ssh"
ensure_dir "$SSH_DIR" "$SFTP_USER:$SFTP_USER" 700

if [[ ! -f "$SSH_DIR/authorized_keys" ]]; then
    touch "$SSH_DIR/authorized_keys"
    chown "$SFTP_USER:$SFTP_USER" "$SSH_DIR/authorized_keys"
    chmod 600 "$SSH_DIR/authorized_keys"
    info "Created $SSH_DIR/authorized_keys (add SOAR public key here)"
fi

#------------------------------------------------------------------------------
# Summary
#------------------------------------------------------------------------------
echo ""
echo "=== Installation Complete ==="
echo ""
echo "Before starting:"
echo "  1. Edit config:       sudo vi $CONFIG_DIR/config.env"
echo "  2. Add model weights: $VLLM_MODEL_PATH"
echo "  3. Add SOAR SSH key:  $SSH_DIR/authorized_keys"
echo "  4. Restart sshd:      sudo systemctl restart sshd"
echo ""
echo "Start services:"
echo "  sudo systemctl enable --now vllm"
echo "  sudo systemctl enable --now notable-analyzer"
echo "  sudo systemctl enable --now notable-retention.timer  # optional"
echo ""
echo "Verify:"
echo "  sudo systemctl status vllm notable-analyzer"
echo "  sudo journalctl -u notable-analyzer -f"
echo ""
echo "Troubleshooting vLLM:"
echo "  - If vllm.service fails with status=203/EXEC:"
echo "      sudo ls -la $VLLM_VENV_DIR/bin/python"
echo "  - If vllm.service starts then immediately exits, run vLLM in foreground to see the real error:"
echo "      sudo systemctl stop vllm"
echo "      sudo -u $VLLM_USER $VLLM_VENV_DIR/bin/python -m vllm.entrypoints.openai.api_server \\"
echo "        --model $VLLM_MODEL_PATH \\"
echo "        --served-model-name gpt-oss-20b \\"
echo "        --host 127.0.0.1 --port 8000 \\"
echo "        --gpu-memory-utilization 0.9 --max-model-len 131072 --dtype auto"
echo "  - If the error mentions trust_remote_code, consider enabling it explicitly (security tradeoff):"
echo "      sudo vi /etc/systemd/system/vllm.service  # add --trust-remote-code"
echo "      sudo systemctl daemon-reload && sudo systemctl restart vllm"
echo ""
echo "Optional installer flags:"
echo "  - Skip vLLM install (air-gapped / preinstalled):"
echo "      sudo VLLM_SKIP_INSTALL=true bash install.sh"
echo "  - Add extra vLLM smoke checks (non-fatal):"
echo "      sudo VLLM_SMOKE_TEST=true bash install.sh"
echo "  - Download model non-interactively (requires internet + HF token):"
echo "      sudo MODEL_DOWNLOAD=true HF_TOKEN=... bash install.sh"
echo "      # optional: MODEL_REPO=openai/gpt-oss-20b"
echo "  - Auto-start services after install (best-effort):"
echo "      sudo AUTO_START_SERVICES=true bash install.sh"

# Best-effort auto-start (disabled by default)
if [[ "${AUTO_START_SERVICES:-false}" == "true" ]]; then
    echo ""
    info "AUTO_START_SERVICES=true: attempting to start services (best-effort)"
    if [[ ! -f "$VLLM_MODEL_PATH/config.json" ]]; then
        warn "Model not present at $VLLM_MODEL_PATH (missing config.json); skipping auto-start of vLLM"
    else
        # Use restart (not start) so re-running install.sh applies updated unit files/venvs cleanly.
        systemctl enable vllm 2>/dev/null || true
        systemctl restart vllm 2>/dev/null || systemctl start vllm 2>/dev/null || warn "Could not start/restart vllm.service (check systemctl/journalctl)"
        if wait_for_http_200_best_effort "http://127.0.0.1:8000/health" 240; then
            info "vLLM health check OK"
        else
            warn "vLLM health check timed out; check: sudo journalctl -u vllm -n 200 --no-pager"
        fi
        systemctl enable notable-analyzer 2>/dev/null || true
        systemctl restart notable-analyzer 2>/dev/null || systemctl start notable-analyzer 2>/dev/null || warn "Could not start/restart notable-analyzer.service (check systemctl/journalctl)"
    fi
fi