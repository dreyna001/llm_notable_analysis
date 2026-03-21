#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_TEST="$SCRIPT_DIR/static_validation.sh"
INTEGRATION_TEST="$SCRIPT_DIR/integration_all.sh"

MODE="${1:-all}"

run_test() {
    local test_file="$1"
    echo ""
    echo "=== Running $(basename "$test_file") ==="
    bash "$test_file"
    echo "=== PASS: $(basename "$test_file") ==="
}

case "$MODE" in
    all)
        run_test "$STATIC_TEST"
        run_test "$INTEGRATION_TEST"
        ;;
    static)
        run_test "$STATIC_TEST"
        ;;
    integration)
        run_test "$INTEGRATION_TEST"
        ;;
    *)
        echo "Usage: $0 [all|static|integration]" >&2
        exit 2
        ;;
esac

echo ""
echo "All requested PoC tests passed."
