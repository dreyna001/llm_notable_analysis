#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "$TEST_DIR/.." && pwd)"
INSTALLER="$PKG_DIR/install_llamacpp.sh"

EXPECTED_SHA="7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
EXPECTED_SIZE="2497280256"

MODEL_PATH_DEFAULT="/opt/llamacpp/models/Qwen3-4B-Q4_K_M.gguf"
HEALTH_URL="http://127.0.0.1:8000/health"
METRICS_URL="http://127.0.0.1:8000/metrics"
CHAT_URL="http://127.0.0.1:8000/v1/chat/completions"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command missing: $1"
}

run_installer() {
    if [[ $EUID -eq 0 ]]; then
        bash "$INSTALLER"
    else
        sudo bash "$INSTALLER"
    fi
}

run_as_root() {
    if [[ $EUID -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

http_status() {
    local method="$1"
    local url="$2"
    local body_file="${3:-}"
    if [[ -n "$body_file" ]]; then
        curl -s -o /dev/null -w "%{http_code}" -X "$method" "$url" -H "Content-Type: application/json" --data @"$body_file"
    else
        curl -s -o /dev/null -w "%{http_code}" -X "$method" "$url"
    fi
}

echo "[0/9] Preflight command checks..."
require_cmd curl
require_cmd sha256sum
require_cmd systemctl
require_cmd journalctl
require_cmd grep

echo "[1/9] Installer smoke test..."
run_installer

echo "[2/9] Config validation (negative) test..."
set +e
if [[ $EUID -eq 0 ]]; then
    INVALID_OUTPUT="$(LLAMA_PORT=not_a_number LLAMA_SKIP_RUNTIME_BUILD=true LLAMA_SKIP_MODEL_DOWNLOAD=true bash "$INSTALLER" 2>&1)"
else
    INVALID_OUTPUT="$(sudo env LLAMA_PORT=not_a_number LLAMA_SKIP_RUNTIME_BUILD=true LLAMA_SKIP_MODEL_DOWNLOAD=true bash "$INSTALLER" 2>&1)"
fi
INVALID_CODE=$?
set -e
[[ $INVALID_CODE -ne 0 ]] || fail "Installer unexpectedly accepted invalid LLAMA_PORT"
echo "$INVALID_OUTPUT" | grep -Eq "LLAMA_PORT must be a positive integer" || fail "Expected config validation error not found"

set +e
if [[ $EUID -eq 0 ]]; then
    ZERO_OUTPUT="$(LLAMA_PORT=0 LLAMA_SKIP_RUNTIME_BUILD=true LLAMA_SKIP_MODEL_DOWNLOAD=true bash "$INSTALLER" 2>&1)"
else
    ZERO_OUTPUT="$(sudo env LLAMA_PORT=0 LLAMA_SKIP_RUNTIME_BUILD=true LLAMA_SKIP_MODEL_DOWNLOAD=true bash "$INSTALLER" 2>&1)"
fi
ZERO_CODE=$?
set -e
[[ $ZERO_CODE -ne 0 ]] || fail "Installer unexpectedly accepted LLAMA_PORT=0"
echo "$ZERO_OUTPUT" | grep -Eq "LLAMA_PORT must be a positive integer" || fail "Expected zero-value validation error not found"

echo "[3/9] Artifact integrity test..."
MODEL_PATH="$MODEL_PATH_DEFAULT"
if [[ -f "/etc/llamacpp/llamacpp.env" ]]; then
    if [[ $EUID -eq 0 ]]; then
        # shellcheck disable=SC1091
        source /etc/llamacpp/llamacpp.env
        MODEL_PATH="${LLAMA_MODEL_PATH:-$MODEL_PATH_DEFAULT}"
    else
        MODEL_PATH_FROM_ENV="$(sudo awk -F= '$1=="LLAMA_MODEL_PATH"{print $2}' /etc/llamacpp/llamacpp.env 2>/dev/null || true)"
        MODEL_PATH="${MODEL_PATH_FROM_ENV:-$MODEL_PATH_DEFAULT}"
    fi
fi
[[ -f "$MODEL_PATH" ]] || fail "Model file missing: $MODEL_PATH"
ACTUAL_SHA="$(sha256sum "$MODEL_PATH" | awk '{print $1}')"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || fail "Model SHA mismatch: $ACTUAL_SHA"
ACTUAL_SIZE="$(stat -c '%s' "$MODEL_PATH")"
[[ "$ACTUAL_SIZE" == "$EXPECTED_SIZE" ]] || fail "Model size mismatch: $ACTUAL_SIZE"

echo "[4/9] Service startup/readiness test..."
run_as_root systemctl is-active --quiet llamacpp || fail "llamacpp service is not active"
HEALTH_CODE="$(http_status GET "$HEALTH_URL")"
[[ "$HEALTH_CODE" == "200" ]] || fail "/health did not return 200 (got $HEALTH_CODE)"

echo "[5/9] API smoke test..."
VALID_REQ="$(mktemp)"
cat >"$VALID_REQ" <<'EOF'
{
  "model": "Qwen3-4B-Q4_K_M",
  "messages": [
    {"role": "system", "content": "You are concise."},
    {"role": "user", "content": "Reply with the word ok."}
  ],
  "temperature": 0.1,
  "max_tokens": 16,
  "stream": false
}
EOF
VALID_RESP="$(mktemp)"
VALID_STATUS="$(curl -s -o "$VALID_RESP" -w "%{http_code}" -X POST "$CHAT_URL" -H "Content-Type: application/json" --data @"$VALID_REQ")"
[[ "$VALID_STATUS" =~ ^2[0-9][0-9]$ ]] || fail "Valid chat request failed with status $VALID_STATUS"
grep -Eq "\"choices\"" "$VALID_RESP" || fail "Valid chat response missing 'choices'"

echo "[6/9] API negative/error-contract test..."
INVALID_REQ="$(mktemp)"
cat >"$INVALID_REQ" <<'EOF'
{
  "bad": "payload"
}
EOF
INVALID_RESP="$(mktemp)"
INVALID_STATUS="$(curl -s -o "$INVALID_RESP" -w "%{http_code}" -X POST "$CHAT_URL" -H "Content-Type: application/json" --data @"$INVALID_REQ")"
[[ ! "$INVALID_STATUS" =~ ^2[0-9][0-9]$ ]] || fail "Invalid request unexpectedly returned success"
grep -Eq "\"error\"|\"message\"" "$INVALID_RESP" || fail "Invalid response missing machine-parseable error markers"

echo "[7/9] Observability test..."
METRICS_CODE="$(http_status GET "$METRICS_URL")"
[[ "$METRICS_CODE" == "200" ]] || fail "/metrics did not return 200 (got $METRICS_CODE)"
run_as_root journalctl -u llamacpp -n 20 --no-pager >/tmp/llamacpp_journal_tail.txt
[[ -s /tmp/llamacpp_journal_tail.txt ]] || fail "No recent journal entries found for llamacpp"

echo "[8/9] End-to-end single-consumer integration test..."
E2E_REQ="$(mktemp)"
cat >"$E2E_REQ" <<'EOF'
{
  "model": "Qwen3-4B-Q4_K_M",
  "messages": [
    {"role": "system", "content": "You are a triage assistant."},
    {"role": "user", "content": "Summarize: one suspicious login and one blocked IP."}
  ],
  "temperature": 0.1,
  "max_tokens": 64,
  "stream": false
}
EOF
E2E_RESP="$(mktemp)"
E2E_STATUS="$(curl -s -o "$E2E_RESP" -w "%{http_code}" -X POST "$CHAT_URL" -H "Content-Type: application/json" --data @"$E2E_REQ")"
[[ "$E2E_STATUS" =~ ^2[0-9][0-9]$ ]] || fail "E2E request failed with status $E2E_STATUS"
grep -Eq "\"choices\"" "$E2E_RESP" || fail "E2E response missing choices"
grep -Eq "\"content\"" "$E2E_RESP" || fail "E2E response missing assistant content"

rm -f "$VALID_REQ" "$VALID_RESP" "$INVALID_REQ" "$INVALID_RESP" "$E2E_REQ" "$E2E_RESP" /tmp/llamacpp_journal_tail.txt

echo "[9/9] Integration suite complete."
echo "Integration checks passed."
