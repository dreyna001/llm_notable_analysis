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
readonly VLLM_MODEL_PATH="${VLLM_MODEL_PATH:-/opt/models/gemma-4-31B-it}"
readonly VLLM_SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-gemma-4-31B-it}"
readonly VLLM_INSTALL_DIR="${VLLM_INSTALL_DIR:-/opt/vllm}"
readonly VLLM_VENV_DIR="${VLLM_VENV_DIR:-$VLLM_INSTALL_DIR/venv}"
readonly LITELLM_INSTALL_DIR="${LITELLM_INSTALL_DIR:-/opt/litellm}"
readonly LITELLM_CONFIG_DIR="${LITELLM_CONFIG_DIR:-/etc/litellm}"
readonly RAG_PACKAGE_INSTALL_DIR="$INSTALL_DIR/onprem_rag_notable_analysis"

# vLLM install pinning (supply chain / reproducibility)
# - Default pins to a known-good version.
# - Override for air-gapped installs to point at an internal wheelhouse or local artifact.
#   Examples:
#     sudo VLLM_PIP_SPEC="vllm==0.21.0" bash scripts/install.sh
#     sudo VLLM_PIP_SPEC="/mnt/media/wheels/vllm-0.21.0-*.whl" bash scripts/install.sh
readonly VLLM_PIP_SPEC="${VLLM_PIP_SPEC:-vllm==0.21.0}"
readonly LITELLM_PIP_SPEC="${LITELLM_PIP_SPEC:-litellm[proxy]==1.83.14}"
readonly HUGGINGFACE_HUB_PIP_SPEC="${HUGGINGFACE_HUB_PIP_SPEC:-huggingface_hub==1.16.4}"

# Python interpreter selection (pinning / reproducibility)
#
# For regulated environments, prefer pinning vLLM to a specific Python (commonly 3.12).
# Example:
#   sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash scripts/install.sh
#
# If these are set and missing/unusable, the installer will fail early unless
# INSTALL_PYTHON=true (default) can install python3.12 system packages first.
readonly ANALYZER_PYTHON_BIN="${ANALYZER_PYTHON_BIN:-python3.12}"
readonly VLLM_PYTHON_BIN="${VLLM_PYTHON_BIN:-python3.12}"

# Users
readonly SVC_USER="notable-analyzer"
readonly VLLM_USER="vllm"
readonly LITELLM_USER="litellm"
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
NON_FATAL_ISSUES=()

record_issue() {
    local msg="$1"
    NON_FATAL_ISSUES+=("$msg")
    warn "$msg"
}

strip_crlf_in_file_best_effort() {
    # Best-effort: strip Windows CRLF from a file if present; never fail install.
    local file="$1"
    if [[ -f "$file" ]]; then
        sed -i 's/\r$//' "$file" 2>/dev/null || true
    fi
}

read_config_value_best_effort() {
    # Parse one config.env value without shell-sourcing the file.
    local config_file="$1"
    local key="$2"
    local fallback="$3"
    python3 - "$config_file" "$key" "$fallback" <<'PY' 2>/dev/null || printf '%s\n' "$fallback"
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
target_key = sys.argv[2]
fallback = sys.argv[3]

try:
    lines = path.read_text(encoding="utf-8").splitlines()
except OSError:
    print(fallback)
    raise SystemExit(0)

for raw_line in lines:
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    try:
        tokens = shlex.split(stripped, comments=True, posix=True)
    except ValueError:
        continue
    if tokens and tokens[0] == "export":
        tokens = tokens[1:]
    if len(tokens) == 1 and "=" in tokens[0]:
        key, value = tokens[0].split("=", 1)
        if key == target_key:
            print(value)
            raise SystemExit(0)

print(fallback)
PY
}

download_model_best_effort() {
    # Optional: download model weights non-interactively via Hugging Face Hub.
    #
    # Enable with:
    #   sudo MODEL_DOWNLOAD=true HF_TOKEN=... bash scripts/install.sh
    #
    # Optional:
    #   MODEL_REPO=google/gemma-4-31B-it   (default)
    #
    # Never fails the installer; logs warnings on failure.
    local model_repo="${MODEL_REPO:-google/gemma-4-31B-it}"
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

    "$INSTALL_DIR/venv/bin/pip" install --quiet "$HUGGINGFACE_HUB_PIP_SPEC" \
        || { warn "Failed to install huggingface_hub; skipping model download"; return 0; }

    mkdir -p "$model_dir" 2>/dev/null || true

    # Snapshot download into the target directory; avoids git-lfs.
    "$INSTALL_DIR/venv/bin/python" - << 'PY' || true
import os
from huggingface_hub import snapshot_download

repo_id = os.environ.get("MODEL_REPO", "google/gemma-4-31B-it")
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
local_dir = os.environ.get("VLLM_MODEL_PATH", "/opt/models/gemma-4-31B-it")

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

patch_vllm_systemd_unit() {
    # Update vLLM unit paths to match installer-selected install/venv locations.
    # This keeps runtime systemd config consistent when VLLM_INSTALL_DIR/VLLM_VENV_DIR
    # are overridden (for example, running a Python 3.12 canary side-by-side).
    local unit_file="$1"
    [[ -f "$unit_file" ]] || err "vLLM unit not found for patching: $unit_file"

    local vllm_python="$VLLM_VENV_DIR/bin/python"
    local escaped_install_dir escaped_python escaped_model_path escaped_served_model_name
    escaped_install_dir="$(printf '%s' "$VLLM_INSTALL_DIR" | sed 's/[&|]/\\&/g')"
    escaped_python="$(printf '%s' "$vllm_python" | sed 's/[&|]/\\&/g')"
    escaped_model_path="$(printf '%s' "$VLLM_MODEL_PATH" | sed 's/[&|]/\\&/g')"
    escaped_served_model_name="$(printf '%s' "$VLLM_SERVED_MODEL_NAME" | sed 's/[&|]/\\&/g')"

    sed -i -E "s|^WorkingDirectory=.*$|WorkingDirectory=${escaped_install_dir}|" "$unit_file" \
        || err "Failed to patch WorkingDirectory in $unit_file"
    sed -i -E "s|^ExecStart=.*-m vllm\\.entrypoints\\.openai\\.api_server[[:space:]]*\\\\$|ExecStart=${escaped_python} -m vllm.entrypoints.openai.api_server \\\\|" "$unit_file" \
        || err "Failed to patch ExecStart in $unit_file"
    sed -i -E "s|^([[:space:]]*--model[[:space:]]+).*$|\\1${escaped_model_path} \\\\|" "$unit_file" \
        || err "Failed to patch --model in $unit_file"
    sed -i -E "s|^([[:space:]]*--served-model-name[[:space:]]+).*$|\\1${escaped_served_model_name} \\\\|" "$unit_file" \
        || err "Failed to patch --served-model-name in $unit_file"
}

detect_cuda_home_best_effort() {
    # vLLM/FlashInfer can JIT-build CUDA kernels at runtime. Prefer an explicit
    # CUDA_HOME, then common NVIDIA toolkit install paths.
    if [[ -n "${CUDA_HOME:-}" && -x "$CUDA_HOME/bin/nvcc" ]]; then
        printf '%s\n' "$CUDA_HOME"
        return 0
    fi

    if [[ -x /usr/local/cuda/bin/nvcc ]]; then
        printf '%s\n' "/usr/local/cuda"
        return 0
    fi

    local nvcc_path
    for nvcc_path in /usr/local/cuda-*/bin/nvcc; do
        [[ -x "$nvcc_path" ]] || continue
        dirname "$(dirname "$nvcc_path")"
        return 0
    done

    if command -v nvcc &>/dev/null; then
        nvcc_path="$(command -v nvcc)"
        dirname "$(dirname "$nvcc_path")"
        return 0
    fi

    printf '%s\n' "/usr/local/cuda"
}

patch_vllm_cuda_environment() {
    local unit_file="$1"
    local cuda_home
    cuda_home="$(detect_cuda_home_best_effort)"

    local escaped_cuda_home escaped_path
    escaped_cuda_home="$(printf '%s' "$cuda_home" | sed 's/[&|]/\\&/g')"
    escaped_path="$(printf '%s' "$cuda_home/bin:$VLLM_VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" | sed 's/[&|]/\\&/g')"

    sed -i -E "s|^Environment=\"CUDA_HOME=.*\"$|Environment=\"CUDA_HOME=${escaped_cuda_home}\"|" "$unit_file" \
        || err "Failed to patch CUDA_HOME in $unit_file"
    sed -i -E "s|^Environment=\"PATH=.*\"$|Environment=\"PATH=${escaped_path}\"|" "$unit_file" \
        || err "Failed to patch CUDA PATH in $unit_file"

    if [[ -x "$cuda_home/bin/nvcc" ]]; then
        info "Configured vLLM CUDA_HOME=$cuda_home"
    else
        warn "CUDA toolkit nvcc not found; vLLM may fail if runtime JIT compilation is required. Expected: $cuda_home/bin/nvcc"
    fi
}

handle_vllm_systemd_overrides() {
    # Existing drop-ins can silently override newly installed unit settings.
    # By default we warn; optionally clear them for deterministic installs.
    local dropin_dir="/etc/systemd/system/vllm.service.d"
    if [[ ! -d "$dropin_dir" ]]; then
        return 0
    fi

    local conf_files=("$dropin_dir"/*.conf)
    if [[ ! -e "${conf_files[0]}" ]]; then
        return 0
    fi

    if [[ "${VLLM_RESET_OVERRIDES:-false}" == "true" ]]; then
        rm -f "$dropin_dir"/*.conf \
            || err "Failed to remove existing vLLM drop-ins from $dropin_dir"
        info "Cleared existing vLLM systemd drop-ins from $dropin_dir (VLLM_RESET_OVERRIDES=true)"
    else
        warn "Detected existing vLLM systemd drop-ins in $dropin_dir; these may override installed unit settings."
        warn "Set VLLM_RESET_OVERRIDES=true to clear drop-ins during install."
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
            if curl -fsS --max-time 5 "$url" &>/dev/null; then
                return 0
            fi
        else
            # Fallback to Python if curl is not installed
            python3 - "$url" <<'PY' >/dev/null 2>&1 || true
import sys, urllib.request
try:
    urllib.request.urlopen(sys.argv[1], timeout=2).read()
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

smoke_test_inference_best_effort() {
    # Best-effort canned inference run. Never fails install.
    local config_file="$CONFIG_DIR/config.env"
    local timeout_s="${SMOKE_TEST_TIMEOUT_SECONDS:-240}"
    local poll_s=2
    local default_incoming="$DATA_DIR/incoming"
    local default_reports="$DATA_DIR/reports"
    local incoming_dir="$default_incoming"
    local report_dir="$default_reports"
    local smoke_id="install-smoke-$(date +%s)"
    local payload_file
    local report_file

    if [[ ! -f "$config_file" ]]; then
        record_issue "Smoke test skipped: missing config file at $config_file"
        return 0
    fi

    incoming_dir="$(read_config_value_best_effort "$config_file" INCOMING_DIR "$default_incoming")"
    report_dir="$(read_config_value_best_effort "$config_file" REPORT_DIR "$default_reports")"
    payload_file="$incoming_dir/${smoke_id}.json"
    report_file="$report_dir/${smoke_id}.md"
    local tmp_payload
    tmp_payload="$(mktemp "$incoming_dir/.${smoke_id}.json.tmp.XXXXXX")" || {
        record_issue "Smoke test skipped: could not create temp payload in $incoming_dir"
        return 0
    }

    if ! systemctl is-active --quiet vllm; then
        record_issue "Smoke test skipped: vllm.service is not active"
        return 0
    fi
    if ! systemctl is-active --quiet litellm; then
        record_issue "Smoke test skipped: litellm.service is not active"
        return 0
    fi
    if ! systemctl is-active --quiet notable-analyzer; then
        record_issue "Smoke test skipped: notable-analyzer.service is not active"
        return 0
    fi
    if [[ ! -d "$incoming_dir" ]]; then
        record_issue "Smoke test skipped: INCOMING_DIR does not exist: $incoming_dir"
        return 0
    fi
    if [[ ! -d "$report_dir" ]]; then
        record_issue "Smoke test skipped: REPORT_DIR does not exist: $report_dir"
        return 0
    fi

    cat > "$tmp_payload" <<EOF
{"notable_id":"$smoke_id","summary":"Suspicious login from unusual IP","ip_address":"203.0.113.45","user":"admin"}
EOF
    chmod 660 "$tmp_payload" 2>/dev/null || true
    mv "$tmp_payload" "$payload_file" || {
        rm -f "$tmp_payload" 2>/dev/null || true
        record_issue "Smoke test failed: could not atomically publish payload to $payload_file"
        return 0
    }

    if [[ ! -f "$payload_file" ]]; then
        record_issue "Smoke test failed: could not write payload to $payload_file"
        return 0
    fi

    info "Smoke test submitted: $payload_file"
    local elapsed=0
    while (( elapsed < timeout_s )); do
        if [[ -f "$report_file" ]]; then
            info "Smoke test passed: report created at $report_file"
            return 0
        fi
        sleep "$poll_s"
        elapsed=$((elapsed + poll_s))
    done

    record_issue "Smoke test timed out after ${timeout_s}s (expected report: $report_file)"
    return 0
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

_python_major_minor() {
    local pybin="$1"
    "$pybin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null \
        || return 1
}

check_python_version() {
    local pybin="$1"
    local label="${2:-Python}"

    local ver
    ver="$(_python_major_minor "$pybin")" || err "$label interpreter not found or broken: $pybin"

    local major minor
    major="${ver%%.*}"
    minor="${ver##*.}"

    if [[ "$major" -lt "$MIN_PYTHON_MAJOR" ]] || \
       { [[ "$major" -eq "$MIN_PYTHON_MAJOR" ]] && [[ "$minor" -lt "$MIN_PYTHON_MINOR" ]]; }; then
        err "$label requires Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+ (found $ver at $pybin)"
    fi

    info "$label Python version: $ver ($pybin)"

    # vLLM compatibility varies by platform/Python; warn early only on very new versions.
    # (Do not fail install: some environments ship newer Pythons by default.)
    if [[ "$major" -eq 3 && "$minor" -ge 13 ]]; then
        warn "Detected $label Python $ver. If vLLM fails to start, try pinning to Python 3.12."
    fi
}

install_requires_python312_package() {
    [[ "$ANALYZER_PYTHON_BIN" == "python3.12" || "$VLLM_PYTHON_BIN" == "python3.12" ]]
}

ensure_python312_for_install() {
    local helper="$1"

    if command -v python3.12 >/dev/null 2>&1; then
        return 0
    fi
    if ! install_requires_python312_package; then
        return 0
    fi
    if [[ "${INSTALL_PYTHON:-true}" != "true" ]]; then
        err "python3.12 is required (ANALYZER_PYTHON_BIN/VLLM_PYTHON_BIN) but was not found. Install Python 3.12 manually or rerun with INSTALL_PYTHON=true (default)."
    fi
    [[ -f "$helper" ]] || err "Missing Python 3.12 install helper: $helper (install python3.12 manually or set INSTALL_PYTHON=false)"
    [[ -x "$helper" ]] || chmod +x "$helper" 2>/dev/null || true

    info "python3.12 not found; installing system Python 3.12 packages..."
    bash "$helper" || err "Failed to install Python 3.12 system packages (see output above)"
    command -v python3.12 >/dev/null 2>&1 \
        || err "python3.12 is still not on PATH after package install"
    info "python3.12 is available: $(python3.12 --version 2>&1)"
}

resolve_python312_install_helper() {
    local candidate=""
    for candidate in \
        "$SCRIPT_DIR/install_python312.sh" \
        "$MONOREPO_ROOT/scripts/install_python312.sh"; do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    err "Missing Python 3.12 install helper under $SCRIPT_DIR or $MONOREPO_ROOT/scripts (install python3.12 manually or set INSTALL_PYTHON=false)"
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

generate_random_hex_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
        return 0
    fi
    python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}

install_portal_env_config() {
    local portal_env="$CONFIG_DIR/portal.env"
    local portal_secret=""
    if [[ -f "$portal_env" ]]; then
        info "Portal config exists: $portal_env (not overwritten)"
        return 0
    fi

    [[ -f "$REPO_DIR/config.portal.env.example" ]] \
        || err "Missing config.portal.env.example"
    cp "$REPO_DIR/config.portal.env.example" "$portal_env" \
        || err "Failed to copy config.portal.env.example"
    portal_secret="$(generate_random_hex_secret)"
    python3 - "$portal_env" "$CONFIG_DIR/config.env" "$portal_secret" <<'PY'
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import urlunparse, urlparse, unquote, quote


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            continue
        if not tokens:
            continue
        if tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) == 1 and "=" in tokens[0]:
            key, value = tokens[0].split("=", 1)
            values[key] = value
    return values


def replace_line(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*(?:export\s+)?{re.escape(key)}=).*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(rf"\1{value}", text, count=1)
    return text


portal_path = Path(sys.argv[1])
config_path = Path(sys.argv[2])
secret = sys.argv[3]
text = portal_path.read_text(encoding="utf-8")
text = text.replace("<generate-a-random-shared-secret>", secret)
text = replace_line(text, "PORTAL_PROXY_SECRET", secret)

config = parse_env(config_path)
analyzer_dsn = config.get(
    "CASE_POSTGRES_DSN",
    "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
)
portal_values = parse_env(portal_path)
portal_dsn = portal_values.get(
    "CASE_POSTGRES_DSN",
    "postgresql://notable_portal@127.0.0.1:5432/notable_rag",
)
analyzer = urlparse(analyzer_dsn)
portal = urlparse(portal_dsn)
aligned = urlunparse(
    (
        portal.scheme or analyzer.scheme or "postgresql",
        portal.netloc or analyzer.netloc,
        analyzer.path or portal.path,
        "",
        "",
        "",
    )
)
text = replace_line(text, "CASE_POSTGRES_DSN", aligned)
portal_path.write_text(text, encoding="utf-8")
PY
    chown "$SVC_USER:$SVC_USER" "$portal_env"
    chmod 600 "$portal_env"
    info "Portal config installed: $portal_env"
}

sync_portal_proxy_secret_to_config() {
    local config_file="$CONFIG_DIR/config.env"
    local portal_env="$CONFIG_DIR/portal.env"
    local portal_secret=""

    [[ -f "$config_file" ]] || err "Missing analyzer config: $config_file"
    [[ -f "$portal_env" ]] || err "Missing portal config: $portal_env"

    portal_secret="$(read_config_value_best_effort "$portal_env" "PORTAL_PROXY_SECRET" "")"
    if [[ -z "$portal_secret" || "$portal_secret" == "<generate-a-random-shared-secret>" ]]; then
        record_issue "PORTAL_PROXY_SECRET is unset in $portal_env; analyzer config was not synchronized"
        return 0
    fi

    python3 - "$config_file" "$portal_env" <<'PY'
import re
import shlex
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
portal_path = Path(sys.argv[2])


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            continue
        if tokens and tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) == 1 and "=" in tokens[0]:
            key, value = tokens[0].split("=", 1)
            values[key] = value
    return values


secret = parse_env(portal_path).get("PORTAL_PROXY_SECRET", "")
lines = config_path.read_text(encoding="utf-8").splitlines()
updated = False
found = False
warning = False

for index, raw_line in enumerate(lines):
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    try:
        tokens = shlex.split(stripped, comments=True, posix=True)
    except ValueError:
        continue
    if tokens and tokens[0] == "export":
        tokens = tokens[1:]
    if len(tokens) != 1 or "=" not in tokens[0]:
        continue
    key, value = tokens[0].split("=", 1)
    if key != "PORTAL_PROXY_SECRET":
        continue
    found = True
    if value in {"", "<generate-a-random-shared-secret>"}:
        lines[index] = re.sub(
            r"^(\s*(?:export\s+)?PORTAL_PROXY_SECRET=).*",
            rf"\1{secret}",
            raw_line,
            count=1,
        )
        updated = True
    elif value != secret:
        warning = True
    break

if not found:
    lines.append(f"PORTAL_PROXY_SECRET={secret}")
    updated = True

if updated:
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
elif warning:
    print("WARN_DIFFERENT_SECRET")
PY
    chown "$SVC_USER:$SVC_USER" "$config_file"
    chmod 600 "$config_file"
}

ensure_case_archive_postgres_passwords() {
    local config_file="$CONFIG_DIR/config.env"
    local portal_env="$CONFIG_DIR/portal.env"

    [[ -f "$config_file" ]] || err "Missing analyzer config: $config_file"
    [[ -f "$portal_env" ]] || err "Missing portal config: $portal_env"

    python3 - "$config_file" "$portal_env" <<'PY'
import re
import secrets
import shlex
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunparse

config_path = Path(sys.argv[1])
portal_path = Path(sys.argv[2])


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            continue
        if tokens and tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) == 1 and "=" in tokens[0]:
            key, value = tokens[0].split("=", 1)
            values[key] = value
    return values


def render_host(parsed) -> str:
    if parsed.hostname is None:
        return ""
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return host


def passworded_dsn(dsn: str, default_user: str) -> tuple[str, bool]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise SystemExit("CASE_POSTGRES_DSN must use postgresql:// or postgres://.")
    if parsed.password:
        return dsn, False
    host = render_host(parsed)
    if not host:
        # Preserve explicit socket/peer-auth DSNs. Operators using this mode own
        # pg_hba/pg_ident compatibility for the systemd service users.
        return dsn, False
    username = unquote(parsed.username or default_user)
    password = secrets.token_hex(16)
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}"
    return urlunparse(
        (
            parsed.scheme or "postgresql",
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    ), True


def replace_line(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*(?:export\s+)?{re.escape(key)}=).*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(rf"\1{value}", text, count=1)
    return text + ("\n" if text and not text.endswith("\n") else "") + f"{key}={value}\n"


config_values = parse_env(config_path)
portal_values = parse_env(portal_path)
config_dsn = config_values.get(
    "CASE_POSTGRES_DSN",
    "postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
)
portal_dsn = portal_values.get(
    "CASE_POSTGRES_DSN",
    "postgresql://notable_portal@127.0.0.1:5432/notable_rag",
)

new_config_dsn, config_changed = passworded_dsn(config_dsn, "notable_analyzer")
new_portal_dsn, portal_changed = passworded_dsn(portal_dsn, "notable_portal")

if config_changed:
    config_text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        replace_line(config_text, "CASE_POSTGRES_DSN", new_config_dsn),
        encoding="utf-8",
    )
if portal_changed:
    portal_text = portal_path.read_text(encoding="utf-8")
    portal_path.write_text(
        replace_line(portal_text, "CASE_POSTGRES_DSN", new_portal_dsn),
        encoding="utf-8",
    )

if config_changed or portal_changed:
    print("GENERATED_CASE_ARCHIVE_POSTGRES_PASSWORDS")
PY
    chown "$SVC_USER:$SVC_USER" "$config_file" "$portal_env"
    chmod 600 "$config_file" "$portal_env"
}

install_nginx_portal_proxy_secret() {
    local portal_env="$CONFIG_DIR/portal.env"
    local include_path="/etc/nginx/notable-portal-proxy-secret.conf"
    local secret=""

    [[ -f "$portal_env" ]] || return 0
    secret="$(read_config_value_best_effort "$portal_env" "PORTAL_PROXY_SECRET" "")"
    if [[ -z "$secret" || "$secret" == "<generate-a-random-shared-secret>" ]]; then
        record_issue "PORTAL_PROXY_SECRET is unset in $portal_env; nginx proxy secret include was not created"
        return 0
    fi

    if [[ -f "$include_path" ]]; then
        info "Nginx portal proxy secret include exists: $include_path (not overwritten)"
        return 0
    fi

    if ! command -v nginx >/dev/null 2>&1; then
        record_issue "nginx is not installed; skipped $include_path (install nginx before enabling the portal front door)"
        return 0
    fi

    mkdir -p /etc/nginx
    cat > "$include_path" <<EOF
# Managed by scripts/install.sh. Must match PORTAL_PROXY_SECRET in $portal_env.
proxy_set_header X-Notable-Portal-Proxy-Secret "$secret";
EOF
    chown root:root "$include_path"
    chmod 600 "$include_path"
    info "Installed nginx portal proxy secret include: $include_path"
}

install_nginx_portal_site_config() {
    local site_path="/etc/nginx/conf.d/notable-portal.conf"
    local example_path="/etc/nginx/conf.d/notable-portal.conf.example"
    local src="$REPO_DIR/deploy/nginx/notable-portal.conf"

    [[ -f "$src" ]] || err "Missing nginx example config: $src"
    if ! command -v nginx >/dev/null 2>&1; then
        record_issue "nginx is not installed; skipped analyst portal site config"
        return 0
    fi

    mkdir -p /etc/nginx/conf.d
    if [[ ! -f "$site_path" ]]; then
        cp "$src" "$site_path" || err "Failed to copy notable-portal.conf"
        chown root:root "$site_path"
        chmod 644 "$site_path"
        info "Installed nginx site config: $site_path"
        warn "Edit server_name, TLS paths, and htpasswd before reloading nginx"
    else
        info "Nginx site config exists: $site_path (not overwritten)"
    fi

    if [[ ! -f "$example_path" ]]; then
        cp "$src" "$example_path" || err "Failed to copy notable-portal.conf.example"
        chown root:root "$example_path"
        chmod 644 "$example_path"
        info "Installed nginx site example: $example_path"
    fi
}

enable_analyst_portal_profile_in_config() {
    local config_file="$CONFIG_DIR/config.env"
    [[ -f "$config_file" ]] || err "Missing analyzer config: $config_file"
    python3 - "$config_file" <<'PY'
import re
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
updated = False
profile_found = False
for index, raw_line in enumerate(lines):
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    try:
        tokens = shlex.split(stripped, comments=True, posix=True)
    except ValueError:
        continue
    if not tokens:
        continue
    if tokens[0] == "export":
        tokens = tokens[1:]
    if len(tokens) != 1 or "=" not in tokens[0]:
        continue
    key, value = tokens[0].split("=", 1)
    if key != "CAPABILITY_PROFILES":
        continue
    profile_found = True
    profiles = [part.strip() for part in value.split(",") if part.strip()]
    if "analyst_portal" not in profiles:
        profiles.append("analyst_portal")
        lines[index] = re.sub(
            r"^(\s*(?:export\s+)?CAPABILITY_PROFILES=).*",
            rf"\1{','.join(profiles)}",
            raw_line,
            count=1,
        )
        updated = True
    break

if not profile_found:
    lines.append("CAPABILITY_PROFILES=core,analyst_portal")
    updated = True

if updated:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
    info "Enabled analyst_portal in $config_file"
}

detect_os_family() {
    if [[ ! -f /etc/os-release ]]; then
        echo "unknown"
        return 0
    fi
    # shellcheck source=/dev/null
    source /etc/os-release
    local distro_id="${ID:-}"
    local id_like="${ID_LIKE:-}"
    case "$distro_id" in
        ubuntu|debian|linuxmint|pop)
            echo "debian"
            ;;
        rhel|centos|rocky|almalinux|fedora|ol)
            echo "rhel"
            ;;
        *)
            if [[ "$id_like" == *debian* ]]; then
                echo "debian"
            elif [[ "$id_like" == *rhel* || "$id_like" == *fedora* ]]; then
                echo "rhel"
            else
                echo "unknown"
            fi
            ;;
    esac
}

detect_postgresql_major_version() {
    local pg_major=""
    if command -v psql >/dev/null 2>&1; then
        pg_major="$(psql -V 2>/dev/null | sed -E 's/.* ([0-9]+).*/\1/')"
    fi
    if [[ -z "$pg_major" && -d /etc/postgresql ]]; then
        pg_major="$(
            find /etc/postgresql -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null \
                | sort -rn \
                | head -n1
        )"
    fi
    printf '%s' "$pg_major"
}

verify_postgresql_pgvector_extension() {
    local admin_user="${POSTGRES_ADMIN_USER:-postgres}"
    local admin_db="${POSTGRES_ADMIN_DB:-postgres}"
    if [[ "$(id -un)" == "$admin_user" ]]; then
        psql -v ON_ERROR_STOP=1 -d "$admin_db" \
            -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
    else
        sudo -u "$admin_user" psql -v ON_ERROR_STOP=1 -d "$admin_db" \
            -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
    fi
}

install_portal_pgvector_from_source() {
    local pg_major="$1"
    local os_family workdir pgvector_ref="${PGVECTOR_GIT_REF:-v0.8.0}"

    info "Building pgvector from source for PostgreSQL ${pg_major} (ref: $pgvector_ref)"
    os_family="$(detect_os_family)"
    case "$os_family" in
        debian)
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                "postgresql-server-dev-${pg_major}" \
                build-essential \
                git \
                || err "Failed to install pgvector build dependencies for PostgreSQL ${pg_major}"
            ;;
        rhel)
            local dev_pkg=""
            for candidate in \
                "postgresql${pg_major}-devel" \
                "postgresql${pg_major}-server-devel" \
                "postgresql-server-devel" \
                "postgresql-devel"; do
                if dnf -q list installed "$candidate" >/dev/null 2>&1 \
                    || dnf -q list available "$candidate" >/dev/null 2>&1; then
                    dev_pkg="$candidate"
                    break
                fi
            done
            [[ -n "$dev_pkg" ]] \
                || err "Could not find PostgreSQL server development headers for PostgreSQL ${pg_major}"
            dnf install -y "$dev_pkg" gcc make git \
                || err "Failed to install pgvector build dependencies for PostgreSQL ${pg_major}"
            ;;
        *)
            err "Automatic pgvector source build is not implemented for OS family: $os_family"
            ;;
    esac

    workdir="$(mktemp -d)"
    git clone --depth 1 --branch "$pgvector_ref" https://github.com/pgvector/pgvector.git "$workdir/pgvector" \
        || err "Failed to clone pgvector source (ref: $pgvector_ref)"
    make -C "$workdir/pgvector" OPTFLAGS=""
    make -C "$workdir/pgvector" install
    rm -rf "$workdir"
    systemctl restart postgresql
    info "Installed pgvector from source for PostgreSQL ${pg_major}"
}

install_portal_pgvector_os_package() {
    local os_family pg_major pgvector_pkg install_method=""
    os_family="$(detect_os_family)"
    pg_major="$(detect_postgresql_major_version)"
    if [[ -z "$pg_major" ]]; then
        err "Could not detect PostgreSQL major version for pgvector package install"
    fi

    case "$os_family" in
        debian)
            pgvector_pkg="postgresql-${pg_major}-pgvector"
            info "Installing required PostgreSQL pgvector package: $pgvector_pkg"
            if DEBIAN_FRONTEND=noninteractive apt-get install -y "$pgvector_pkg"; then
                install_method="$pgvector_pkg"
            else
                warn "Package $pgvector_pkg is unavailable in apt; falling back to source build"
                install_portal_pgvector_from_source "$pg_major"
                install_method="pgvector source build (PostgreSQL ${pg_major})"
            fi
            ;;
        rhel)
            pgvector_pkg=""
            for candidate in "postgresql${pg_major}-pgvector" "pgvector_${pg_major}"; do
                if dnf -q list available "$candidate" >/dev/null 2>&1; then
                    pgvector_pkg="$candidate"
                    break
                fi
            done
            if [[ -n "$pgvector_pkg" ]]; then
                info "Installing required PostgreSQL pgvector package: $pgvector_pkg"
                if dnf install -y "$pgvector_pkg"; then
                    install_method="$pgvector_pkg"
                else
                    warn "Package $pgvector_pkg failed to install; falling back to source build"
                    install_portal_pgvector_from_source "$pg_major"
                    install_method="pgvector source build (PostgreSQL ${pg_major})"
                fi
            else
                warn "PostgreSQL pgvector package not found for major version $pg_major; falling back to source build"
                install_portal_pgvector_from_source "$pg_major"
                install_method="pgvector source build (PostgreSQL ${pg_major})"
            fi
            ;;
        *)
            err "Automatic pgvector package install is not implemented for OS family: $os_family"
            ;;
    esac

    info "Installed PostgreSQL pgvector via: $install_method"
    verify_postgresql_pgvector_extension \
        || err "PostgreSQL pgvector extension is not loadable after pgvector install"
    info "Verified PostgreSQL pgvector extension loads successfully"
}

install_portal_os_packages() {
    if [[ "${INSTALL_ANALYST_PORTAL:-false}" != "true" ]]; then
        return 0
    fi
    if [[ "${INSTALL_PORTAL_SKIP_OS_PACKAGES:-false}" == "true" ]]; then
        info "INSTALL_PORTAL_SKIP_OS_PACKAGES=true; skipping portal OS package install"
        return 0
    fi

    local os_family
    os_family="$(detect_os_family)"
    info "INSTALL_ANALYST_PORTAL=true: installing portal OS packages ($os_family)"

    case "$os_family" in
        debian)
            apt-get update
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                nginx \
                postgresql \
                postgresql-contrib \
                apache2-utils
            systemctl enable postgresql
            systemctl start postgresql
            install_portal_pgvector_os_package
            ;;
        rhel)
            if ! command -v dnf >/dev/null 2>&1; then
                err "dnf is required to install portal OS packages on RHEL-compatible hosts"
            fi
            dnf install -y nginx postgresql-server postgresql httpd-tools
            if command -v postgresql-setup >/dev/null 2>&1; then
                postgresql-setup --initdb || true
            fi
            systemctl enable postgresql
            systemctl start postgresql
            install_portal_pgvector_os_package
            ;;
        *)
            record_issue "Unsupported OS for automatic portal package install; install nginx, PostgreSQL, and an htpasswd tool manually, then rerun with INSTALL_ANALYST_PORTAL=true"
            return 0
            ;;
    esac

    if command -v nginx >/dev/null 2>&1; then
        systemctl enable nginx 2>/dev/null || true
        info "nginx installed"
    else
        record_issue "nginx install completed but nginx binary is missing from PATH"
    fi
    if command -v psql >/dev/null 2>&1; then
        info "PostgreSQL client installed"
    else
        record_issue "PostgreSQL install completed but psql is missing from PATH"
    fi
}

resolve_portal_frontend_toolchain() {
    local venv_bin="$MONOREPO_ROOT/.venv/bin"
    local npm_bin="${NPM_BIN:-npm}"
    local node_bin="${NODE_BIN:-}"
    local toolchain_path=""

    if [[ -x "$venv_bin/npm" && "$npm_bin" == "npm" ]]; then
        npm_bin="$venv_bin/npm"
        info "Using monorepo dev npm: $npm_bin"
    fi
    if [[ -z "$node_bin" && -x "$venv_bin/node" ]]; then
        node_bin="$venv_bin/node"
    fi
    if [[ -n "$node_bin" ]]; then
        toolchain_path="$(dirname "$node_bin")"
    elif command -v node >/dev/null 2>&1; then
        node_bin="$(command -v node)"
        toolchain_path="$(dirname "$node_bin")"
    fi
    if [[ -n "$toolchain_path" ]]; then
        info "Using Node.js toolchain from: $toolchain_path"
    fi
    if ! command -v "$npm_bin" >/dev/null 2>&1 && [[ ! -x "$npm_bin" ]]; then
        err "npm is required for INSTALL_ANALYST_PORTAL=true (install Node.js or set NPM_BIN, e.g. $venv_bin/npm)"
    fi
    if [[ -z "$toolchain_path" ]] || [[ ! -x "$toolchain_path/node" ]]; then
        err "node is required for INSTALL_ANALYST_PORTAL=true (bootstrap repo .venv with scripts/bootstrap_dev_venv.sh or set NODE_BIN)"
    fi

    PORTAL_NPM_BIN="$npm_bin"
    PORTAL_NODE_TOOLCHAIN_PATH="$toolchain_path"
}

analyst_portal_frontend_dir() {
    printf '%s/frontend/analyst-portal' "$REPO_DIR"
}

analyst_portal_dist_dir() {
    printf '%s/dist' "$(analyst_portal_frontend_dir)"
}

require_analyst_portal_dist() {
    local dist_dir
    dist_dir="$(analyst_portal_dist_dir)"
    if [[ -d "$dist_dir" && -f "$dist_dir/index.html" ]]; then
        return 0
    fi
    err "Analyst portal dist/ is required but missing: $dist_dir/index.html. Build on a connected host: cd frontend/analyst-portal && npm install && npm run build. Transfer dist/ to this host, then rerun with INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true. See docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md"
}

build_analyst_portal_frontend() {
    if [[ "${INSTALL_ANALYST_PORTAL:-false}" != "true" ]]; then
        return 0
    fi
    if [[ "${INSTALL_PORTAL_SKIP_FRONTEND_BUILD:-false}" == "true" ]]; then
        info "INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true; using pre-built analyst portal dist (air-gapped path)"
        require_analyst_portal_dist
        return 0
    fi

    local frontend_dir
    frontend_dir="$(analyst_portal_frontend_dir)"
    [[ -f "$frontend_dir/package.json" ]] || err "Missing analyst portal package.json: $frontend_dir/package.json"
    resolve_portal_frontend_toolchain

    info "Building analyst portal frontend in $frontend_dir"
    (
        export PATH="$PORTAL_NODE_TOOLCHAIN_PATH:$PATH"
        export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
        cd "$frontend_dir"
        if [[ -f package-lock.json ]]; then
            "$PORTAL_NPM_BIN" ci
        else
            "$PORTAL_NPM_BIN" install
        fi
        "$PORTAL_NPM_BIN" run build
    ) || err "Failed to build analyst portal frontend (npm run build)"

    [[ -d "$frontend_dir/dist" ]] || err "Analyst portal build did not produce dist/: $frontend_dir/dist"
    info "Analyst portal frontend build complete: $frontend_dir/dist"
}

setup_case_archive_postgres_best_effort() {
    local setup_script="$REPO_DIR/scripts/setup_postgres_case_archive.sh"
    [[ -x "$setup_script" ]] || chmod +x "$setup_script" 2>/dev/null || true
    [[ -f "$setup_script" ]] || err "Missing setup script: $setup_script"
    if ! command -v psql >/dev/null 2>&1; then
        if [[ "${INSTALL_PORTAL_ALLOW_PARTIAL:-false}" == "true" ]]; then
            record_issue "psql is unavailable; skipped PostgreSQL case archive setup (install PostgreSQL client/server and rerun with INSTALL_ANALYST_PORTAL=true)"
            return 0
        fi
        err "psql is unavailable; cannot complete INSTALL_ANALYST_PORTAL=true (set INSTALL_PORTAL_ALLOW_PARTIAL=true to install files without DB setup)"
    fi
    if bash "$setup_script" \
        --config-env "$CONFIG_DIR/config.env" \
        --portal-env "$CONFIG_DIR/portal.env"; then
        return 0
    fi
    if [[ "${INSTALL_PORTAL_ALLOW_PARTIAL:-false}" == "true" ]]; then
        record_issue "PostgreSQL case archive setup failed; review output and rerun scripts/setup_postgres_case_archive.sh"
        return 0
    fi
    err "PostgreSQL case archive setup failed; review output and rerun scripts/setup_postgres_case_archive.sh"
}

install_analyst_portal_bringup_assets() {
    install_portal_os_packages
    install_portal_env_config
    sync_portal_proxy_secret_to_config
    install_nginx_portal_proxy_secret
    if [[ "${INSTALL_ANALYST_PORTAL:-false}" == "true" ]]; then
        enable_analyst_portal_profile_in_config
        ensure_case_archive_postgres_passwords
        setup_case_archive_postgres_best_effort
        install_nginx_portal_site_config
    else
        info "INSTALL_ANALYST_PORTAL=false; installed portal.env and nginx proxy secret only"
        info "Enable full portal bring-up with: sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh"
    fi
}

#------------------------------------------------------------------------------
# Preflight checks
#------------------------------------------------------------------------------
echo "=== On-prem Notable Analyzer Installation ==="
echo ""

check_root

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MONOREPO_ROOT="$(cd "$REPO_DIR/.." && pwd)"
RAG_PACKAGE_SRC_DIR="${RAG_PACKAGE_SRC_DIR:-$MONOREPO_ROOT/onprem_rag_notable_analysis}"
SDK_SOURCE_DIR="${SDK_SOURCE_DIR:-$MONOREPO_ROOT/onprem-llm-sdk}"

ensure_python312_for_install "$(resolve_python312_install_helper)"

check_command python3
check_command pip3
check_command systemctl
check_python_interpreter "$ANALYZER_PYTHON_BIN"
check_python_interpreter "$VLLM_PYTHON_BIN"
check_python_version "$ANALYZER_PYTHON_BIN" "Analyzer"
check_python_version "$VLLM_PYTHON_BIN" "vLLM"

# Verify required files exist
for f in requirements.txt config.env.example; do
    [[ -f "$REPO_DIR/$f" ]] || err "Missing required file: $REPO_DIR/$f"
done
[[ -f "$REPO_DIR/pyproject.toml" ]] || err "Missing required file: $REPO_DIR/pyproject.toml"
[[ -d "$REPO_DIR/src/llm_notable_analysis_onprem_systemd/onprem_service" ]] || err "Missing package directory: $REPO_DIR/src/llm_notable_analysis_onprem_systemd/onprem_service"
[[ -d "$REPO_DIR/deploy/systemd" ]] || err "Missing directory: $REPO_DIR/deploy/systemd"
[[ -f "$RAG_PACKAGE_SRC_DIR/pyproject.toml" ]] || err "Missing RAG package metadata: $RAG_PACKAGE_SRC_DIR/pyproject.toml"
[[ -d "$RAG_PACKAGE_SRC_DIR/future" ]] || err "Missing RAG package directory: $RAG_PACKAGE_SRC_DIR/future"
[[ -f "$SDK_SOURCE_DIR/pyproject.toml" ]] || err "Missing SDK package metadata: $SDK_SOURCE_DIR (clone full monorepo or set SDK_SOURCE_DIR)"

echo ""

#------------------------------------------------------------------------------
# 1. Create system users
#------------------------------------------------------------------------------
echo "[1/8] Creating system users..."

create_user_if_missing "$SVC_USER" "$INSTALL_DIR"
create_user_if_missing "$VLLM_USER" "$VLLM_INSTALL_DIR"
create_user_if_missing "$LITELLM_USER" "$LITELLM_INSTALL_DIR"
create_user_if_missing "$SFTP_USER" "$SFTP_CHROOT"

# Add SFTP user to service group for shared write access
if ! id -nG "$SFTP_USER" | tr ' ' '\n' | grep -Fxq "$SVC_USER"; then
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
ensure_dir "$LITELLM_INSTALL_DIR" "$LITELLM_USER:$LITELLM_USER" 755
ensure_dir "$LITELLM_CONFIG_DIR" "$LITELLM_USER:$LITELLM_USER" 750

# Data directories (service user owns)
for subdir in processed quarantine reports; do
    ensure_dir "$DATA_DIR/$subdir" "$SVC_USER:$SVC_USER" 750
done
ensure_dir "$DATA_DIR/cache" "$SVC_USER:$SVC_USER" 750
ensure_dir "$DATA_DIR/cache/huggingface" "$SVC_USER:$SVC_USER" 750
ensure_dir "$DATA_DIR/cache/sentence-transformers" "$SVC_USER:$SVC_USER" 750

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
#   /opt/models/gemma-4-31B-it
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
chgrp -R "$VLLM_USER" "$VLLM_MODEL_PATH" 2>/dev/null || true
chmod -R g+rX,o-rwx "$VLLM_MODEL_PATH" 2>/dev/null || true

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
# 3b. Analyst portal frontend build (before dist copy)
#------------------------------------------------------------------------------
if [[ "${INSTALL_ANALYST_PORTAL:-false}" == "true" ]]; then
    echo ""
    if [[ "${INSTALL_PORTAL_SKIP_FRONTEND_BUILD:-false}" == "true" ]]; then
        echo "[3b/8] Verifying pre-built analyst portal frontend..."
    else
        echo "[3b/8] Building analyst portal frontend (connected host; requires npm registry)..."
    fi
    build_analyst_portal_frontend
fi

#------------------------------------------------------------------------------
# 4. Copy application code
#------------------------------------------------------------------------------
echo "[4/8] Copying application code..."

rm -rf "$INSTALL_DIR/onprem_service" "$INSTALL_DIR/src" "$RAG_PACKAGE_INSTALL_DIR"
cp -a "$REPO_DIR/src" "$INSTALL_DIR/" \
    || err "Failed to copy src package tree to $INSTALL_DIR"
mkdir -p "$RAG_PACKAGE_INSTALL_DIR"
cp "$RAG_PACKAGE_SRC_DIR/pyproject.toml" "$RAG_PACKAGE_INSTALL_DIR/" \
    || err "Failed to copy RAG pyproject.toml"
cp "$RAG_PACKAGE_SRC_DIR/__init__.py" "$RAG_PACKAGE_INSTALL_DIR/" \
    || err "Failed to copy RAG package __init__.py"
cp -a "$RAG_PACKAGE_SRC_DIR/future" "$RAG_PACKAGE_INSTALL_DIR/" \
    || err "Failed to copy RAG package modules"
if [[ -f "$RAG_PACKAGE_SRC_DIR/README.md" ]]; then
    cp "$RAG_PACKAGE_SRC_DIR/README.md" "$RAG_PACKAGE_INSTALL_DIR/"
fi
rm -rf "$RAG_PACKAGE_INSTALL_DIR/__pycache__" \
       "$RAG_PACKAGE_INSTALL_DIR/future/__pycache__" \
       "$RAG_PACKAGE_INSTALL_DIR/build" \
       "$RAG_PACKAGE_INSTALL_DIR"/*.egg-info 2>/dev/null || true
cp "$REPO_DIR/pyproject.toml" "$INSTALL_DIR/" \
    || err "Failed to copy pyproject.toml"
cp "$REPO_DIR/requirements.txt" "$INSTALL_DIR/" \
    || err "Failed to copy requirements.txt"
if [[ -d "$REPO_DIR/frontend/analyst-portal/dist" ]]; then
    mkdir -p "$INSTALL_DIR/frontend/analyst-portal"
    rm -rf "$INSTALL_DIR/frontend/analyst-portal/dist"
    cp -a "$REPO_DIR/frontend/analyst-portal/dist" "$INSTALL_DIR/frontend/analyst-portal/" \
        || err "Failed to copy analyst portal React dist"
else
    if [[ "${INSTALL_ANALYST_PORTAL:-false}" == "true" ]]; then
        require_analyst_portal_dist
    else
        record_issue "React analyst portal dist not found; run INSTALL_ANALYST_PORTAL=true bash scripts/install.sh or npm --prefix frontend/analyst-portal run build before installing the nginx SPA"
    fi
fi

chown -R "$SVC_USER:$SVC_USER" "$INSTALL_DIR"
info "Code installed at $INSTALL_DIR/src/llm_notable_analysis_onprem_systemd"
info "RAG package installed at $RAG_PACKAGE_INSTALL_DIR"

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

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel --quiet \
    || err "Failed to upgrade pip"

tmp_requirements="$(mktemp)"
awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    /^[[:space:]]*onprem-llm-sdk([[:space:]]*(==|>=|<=|~=|!=).*)?$/ { next }
    { print }
' "$INSTALL_DIR/requirements.txt" > "$tmp_requirements"
if [[ -s "$tmp_requirements" ]]; then
    "$INSTALL_DIR/venv/bin/pip" install -r "$tmp_requirements" --quiet \
        || err "Failed to install requirements"
fi
rm -f "$tmp_requirements"

"$INSTALL_DIR/venv/bin/pip" install --upgrade "$SDK_SOURCE_DIR" --quiet \
    || err "Failed to install onprem-llm-sdk from $SDK_SOURCE_DIR"
"$INSTALL_DIR/venv/bin/pip" install --upgrade "$RAG_PACKAGE_INSTALL_DIR" --quiet \
    || err "Failed to install onprem_rag_notable_analysis package"
"$INSTALL_DIR/venv/bin/pip" install --upgrade "$INSTALL_DIR" --quiet \
    || err "Failed to install analyzer package"

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
#   sudo VLLM_SKIP_INSTALL=true bash scripts/install.sh
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
    "$VLLM_VENV_DIR/bin/pip" install "$VLLM_PIP_SPEC" --quiet \
        || err "Failed to install vLLM ($VLLM_PIP_SPEC). Ensure GPU drivers/toolkit are installed and artifacts are available."

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
# 5c. Create LiteLLM virtual environment
#------------------------------------------------------------------------------
echo ""
echo "[5c] Creating LiteLLM virtual environment..."

if [[ -d "$LITELLM_INSTALL_DIR/venv" ]]; then
    info "LiteLLM venv exists; upgrading dependencies..."
else
    "$ANALYZER_PYTHON_BIN" -m venv "$LITELLM_INSTALL_DIR/venv" \
        || err "Failed to create LiteLLM virtual environment at $LITELLM_INSTALL_DIR/venv"
    info "Created LiteLLM venv at $LITELLM_INSTALL_DIR/venv"
fi

"$LITELLM_INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet \
    || err "Failed to upgrade pip in LiteLLM venv"
"$LITELLM_INSTALL_DIR/venv/bin/pip" install "$LITELLM_PIP_SPEC" --quiet \
    || err "Failed to install LiteLLM ($LITELLM_PIP_SPEC)"
chown -R "$LITELLM_USER:$LITELLM_USER" "$LITELLM_INSTALL_DIR/venv"
info "LiteLLM installed in $LITELLM_INSTALL_DIR/venv"

#------------------------------------------------------------------------------
# 6. Install configuration
#------------------------------------------------------------------------------
echo "[6/8] Installing configuration..."

if [[ -f "$CONFIG_DIR/config.env" ]]; then
    info "Config exists: $CONFIG_DIR/config.env (not overwritten)"
else
    cp "$REPO_DIR/config.env.example" "$CONFIG_DIR/config.env" \
        || err "Failed to copy config.env.example"
    chown "$SVC_USER:$SVC_USER" "$CONFIG_DIR/config.env"
    chmod 600 "$CONFIG_DIR/config.env"
    info "Config installed: $CONFIG_DIR/config.env"
    warn "EDIT THIS FILE before starting the service"
fi

if [[ -f "$LITELLM_CONFIG_DIR/config.yaml" ]]; then
    info "LiteLLM config exists: $LITELLM_CONFIG_DIR/config.yaml (not overwritten)"
else
    cp "$REPO_DIR/deploy/litellm/config.yaml.example" "$LITELLM_CONFIG_DIR/config.yaml" \
        || err "Failed to copy LiteLLM config.yaml.example"
    chown "$LITELLM_USER:$LITELLM_USER" "$LITELLM_CONFIG_DIR/config.yaml"
    chmod 600 "$LITELLM_CONFIG_DIR/config.yaml"
    info "LiteLLM config installed: $LITELLM_CONFIG_DIR/config.yaml"
fi

#------------------------------------------------------------------------------
# 6b. Analyst portal bring-up assets
#------------------------------------------------------------------------------
echo ""
echo "[6b/8] Installing analyst portal bring-up assets..."
install_analyst_portal_bringup_assets

#------------------------------------------------------------------------------
# 7. Install systemd units
#------------------------------------------------------------------------------
echo "[7/8] Installing systemd units..."

# If you want to "comment out" systemd unit installation without deleting code:
#   sudo INSTALL_SYSTEMD_UNITS=false bash scripts/install.sh
if [[ "${INSTALL_SYSTEMD_UNITS:-true}" == "true" ]]; then
    # Default units (stable baseline)
    units=(
        notable-analyzer.service
        notable-portal.service
        litellm.service
        vllm.service
        notable-retention.service
        notable-retention.timer
    )

    for unit in "${units[@]}"; do
        src="$REPO_DIR/deploy/systemd/$unit"
        [[ -f "$src" ]] || err "Missing systemd unit: $src"
        # Prevent subtle failures when unit files were edited on Windows.
        strip_crlf_in_file_best_effort "$src"
        cp "$src" /etc/systemd/system/ || err "Failed to copy $unit"
        strip_crlf_in_file_best_effort "/etc/systemd/system/$unit"
        if [[ "$unit" == "vllm.service" ]]; then
            patch_vllm_systemd_unit "/etc/systemd/system/$unit"
            patch_vllm_cuda_environment "/etc/systemd/system/$unit"
        fi
        info "Installed: $unit"
    done

    handle_vllm_systemd_overrides

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
ensure_dir "$SSH_DIR" "root:root" 700

if [[ ! -f "$SSH_DIR/authorized_keys" ]]; then
    touch "$SSH_DIR/authorized_keys"
    chown "root:root" "$SSH_DIR/authorized_keys"
    chmod 600 "$SSH_DIR/authorized_keys"
    info "Created $SSH_DIR/authorized_keys (add SOAR public key here)"
fi

# Best-effort auto-start (enabled by default)
if [[ "${AUTO_START_SERVICES:-true}" == "true" ]]; then
    echo ""
    info "AUTO_START_SERVICES=true: attempting to start services (best-effort)"
    if [[ ! -f "$VLLM_MODEL_PATH/config.json" ]]; then
        record_issue "Model not present at $VLLM_MODEL_PATH (missing config.json); skipping auto-start of vLLM"
    else
        local_vllm_ready="false"
        local_litellm_ready="false"
        vllm_health_timeout_s="${VLLM_HEALTH_TIMEOUT_SECONDS:-420}"
        litellm_health_timeout_s="${LITELLM_HEALTH_TIMEOUT_SECONDS:-120}"
        # Use restart (not start) so re-running install.sh applies updated unit files/venvs cleanly.
        systemctl enable vllm 2>/dev/null || true
        systemctl restart vllm 2>/dev/null || systemctl start vllm 2>/dev/null || record_issue "Could not start/restart vllm.service (check systemctl/journalctl)"
        if wait_for_http_200_best_effort "http://127.0.0.1:8000/health" "$vllm_health_timeout_s"; then
            info "vLLM health check OK"
            local_vllm_ready="true"
        else
            record_issue "vLLM health check timed out; check: sudo journalctl -u vllm -n 200 --no-pager"
        fi
        systemctl enable litellm 2>/dev/null || true
        systemctl restart litellm 2>/dev/null || systemctl start litellm 2>/dev/null || record_issue "Could not start/restart litellm.service (check systemctl/journalctl)"
        if wait_for_http_200_best_effort "http://127.0.0.1:4000/v1/models" "$litellm_health_timeout_s"; then
            info "LiteLLM readiness check OK"
            local_litellm_ready="true"
        else
            record_issue "LiteLLM readiness check timed out; check: sudo journalctl -u litellm -n 200 --no-pager"
        fi
        systemctl enable notable-analyzer 2>/dev/null || true
        systemctl restart notable-analyzer 2>/dev/null || systemctl start notable-analyzer 2>/dev/null || record_issue "Could not start/restart notable-analyzer.service (check systemctl/journalctl)"
        if [[ "${INSTALL_ANALYST_PORTAL:-false}" == "true" ]]; then
            systemctl enable notable-portal 2>/dev/null || true
            systemctl restart notable-portal 2>/dev/null || systemctl start notable-portal 2>/dev/null || record_issue "Could not start/restart notable-portal.service (check systemctl/journalctl)"
            if wait_for_http_200_best_effort "http://127.0.0.1:8080/health" 30; then
                info "Portal health check OK"
            else
                record_issue "Portal health check timed out; check: sudo journalctl -u notable-portal -n 200 --no-pager"
            fi
        fi
        if [[ "${RUN_SMOKE_TEST:-true}" == "true" && "$local_vllm_ready" == "true" && "$local_litellm_ready" == "true" ]]; then
            info "RUN_SMOKE_TEST=true: running canned inference smoke test (best-effort)"
            smoke_test_inference_best_effort
        elif [[ "${RUN_SMOKE_TEST:-true}" == "true" ]]; then
            record_issue "Skipping canned smoke test because vLLM/LiteLLM was not healthy during post-install checks"
        else
            info "RUN_SMOKE_TEST=false: skipping canned inference smoke test"
        fi
    fi
else
    info "AUTO_START_SERVICES=false: skipping service start and canned smoke test"
fi

#------------------------------------------------------------------------------
# Summary
#------------------------------------------------------------------------------
echo ""
echo "=== Installation Complete ==="
echo ""
echo "Before starting:"
echo "  1. Edit config:       sudo vi $CONFIG_DIR/config.env"
echo "  2. Edit portal env:   sudo vi $CONFIG_DIR/portal.env"
echo "  3. Add model weights: $VLLM_MODEL_PATH"
echo "  4. Add SOAR SSH key:  $SSH_DIR/authorized_keys"
echo "  5. Restart sshd:      sudo systemctl restart sshd"
echo ""
echo "Analyst portal bring-up:"
echo "  - Full portal wiring (OS packages, npm build, Postgres schema, analyst_portal profile, nginx site):"
echo "      sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh"
echo "  - Air-gapped UI: build frontend/analyst-portal on a connected host, transfer dist/, then:"
echo "      sudo INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh"
echo "  - Operator still required: TLS certs, htpasswd, nginx server_name, DNS, firewall, optional report backfill"
echo "  - See docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md and docs/operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md"
echo "  - Skip OS packages or frontend build when pre-staged:"
echo "      sudo INSTALL_PORTAL_SKIP_OS_PACKAGES=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh"
echo "      sudo INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh"
echo ""
echo "Start services:"
echo "  sudo systemctl enable --now vllm"
echo "  sudo systemctl enable --now litellm"
echo "  sudo systemctl enable --now notable-analyzer"
echo "  sudo systemctl enable --now notable-portal      # when analyst_portal is enabled"
echo "  sudo systemctl enable --now notable-retention.timer  # optional"
echo ""
echo "Verify:"
echo "  sudo systemctl status vllm litellm notable-analyzer notable-portal"
echo "  sudo journalctl -u notable-analyzer -f"
echo "  curl -fsS http://127.0.0.1:8080/health   # portal liveness when enabled"
echo ""
echo "Troubleshooting vLLM:"
echo "  - If vllm.service fails with status=203/EXEC:"
echo "      sudo ls -la $VLLM_VENV_DIR/bin/python"
echo "  - If vllm.service starts then immediately exits, run vLLM in foreground to see the real error:"
echo "      sudo systemctl stop vllm"
echo "      sudo -u $VLLM_USER $VLLM_VENV_DIR/bin/python -m vllm.entrypoints.openai.api_server \\"
echo "        --model $VLLM_MODEL_PATH \\"
echo "        --served-model-name $VLLM_SERVED_MODEL_NAME \\"
echo "        --host 127.0.0.1 --port 8000 \\"
echo "        --gpu-memory-utilization 0.92 --max-model-len 32768 --dtype auto \\"
echo "        --distributed-executor-backend mp"
echo "  - If the error mentions trust_remote_code, consider enabling it explicitly (security tradeoff):"
echo "      sudo vi /etc/systemd/system/vllm.service  # add --trust-remote-code"
echo "      sudo systemctl daemon-reload && sudo systemctl restart vllm"
echo ""
echo "Optional installer flags:"
echo "  - Skip automatic Python 3.12 OS package install (air-gapped / pre-staged):"
echo "      sudo INSTALL_PYTHON=false bash scripts/install.sh"
echo "  - Skip vLLM install (air-gapped / preinstalled):"
echo "      sudo VLLM_SKIP_INSTALL=true bash scripts/install.sh"
echo "  - Add extra vLLM smoke checks (non-fatal):"
echo "      sudo VLLM_SMOKE_TEST=true bash scripts/install.sh"
echo "  - Download model non-interactively (requires internet + HF token):"
echo "      sudo MODEL_DOWNLOAD=true HF_TOKEN=... bash scripts/install.sh"
echo "      # optional: MODEL_REPO=google/gemma-4-31B-it VLLM_MODEL_PATH=/opt/models/gemma-4-31B-it VLLM_SERVED_MODEL_NAME=gemma-4-31B-it"
echo "  - Auto-start services after install (best-effort, default true):"
echo "      sudo AUTO_START_SERVICES=true bash scripts/install.sh"
echo "  - Skip post-install service start:"
echo "      sudo AUTO_START_SERVICES=false bash scripts/install.sh"
echo "  - Run/skip canned smoke inference (best-effort, default true):"
echo "      sudo RUN_SMOKE_TEST=true bash scripts/install.sh"
echo "      sudo RUN_SMOKE_TEST=false bash scripts/install.sh"
echo "  - Override vLLM health timeout seconds (default: 420):"
echo "      sudo VLLM_HEALTH_TIMEOUT_SECONDS=420 bash scripts/install.sh"
echo "  - Reset existing vLLM systemd drop-ins (recommended when standardizing unit behavior):"
echo "      sudo VLLM_RESET_OVERRIDES=true bash scripts/install.sh"
echo "  - Override smoke test timeout seconds (default: 240):"
echo "      sudo SMOKE_TEST_TIMEOUT_SECONDS=240 bash scripts/install.sh"
echo "  - Install analyst portal OS packages, npm build, Postgres schema, profile, and nginx site:"
echo "      sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh"

echo ""
if [[ ${#NON_FATAL_ISSUES[@]} -gt 0 ]]; then
    echo "Non-fatal issues encountered:"
    for issue in "${NON_FATAL_ISSUES[@]}"; do
        echo "  - $issue"
    done
else
    echo "No non-fatal issues recorded."
fi