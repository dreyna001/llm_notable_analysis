#!/usr/bin/env bash
# Apply the non-secret application and gateway settings for the two-T4
# llama.cpp demo profile. Dry-run is the default; --execute makes changes.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CONFIG_ENV="/etc/notable-analyzer/config.env"
PORTAL_ENV="/etc/notable-analyzer/portal.env"
LITELLM_CONFIG="/etc/litellm/config.yaml"
LITELLM_OVERRIDE="/etc/systemd/system/litellm.service.d/t4x2-llamacpp.conf"
PROFILE_LITELLM_CONFIG="$PROJECT_DIR/deploy/litellm/config.t4x2-llamacpp-demo.yaml.example"
PROFILE_LITELLM_DROP_IN="$PROJECT_DIR/deploy/systemd/litellm.t4x2-llamacpp.drop-in.example"
BACKUP_ROOT="/root/notable-profile-backups/t4x2-llamacpp-demo"
EXECUTE=false

usage() {
    cat <<'EOF'
Usage: apply_t4x2_llamacpp_demo_profile.sh [options]

Options:
  --execute                    Back up and apply; dry-run is the default
  --config-env PATH            Analyzer env file
  --portal-env PATH            Portal env file
  --litellm-config PATH        LiteLLM config destination
  --litellm-override PATH      LiteLLM systemd drop-in destination
  --backup-root PATH           Backup parent directory
  -h, --help                   Show this help

Only non-secret inference settings are changed. Services are not restarted.
EOF
}

err() {
    echo "ERROR: $*" >&2
    exit 1
}

require_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || err "Missing value for $option"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --execute)
            EXECUTE=true
            shift
            ;;
        --config-env)
            require_value "$1" "${2:-}"
            CONFIG_ENV="$2"
            shift 2
            ;;
        --portal-env)
            require_value "$1" "${2:-}"
            PORTAL_ENV="$2"
            shift 2
            ;;
        --litellm-config)
            require_value "$1" "${2:-}"
            LITELLM_CONFIG="$2"
            shift 2
            ;;
        --litellm-override)
            require_value "$1" "${2:-}"
            LITELLM_OVERRIDE="$2"
            shift 2
            ;;
        --backup-root)
            require_value "$1" "${2:-}"
            BACKUP_ROOT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            err "Unknown argument: $1"
            ;;
    esac
done

[[ -f "$CONFIG_ENV" ]] || err "Missing analyzer config: $CONFIG_ENV"
[[ -f "$PROFILE_LITELLM_CONFIG" ]] || err "Missing profile LiteLLM config: $PROFILE_LITELLM_CONFIG"
[[ -f "$PROFILE_LITELLM_DROP_IN" ]] || err "Missing profile LiteLLM drop-in: $PROFILE_LITELLM_DROP_IN"
command -v python3 >/dev/null 2>&1 || err "Missing required command: python3"

echo "Two-T4 llama.cpp demo profile"
echo "  Mode: $([[ "$EXECUTE" == "true" ]] && echo execute || echo dry-run)"
echo "  Analyzer config: $CONFIG_ENV"
echo "  Portal config: $PORTAL_ENV $([[ -f "$PORTAL_ENV" ]] || echo '(not present; skipped)')"
echo "  Model: gemma-4-26B-A4B-it (official QAT Q4_0 GGUF)"
echo "  Capacity: 16384 context tokens, one request at a time"
echo "  Gateway: $LITELLM_CONFIG"

if [[ "$EXECUTE" != "true" ]]; then
    echo "Dry-run only; rerun with --execute to apply."
    exit 0
fi

[[ "${EUID:-$(id -u)}" -eq 0 ]] || err "--execute must run as root"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP_ROOT"
backup_dir="$(mktemp -d "$BACKUP_ROOT/${stamp}.XXXXXX")"
chmod 0700 "$backup_dir"
cp -a -- "$CONFIG_ENV" "$backup_dir/config.env"
if [[ -f "$PORTAL_ENV" ]]; then
    cp -a -- "$PORTAL_ENV" "$backup_dir/portal.env"
fi
if [[ -e "$LITELLM_CONFIG" ]]; then
    cp -a -- "$LITELLM_CONFIG" "$backup_dir/litellm-config.yaml"
fi
if [[ -e "$LITELLM_OVERRIDE" ]]; then
    cp -a -- "$LITELLM_OVERRIDE" "$backup_dir/litellm-t4x2-override.conf"
fi

python3 - "$CONFIG_ENV" "$PORTAL_ENV" <<'PY'
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

config_path = Path(sys.argv[1])
portal_path = Path(sys.argv[2])

config_values = {
    "LLM_MODEL_NAME": "gemma-4-26B-A4B-it",
    "LLM_STRUCTURED_OUTPUT_MODE": "prompt_json",
    "LLM_MAX_TOKENS": "2048",
    "LLM_TIMEOUT": "300",
    "CASE_QA_MODEL_CONTEXT_TOKENS": "16384",
    "CASE_QA_MAX_ANSWER_TOKENS": "800",
    "CONCURRENCY_ENABLED": "false",
    "MAX_WORKERS": "1",
    "MAX_QUEUE_DEPTH": "8",
}

portal_values = {
    "LLM_MODEL_NAME": "gemma-4-26B-A4B-it",
    "LLM_TIMEOUT": "300",
    "CASE_QA_MODEL_CONTEXT_TOKENS": "16384",
    "CASE_QA_MAX_ANSWER_TOKENS": "800",
    "PORTAL_CHAT_MAX_CONCURRENCY": "1",
}

assignment = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


def upsert(path: Path, updates: dict[str, str]) -> None:
    original_stat = path.stat()
    output: list[str] = []
    written: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = assignment.match(line)
        key = match.group(1) if match else ""
        if key not in updates:
            output.append(line)
            continue
        if key not in written:
            output.append(f"{key}={updates[key]}")
            written.add(key)
    missing = [key for key in updates if key not in written]
    if missing:
        output.extend(["", "# Two-T4 llama.cpp demo profile"])
        output.extend(f"{key}={updates[key]}" for key in missing)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary_name, original_stat.st_uid, original_stat.st_gid)
        os.chmod(temporary_name, stat.S_IMODE(original_stat.st_mode))
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


upsert(config_path, config_values)
if portal_path.is_file():
    upsert(portal_path, portal_values)
PY

install -d -m 0755 "$(dirname -- "$LITELLM_CONFIG")"
install -o litellm -g litellm -m 0600 "$PROFILE_LITELLM_CONFIG" "$LITELLM_CONFIG"
install -d -m 0755 "$(dirname -- "$LITELLM_OVERRIDE")"
install -o root -g root -m 0644 "$PROFILE_LITELLM_DROP_IN" "$LITELLM_OVERRIDE"

echo "Profile applied."
echo "  Backup: $backup_dir"
echo "  Services were not restarted."
