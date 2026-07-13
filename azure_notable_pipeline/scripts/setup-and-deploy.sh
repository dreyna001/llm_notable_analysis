#!/usr/bin/env bash
set -euo pipefail

required=(
  AZURE_SUBSCRIPTION_ID AZURE_RESOURCE_GROUP AZURE_DEPLOYMENT_PREFIX
  CONTAINER_REGISTRY_RESOURCE_ID CONTAINER_IMAGE_URI
  AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL AZURE_AI_FOUNDRY_RESOURCE_ID
  FUNCTIONS_HOST_STORAGE_ACCOUNT_NAME INPUT_STORAGE_ACCOUNT_NAME
  OUTPUT_STORAGE_ACCOUNT_NAME COSMOS_ACCOUNT_NAME COSMOS_DATABASE_NAME
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Required environment variable is unset: ${name}" >&2
    exit 2
  fi
done

command -v az >/dev/null || { echo 'Azure CLI (az) is required.' >&2; exit 2; }
LOCATION="${AZURE_LOCATION:-eastus}"

if [[ "${CONTAINER_IMAGE_URI}" != *@sha256:* ]]; then
  echo 'CONTAINER_IMAGE_URI must be pinned to an immutable @sha256: digest.' >&2
  exit 2
fi

az account set --subscription "${AZURE_SUBSCRIPTION_ID}"
acr_login_server="$(az resource show --ids "${CONTAINER_REGISTRY_RESOURCE_ID}" --query properties.loginServer -o tsv)"
if [[ "${CONTAINER_IMAGE_URI,,}" != "${acr_login_server,,}/"* ]]; then
  echo "Container image registry does not match ${CONTAINER_REGISTRY_RESOURCE_ID}." >&2
  exit 2
fi

az group create --name "${AZURE_RESOURCE_GROUP}" --location "${LOCATION}" --output none
deployment_name="${AZURE_DEPLOYMENT_PREFIX}-$(date -u +%Y%m%d%H%M%S)"

az deployment group create \
  --name "${deployment_name}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --template-file deploy/azure/main.bicep \
  --parameters \
    DeploymentPrefix="${AZURE_DEPLOYMENT_PREFIX}" \
    Location="${LOCATION}" \
    ContainerRegistryResourceId="${CONTAINER_REGISTRY_RESOURCE_ID}" \
    ContainerImageUri="${CONTAINER_IMAGE_URI}" \
    AzureAiFoundryAnthropicBaseUrl="${AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL}" \
    AzureAiFoundryResourceId="${AZURE_AI_FOUNDRY_RESOURCE_ID}" \
    AzureAiFoundryAnalysisDeployment="${AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT:-claude-sonnet-4-6}" \
    AzureOpenAiEndpoint="${AZURE_OPENAI_ENDPOINT:-}" \
    AzureOpenAiResourceId="${AZURE_OPENAI_RESOURCE_ID:-}" \
    AzureOpenAiEmbeddingsDeployment="${AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT:-}" \
    KeyVaultName="${KEY_VAULT_NAME:-}" \
    CosmosAccountName="${COSMOS_ACCOUNT_NAME}" \
    CosmosDatabaseName="${COSMOS_DATABASE_NAME}" \
    CapabilityProfiles="${CAPABILITY_PROFILES:-core}" \
    ServiceNowDispositionSyncEnabled="${SERVICENOW_DISPOSITION_SYNC_ENABLED:-false}" \
    CaseQaChatHistoryEnabled="${CASE_QA_CHAT_HISTORY_ENABLED:-false}" \
    FunctionsHostStorageAccountName="${FUNCTIONS_HOST_STORAGE_ACCOUNT_NAME}" \
    StorageAccountNameInput="${INPUT_STORAGE_ACCOUNT_NAME}" \
    StorageAccountNameOutput="${OUTPUT_STORAGE_ACCOUNT_NAME}" \
    StorageAccountNamePortalUi="${PORTAL_UI_STORAGE_ACCOUNT_NAME:-}" \
    AnalyzerMaxInstanceCount="${ANALYZER_MAX_INSTANCE_COUNT:-5}" \
    EmbedMaxInstanceCount="${EMBED_MAX_INSTANCE_COUNT:-5}" \
  --output none

analyzer_name="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.AnalyzerFunctionAppName.value -o tsv)"
embed_name="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.EmbedFunctionAppName.value -o tsv)"

forbidden_setting_pattern='^(AZUREWEBJOBSSTORAGE|AZUREWEBJOBSDASHBOARD|WEBSITE_CONTENTAZUREFILECONNECTIONSTRING|WEBSITE_CONTENTSHARE)$|(^|_)(DOCKER_REGISTRY_SERVER|ACR|AZURE_CONTAINER_REGISTRY|CONTAINER_REGISTRY)(_|$).*(USERNAME|PASSWORD|API_?KEY|ACCESS_?KEY|KEY|TOKEN|SECRET|CREDENTIAL|CONNECTION_?STRING)|(^|_)(AZURE_)?(STORAGE|BLOB|QUEUE|TABLE|FILE|FILES)(_|$).*(ACCOUNT_?KEY|ACCESS_?KEY|API_?KEY|KEY|CONNECTION_?STRING|SAS(_TOKEN)?|PASSWORD|SECRET)|(^|_)(AZURE_AI_FOUNDRY|AI_FOUNDRY|FOUNDRY|ANTHROPIC|AZURE_OPENAI|OPENAI|AZURE_SEARCH|COGNITIVE_SEARCH|SEARCH_SERVICE|SEARCH|COSMOSDB|COSMOS|AZURE_COSMOS)(_|$).*(API_?KEY|ACCOUNT_?KEY|ACCESS_?KEY|PRIMARY_?KEY|SECONDARY_?KEY|MASTER_?KEY|KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|CONNECTION_?STRING)'

app_setting_value() {
  local app="$1"
  local setting_name="$2"
  az functionapp config appsettings list \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${app}" \
    --query "[?name=='${setting_name}'].value | [0]" \
    -o tsv
}

verify_no_forbidden_settings() {
  local app="$1"
  local setting_name normalized_name setting_names

  setting_names="$(
    az functionapp config appsettings list \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${app}" \
      --query '[].name' \
      -o tsv
  )"
  while IFS= read -r setting_name; do
    [[ -z "${setting_name}" ]] && continue
    normalized_name="$(tr '[:lower:]' '[:upper:]' <<<"${setting_name}")"
    if [[ "${normalized_name}" =~ ${forbidden_setting_pattern} ]]; then
      echo "Forbidden credential, key, secret, connection-string, or Azure Files setting found on ${app}: ${setting_name}." >&2
      exit 1
    fi
  done <<<"${setting_names}"
}

verify_managed_identity_configuration() {
  local app="$1"
  local identity_output identity_client_id image_setting acr_mi_enabled acr_mi_client_id
  local host_credential host_client_id host_service_uri
  local -a identity_ids=()

  identity_output="$(
    az functionapp identity show \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${app}" \
      --query 'keys(userAssignedIdentities)' \
      -o tsv
  )"
  while IFS= read -r identity_id; do
    [[ -n "${identity_id}" ]] && identity_ids+=("${identity_id}")
  done <<<"${identity_output}"
  if (( ${#identity_ids[@]} != 1 )); then
    echo "${app} must have exactly one user-assigned managed identity." >&2
    exit 1
  fi

  identity_client_id="$(az identity show --ids "${identity_ids[0]}" --query clientId -o tsv)"
  image_setting="$(az functionapp config show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${app}" --query linuxFxVersion -o tsv)"
  acr_mi_enabled="$(az functionapp config show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${app}" --query acrUseManagedIdentityCreds -o tsv)"
  acr_mi_client_id="$(az functionapp config show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${app}" --query acrUserManagedIdentityID -o tsv)"
  if [[ "${image_setting,,}" != "docker|${CONTAINER_IMAGE_URI,,}" || "${acr_mi_enabled,,}" != 'true' || "${acr_mi_client_id,,}" != "${identity_client_id,,}" ]]; then
    echo "Managed-identity image-pull configuration is not ready on ${app}." >&2
    exit 1
  fi

  host_credential="$(app_setting_value "${app}" 'AzureWebJobsStorage__credential')"
  host_client_id="$(app_setting_value "${app}" 'AzureWebJobsStorage__clientId')"
  if [[ "${host_credential,,}" != 'managedidentity' || "${host_client_id,,}" != "${identity_client_id,,}" ]]; then
    echo "Identity-based Functions host storage is not configured for the app identity on ${app}." >&2
    exit 1
  fi
  for service in blob queue table; do
    host_service_uri="$(app_setting_value "${app}" "AzureWebJobsStorage__${service}ServiceUri")"
    if [[ ! "${host_service_uri}" =~ ^https:// || "${host_service_uri}" =~ (AccountKey|SharedAccessSignature|sig=) ]]; then
      echo "Identity-based Functions host ${service} service configuration is not ready on ${app}." >&2
      exit 1
    fi
  done
}

wait_for_function_host() {
  local app="$1"
  shift
  local app_id app_state host_state function_output actual_names expected_names
  local function_exit_code=1

  app_id="$(az functionapp show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${app}" --query id -o tsv)"
  expected_names="$(printf '%s\n' "$@" | LC_ALL=C sort)"
  for attempt in {1..18}; do
    app_state="$(az functionapp show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${app}" --query state -o tsv 2>/dev/null || true)"
    host_state="$(
      az rest \
        --method get \
        --url "https://management.azure.com${app_id}/hostruntime/admin/host/status?api-version=2022-03-01" \
        --query state \
        -o tsv 2>/dev/null || true
    )"
    function_output="$(az functionapp function list --resource-group "${AZURE_RESOURCE_GROUP}" --name "${app}" --query '[].name' -o tsv 2>/dev/null)" && function_exit_code=0 || function_exit_code=$?
    actual_names="$(sed -E 's#^.*/##' <<<"${function_output}" | sed '/^$/d' | LC_ALL=C sort)"
    if [[ "${app_state}" == 'Running' && "${host_state}" == 'Running' && ${function_exit_code} -eq 0 && "${actual_names}" == "${expected_names}" ]]; then
      return
    fi
    sleep 10
  done

  echo "${app} did not reach a healthy Functions host with the exact expected enabled function set after managed-identity image-pull and host-storage propagation." >&2
  exit 1
}

for app in "${analyzer_name}" "${embed_name}"; do
  verify_no_forbidden_settings "${app}"
  verify_managed_identity_configuration "${app}"
done

wait_for_function_host "${analyzer_name}" intake_blob analyzer_queue
wait_for_function_host "${embed_name}" case_embed_queue

echo "Deployment ${deployment_name} completed: ${analyzer_name}, ${embed_name}."
