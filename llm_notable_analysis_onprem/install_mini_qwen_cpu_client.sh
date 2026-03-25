#!/usr/bin/env bash
# shellcheck shell=bash
# install_mini_qwen_cpu_client.sh
# Purpose:
#   Install/configure llm_notable_analysis_onprem as a client of the
#   onprem_qwen3_sudo_llamacpp_service llama.cpp CPU service (Qwen3 GGUF).
set -euo pipefail
IFS=$'\n\t'

err() { echo "ERROR: $*" >&2; exit 1; }
warn() { echo "WARN: $*" >&2; }
info() { echo "  $*"; }

trap 'err "Failed at line ${LINENO}: ${BASH_COMMAND}"' ERR

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------------------------
# Configuration (override with env vars if needed)
# ------------------------------------------------------------------------------
readonly ANALYZER_INSTALL_DIR="${ANALYZER_INSTALL_DIR:-/opt/notable-analyzer}"
readonly ANALYZER_CONFIG_DIR="${ANALYZER_CONFIG_DIR:-/etc/notable-analyzer}"
readonly ANALYZER_CONFIG_FILE="${ANALYZER_CONFIG_FILE:-$ANALYZER_CONFIG_DIR/config.env}"
readonly ANALYZER_DATA_DIR="${ANALYZER_DATA_DIR:-/var/notables}"
readonly ANALYZER_VENV_DIR="${ANALYZER_VENV_DIR:-$ANALYZER_INSTALL_DIR/venv}"
readonly ANALYZER_PYTHON_BIN="${ANALYZER_PYTHON_BIN:-python3}"
readonly ANALYZER_SERVICE_USER="${ANALYZER_SERVICE_USER:-notable-analyzer}"
readonly ANALYZER_SERVICE_GROUP="${ANALYZER_SERVICE_GROUP:-$ANALYZER_SERVICE_USER}"
readonly ANALYZER_ENTRYPOINT="${ANALYZER_ENTRYPOINT:-onprem_service.onprem_main}"
readonly SDK_SOURCE_DIR="${SDK_SOURCE_DIR:-$SCRIPT_DIR/../onprem-llm-sdk}"
readonly LAUNCHER_PATH="${LAUNCHER_PATH:-/usr/local/bin/notable-analyzer-mini-run}"

# Systemd behavior:
#   auto  -> install/start only if systemd runtime is available
#   true  -> require systemd runtime
#   false -> never install/start systemd unit
readonly INSTALL_SYSTEMD_UNIT="${INSTALL_SYSTEMD_UNIT:-auto}"
readonly AUTO_START_ANALYZER="${AUTO_START_ANALYZER:-false}"
readonly SYSTEMD_UNIT_NAME="${SYSTEMD_UNIT_NAME:-notable-analyzer-mini.service}"

# Mini/Qwen CPU profile defaults
readonly LLM_API_URL="${LLM_API_URL:-http://127.0.0.1:8000/v1/chat/completions}"
readonly LLM_MODEL_NAME="${LLM_MODEL_NAME:-Qwen3-4B-Q4_K_M.gguf}"
readonly LLM_TIMEOUT="${LLM_TIMEOUT:-300}"
readonly LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-2048}"
readonly MITRE_IDS_PATH="${MITRE_IDS_PATH:-$ANALYZER_INSTALL_DIR/onprem_service/enterprise_attack_v17.1_ids.json}"

check_root() {
    [[ "${EUID}" -eq 0 ]] || err "Run as root (or sudo)."
}

check_command() {
    command -v "$1" >/dev/null 2>&1 || err "Required command not found: $1"
}

check_python_version() {
    local pybin="$1"
    check_command "$pybin"
    "$pybin" - <<'PY' >/dev/null
import sys
major, minor = sys.version_info[:2]
if (major, minor) < (3, 10):
    raise SystemExit("python_too_old")
PY
}

ensure_group_if_missing() {
    local group="$1"
    if getent group "$group" >/dev/null 2>&1; then
        info "Group exists: $group"
    else
        groupadd --system "$group" || err "Failed to create group: $group"
        info "Created group: $group"
    fi
}

create_service_user_if_missing() {
    local user="$1"
    local group="$2"
    local home="$3"
    local nologin_shell

    nologin_shell="$(command -v nologin || true)"
    if [[ -z "$nologin_shell" ]]; then
        nologin_shell="/sbin/nologin"
    fi

    if id "$user" >/dev/null 2>&1; then
        info "User exists: $user"
    else
        useradd --system --shell "$nologin_shell" --home-dir "$home" --gid "$group" --create-home "$user" \
            || err "Failed to create user: $user"
        info "Created user: $user"
    fi
}

ensure_dir() {
    local path="$1"
    local owner="$2"
    local mode="$3"
    mkdir -p "$path" || err "Failed to create directory: $path"
    chown "$owner" "$path" || err "Failed to set ownership on: $path"
    chmod "$mode" "$path" || err "Failed to set permissions on: $path"
}

upsert_env_value() {
    local file="$1"
    local key="$2"
    local value="$3"
    python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
new_line = f"{key}={value}"

if path.exists():
    lines = path.read_text(encoding="utf-8").splitlines()
else:
    lines = []

found = False
out = []
for line in lines:
    if line.startswith(f"{key}="):
        if not found:
            out.append(new_line)
            found = True
        continue
    out.append(line)

if not found:
    out.append(new_line)

path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
PY
}

is_systemd_runtime() {
    [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1
}

write_launcher_script() {
    cat > "$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
IFS=\$'\\n\\t'

readonly CONFIG_FILE="${ANALYZER_CONFIG_FILE}"
readonly VENV_DIR="${ANALYZER_VENV_DIR}"
readonly INSTALL_DIR="${ANALYZER_INSTALL_DIR}"
readonly ENTRYPOINT="${ANALYZER_ENTRYPOINT}"

[[ -f "\$CONFIG_FILE" ]] || { echo "Missing config: \$CONFIG_FILE" >&2; exit 1; }
[[ -f "\$VENV_DIR/bin/activate" ]] || { echo "Missing venv activate script: \$VENV_DIR/bin/activate" >&2; exit 1; }

set -a
source "\$CONFIG_FILE"
set +a
source "\$VENV_DIR/bin/activate"

cd "\$INSTALL_DIR"
exec python -m "\$ENTRYPOINT"
EOF
    chmod 755 "$LAUNCHER_PATH" || err "Failed to mark launcher executable: $LAUNCHER_PATH"
}

install_systemd_unit() {
    local unit_path="/etc/systemd/system/${SYSTEMD_UNIT_NAME}"
    cat > "$unit_path" <<EOF
[Unit]
Description=Notable Analyzer (mini Qwen CPU client mode)
After=network.target

[Service]
Type=simple
User=${ANALYZER_SERVICE_USER}
Group=${ANALYZER_SERVICE_GROUP}
WorkingDirectory=${ANALYZER_INSTALL_DIR}
EnvironmentFile=${ANALYZER_CONFIG_FILE}
ExecStart=${ANALYZER_VENV_DIR}/bin/python -m ${ANALYZER_ENTRYPOINT}
Restart=on-failure
RestartSec=10
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=${ANALYZER_DATA_DIR}
ProtectHome=yes
UMask=0077
StandardOutput=journal
StandardError=journal
SyslogIdentifier=notable-analyzer-mini

[Install]
WantedBy=multi-user.target
EOF
    chmod 644 "$unit_path" || err "Failed to set unit permissions: $unit_path"
    systemctl daemon-reload || err "Failed to reload systemd"
    systemctl enable "${SYSTEMD_UNIT_NAME}" >/dev/null 2>&1 || true
}

echo "=== Notable Analyzer mini/Qwen CPU client install ==="
echo ""

check_root
check_command cp
check_command sed
check_python_version "$ANALYZER_PYTHON_BIN"

[[ -d "$SCRIPT_DIR/onprem_service" ]] || err "Missing directory: $SCRIPT_DIR/onprem_service"
[[ -f "$SCRIPT_DIR/config.env.example" ]] || err "Missing file: $SCRIPT_DIR/config.env.example"
[[ -f "$SCRIPT_DIR/requirements.txt" ]] || err "Missing file: $SCRIPT_DIR/requirements.txt"
[[ -f "$SDK_SOURCE_DIR/pyproject.toml" ]] || err "SDK source not found: $SDK_SOURCE_DIR"

echo "[1/8] Creating service identity..."
ensure_group_if_missing "$ANALYZER_SERVICE_GROUP"
create_service_user_if_missing "$ANALYZER_SERVICE_USER" "$ANALYZER_SERVICE_GROUP" "$ANALYZER_INSTALL_DIR"

echo "[2/8] Creating directories..."
ensure_dir "$ANALYZER_INSTALL_DIR" "$ANALYZER_SERVICE_USER:$ANALYZER_SERVICE_GROUP" 755
ensure_dir "$ANALYZER_CONFIG_DIR" "root:$ANALYZER_SERVICE_GROUP" 750
ensure_dir "$ANALYZER_DATA_DIR" "$ANALYZER_SERVICE_USER:$ANALYZER_SERVICE_GROUP" 750
for subdir in incoming processed quarantine reports; do
    ensure_dir "$ANALYZER_DATA_DIR/$subdir" "$ANALYZER_SERVICE_USER:$ANALYZER_SERVICE_GROUP" 750
done
for subdir in processed quarantine reports; do
    ensure_dir "$ANALYZER_DATA_DIR/archive/$subdir" "$ANALYZER_SERVICE_USER:$ANALYZER_SERVICE_GROUP" 750
done

echo "[3/8] Installing analyzer code..."
rm -rf "$ANALYZER_INSTALL_DIR/onprem_service"
cp -a "$SCRIPT_DIR/onprem_service" "$ANALYZER_INSTALL_DIR/" \
    || err "Failed to copy onprem_service"
cp "$SCRIPT_DIR/requirements.txt" "$ANALYZER_INSTALL_DIR/requirements.txt" \
    || err "Failed to copy requirements.txt"
chown -R "$ANALYZER_SERVICE_USER:$ANALYZER_SERVICE_GROUP" "$ANALYZER_INSTALL_DIR"

echo "[4/8] Creating/updating virtual environment..."
if [[ ! -d "$ANALYZER_VENV_DIR" ]]; then
    "$ANALYZER_PYTHON_BIN" -m venv "$ANALYZER_VENV_DIR" \
        || err "Failed to create venv at $ANALYZER_VENV_DIR"
fi
"$ANALYZER_VENV_DIR/bin/pip" install --upgrade pip wheel >/dev/null \
    || err "Failed to upgrade pip/wheel"

echo "[5/8] Installing Python dependencies..."
tmp_requirements="$(mktemp)"
awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    /^[[:space:]]*onprem-llm-sdk([[:space:]]*(==|>=|<=|~=|!=).*)?$/ { next }
    { print }
' "$ANALYZER_INSTALL_DIR/requirements.txt" > "$tmp_requirements"

if [[ -s "$tmp_requirements" ]]; then
    "$ANALYZER_VENV_DIR/bin/pip" install -r "$tmp_requirements" >/dev/null \
        || err "Failed installing analyzer requirements"
fi
rm -f "$tmp_requirements"

"$ANALYZER_VENV_DIR/bin/pip" install --upgrade "$SDK_SOURCE_DIR" >/dev/null \
    || err "Failed installing local onprem-llm-sdk from $SDK_SOURCE_DIR"

chown -R "$ANALYZER_SERVICE_USER:$ANALYZER_SERVICE_GROUP" "$ANALYZER_VENV_DIR"

echo "[6/8] Installing/updating config..."
if [[ ! -f "$ANALYZER_CONFIG_FILE" ]]; then
    cp "$SCRIPT_DIR/config.env.example" "$ANALYZER_CONFIG_FILE" \
        || err "Failed to create config: $ANALYZER_CONFIG_FILE"
fi

upsert_env_value "$ANALYZER_CONFIG_FILE" "LLM_API_URL" "$LLM_API_URL"
upsert_env_value "$ANALYZER_CONFIG_FILE" "LLM_MODEL_NAME" "$LLM_MODEL_NAME"
upsert_env_value "$ANALYZER_CONFIG_FILE" "LLM_MAX_TOKENS" "$LLM_MAX_TOKENS"
upsert_env_value "$ANALYZER_CONFIG_FILE" "LLM_TIMEOUT" "$LLM_TIMEOUT"
upsert_env_value "$ANALYZER_CONFIG_FILE" "MITRE_IDS_PATH" "$MITRE_IDS_PATH"

chown "root:$ANALYZER_SERVICE_GROUP" "$ANALYZER_CONFIG_FILE"
chmod 640 "$ANALYZER_CONFIG_FILE"

echo "[7/8] Installing launcher..."
write_launcher_script

echo "[8/8] Optional systemd integration..."
case "$INSTALL_SYSTEMD_UNIT" in
    auto)
        if is_systemd_runtime; then
            install_systemd_unit
            info "Installed systemd unit: $SYSTEMD_UNIT_NAME"
            if [[ "$AUTO_START_ANALYZER" == "true" ]]; then
                systemctl restart "$SYSTEMD_UNIT_NAME" \
                    || err "Failed to start $SYSTEMD_UNIT_NAME"
                info "Started $SYSTEMD_UNIT_NAME"
            fi
        else
            info "Systemd runtime not detected; skipping unit installation."
        fi
        ;;
    true)
        is_systemd_runtime || err "INSTALL_SYSTEMD_UNIT=true but systemd runtime is unavailable."
        install_systemd_unit
        info "Installed systemd unit: $SYSTEMD_UNIT_NAME"
        if [[ "$AUTO_START_ANALYZER" == "true" ]]; then
            systemctl restart "$SYSTEMD_UNIT_NAME" \
                || err "Failed to start $SYSTEMD_UNIT_NAME"
            info "Started $SYSTEMD_UNIT_NAME"
        fi
        ;;
    false)
        info "INSTALL_SYSTEMD_UNIT=false; skipping unit installation."
        ;;
    *)
        err "INSTALL_SYSTEMD_UNIT must be one of: auto, true, false"
        ;;
esac

echo ""
echo "=== Client setup complete ==="
echo "Analyzer install dir: $ANALYZER_INSTALL_DIR"
echo "Analyzer venv:        $ANALYZER_VENV_DIR"
echo "Config file:          $ANALYZER_CONFIG_FILE"
echo "Launcher:             $LAUNCHER_PATH"
echo "LLM API URL:          $LLM_API_URL"
echo "LLM model name:       $LLM_MODEL_NAME"
echo ""
echo "Run in foreground:"
echo "  sudo -u $ANALYZER_SERVICE_USER $LAUNCHER_PATH"
echo ""
echo "Run in background (no systemd):"
echo "  sudo -u $ANALYZER_SERVICE_USER bash -lc '$LAUNCHER_PATH >/tmp/notable-analyzer-mini.log 2>&1 &'"
echo "  tail -f /tmp/notable-analyzer-mini.log"
echo ""
echo "Drop a test notable:"
echo "  echo '{\"summary\":\"test notable\",\"ip_address\":\"203.0.113.45\",\"user\":\"svc_test\"}' > $ANALYZER_DATA_DIR/incoming/notable_test_001.json"
