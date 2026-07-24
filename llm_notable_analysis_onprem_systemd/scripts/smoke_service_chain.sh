#!/usr/bin/env bash
# Verify the local vLLM -> LiteLLM -> notable-analyzer service chain.
set -euo pipefail
IFS=$'\n\t'

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VLLM_HEALTH_URL="${VLLM_HEALTH_URL:-http://127.0.0.1:8000/health}"
LITELLM_MODELS_URL="${LITELLM_MODELS_URL:-http://127.0.0.1:4000/v1/models}"
HTTP_TIMEOUT_SECONDS="${HTTP_TIMEOUT_SECONDS:-30}"
REPORT_TIMEOUT_SECONDS="${REPORT_TIMEOUT_SECONDS:-240}"
SKIP_FILE_DROP="${SKIP_FILE_DROP:-false}"
ALLOW_NON_LOOPBACK_HTTP="${ALLOW_NON_LOOPBACK_HTTP:-false}"

usage() {
    cat <<'EOF'
Usage: smoke_service_chain.sh [options]

Options:
  --config-env PATH       Analyzer config.env path
  --skip-file-drop        Only test vLLM and LiteLLM HTTP paths
  -h, --help              Show this help

Environment overrides:
  CONFIG_ENV, VLLM_HEALTH_URL, LITELLM_MODELS_URL,
  HTTP_TIMEOUT_SECONDS, REPORT_TIMEOUT_SECONDS, SKIP_FILE_DROP,
  ALLOW_NON_LOOPBACK_HTTP
EOF
}

err() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "  $*"
}

warn() {
    echo "WARN: $*" >&2
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || err "Missing required command: $1"
}

require_arg_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || err "Missing value for $option"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config-env)
            require_arg_value "$1" "${2:-}"
            CONFIG_ENV="$2"
            shift 2
            ;;
        --skip-file-drop)
            SKIP_FILE_DROP="true"
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

require_command curl
require_command "$PYTHON_BIN"
[[ -f "$CONFIG_ENV" ]] || err "Missing config file: $CONFIG_ENV"

read_config() {
    local key="$1"
    local fallback="$2"
    "$PYTHON_BIN" - "$CONFIG_ENV" "$key" "$fallback" <<'PY'
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
target_key = sys.argv[2]
fallback = sys.argv[3]

for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    try:
        tokens = shlex.split(stripped, comments=True, posix=True)
    except ValueError as exc:
        raise SystemExit(f"Invalid config.env line {line_number}: {exc}") from exc
    if tokens and tokens[0] == "export":
        tokens = tokens[1:]
    if len(tokens) != 1 or "=" not in tokens[0]:
        raise SystemExit(f"Invalid config.env line {line_number}: expected KEY=VALUE.")
    key, value = tokens[0].split("=", 1)
    if not key.isidentifier():
        raise SystemExit(f"Invalid config.env line {line_number}: invalid key {key!r}.")
    if key == target_key:
        print(value)
        raise SystemExit(0)
print(fallback)
PY
}

LLM_API_URL="$(read_config LLM_API_URL "http://127.0.0.1:4000/v1/chat/completions")"
LLM_MODEL_NAME="$(read_config LLM_MODEL_NAME "gemma-4-31B-it")"
LLM_API_TOKEN="$(read_config LLM_API_TOKEN "")"
INCOMING_DIR="$(read_config INCOMING_DIR "/var/notables/incoming")"
REPORT_DIR="$(read_config REPORT_DIR "/var/notables/reports")"

if [[ "$LLM_API_URL" != http://127.0.0.1:* && "$LLM_API_URL" != http://localhost:* && "$LLM_API_URL" != https://* ]]; then
    if [[ "$ALLOW_NON_LOOPBACK_HTTP" == "true" ]]; then
        warn "LLM_API_URL is non-loopback HTTP; continuing because ALLOW_NON_LOOPBACK_HTTP=true."
    else
        err "LLM_API_URL is non-loopback HTTP. Use loopback, HTTPS, or set ALLOW_NON_LOOPBACK_HTTP=true for an explicit lab exception."
    fi
fi

if command -v systemctl >/dev/null 2>&1; then
    for unit in vllm litellm notable-analyzer; do
        if systemctl is-active --quiet "$unit"; then
            info "$unit.service is active"
        else
            warn "$unit.service is not active"
        fi
    done
fi

info "Checking vLLM health at $VLLM_HEALTH_URL"
curl -fsS --max-time "$HTTP_TIMEOUT_SECONDS" "$VLLM_HEALTH_URL" >/dev/null

tmpdir="$(mktemp -d)"
cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT

litellm_curl_args=(-fsS --max-time "$HTTP_TIMEOUT_SECONDS")
auth_header_file=""
if [[ -n "$LLM_API_TOKEN" ]]; then
    auth_header_file="$tmpdir/auth_header.txt"
    umask 077
    printf 'Authorization: Bearer %s\n' "$LLM_API_TOKEN" > "$auth_header_file"
    litellm_curl_args+=(-H "@$auth_header_file")
fi

info "Checking LiteLLM models endpoint at $LITELLM_MODELS_URL"
curl "${litellm_curl_args[@]}" "$LITELLM_MODELS_URL" >/dev/null

chat_payload="$tmpdir/chat_payload.json"
chat_response="$tmpdir/chat_response.json"
"$PYTHON_BIN" - "$LLM_MODEL_NAME" > "$chat_payload" <<'PY'
import json
import sys

model = sys.argv[1]
print(
    json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "Respond with OK for a service-chain smoke test.",
                }
            ],
            "max_tokens": 16,
            "temperature": 0,
        }
    )
)
PY

chat_curl_args=("${litellm_curl_args[@]}" -H "Content-Type: application/json")

info "Checking LiteLLM chat completion for model $LLM_MODEL_NAME"
curl "${chat_curl_args[@]}" -d @"$chat_payload" "$LLM_API_URL" > "$chat_response"
"$PYTHON_BIN" - "$chat_response" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("error"):
    raise SystemExit(f"chat completion returned error: {payload.get('error')}")
choices = payload.get("choices")
if not isinstance(choices, list) or not choices:
    raise SystemExit("chat completion response did not include choices")
message = choices[0].get("message") if isinstance(choices[0], dict) else None
content = message.get("content") if isinstance(message, dict) else None
if not isinstance(content, str) or not content.strip():
    raise SystemExit("chat completion response did not include non-empty message content")
PY

if [[ "$SKIP_FILE_DROP" == "true" ]]; then
    info "SKIP_FILE_DROP=true; analyzer file-drop smoke skipped"
    exit 0
fi

[[ -d "$INCOMING_DIR" ]] || err "INCOMING_DIR does not exist: $INCOMING_DIR"
[[ -d "$REPORT_DIR" ]] || err "REPORT_DIR does not exist: $REPORT_DIR"

smoke_id="service-chain-smoke-$(date +%s)"
payload_file="$INCOMING_DIR/$smoke_id.json"
report_file="$REPORT_DIR/$smoke_id.md"
tmp_payload="$INCOMING_DIR/.${smoke_id}.json.tmp"

info "Dropping analyzer smoke payload: $payload_file"
cat > "$tmp_payload" <<EOF
{
  "notable_id": "$smoke_id",
  "search_name": "Service Chain Smoke",
  "severity": "low",
  "description": "Benign smoke test alert for local vLLM to LiteLLM to analyzer validation.",
  "raw": "PowerShell EncodedCommand service-chain smoke test; no real incident."
}
EOF

chmod 660 "$tmp_payload" 2>/dev/null || true
if [[ "$(id -u)" == "0" ]] && id notable-analyzer >/dev/null 2>&1; then
    chown notable-analyzer:notable-analyzer "$tmp_payload" 2>/dev/null || true
fi
mv "$tmp_payload" "$payload_file"

info "Waiting for analyzer report: $report_file"
start_epoch="$(date +%s)"
while [[ ! -f "$report_file" ]]; do
    now_epoch="$(date +%s)"
    if (( now_epoch - start_epoch >= REPORT_TIMEOUT_SECONDS )); then
        err "Timed out waiting for analyzer report. Check: journalctl -u notable-analyzer -n 200 --no-pager"
    fi
    sleep 2
done

info "Service-chain smoke passed: $report_file"
