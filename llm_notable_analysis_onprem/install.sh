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

check_root() {
    [[ $EUID -eq 0 ]] || err "This script must be run as root (or sudo)"
}

check_command() {
    command -v "$1" &>/dev/null || err "Required command not found: $1. Install it first."
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
    python3 -m venv "$INSTALL_DIR/venv" \
        || err "Failed to create virtual environment"
    info "Created venv at $INSTALL_DIR/venv"
fi

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet \
    || err "Failed to upgrade pip"
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet \
    || err "Failed to install requirements"

chown -R "$SVC_USER:$SVC_USER" "$INSTALL_DIR/venv"
info "Dependencies installed"

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

for unit in notable-analyzer.service vllm.service notable-retention.service notable-retention.timer; do
    src="$SCRIPT_DIR/systemd/$unit"
    [[ -f "$src" ]] || err "Missing systemd unit: $src"
    cp "$src" /etc/systemd/system/ || err "Failed to copy $unit"
    info "Installed: $unit"
done

systemctl daemon-reload || err "Failed to reload systemd"

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
