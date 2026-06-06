#!/usr/bin/env bash
# Walk the analyst portal UI/API paths (nginx + basic auth).
set -euo pipefail

BASE="${PORTAL_BASE_URL:-https://127.0.0.1}"
AUTH="${PORTAL_AUTH:-analyst:analyst-lab-change-me}"
CURL=(curl -kfsS -u "$AUTH")

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

echo "=== Portal UI smoke: $BASE ==="

html="$("${CURL[@]}" "$BASE/")"
echo "$html" | grep -q '<div id="root">' || fail "SPA index missing root div"
pass "SPA index.html loads"

mapfile -t assets < <(echo "$html" | grep -oE '/assets/[^" ]+' | sort -u | head -5)
if ((${#assets[@]} == 0)); then
  fail "No /assets/* references in index.html"
fi
for asset in "${assets[@]}"; do
  code="$(curl -kfsS -u "$AUTH" -o /dev/null -w '%{http_code}' "$BASE$asset")"
  [[ "$code" == "200" ]] || fail "asset $asset returned $code"
  pass "asset $asset"
done

caps="$("${CURL[@]}" "$BASE/api/capabilities")"
echo "$caps" | grep -q 'case_qa_enabled' || fail "capabilities payload unexpected"
pass "GET /api/capabilities"

cases="$("${CURL[@]}" "$BASE/api/cases")"
case_id="$(echo "$cases" | python3 -c 'import json,sys; d=json.load(sys.stdin); items=d.get("items") or []; print(items[0]["case_id"] if items else "")')"
[[ -n "$case_id" ]] || fail "case list empty"
pass "GET /api/cases ($case_id)"

detail="$("${CURL[@]}" "$BASE/api/cases/$(python3 -c "import urllib.parse; print(urllib.parse.quote('$case_id'))")")"
echo "$detail" | grep -q '"case_id"' || fail "case detail payload unexpected"
pass "GET /api/cases/{id}"

readiness="$("${CURL[@]}" "$BASE/api/diagnostics/chat-readiness")"
echo "$readiness" | grep -q '"status"' || fail "chat-readiness payload unexpected"
pass "GET /api/diagnostics/chat-readiness ($readiness)"

chat_payload="$(python3 - "$case_id" <<'PY'
import json, sys
print(json.dumps({
    "mode": "selected_case",
    "question": "What is the verdict for this case? Answer in one sentence using only case evidence.",
    "selected_case_id": sys.argv[1],
}))
PY
)"
chat_response_file="$(mktemp)"
chat_http="$(curl -kfsS -u "$AUTH" -H "Content-Type: application/json" -d "$chat_payload" \
  -o "$chat_response_file" -w '%{http_code}' "$BASE/api/chat" || true)"
if [[ "$chat_http" != "200" ]]; then
  echo "Chat response body:" >&2
  cat "$chat_response_file" >&2 || true
  rm -f "$chat_response_file"
  fail "POST /api/chat returned HTTP $chat_http"
fi
chat="$(cat "$chat_response_file")"
rm -f "$chat_response_file"
echo "$chat" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("answer_status") in {"answered","refused","unknown"}, d; print(d.get("answer_status"))' >/dev/null
answer_status="$(echo "$chat" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("answer_status",""))')"
pass "POST /api/chat (answer_status=$answer_status)"

echo "=== All portal UI smoke checks passed ==="
