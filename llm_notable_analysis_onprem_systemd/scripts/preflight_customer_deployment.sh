#!/usr/bin/env bash
# Read-only preflight for the on-prem customer-default deployment.
set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODEL_PATH="/opt/models/gemma-4-31B-it"
PORTAL_DIST=""
WHEELHOUSE=""
OFFLINE=false
REPORT_FILE=""

pass_count=0
fail_count=0

usage() {
    cat <<'EOF'
Usage: preflight_customer_deployment.sh [options]

Options:
  --repo-root PATH     Monorepo root (default: detected from this script)
  --model-path PATH    Local vLLM model directory
  --portal-dist PATH   Prebuilt analyst portal dist directory
  --wheelhouse PATH    Offline Python wheelhouse
  --offline            Require portal dist and wheelhouse to be staged
  --report-file PATH   Save the complete, secret-free result to PATH
  -h, --help           Show this help

This command is read-only except for the optional report file. It checks the
host and staged inputs before scripts/install.sh changes the target host.

Exit codes:
  0  All required checks passed
  1  One or more required checks failed
  2  Invalid invocation
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
        *) die "Internal error: unsupported status $status" ;;
    esac
    printf '%-5s %-24s %s\n' "$status" "$check_id" "$message"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-root)
            require_value "$1" "${2:-}"
            REPO_ROOT="$2"
            shift 2
            ;;
        --model-path)
            require_value "$1" "${2:-}"
            MODEL_PATH="$2"
            shift 2
            ;;
        --portal-dist)
            require_value "$1" "${2:-}"
            PORTAL_DIST="$2"
            shift 2
            ;;
        --wheelhouse)
            require_value "$1" "${2:-}"
            WHEELHOUSE="$2"
            shift 2
            ;;
        --offline)
            OFFLINE=true
            shift
            ;;
        --report-file)
            require_value "$1" "${2:-}"
            REPORT_FILE="$2"
            shift 2
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

if [[ -n "$REPORT_FILE" ]]; then
    report_parent="$(dirname "$REPORT_FILE")"
    [[ -d "$report_parent" ]] || die "Report directory does not exist: $report_parent"
    : >"$REPORT_FILE" || die "Cannot write report file: $REPORT_FILE"
    exec > >(tee "$REPORT_FILE") 2>&1
fi

ONPREM_DIR="$REPO_ROOT/llm_notable_analysis_onprem_systemd"
[[ -n "$PORTAL_DIST" ]] || PORTAL_DIST="$ONPREM_DIR/frontend/analyst-portal/dist"

echo "On-prem customer deployment preflight"
echo "UTC time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Host: $(hostname -f 2>/dev/null || hostname)"
echo "Mode: $([[ "$OFFLINE" == "true" ]] && echo offline || echo connected-or-prestaged)"

if [[ -r /etc/os-release ]] && . /etc/os-release \
    && [[ " ${ID:-} ${ID_LIKE:-} " =~ (rhel|fedora|centos|rocky|almalinux) ]]; then
    record PASS supported-os "${PRETTY_NAME:-RHEL-compatible Linux}"
else
    record FAIL supported-os "RHEL 8/9 or a compatible distribution is required"
fi

if command -v python3.12 >/dev/null 2>&1; then
    record PASS python-3.12 "$(python3.12 --version 2>&1)"
else
    record FAIL python-3.12 "python3.12 is not on PATH"
fi

for command_name in bash systemctl; do
    if command -v "$command_name" >/dev/null 2>&1; then
        record PASS "command-$command_name" "$command_name is available"
    else
        record FAIL "command-$command_name" "$command_name is not available"
    fi
done

for package_dir in llm_notable_analysis_onprem_systemd onprem-llm-sdk onprem_rag_notable_analysis; do
    if [[ -d "$REPO_ROOT/$package_dir" ]]; then
        record PASS "repo-$package_dir" "$REPO_ROOT/$package_dir exists"
    else
        record FAIL "repo-$package_dir" "$REPO_ROOT/$package_dir is missing"
    fi
done

for template in config.env.example config.portal.env.example; do
    if [[ -r "$ONPREM_DIR/$template" ]]; then
        record PASS "template-$template" "$template is readable"
    else
        record FAIL "template-$template" "$ONPREM_DIR/$template is missing"
    fi
done

if [[ -r "$MODEL_PATH/config.json" ]]; then
    record PASS model-weights "$MODEL_PATH/config.json is staged"
else
    record FAIL model-weights "$MODEL_PATH/config.json is missing"
fi

if [[ "$OFFLINE" == "true" ]]; then
    if [[ -d "$PORTAL_DIST" && -r "$PORTAL_DIST/index.html" ]]; then
        record PASS portal-dist "$PORTAL_DIST/index.html is staged"
    else
        record FAIL portal-dist "prebuilt portal assets are missing from $PORTAL_DIST"
    fi
    if [[ -n "$WHEELHOUSE" && -d "$WHEELHOUSE" ]] \
        && find "$WHEELHOUSE" -maxdepth 1 -type f -name '*.whl' -print -quit | grep -q .; then
        record PASS wheelhouse "$WHEELHOUSE contains Python wheels"
    else
        record FAIL wheelhouse "--wheelhouse must contain staged .whl files in offline mode"
    fi
else
    record PASS offline-artifacts "not required in connected-or-prestaged mode"
fi

printf 'SUMMARY PASS=%d FAIL=%d\n' "$pass_count" "$fail_count"
if (( fail_count > 0 )); then
    exit 1
fi
exit 0
