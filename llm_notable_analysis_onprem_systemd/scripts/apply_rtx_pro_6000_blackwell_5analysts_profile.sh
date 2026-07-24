#!/usr/bin/env bash
# Apply the non-secret runtime settings for the customer RTX PRO 6000
# Blackwell + Intel Core Ultra 9 285K + five-analyst deployment.
#
# This script intentionally:
#   - preserves DSNs, tokens, proxy secrets, credentials, and integrations
#   - updates only the profile-owned keys listed in the Python mappings below
#   - collapses duplicate profile-owned keys to one effective value
#   - backs up every changed live file before writing
#   - installs the paired vLLM drop-in
#   - does not restart or reload services
#
# Dry-run is the default. Use --execute as root to make changes.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CONFIG_ENV="/etc/notable-analyzer/config.env"
PORTAL_ENV="/etc/notable-analyzer/portal.env"
VLLM_OVERRIDE="/etc/systemd/system/vllm.service.d/override.conf"
PROFILE_DROP_IN="$PROJECT_DIR/deploy/systemd/vllm.rtx-pro-6000-blackwell-5analysts.drop-in.example"
BACKUP_ROOT="/root/notable-profile-backups"
EXECUTE=false

usage() {
    cat <<'EOF'
Usage: apply_rtx_pro_6000_blackwell_5analysts_profile.sh [options]

Options:
  --execute              Back up and apply the profile; dry-run is the default
  --config-env PATH      Analyzer env file
  --portal-env PATH      Portal env file
  --vllm-override PATH   vLLM systemd drop-in destination
  --backup-root PATH     Backup parent directory
  -h, --help             Show this help

The script preserves all secret values and does not restart services.
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
        --vllm-override)
            require_value "$1" "${2:-}"
            VLLM_OVERRIDE="$2"
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
[[ -f "$PORTAL_ENV" ]] || err "Missing portal config: $PORTAL_ENV"
[[ -f "$PROFILE_DROP_IN" ]] || err "Missing profile drop-in: $PROFILE_DROP_IN"
command -v python3 >/dev/null 2>&1 || err "Missing required command: python3"

echo "RTX PRO 6000 Blackwell customer profile"
echo "  Mode: $([[ "$EXECUTE" == "true" ]] && echo execute || echo dry-run)"
echo "  Analyzer config: $CONFIG_ENV"
echo "  Portal config: $PORTAL_ENV"
echo "  vLLM override: $VLLM_OVERRIDE"
echo "  Analyzer: sequential worker, queue depth 8"
echo "  Portal: 4 concurrent chats, 25 sessions/user, 30 messages/session"
echo "  Model contract: gemma-4-31B-it, 32768 context tokens"
echo "  vLLM: 0.85 GPU memory, 4 sequences, bfloat16, eager mode, CUDA 13.3"

if [[ "$EXECUTE" != "true" ]]; then
    echo "Dry-run only; rerun with --execute to apply."
    exit 0
fi

[[ "${EUID:-$(id -u)}" -eq 0 ]] || err "--execute must run as root"

python3 - "$CONFIG_ENV" "$PORTAL_ENV" <<'PY'
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
portal_path = Path(sys.argv[2])

required_secrets = {
    config_path: ("CASE_POSTGRES_DSN", "LLM_API_TOKEN", "PORTAL_PROXY_SECRET"),
    portal_path: ("CASE_POSTGRES_DSN", "LLM_API_TOKEN", "PORTAL_PROXY_SECRET"),
}

parsed_values = {}
for path, keys in required_secrets.items():
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", raw_line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    missing = [key for key in keys if not values.get(key)]
    if missing:
        raise SystemExit(
            f"ERROR: {path} has empty or missing required live values: "
            + ", ".join(missing)
        )
    parsed_values[path] = values

for shared_key in ("LLM_API_TOKEN", "PORTAL_PROXY_SECRET"):
    if parsed_values[config_path][shared_key] != parsed_values[portal_path][shared_key]:
        raise SystemExit(
            f"ERROR: {shared_key} must match in {config_path} and {portal_path}"
        )
PY

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$BACKUP_ROOT/$stamp"
install -d -m 0700 "$backup_dir"
cp -a -- "$CONFIG_ENV" "$backup_dir/config.env"
cp -a -- "$PORTAL_ENV" "$backup_dir/portal.env"
if [[ -e "$VLLM_OVERRIDE" ]]; then
    cp -a -- "$VLLM_OVERRIDE" "$backup_dir/vllm-override.conf"
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
    "CAPABILITY_PROFILES": "core,analyst_portal",
    "INGEST_MODE": "file_drop",
    "INCOMING_DIR": "/var/notables/incoming",
    "PROCESSED_DIR": "/var/notables/processed",
    "QUARANTINE_DIR": "/var/notables/quarantine",
    "REPORT_DIR": "/var/notables/reports",
    "ARCHIVE_DIR": "/var/notables/archive",
    "POLL_INTERVAL": "5",
    "MAX_INPUT_FILE_BYTES": "4194304",
    "LLM_API_URL": "http://127.0.0.1:4000/v1/chat/completions",
    "LLM_MODEL_NAME": "gemma-4-31B-it",
    "LLM_STRUCTURED_OUTPUT_MODE": "prompt_json",
    "LLM_MAX_TOKENS": "4096",
    "LLM_TIMEOUT": "240",
    "CASE_QA_CHAT_HISTORY_ENABLED": "true",
    "CASE_QA_CHAT_HISTORY_RETENTION_DAYS": "30",
    "CASE_QA_MAX_MESSAGES_PER_SESSION": "30",
    "CASE_QA_MAX_SESSIONS_PER_USER": "25",
    "CASE_QA_MODEL_CONTEXT_TOKENS": "32768",
    "CONCURRENCY_ENABLED": "false",
    "MAX_WORKERS": "1",
    "MAX_QUEUE_DEPTH": "8",
}

portal_values = {
    "CAPABILITY_PROFILES": "core,analyst_portal",
    "CASE_POSTGRES_SCHEMA": "notable_cases",
    "CASE_POSTGRES_STATEMENT_TIMEOUT_MS": "5000",
    "CASE_RETENTION_DAYS": "30",
    "CASE_RETENTION_DELETE_BATCH_SIZE": "500",
    "CASE_QA_ENABLED": "true",
    "CASE_QA_CHAT_HISTORY_ENABLED": "true",
    "CASE_QA_CHAT_HISTORY_RETENTION_DAYS": "30",
    "CASE_QA_MAX_MESSAGES_PER_SESSION": "30",
    "CASE_QA_MAX_SESSIONS_PER_USER": "25",
    "CASE_QA_MAX_CHUNKS_PER_LANE": "6",
    "CASE_QA_MAX_TOTAL_CHUNKS": "18",
    "CASE_QA_CONTEXT_BUDGET_CHARS": "12000",
    "CASE_QA_MAX_QUESTION_CHARS": "2000",
    "CASE_QA_MAX_ANSWER_TOKENS": "800",
    "CASE_QA_MODEL_CONTEXT_TOKENS": "32768",
    "CASE_QA_EMBEDDING_MODEL": "mixedbread-ai/mxbai-embed-large-v1",
    "CASE_QA_VECTOR_DIMENSIONS": "1024",
    "CASE_QA_MAX_STORED_MESSAGE_BYTES": "4000",
    "CASE_QA_GENERAL_KNOWLEDGE_ENABLED": "true",
    "LLM_API_URL": "http://127.0.0.1:4000/v1/chat/completions",
    "LLM_MODEL_NAME": "gemma-4-31B-it",
    "LLM_TIMEOUT": "240",
    "PORTAL_BIND_HOST": "127.0.0.1",
    "PORTAL_PORT": "8080",
    "PORTAL_PAGE_SIZE": "50",
    "PORTAL_CHAT_MAX_CONCURRENCY": "4",
    "PORTAL_TRUSTED_USER_HEADER": "X-Forwarded-User",
    "PORTAL_ALLOW_NON_LOOPBACK_BIND": "false",
    "PORTAL_PROXY_SECRET_HEADER": "X-Notable-Portal-Proxy-Secret",
}

assignment = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


def upsert(path: Path, updates: dict[str, str]) -> None:
    original_stat = path.stat()
    output = []
    written = set()
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
        output.extend(["", "# RTX PRO 6000 Blackwell customer profile"])
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
upsert(portal_path, portal_values)
PY

install -d -m 0755 "$(dirname -- "$VLLM_OVERRIDE")"
install -o root -g root -m 0644 "$PROFILE_DROP_IN" "$VLLM_OVERRIDE"

echo "Profile applied."
echo "  Backup: $backup_dir"
echo "  Services were not restarted."
