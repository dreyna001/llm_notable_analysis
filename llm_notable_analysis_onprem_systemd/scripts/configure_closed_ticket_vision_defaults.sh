#!/usr/bin/env bash
# Enable closed-ticket image description defaults in analyzer config.env.
# Vision API base, model, and key default from LLM_* at runtime when left empty.
set -euo pipefail
IFS=$'\n\t'

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"

usage() {
    cat <<'EOF'
Usage: configure_closed_ticket_vision_defaults.sh [options]

Upserts customer-default closed-ticket vision keys in analyzer config.env:
  CLOSED_TICKET_VISION_ENABLED=true
  CLOSED_TICKET_VISION_TIMEOUT_SECONDS=60 (only when key is missing)

Does not overwrite CLOSED_TICKET_VISION_API_BASE, _MODEL, or _API_KEY when set.

Options:
  --config-env PATH   Analyzer config.env (default: /etc/notable-analyzer/config.env)
  --disable           Set CLOSED_TICKET_VISION_ENABLED=false
  -h, --help          Show this help
EOF
}

err() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "  $*"
}

require_arg_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || err "Missing value for $option"
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

env_has_key() {
    local file="$1"
    local key="$2"
    [[ -f "$file" ]] && grep -q "^${key}=" "$file"
}

ENABLE="true"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config-env)
            require_arg_value "$1" "${2:-}"
            CONFIG_ENV="$2"
            shift 2
            ;;
        --disable)
            ENABLE="false"
            shift
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

[[ -f "$CONFIG_ENV" ]] || err "Missing config file: $CONFIG_ENV"

upsert_env_value "$CONFIG_ENV" "CLOSED_TICKET_VISION_ENABLED" "$ENABLE"
if [[ "$ENABLE" == "true" ]] && ! env_has_key "$CONFIG_ENV" "CLOSED_TICKET_VISION_TIMEOUT_SECONDS"; then
    upsert_env_value "$CONFIG_ENV" "CLOSED_TICKET_VISION_TIMEOUT_SECONDS" "60"
fi

info "Updated closed-ticket vision defaults in $CONFIG_ENV (CLOSED_TICKET_VISION_ENABLED=$ENABLE)"
if [[ "$ENABLE" == "true" ]]; then
    info "When API base/model/key are empty, analyzer uses LLM_API_URL, LLM_MODEL_NAME, LLM_API_TOKEN"
    info "Restart notable-analyzer after changing config: sudo systemctl restart notable-analyzer"
    info "Validate multimodal chat on LiteLLM before relying on attachment indexing"
fi
