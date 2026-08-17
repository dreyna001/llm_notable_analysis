#!/usr/bin/env bash
# Read-only audit for the customer on-prem target host.
#
# The default run does not restart services, modify configuration, write test
# payloads, fetch Git remotes, or contact external integrations. Secret values
# are never printed. Use --run-smoke only with operator approval because the
# existing service-chain smoke writes a synthetic file-drop payload and report.
set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="/opt/src/llm_notable_analysis"
INSTALL_DIR="/opt/notable-analyzer"
CONFIG_ENV="/etc/notable-analyzer/config.env"
PORTAL_ENV="/etc/notable-analyzer/portal.env"
VLLM_OVERRIDE="/etc/systemd/system/vllm.service.d/override.conf"
NGINX_SITE="/etc/nginx/conf.d/notable-portal.conf"
ANALYZER_VENV="/opt/notable-analyzer/venv"
RUN_SMOKE=false

pass_count=0
fail_count=0
unknown_count=0
skip_count=0

usage() {
    cat <<'EOF'
Usage: audit_customer_target_host.sh [options]

Options:
  --repo-root PATH       Monorepo checkout (default: /opt/src/llm_notable_analysis)
  --install-dir PATH     Installed runtime (default: /opt/notable-analyzer)
  --config-env PATH      Analyzer env file
  --portal-env PATH      Portal env file
  --vllm-override PATH   Installed vLLM systemd drop-in
  --nginx-site PATH      Installed portal nginx site
  --analyzer-venv PATH   Analyzer virtualenv
  --run-smoke            Run the mutating synthetic file-drop smoke at the end
  -h, --help             Show this help

Run as root to inspect protected configuration and database state. The default
audit is read-only and does not print DSNs, tokens, passwords, or proxy secrets.

Exit codes:
  0  Audit completed with no FAIL results
  1  One or more FAIL results
  2  Invalid invocation or required local tooling missing
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 2
}

require_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || die "Missing value for $option"
}

record() {
    local status="$1"
    local check_id="$2"
    local message="$3"
    case "$status" in
        PASS) pass_count=$((pass_count + 1)) ;;
        FAIL) fail_count=$((fail_count + 1)) ;;
        UNKNOWN) unknown_count=$((unknown_count + 1)) ;;
        SKIP) skip_count=$((skip_count + 1)) ;;
        *) die "Internal error: unsupported status $status" ;;
    esac
    printf '%-7s %-28s %s\n' "$status" "$check_id" "$message"
}

section() {
    printf '\n[%s]\n' "$1"
}

read_config() {
    local path="$1"
    local key="$2"
    local fallback="${3:-}"
    python3 - "$path" "$key" "$fallback" <<'PY'
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
target = sys.argv[2]
fallback = sys.argv[3]
if not path.is_file():
    print(fallback)
    raise SystemExit(0)
for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        continue
    try:
        tokens = shlex.split(stripped, comments=True, posix=True)
    except ValueError as exc:
        raise SystemExit(f"invalid env syntax at {path}:{line_number}: {exc}") from exc
    if tokens and tokens[0] == "export":
        tokens = tokens[1:]
    if len(tokens) != 1 or "=" not in tokens[0]:
        continue
    key, value = tokens[0].split("=", 1)
    if key == target:
        print(value)
        raise SystemExit(0)
print(fallback)
PY
}

secret_is_set() {
    local path="$1"
    local key="$2"
    local value
    value="$(read_config "$path" "$key" "")"
    [[ -n "$value" && "$value" != "<generate-a-random-shared-secret>" ]]
}

resolve_checkout() {
    if [[ -d "$REPO_ROOT/llm_notable_analysis_onprem_systemd" ]]; then
        CHECKOUT_DIR="$REPO_ROOT/llm_notable_analysis_onprem_systemd"
        GIT_ROOT="$REPO_ROOT"
    elif [[ -d "$REPO_ROOT/src/llm_notable_analysis_onprem_systemd" ]]; then
        CHECKOUT_DIR="$REPO_ROOT"
        GIT_ROOT="$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
    else
        CHECKOUT_DIR=""
        GIT_ROOT=""
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-root)
            require_value "$1" "${2:-}"
            REPO_ROOT="$2"
            shift 2
            ;;
        --install-dir)
            require_value "$1" "${2:-}"
            INSTALL_DIR="$2"
            shift 2
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
        --nginx-site)
            require_value "$1" "${2:-}"
            NGINX_SITE="$2"
            shift 2
            ;;
        --analyzer-venv)
            require_value "$1" "${2:-}"
            ANALYZER_VENV="$2"
            shift 2
            ;;
        --run-smoke)
            RUN_SMOKE=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
done

command -v python3 >/dev/null 2>&1 || die "python3 is required"
resolve_checkout

echo "Customer target-host audit"
echo "UTC time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Host: $(hostname -f 2>/dev/null || hostname)"
echo "Mode: $([[ "$RUN_SMOKE" == "true" ]] && echo 'read-only checks plus approved synthetic smoke' || echo 'read-only')"

section "Git checkout and installed runtime"
if [[ -n "$GIT_ROOT" && -d "$GIT_ROOT/.git" ]]; then
    checkout_commit="$(git -C "$GIT_ROOT" rev-parse HEAD)"
    checkout_short="$(git -C "$GIT_ROOT" rev-parse --short HEAD)"
    checkout_branch="$(git -C "$GIT_ROOT" branch --show-current)"
    record PASS git-checkout "commit=$checkout_short branch=${checkout_branch:-detached}"
    if [[ -z "$(git -C "$GIT_ROOT" status --porcelain)" ]]; then
        record PASS git-clean "checkout is clean"
    else
        record FAIL git-clean "checkout has modified or untracked files"
    fi
    upstream="$(git -C "$GIT_ROOT" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || true)"
    if [[ -n "$upstream" ]]; then
        read -r behind ahead < <(git -C "$GIT_ROOT" rev-list --left-right --count "$upstream...HEAD")
        if [[ "$behind" == "0" && "$ahead" == "0" ]]; then
            record PASS git-upstream "matches locally known $upstream; no network fetch performed"
        else
            record UNKNOWN git-upstream "locally known $upstream: behind=$behind ahead=$ahead; run git fetch to prove remote currency"
        fi
    else
        record UNKNOWN git-upstream "no upstream configured"
    fi
else
    checkout_commit=""
    record FAIL git-checkout "Git checkout not found under $REPO_ROOT"
fi

if [[ -n "$CHECKOUT_DIR" && -d "$INSTALL_DIR/src/llm_notable_analysis_onprem_systemd" ]]; then
    diff_output="$(diff -qr \
        --exclude='__pycache__' --exclude='*.pyc' \
        "$CHECKOUT_DIR/src/llm_notable_analysis_onprem_systemd" \
        "$INSTALL_DIR/src/llm_notable_analysis_onprem_systemd" 2>&1 || true)"
    if [[ -z "$diff_output" ]]; then
        record PASS runtime-source "installed source matches checkout${checkout_commit:+ at ${checkout_commit:0:12}}"
    else
        diff_count="$(printf '%s\n' "$diff_output" | sed '/^$/d' | wc -l)"
        record FAIL runtime-source "installed source differs from checkout ($diff_count differences)"
    fi
    metadata_match=true
    for name in pyproject.toml requirements.txt; do
        if [[ ! -f "$CHECKOUT_DIR/$name" || ! -f "$INSTALL_DIR/$name" ]] \
            || ! cmp -s "$CHECKOUT_DIR/$name" "$INSTALL_DIR/$name"; then
            metadata_match=false
        fi
    done
    if [[ "$metadata_match" == "true" ]]; then
        record PASS runtime-metadata "installed pyproject and requirements match checkout"
    else
        record FAIL runtime-metadata "installed pyproject or requirements differ from checkout"
    fi
    record UNKNOWN runtime-commit "no immutable installed commit marker; source equality is current-state evidence only"
else
    record FAIL runtime-source "checkout source or installed source tree is missing"
    record UNKNOWN runtime-commit "cannot infer installed revision"
fi

section "Services and profile result"
if command -v systemctl >/dev/null 2>&1; then
    for unit in postgresql vllm litellm notable-analyzer notable-portal nginx; do
        if systemctl is-active --quiet "$unit"; then
            record PASS "service-$unit" "$unit is active"
        else
            record FAIL "service-$unit" "$unit is not active"
        fi
    done
else
    record SKIP services "systemctl is unavailable"
fi

for path in "$CONFIG_ENV" "$PORTAL_ENV"; do
    if [[ -r "$path" ]]; then
        record PASS "env-$(basename "$path")" "$path is readable"
    elif [[ -e "$path" ]]; then
        record FAIL "env-$(basename "$path")" "$path exists but is unreadable; rerun as root"
    else
        record FAIL "env-$(basename "$path")" "$path is missing"
    fi
done

if [[ -r "$CONFIG_ENV" && -r "$PORTAL_ENV" ]]; then
    profile_result="$(python3 - "$CONFIG_ENV" "$PORTAL_ENV" <<'PY'
import shlex
import sys
from pathlib import Path

def env(path: str) -> dict[str, str]:
    values = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
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

analyzer = env(sys.argv[1])
portal = env(sys.argv[2])
expected_analyzer = {
    "LLM_API_URL": "http://127.0.0.1:4000/v1/chat/completions",
    "LLM_MODEL_NAME": "gemma-4-31B-it",
    "LLM_STRUCTURED_OUTPUT_MODE": "prompt_json",
    "LLM_MAX_TOKENS": "4096",
    "LLM_TIMEOUT": "240",
    "CASE_QA_MODEL_CONTEXT_TOKENS": "32768",
    "CONCURRENCY_ENABLED": "false",
    "MAX_WORKERS": "1",
    "MAX_QUEUE_DEPTH": "8",
}
expected_portal = {
    "CASE_QA_MODEL_CONTEXT_TOKENS": "32768",
    "PORTAL_BIND_HOST": "127.0.0.1",
    "PORTAL_PORT": "8080",
    "PORTAL_CHAT_MAX_CONCURRENCY": "4",
    "PORTAL_ALLOW_NON_LOOPBACK_BIND": "false",
}
mismatches = [key for key, value in expected_analyzer.items() if analyzer.get(key) != value]
mismatches += [f"portal:{key}" for key, value in expected_portal.items() if portal.get(key) != value]
profiles = {item.strip() for item in analyzer.get("CAPABILITY_PROFILES", "").replace(";", ",").split(",") if item.strip()}
missing_profiles = sorted({"core", "rag", "analyst_portal"} - profiles)
print(",".join(mismatches))
print(",".join(missing_profiles))
PY
)"
    profile_mismatches="$(printf '%s\n' "$profile_result" | sed -n '1p')"
    missing_profiles="$(printf '%s\n' "$profile_result" | sed -n '2p')"
    if [[ -z "$profile_mismatches" ]]; then
        record PASS rtx-env-result "live non-secret RTX tuning matches the applicator result"
    else
        record FAIL rtx-env-result "mismatched keys: $profile_mismatches"
    fi
    if [[ -z "$missing_profiles" ]]; then
        record PASS customer-profiles "analyzer includes core, rag, and analyst_portal"
    else
        record FAIL customer-profiles "missing profiles: $missing_profiles"
    fi
    record UNKNOWN rtx-applicator-history "result can be checked, but execution of the applicator cannot be historically proven"
else
    record SKIP rtx-env-result "env files are not readable"
    record SKIP customer-profiles "env files are not readable"
fi

profile_drop_in="$CHECKOUT_DIR/deploy/systemd/vllm.rtx-pro-6000-blackwell-5analysts.drop-in.example"
if [[ -n "$CHECKOUT_DIR" && -f "$profile_drop_in" && -f "$VLLM_OVERRIDE" ]]; then
    if cmp -s "$profile_drop_in" "$VLLM_OVERRIDE"; then
        record PASS vllm-profile "installed vLLM override exactly matches the checkout profile"
    else
        record FAIL vllm-profile "installed vLLM override differs from the checkout profile"
    fi
elif [[ ! -f "$VLLM_OVERRIDE" ]]; then
    record FAIL vllm-profile "$VLLM_OVERRIDE is missing"
else
    record SKIP vllm-profile "checkout profile is unavailable"
fi

section "Granite models, image ingest, and vector migration"
if [[ -r "$CONFIG_ENV" && -r "$PORTAL_ENV" ]]; then
    granite_result="$(python3 - "$CONFIG_ENV" "$PORTAL_ENV" <<'PY'
import shlex
import sys
from pathlib import Path

def env(path: str) -> dict[str, str]:
    result = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
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
            result[key] = value
    return result

expected = {
    "RAG_EMBEDDING_MODEL": "ibm-granite/granite-embedding-english-r2",
    "RAG_RERANK_MODEL": "ibm-granite/granite-embedding-reranker-english-r2",
    "RAG_VECTOR_DIMENSIONS": "768",
    "CASE_QA_VECTOR_DIMENSIONS": "768",
}
for label, path in (("analyzer", sys.argv[1]), ("portal", sys.argv[2])):
    values = env(path)
    bad = [key for key, value in expected.items() if values.get(key) != value]
    print(f"{label}|{','.join(bad)}")
PY
)"
    while IFS='|' read -r label bad; do
        if [[ -z "$bad" ]]; then
            record PASS "granite-$label-env" "$label Granite model IDs and 768 dimensions are configured"
        else
            record FAIL "granite-$label-env" "mismatched or missing keys: $bad"
        fi
    done <<<"$granite_result"

    hf_home="$(read_config "$CONFIG_ENV" HF_HOME "/var/notables/cache/huggingface")"
    st_home="$(read_config "$CONFIG_ENV" SENTENCE_TRANSFORMERS_HOME "/var/notables/cache/sentence-transformers")"
    for model in \
        "ibm-granite/granite-embedding-english-r2" \
        "ibm-granite/granite-embedding-reranker-english-r2"; do
        cache_name="models--${model//\//--}"
        if find "$hf_home/hub/$cache_name/snapshots" "$st_home/hub/$cache_name/snapshots" \
            -type f -name config.json -print -quit 2>/dev/null | grep -q .; then
            record PASS "model-$(basename "$model")" "staged model config found in an approved local cache"
        else
            record FAIL "model-$(basename "$model")" "no staged model config found in configured caches"
        fi
    done
else
    record SKIP granite-env "env files are not readable"
fi

if [[ -x "$ANALYZER_VENV/bin/python" ]]; then
    image_result="$($ANALYZER_VENV/bin/python - <<'PY'
missing = []
for module in ("docx", "PIL", "pypdfium2"):
    try:
        __import__(module)
    except Exception:
        missing.append(module)
print(",".join(missing))
PY
)"
    if [[ -z "$image_result" ]] && command -v tesseract >/dev/null 2>&1; then
        record PASS image-prerequisites "Pillow, pypdfium2, python-docx, and tesseract are installed"
    else
        missing_text="$image_result"
        command -v tesseract >/dev/null 2>&1 || missing_text="${missing_text:+$missing_text,}tesseract"
        record FAIL image-prerequisites "missing: $missing_text"
    fi
else
    record FAIL image-prerequisites "analyzer Python is missing: $ANALYZER_VENV/bin/python"
fi

if [[ -x "$ANALYZER_VENV/bin/python" && -r "$CONFIG_ENV" ]]; then
    db_result="$($ANALYZER_VENV/bin/python - "$CONFIG_ENV" <<'PY'
import shlex
import sys
from pathlib import Path

try:
    import psycopg
    from psycopg import sql
except Exception as exc:
    print(f"ERROR|driver|psycopg unavailable: {type(exc).__name__}")
    raise SystemExit(0)

def env(path: Path) -> dict[str, str]:
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
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

values = env(Path(sys.argv[1]))
dsn = values.get("RAG_POSTGRES_DSN") or values.get("CASE_POSTGRES_DSN")
if not dsn:
    print("ERROR|connection|RAG_POSTGRES_DSN and CASE_POSTGRES_DSN are empty")
    raise SystemExit(0)

tables = [
    ("general-kb", values.get("RAG_POSTGRES_SCHEMA", "notable_rag"), values.get("RAG_POSTGRES_CHUNKS_TABLE", "kb_chunks")),
    ("spl-kb", values.get("RAG_POSTGRES_SCHEMA", "notable_rag"), values.get("SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE", "spl_query_chunks")),
    ("case-chunks", values.get("CASE_POSTGRES_SCHEMA", "notable_cases"), "case_chunks"),
    ("closed-tickets", values.get("CLOSED_TICKET_POSTGRES_SCHEMA", "notable_closed_tickets"), values.get("CLOSED_TICKET_POSTGRES_CHUNKS_TABLE", "ticket_chunks")),
]
try:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            for label, schema, table in tables:
                try:
                    cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
                    count = cur.fetchone()[0]
                    cur.execute(
                        """
                        SELECT format_type(a.atttypid, a.atttypmod)
                        FROM pg_attribute a
                        JOIN pg_class c ON c.oid = a.attrelid
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = %s AND c.relname = %s
                          AND a.attname = 'embedding' AND NOT a.attisdropped
                        """,
                        (schema, table),
                    )
                    row = cur.fetchone()
                    vector_type = row[0] if row else "no-embedding-column"
                    print(f"TABLE|{label}|{count}|{vector_type}")
                except Exception as exc:
                    conn.rollback()
                    print(f"ERROR|{label}|{type(exc).__name__}")
except Exception as exc:
    print(f"ERROR|connection|{type(exc).__name__}")
PY
)"
    while IFS='|' read -r kind label value detail; do
        case "$kind" in
            TABLE)
                if [[ "$detail" == "vector(768)" ]]; then
                    record PASS "db-$label-vector" "$label embedding column is vector(768)"
                else
                    record FAIL "db-$label-vector" "$label embedding column is $detail"
                fi
                if [[ "$value" =~ ^[0-9]+$ ]] && (( value > 0 )); then
                    record PASS "db-$label-content" "$label contains $value rows"
                else
                    record FAIL "db-$label-content" "$label contains 0 rows"
                fi
                ;;
            ERROR)
                record FAIL "db-$label" "database check failed: $value"
                ;;
        esac
    done <<<"$db_result"
else
    record SKIP database "analyzer Python or analyzer env is unavailable"
fi

section "Portal network and authentication"
portal_bind="$(read_config "$PORTAL_ENV" PORTAL_BIND_HOST "" 2>/dev/null || true)"
if [[ "$portal_bind" == "127.0.0.1" || "$portal_bind" == "localhost" || "$portal_bind" == "::1" ]]; then
    record PASS portal-bind "portal is configured for loopback: $portal_bind"
elif [[ -n "$portal_bind" ]]; then
    record FAIL portal-bind "portal is configured for non-loopback bind: $portal_bind"
else
    record FAIL portal-bind "PORTAL_BIND_HOST is missing"
fi

if command -v ss >/dev/null 2>&1; then
    listeners="$(ss -H -ltn 2>/dev/null || true)"
    if awk '$4 ~ /:443$/ {found=1} END {exit !found}' <<<"$listeners"; then
        record PASS https-listener "TCP 443 has a listening socket"
    else
        record FAIL https-listener "TCP 443 has no listening socket"
    fi
    for port in 8000 8080; do
        non_loopback="$(awk -v port=":$port" '$4 ~ (port "$") && $4 !~ /^(127\.0\.0\.1|\[::1\]):/ {print $4}' <<<"$listeners")"
        if [[ -n "$non_loopback" ]]; then
            record FAIL "loopback-$port" "port $port has a non-loopback listener"
        elif awk -v port=":$port" '$4 ~ (port "$") {found=1} END {exit !found}' <<<"$listeners"; then
            record PASS "loopback-$port" "port $port is listening only on loopback"
        else
            record FAIL "loopback-$port" "port $port is not listening"
        fi
    done
else
    record SKIP listeners "ss is unavailable"
fi

if command -v firewall-cmd >/dev/null 2>&1 \
    && firewall-cmd --state >/dev/null 2>&1; then
    https_allowed=false
    while IFS= read -r zone; do
        [[ -n "$zone" ]] || continue
        if firewall-cmd --quiet --zone="$zone" --query-service=https \
            || firewall-cmd --quiet --zone="$zone" --query-port=443/tcp; then
            https_allowed=true
            break
        fi
    done < <(firewall-cmd --get-active-zones | awk '/^[^[:space:]]/ {print $1}')
    if [[ "$https_allowed" == "true" ]]; then
        record PASS portal-firewall "firewalld allows HTTPS in an active zone"
    else
        record FAIL portal-firewall "firewalld does not allow HTTPS in an active zone"
    fi
elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
    if ufw status 2>/dev/null | grep -Eq '(^|[[:space:]])443(/tcp)?[[:space:]]+ALLOW'; then
        record PASS portal-firewall "ufw has an allow rule for TCP 443"
    else
        record FAIL portal-firewall "ufw is active without a detected TCP 443 allow rule"
    fi
else
    record UNKNOWN portal-firewall "no active firewalld/ufw policy could be verified"
fi

if [[ -r "$NGINX_SITE" ]]; then
    server_name="$(awk '$1 == "server_name" {gsub(/[;\r]/, "", $2); if ($2 != "notable-portal.internal.example.com") {print $2; exit}}' "$NGINX_SITE")"
    cert_path="$(awk '$1 == "ssl_certificate" {gsub(/[;\r]/, "", $2); print $2; exit}' "$NGINX_SITE")"
    key_path="$(awk '$1 == "ssl_certificate_key" {gsub(/[;\r]/, "", $2); print $2; exit}' "$NGINX_SITE")"
    htpasswd_path="$(awk '$1 == "auth_basic_user_file" {gsub(/[;\r]/, "", $2); print $2; exit}' "$NGINX_SITE")"
    if [[ -n "$server_name" ]]; then
        record PASS portal-hostname "configured server_name=$server_name"
        if getent hosts "$server_name" >/dev/null 2>&1; then
            record PASS portal-dns "$server_name resolves from this host"
        else
            record FAIL portal-dns "$server_name does not resolve from this host"
        fi
    else
        record FAIL portal-hostname "production server_name is not configured"
    fi
    if [[ -n "$cert_path" && -r "$cert_path" ]] && command -v openssl >/dev/null 2>&1 \
        && openssl x509 -in "$cert_path" -noout -checkend 0 >/dev/null 2>&1; then
        record PASS portal-tls "configured TLS certificate exists and is currently valid"
    else
        record FAIL portal-tls "configured TLS certificate is missing, unreadable, expired, or invalid"
    fi
    if [[ -n "$key_path" && -e "$key_path" ]]; then
        key_mode="$(stat -c '%a' "$key_path" 2>/dev/null || true)"
        if [[ "$key_mode" =~ ^(400|600|640)$ ]]; then
            record PASS portal-tls-key "TLS private key exists with restrictive mode $key_mode"
        else
            record FAIL portal-tls-key "TLS private key mode is ${key_mode:-unknown}"
        fi
    else
        record FAIL portal-tls-key "configured TLS private key is missing"
    fi
    if [[ -n "$htpasswd_path" && -s "$htpasswd_path" ]]; then
        if grep -q ':\$2[aby]\$' "$htpasswd_path" 2>/dev/null; then
            user_count="$(grep -c '^[^:#][^:]*:' "$htpasswd_path" 2>/dev/null || true)"
            record PASS portal-basic-auth "bcrypt htpasswd exists with $user_count account(s)"
        else
            record FAIL portal-basic-auth "htpasswd exists but no bcrypt entry was detected"
        fi
    else
        record FAIL portal-basic-auth "configured htpasswd file is missing or empty"
    fi
else
    record FAIL nginx-site "$NGINX_SITE is missing or unreadable"
fi

section "SOAR file drop"
incoming_dir="$(read_config "$CONFIG_ENV" INCOMING_DIR "/var/notables/incoming" 2>/dev/null || true)"
processed_dir="$(read_config "$CONFIG_ENV" PROCESSED_DIR "/var/notables/processed" 2>/dev/null || true)"
for pair in "incoming:$incoming_dir" "processed:$processed_dir"; do
    label="${pair%%:*}"
    path="${pair#*:}"
    if [[ -d "$path" ]]; then
        owner="$(stat -c '%U:%G' "$path" 2>/dev/null || echo unknown)"
        mode="$(stat -c '%a' "$path" 2>/dev/null || echo unknown)"
        record PASS "filedrop-$label" "$path exists owner=$owner mode=$mode"
    else
        record FAIL "filedrop-$label" "$path is missing"
    fi
done
if [[ -r /var/sftp/soar/.ssh/authorized_keys && -s /var/sftp/soar/.ssh/authorized_keys ]]; then
    key_count="$(grep -Ec '^(ssh-|ecdsa-|sk-)' /var/sftp/soar/.ssh/authorized_keys 2>/dev/null || true)"
    record PASS soar-authorized-keys "$key_count authorized SSH key line(s) detected"
else
    record FAIL soar-authorized-keys "SOAR authorized_keys is missing, unreadable, or empty"
fi
recent_processed="$(find "$processed_dir" -maxdepth 1 -type f \( -name '*.json' -o -name '*.txt' \) -mtime -30 -print -quit 2>/dev/null || true)"
if [[ -n "$recent_processed" ]]; then
    record PASS processed-evidence "at least one JSON/TXT input was processed in the last 30 days"
else
    record UNKNOWN processed-evidence "no JSON/TXT processed input was found from the last 30 days"
fi
record UNKNOWN real-soar-proof "filesystem state cannot prove that a processed file originated from the real SOAR"

section "ServiceNow closed-ticket synchronization"
sync_enabled="$(read_config "$CONFIG_ENV" SERVICENOW_CLOSED_TICKET_SYNC_ENABLED "false" 2>/dev/null || true)"
sync_query="$(read_config "$CONFIG_ENV" SERVICENOW_CLOSED_TICKET_QUERY "" 2>/dev/null || true)"
base_url="$(read_config "$CONFIG_ENV" SERVICENOW_BASE_URL "" 2>/dev/null || true)"
if [[ "$sync_enabled" == "true" ]]; then
    record PASS servicenow-sync-config "closed-ticket sync is enabled"
else
    record FAIL servicenow-sync-config "closed-ticket sync is disabled"
fi
if [[ "$base_url" == https://* && -n "$sync_query" ]] && secret_is_set "$CONFIG_ENV" SERVICENOW_CLOSED_TICKET_TOKEN; then
    record PASS servicenow-sync-inputs "HTTPS URL, encoded query, and non-empty read token are configured"
else
    record FAIL servicenow-sync-inputs "HTTPS URL, encoded query, or read token is missing"
fi
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-enabled --quiet notable-closed-ticket-sync.timer \
        && systemctl is-active --quiet notable-closed-ticket-sync.timer; then
        record PASS servicenow-sync-timer "closed-ticket sync timer is enabled and active"
    else
        record FAIL servicenow-sync-timer "closed-ticket sync timer is not both enabled and active"
    fi
else
    record SKIP servicenow-sync-timer "systemctl is unavailable"
fi
record UNKNOWN servicenow-live-api "external ServiceNow reachability was not tested"

section "Validation evidence"
if [[ "$RUN_SMOKE" == "true" ]]; then
    smoke_script="$CHECKOUT_DIR/scripts/smoke_service_chain.sh"
    if [[ -x "$smoke_script" ]]; then
        if "$smoke_script" --config-env "$CONFIG_ENV"; then
            record PASS service-chain-smoke "synthetic file-drop smoke passed"
        else
            record FAIL service-chain-smoke "synthetic file-drop smoke failed"
        fi
    else
        record FAIL service-chain-smoke "smoke script is unavailable: $smoke_script"
    fi
else
    record SKIP service-chain-smoke "not run; rerun with --run-smoke after mutation approval"
fi
record UNKNOWN historical-tests "current host state cannot prove that the complete production-readiness suite previously passed"

section "Summary"
printf 'PASS=%d FAIL=%d UNKNOWN=%d SKIP=%d\n' \
    "$pass_count" "$fail_count" "$unknown_count" "$skip_count"
if (( fail_count > 0 )); then
    exit 1
fi
exit 0
