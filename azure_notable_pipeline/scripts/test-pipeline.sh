#!/usr/bin/env bash
set -euo pipefail

# Azure staging acceptance harness. The default is an offline, non-mutating
# contract gate. --staging-gate enables live tests and requires an isolated
# non-production subscription plus explicit chaos acknowledgement.

usage() {
  cat <<'EOF'
Usage: scripts/test-pipeline.sh [--staging-gate] [--resource-group NAME] [--deployment-name NAME]

Default: run offline contract/security/timeout/disposition-dry-run tests only.

Live gate environment (values are not printed):
  AZURE_RESOURCE_GROUP, AZURE_DEPLOYMENT_NAME
  PORTAL_TEST_BEARER_TOKEN                 dedicated synthetic identity token
  STAGING_SUBSCRIPTION_ID                  must equal the active subscription
  STAGING_CHAOS_CONFIRMATION=isolated-nonproduction

The live gate uploads only generated synthetic fixtures. It verifies private
intake, a 3x analyzer-cap burst, three five-attempt poison paths, duplicate
delivery, authenticated Front Door readiness, and the managed-identity AI /
Search / Cosmos pipeline. External writeback remains disabled.
EOF
}

staging_gate=false
resource_group="${AZURE_RESOURCE_GROUP:-}"
deployment_name="${AZURE_DEPLOYMENT_NAME:-}"
while (($#)); do
  case "$1" in
    --staging-gate) staging_gate=true ;;
    --resource-group) resource_group="${2:?missing resource group}"; shift ;;
    --deployment-name) deployment_name="${2:?missing deployment name}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
python_test="${PYTHON:-python3}"

echo "Running offline Azure staging contracts"
"$python_test" -m pytest -q \
  tests/test_private_intake_contract.py \
  tests/test_portal_openapi_contract.py \
  tests/test_portal_jwt.py \
  tests/test_portal_handler.py \
  tests/test_portal_api_contract.py \
  tests/test_azure_openai_gateway.py \
  tests/test_cosmos_store.py \
  tests/test_disposition_sync_handler.py \
  tests/test_servicenow_disposition_sync.py

if [[ "$staging_gate" != true ]]; then
  echo "Offline gate passed. Use --staging-gate only from the isolated Azure staging runner."
  exit 0
fi

for command in az python3; do
  command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 1; }
done
[[ -n "$resource_group" && -n "$deployment_name" ]] || { echo "resource group and deployment name are required" >&2; exit 1; }
[[ "${STAGING_CHAOS_CONFIRMATION:-}" == "isolated-nonproduction" ]] || {
  echo "Set STAGING_CHAOS_CONFIRMATION=isolated-nonproduction after verifying the dedicated staging subscription." >&2
  exit 1
}
active_subscription="$(az account show --query id -o tsv)"
[[ -n "${STAGING_SUBSCRIPTION_ID:-}" && "$active_subscription" == "$STAGING_SUBSCRIPTION_ID" ]] || {
  echo "Active subscription does not match STAGING_SUBSCRIPTION_ID; refusing live mutation." >&2
  exit 1
}

outputs="$(az deployment group show -g "$resource_group" -n "$deployment_name" --query properties.outputs -o json)"
output() { python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1],{}).get("value", ""))' "$1" <<<"$outputs"; }
input_account="$(output InputStorageAccountName)"
output_account="$(output OutputStorageAccountName)"
analyzer_app="$(output AnalyzerFunctionAppName)"
embed_app="$(output EmbedFunctionAppName)"
portal_host="$(output PortalFrontDoorHostName)"
portal_app="$(output PortalFunctionAppName)"
apim_name="$(output PortalApiManagementName)"
analyzer_queue="$(output AnalyzerQueueName)"
embed_queue="$(output CaseEmbedQueueName)"
[[ -n "$input_account" && -n "$output_account" && -n "$analyzer_app" ]] || { echo "Required deployment outputs are missing" >&2; exit 1; }

for account in "$input_account" "$output_account"; do
  [[ "$(az storage account show -g "$resource_group" -n "$account" --query publicNetworkAccess -o tsv)" == "Disabled" ]] || {
    echo "Storage public network access is not disabled for $account" >&2; exit 1;
  }
done
if [[ -n "$portal_app" ]]; then
  [[ "$(az functionapp show -g "$resource_group" -n "$portal_app" --query publicNetworkAccess -o tsv)" == "Disabled" ]] || {
    echo "Portal Function public network access is not disabled" >&2; exit 1;
  }
fi
if [[ -n "$apim_name" ]]; then
  [[ "$(az apim show -g "$resource_group" -n "$apim_name" --query publicNetworkAccess -o tsv)" == "Disabled" ]] || {
    echo "APIM public network access is not disabled" >&2; exit 1;
  }
fi

setting() {
  az functionapp config appsettings list -g "$resource_group" -n "$1" \
    --query "[?name=='$2'].value | [0]" -o tsv
}
for app in "$analyzer_app" "$embed_app"; do
  [[ "$(setting "$app" SPLUNK_SINK_ENABLED)" != "true" ]] || { echo "Consequential Splunk sink is enabled on $app" >&2; exit 1; }
  [[ "$(setting "$app" SERVICENOW_CREATE_ENABLED)" != "true" ]] || { echo "Consequential ServiceNow create is enabled on $app" >&2; exit 1; }
done

tmp_dir="$(mktemp -d)"
original_queue="$analyzer_queue"
restore() {
  if [[ -n "${queue_was_changed:-}" ]]; then
    az functionapp config appsettings set -g "$resource_group" -n "$analyzer_app" \
      --settings "ANALYZER_QUEUE_NAME=$original_queue" --output none >/dev/null || true
  fi
  rm -rf "$tmp_dir"
}
trap restore EXIT

make_fixture() {
  local id="$1" path="$2"
  python3 - "$id" "$path" <<'PY'
import json, sys
payload = {"finding_id": sys.argv[1], "event_time": "2026-01-01T00:00:00Z", "rule_name": "synthetic staging fixture", "description": "Non-production benign pipeline acceptance event"}
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump(payload, stream)
PY
}
upload_fixture() {
  local id="$1" path="$tmp_dir/$1.json"
  make_fixture "$id" "$path"
  az storage blob upload --auth-mode login --account-name "$input_account" \
    --container-name input --name "incoming/$id.json" --file "$path" --overwrite true --output none
}
wait_blob() {
  local name="$1" limit="${2:-900}" elapsed=0
  until [[ "$(az storage blob exists --auth-mode login --account-name "$output_account" --container-name output --name "$name" --query exists -o tsv)" == "true" ]]; do
    ((elapsed+=10)); ((elapsed < limit)) || { echo "Timed out waiting for $name" >&2; return 1; }
    sleep 10
  done
}
wait_queue_message() {
  local account="$1" queue="$2" marker="$3" limit="${4:-900}" elapsed=0 messages
  until messages="$(az storage message peek --auth-mode login --account-name "$account" \
      --queue-name "$queue" --num-messages 32 -o json 2>/dev/null)" && grep -Fq "$marker" <<<"$messages"; do
    ((elapsed+=10)); ((elapsed < limit)) || { echo "Timed out waiting for poison queue $queue" >&2; return 1; }
    sleep 10
  done
}

run_id="staging-$(date -u +%Y%m%d%H%M%S)"
echo "Private intake and managed-identity service smoke"
upload_fixture "$run_id"
wait_blob "reports/$run_id.json"

max_instances="$(az functionapp config appsettings list -g "$resource_group" -n "$analyzer_app" --query "[?name=='WEBSITE_MAX_DYNAMIC_APPLICATION_SCALE_OUT'].value | [0]" -o tsv)"
[[ "$max_instances" =~ ^[1-9][0-9]*$ ]] || max_instances=5
burst_count=$((max_instances * 3))
echo "Publishing $burst_count synthetic intake objects (3x analyzer cap $max_instances)"
for ((i=1; i<=burst_count; i++)); do upload_fixture "$run_id-burst-$i"; done
for ((i=1; i<=burst_count; i++)); do wait_blob "reports/$run_id-burst-$i.json" 1800; done

echo "Duplicate delivery/idempotency"
upload_fixture "$run_id"
wait_blob "reports/$run_id.json"

echo "Analyzer and embed five-attempt poison paths"
missing_etag='"staging-missing-etag"'
analyzer_message="{\"schema_version\":1,\"container_name\":\"input\",\"blob_name\":\"incoming/$run_id-missing.json\",\"etag\":$missing_etag,\"size_bytes\":1,\"last_modified\":\"2026-01-01T00:00:00Z\"}"
embed_message="{\"schema_version\":1,\"case_envelope_container\":\"output\",\"case_envelope_blob_name\":\"cases/2026/01/01/$run_id-missing.json\"}"
az storage message put --auth-mode login --account-name "$output_account" --queue-name "$analyzer_queue" --content "$analyzer_message" --output none
az storage message put --auth-mode login --account-name "$output_account" --queue-name "$embed_queue" --content "$embed_message" --output none
wait_queue_message "$output_account" "${analyzer_queue}-poison" "$run_id" 1800
wait_queue_message "$output_account" "${embed_queue}-poison" "$run_id" 1800

echo "Blob-trigger publication five-attempt poison path"
failure_queue="$run_id-does-not-exist"
az functionapp config appsettings set -g "$resource_group" -n "$analyzer_app" \
  --settings "ANALYZER_QUEUE_NAME=$failure_queue" --output none
queue_was_changed=1
upload_fixture "$run_id-publication-failure"
wait_queue_message "$input_account" webjobs-blobtrigger-poison "$run_id-publication-failure" 1800
az functionapp config appsettings set -g "$resource_group" -n "$analyzer_app" \
  --settings "ANALYZER_QUEUE_NAME=$original_queue" --output none
unset queue_was_changed

alert_names="$(az monitor scheduled-query list -g "$resource_group" --query '[].name' -o tsv; az monitor metrics alert list -g "$resource_group" --query '[].name' -o tsv)"
for suffix in webjobs-blobtrigger-poison-nonempty notable-analysis-jobs-poison-nonempty case-embed-invocations-poison-nonempty function-failures function-timeouts; do
  grep -Eq "${suffix}$" <<<"$alert_names" || { echo "Required enabled alert rule ending in $suffix was not found" >&2; exit 1; }
done

if [[ -n "$portal_host" ]]; then
  [[ -n "${PORTAL_TEST_BEARER_TOKEN:-}" ]] || { echo "PORTAL_TEST_BEARER_TOKEN is required for the portal staging gate" >&2; exit 1; }
  PORTAL_URL="https://$portal_host/ready" PORTAL_TOKEN="$PORTAL_TEST_BEARER_TOKEN" python3 - <<'PY'
import os, urllib.request
request = urllib.request.Request(os.environ["PORTAL_URL"], headers={"Authorization": "Bearer " + os.environ["PORTAL_TOKEN"]})
with urllib.request.urlopen(request, timeout=30) as response:
    if response.status != 200:
        raise SystemExit(f"authenticated /ready returned {response.status}")
PY
fi

# The offline gate above executes the mutation-free disposition dry-run and
# mapping/checkpoint cases. Live staging keeps the timer disabled unless the
# customer has supplied an isolated ServiceNow test instance/read credential.
disposition_app="$(az functionapp list -g "$resource_group" --query "[?contains(name, 'disposition')].name | [0]" -o tsv)"
if [[ -n "$disposition_app" ]]; then
  [[ "$(setting "$disposition_app" SERVICENOW_DISPOSITION_SYNC_ENABLED)" != "true" ]] || {
    echo "Disposition sync must remain disabled during the staging dry run" >&2; exit 1;
  }
fi

echo "Azure staging gate passed. Poison messages are intentionally retained for operator recovery evidence."
