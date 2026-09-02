#!/usr/bin/env bash
set -euo pipefail

required=(
  AZURE_SUBSCRIPTION_ID AZURE_RESOURCE_GROUP AZURE_DEPLOYMENT_PREFIX
  CONTAINER_REGISTRY_RESOURCE_ID CONTAINER_IMAGE_URI
  AZURE_OPENAI_ENDPOINT AZURE_OPENAI_RESOURCE_ID AZURE_OPENAI_ANALYSIS_DEPLOYMENT
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
az cloud set --name AzureUSGovernment
LOCATION="${AZURE_LOCATION:-usgovvirginia}"
case "${LOCATION,,}" in
  usgovvirginia|usgovarizona) ;;
  *) echo 'AZURE_LOCATION must be usgovvirginia or usgovarizona.' >&2; exit 2 ;;
esac
[[ "${AZURE_OPENAI_ENDPOINT,,}" == https://*.openai.azure.us ]] || { echo 'AZURE_OPENAI_ENDPOINT must use .openai.azure.us.' >&2; exit 2; }
[[ "${CONTAINER_IMAGE_URI,,}" == *.azurecr.us/* ]] || { echo 'CONTAINER_IMAGE_URI must use an Azure Government ACR (.azurecr.us).' >&2; exit 2; }
capability_profiles="${CAPABILITY_PROFILES:-core}"
capability_profiles="${capability_profiles//[[:space:]]/}"
deploy_portal=false
deployment_environment="${DEPLOYMENT_ENVIRONMENT:-development}"
deployment_environment="${deployment_environment,,}"
case "${deployment_environment}" in
  development|staging|production) ;;
  *) echo 'DEPLOYMENT_ENVIRONMENT must be development, staging, or production.' >&2; exit 2 ;;
esac
isolate_host_storage="${ISOLATE_FUNCTIONS_HOST_STORAGE:-false}"
if [[ "${isolate_host_storage,,}" == 'true' ]]; then
  for name in ANALYZER_HOST_STORAGE_ACCOUNT_NAME EMBED_HOST_STORAGE_ACCOUNT_NAME DISPOSITION_HOST_STORAGE_ACCOUNT_NAME PORTAL_HOST_STORAGE_ACCOUNT_NAME; do
    if [[ -z "${!name:-}" ]]; then
      echo "${name} is required when ISOLATE_FUNCTIONS_HOST_STORAGE=true." >&2
      exit 2
    fi
  done
fi
blob_data_protection_enabled="${BLOB_DATA_PROTECTION_ENABLED:-false}"
cosmos_continuous_backup_enabled="${COSMOS_CONTINUOUS_BACKUP_ENABLED:-false}"
cosmos_continuous_backup_migration_acknowledged="${COSMOS_CONTINUOUS_BACKUP_MIGRATION_ACKNOWLEDGED:-false}"
cosmos_zone_redundant="${COSMOS_ZONE_REDUNDANT:-false}"
function_plan_zone_redundant="${FUNCTION_PLAN_ZONE_REDUNDANT:-false}"
storage_sku_name="${STORAGE_SKU_NAME:-Standard_LRS}"
if [[ "${function_plan_zone_redundant,,}" == 'true' && "${storage_sku_name}" != 'Standard_ZRS' ]]; then
  echo 'FUNCTION_PLAN_ZONE_REDUNDANT=true requires STORAGE_SKU_NAME=Standard_ZRS.' >&2
  exit 2
fi
disposition_sync_enabled="${SERVICENOW_DISPOSITION_SYNC_ENABLED:-false}"
if [[ ",${capability_profiles,,}," == *,analyst_portal,* ]]; then
  deploy_portal=true
  portal_required=(
    PORTAL_UI_STORAGE_ACCOUNT_NAME PORTAL_UI_DEPLOYER_PRINCIPAL_ID
    PORTAL_JWT_ISSUER PORTAL_JWT_AUDIENCE
    AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT
    AZURE_SEARCH_ENDPOINT AZURE_SEARCH_RESOURCE_ID CASE_QA_AZURE_SEARCH_INDEX
    RAG_TENANT_ID
    PORTAL_OIDC_CLIENT_ID PORTAL_OIDC_AUTHORITY PORTAL_OIDC_API_SCOPE
    PORTAL_VALIDATION_BEARER_TOKEN
  )
  for name in "${portal_required[@]}"; do
    if [[ -z "${!name:-}" ]]; then
      echo "Required analyst-portal environment variable is unset: ${name}" >&2
      exit 2
    fi
  done
  if [[ -z "${PORTAL_ENTRA_REQUIRED_APP_ROLE:-}" ]]; then
    echo 'PORTAL_ENTRA_REQUIRED_APP_ROLE is required when the analyst portal is enabled.' >&2
    exit 2
  fi
  if [[ "${PORTAL_AUTH_MODE:-jwt}" == 'jwt' && "${PORTAL_OIDC_API_SCOPE##*/}" != "${PORTAL_ENTRA_REQUIRED_APP_ROLE}" ]]; then
    echo 'In JWT mode, PORTAL_ENTRA_REQUIRED_APP_ROLE must match the final segment of PORTAL_OIDC_API_SCOPE.' >&2
    exit 2
  fi
fi
if [[ ",${capability_profiles,,}," == *,rag,* ]]; then
  rag_required=(
    AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT AZURE_SEARCH_ENDPOINT AZURE_SEARCH_RESOURCE_ID
    RAG_AZURE_SEARCH_INDEX RAG_TENANT_ID RAG_SOURCE_STORAGE_ACCOUNT_URL
    RAG_SOURCE_STORAGE_ACCOUNT_NAME RAG_SOURCE_CONTAINER
  )
  for name in "${rag_required[@]}"; do
    if [[ -z "${!name:-}" ]]; then
      echo "Required RAG environment variable is unset: ${name}" >&2
      exit 2
    fi
  done
fi
if [[ -n "${AZURE_SEARCH_ENDPOINT:-}" && "${AZURE_SEARCH_ENDPOINT,,}" != https://*.search.azure.us ]]; then
  echo 'AZURE_SEARCH_ENDPOINT must use .search.azure.us.' >&2
  exit 2
fi
if [[ "${deployment_environment}" == 'production' && -z "${ALERT_ACTION_GROUP_RESOURCE_ID:-}" ]]; then
  echo 'ALERT_ACTION_GROUP_RESOURCE_ID is required when DEPLOYMENT_ENVIRONMENT=production.' >&2
  exit 2
fi
if [[ "${deployment_environment}" == 'production' && "${deploy_portal}" == true && -z "${PORTAL_SYNTHETIC_CHECK_NAME:-}" ]]; then
  echo 'PORTAL_SYNTHETIC_CHECK_NAME is required for a production analyst portal.' >&2
  exit 2
fi
if [[ "${disposition_sync_enabled,,}" == 'true' ]]; then
  disposition_required=(
    KEY_VAULT_NAME SERVICENOW_BASE_URL
    SERVICENOW_DISPOSITION_SYNC_TOKEN_SECRET_NAME
  )
  for name in "${disposition_required[@]}"; do
    if [[ -z "${!name:-}" ]]; then
      echo "Required disposition-sync environment variable is unset: ${name}" >&2
      exit 2
    fi
  done
fi

if [[ ! "${CONTAINER_IMAGE_URI}" =~ ^.+@sha256:[0-9a-fA-F]{64}$ ]]; then
  echo 'CONTAINER_IMAGE_URI must be pinned to an immutable @sha256 digest with exactly 64 hexadecimal characters.' >&2
  exit 2
fi

run_preflight() {
  local python_bin="${PYTHON:-python3}"
  command -v "${python_bin}" >/dev/null || { echo "Python is required: ${python_bin}" >&2; exit 2; }
  command -v docker >/dev/null || { echo 'Docker is required for the container preflight.' >&2; exit 2; }
  "${python_bin}" -m pytest tests -q
  "${python_bin}" -m pytest tests/test_portal_openapi_contract.py -q
  az bicep build --file deploy/azure/main.bicep --stdout >/dev/null
  docker build --platform linux/amd64 -f deploy/docker/Dockerfile \
    -t "azure-notable-preflight:${AZURE_DEPLOYMENT_PREFIX,,}" .
  if [[ "${deploy_portal}" == true ]]; then
    command -v npm >/dev/null || { echo 'npm is required for the portal preflight.' >&2; exit 2; }
    export VITE_PORTAL_OIDC_CLIENT_ID="${PORTAL_OIDC_CLIENT_ID}"
    export VITE_PORTAL_OIDC_AUTHORITY="${PORTAL_OIDC_AUTHORITY}"
    export VITE_PORTAL_OIDC_API_SCOPE="${PORTAL_OIDC_API_SCOPE}"
    unset VITE_PORTAL_API_BASE_URL
    npm --prefix frontend/analyst-portal ci
    npm --prefix frontend/analyst-portal test
    npm --prefix frontend/analyst-portal run build
  fi
}

# Complete source, contract, IaC, and image checks before Azure mutation.
run_preflight

az account set --subscription "${AZURE_SUBSCRIPTION_ID}"
resource_manager_endpoint="$(az cloud show --name AzureUSGovernment --query endpoints.resourceManager -o tsv)"
if [[ "${cosmos_continuous_backup_enabled,,}" == 'true' ]]; then
  existing_cosmos_backup_type="$(az cosmosdb show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${COSMOS_ACCOUNT_NAME}" \
    --query 'backupPolicy.type' -o tsv 2>/dev/null || true)"
  if [[ "${existing_cosmos_backup_type,,}" == 'periodic' && "${cosmos_continuous_backup_migration_acknowledged,,}" != 'true' ]]; then
    echo 'Enabling continuous backup on an existing Periodic Cosmos account is one-way; set COSMOS_CONTINUOUS_BACKUP_MIGRATION_ACKNOWLEDGED=true to acknowledge the migration.' >&2
    exit 2
  fi
fi
if [[ "${cosmos_zone_redundant,,}" == 'true' ]]; then
  existing_cosmos_zone="$(az cosmosdb show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${COSMOS_ACCOUNT_NAME}" \
    --query 'locations[0].isZoneRedundant' -o tsv 2>/dev/null || true)"
  if [[ -n "${existing_cosmos_zone}" && "${existing_cosmos_zone,,}" != 'true' ]]; then
    echo 'COSMOS_ZONE_REDUNDANT cannot be enabled in place on an existing non-zonal serverless account; create a new zonal account and migrate.' >&2
    exit 2
  fi
fi
if [[ -n "${ALERT_ACTION_GROUP_RESOURCE_ID:-}" ]]; then
  action_group_type="$(az resource show --ids "${ALERT_ACTION_GROUP_RESOURCE_ID}" --query type -o tsv)"
  if [[ "${action_group_type,,}" != 'microsoft.insights/actiongroups' ]]; then
    echo 'ALERT_ACTION_GROUP_RESOURCE_ID must identify an existing Microsoft.Insights/actionGroups resource.' >&2
    exit 2
  fi
fi
acr_login_server="$(az resource show --ids "${CONTAINER_REGISTRY_RESOURCE_ID}" --query properties.loginServer -o tsv)"
if [[ "${CONTAINER_IMAGE_URI,,}" != "${acr_login_server,,}/"* ]]; then
  echo "Container image registry does not match ${CONTAINER_REGISTRY_RESOURCE_ID}." >&2
  exit 2
fi

az group create --name "${AZURE_RESOURCE_GROUP}" --location "${LOCATION}" --output none
deployment_name="${AZURE_DEPLOYMENT_PREFIX}-$(date -u +%Y%m%d%H%M%S)"

run_group_deployment() {
  local operation="$1"
  az deployment group "${operation}" \
  --name "${deployment_name}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --template-file deploy/azure/main.bicep \
  --parameters \
    DeploymentPrefix="${AZURE_DEPLOYMENT_PREFIX}" \
    Location="${LOCATION}" \
    ContainerRegistryResourceId="${CONTAINER_REGISTRY_RESOURCE_ID}" \
    ContainerImageUri="${CONTAINER_IMAGE_URI}" \
    cloudEnvironment=AzureUSGovernment \
    AzureOpenAiEndpoint="${AZURE_OPENAI_ENDPOINT}" \
    AzureOpenAiResourceId="${AZURE_OPENAI_RESOURCE_ID}" \
    AzureOpenAiAnalysisDeployment="${AZURE_OPENAI_ANALYSIS_DEPLOYMENT}" \
    AzureOpenAiEmbeddingsDeployment="${AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT:-}" \
    AzureOpenAiPortalChatDeployment="${AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT:-}" \
    AzureSearchEndpoint="${AZURE_SEARCH_ENDPOINT:-}" \
    AzureSearchResourceId="${AZURE_SEARCH_RESOURCE_ID:-}" \
    RagAzureSearchIndex="${RAG_AZURE_SEARCH_INDEX:-}" \
    RagTenantId="${RAG_TENANT_ID:-}" \
    RagSourceStorageAccountUrl="${RAG_SOURCE_STORAGE_ACCOUNT_URL:-}" \
    RagSourceStorageAccountName="${RAG_SOURCE_STORAGE_ACCOUNT_NAME:-}" \
    RagSourceContainer="${RAG_SOURCE_CONTAINER:-}" \
    RagSourcePrefix="${RAG_SOURCE_PREFIX:-rag-sources}" \
    RagIngestQueueName="${RAG_INGEST_QUEUE_NAME:-rag-ingest-invocations}" \
    CaseQaAzureSearchIndex="${CASE_QA_AZURE_SEARCH_INDEX:-}" \
    KeyVaultName="${KEY_VAULT_NAME:-}" \
    CosmosAccountName="${COSMOS_ACCOUNT_NAME}" \
    CosmosDatabaseName="${COSMOS_DATABASE_NAME}" \
    CapabilityProfiles="${capability_profiles}" \
    ServiceNowDispositionSyncEnabled="${disposition_sync_enabled}" \
    ServiceNowBaseUrl="${SERVICENOW_BASE_URL:-https://your-instance.service-now.com}" \
    ServiceNowTimeoutSeconds="${SERVICENOW_TIMEOUT_SECONDS:-15}" \
    ServiceNowDispositionSyncTokenSecretName="${SERVICENOW_DISPOSITION_SYNC_TOKEN_SECRET_NAME:-}" \
    ServiceNowDispositionFieldMap="${SERVICENOW_DISPOSITION_FIELD_MAP:-/home/site/wwwroot/deploy/servicenow/disposition_field_map.example.json}" \
    ServiceNowDispositionCodeMap="${SERVICENOW_DISPOSITION_CODE_MAP:-/home/site/wwwroot/deploy/servicenow/disposition_code_map.example.json}" \
    ServiceNowDispositionBackfillDays="${SERVICENOW_DISPOSITION_BACKFILL_DAYS:-90}" \
    DispositionRetentionDays="${DISPOSITION_RETENTION_DAYS:-365}" \
    AllowPrivateOutboundEndpoints="${ALLOW_PRIVATE_OUTBOUND_ENDPOINTS:-false}" \
    CaseQaChatHistoryEnabled="${CASE_QA_CHAT_HISTORY_ENABLED:-false}" \
    FunctionsHostStorageAccountName="${FUNCTIONS_HOST_STORAGE_ACCOUNT_NAME}" \
    IsolateFunctionsHostStorage="${isolate_host_storage}" \
    AnalyzerHostStorageAccountName="${ANALYZER_HOST_STORAGE_ACCOUNT_NAME:-}" \
    EmbedHostStorageAccountName="${EMBED_HOST_STORAGE_ACCOUNT_NAME:-}" \
    DispositionHostStorageAccountName="${DISPOSITION_HOST_STORAGE_ACCOUNT_NAME:-}" \
    PortalHostStorageAccountName="${PORTAL_HOST_STORAGE_ACCOUNT_NAME:-}" \
    StorageSkuName="${storage_sku_name}" \
    BlobDataProtectionEnabled="${blob_data_protection_enabled}" \
    BlobSoftDeleteRetentionDays="${BLOB_SOFT_DELETE_RETENTION_DAYS:-30}" \
    ContainerSoftDeleteRetentionDays="${CONTAINER_SOFT_DELETE_RETENTION_DAYS:-30}" \
    PreviousVersionRetentionDays="${PREVIOUS_VERSION_RETENTION_DAYS:-30}" \
    StorageAccountNameInput="${INPUT_STORAGE_ACCOUNT_NAME}" \
    StorageAccountNameOutput="${OUTPUT_STORAGE_ACCOUNT_NAME}" \
    StorageAccountNamePortalUi="${PORTAL_UI_STORAGE_ACCOUNT_NAME:-}" \
    PortalUiDeployerPrincipalId="${PORTAL_UI_DEPLOYER_PRINCIPAL_ID:-}" \
    PortalAuthMode="${PORTAL_AUTH_MODE:-jwt}" \
    PortalJwtIssuer="${PORTAL_JWT_ISSUER:-}" \
    PortalJwtAudience="${PORTAL_JWT_AUDIENCE:-}" \
    PortalEntraRequiredAppRole="${PORTAL_ENTRA_REQUIRED_APP_ROLE:-}" \
    PortalChatTimeoutSec="${PORTAL_CHAT_TIMEOUT_SEC:-225}" \
    PortalChatDistributedQuotaEnabled="${PORTAL_CHAT_DISTRIBUTED_QUOTA_ENABLED:-true}" \
    ChatQuotaContainerName="${PORTAL_CHAT_QUOTA_CONTAINER:-${AZURE_DEPLOYMENT_PREFIX}-chat-quota}" \
    PortalChatPerUserMaxConcurrency="${PORTAL_CHAT_PER_USER_MAX_CONCURRENCY:-2}" \
    PortalChatQuotaWindowSeconds="${PORTAL_CHAT_QUOTA_WINDOW_SECONDS:-3600}" \
    PortalChatMaxRequestsPerWindow="${PORTAL_CHAT_MAX_REQUESTS_PER_WINDOW:-30}" \
    PortalChatMaxBudgetUnitsPerWindow="${PORTAL_CHAT_MAX_BUDGET_UNITS_PER_WINDOW:-100000}" \
    PortalChatBudgetUnitsPerRequest="${PORTAL_CHAT_BUDGET_UNITS_PER_REQUEST:-5000}" \
    PortalChatLeaseSeconds="${PORTAL_CHAT_LEASE_SECONDS:-300}" \
    PortalChatRequestDedupeSeconds="${PORTAL_CHAT_REQUEST_DEDUPE_SECONDS:-3600}" \
    AnalyzerMaxInstanceCount="${ANALYZER_MAX_INSTANCE_COUNT:-5}" \
    MaxCompressedInputBytes="${MAX_COMPRESSED_INPUT_BYTES:-1048576}" \
    EmbedMaxInstanceCount="${EMBED_MAX_INSTANCE_COUNT:-5}" \
    FunctionPlanZoneRedundant="${function_plan_zone_redundant}" \
    CosmosZoneRedundant="${cosmos_zone_redundant}" \
    CosmosContinuousBackupEnabled="${cosmos_continuous_backup_enabled}" \
    DeploymentEnvironment="${deployment_environment}" \
    AlertActionGroupResourceId="${ALERT_ACTION_GROUP_RESOURCE_ID:-}" \
    PortalSyntheticCheckName="${PORTAL_SYNTHETIC_CHECK_NAME:-}" \
    PoisonQueueDepthThreshold="${POISON_QUEUE_DEPTH_THRESHOLD:-0}" \
    AnalyzerQueueBacklogThreshold="${ANALYZER_QUEUE_BACKLOG_THRESHOLD:-100}" \
    EmbedQueueBacklogThreshold="${EMBED_QUEUE_BACKLOG_THRESHOLD:-100}" \
    ModelErrorThreshold="${MODEL_ERROR_THRESHOLD:-5}" \
    ModelThrottleThreshold="${MODEL_THROTTLE_THRESHOLD:-5}" \
    CosmosThrottleThreshold="${COSMOS_THROTTLE_THRESHOLD:-10}" \
    FrontDoor5xxPercentageThreshold="${FRONTDOOR_5XX_PERCENTAGE_THRESHOLD:-5}" \
    DispositionCompletionGraceHours="${DISPOSITION_COMPLETION_GRACE_HOURS:-26}" \
    QueueTelemetryMaxAgeMinutes="${QUEUE_TELEMETRY_MAX_AGE_MINUTES:-10}" \
    --output none
}

# Ask Resource Manager to validate the exact parameters before it creates resources.
run_group_deployment validate
run_group_deployment create

analyzer_name="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.AnalyzerFunctionAppName.value -o tsv)"
embed_name="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.EmbedFunctionAppName.value -o tsv)"
disposition_name="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.DispositionFunctionAppName.value -o tsv)"
portal_name="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.PortalFunctionAppName.value -o tsv)"
frontdoor_profile="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.PortalFrontDoorProfileName.value -o tsv)"
frontdoor_host="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.PortalFrontDoorHostName.value -o tsv)"
workspace_customer_id="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.outputs.LogAnalyticsWorkspaceCustomerId.value -o tsv)"

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
        --url "${resource_manager_endpoint%/}${app_id}/hostruntime/admin/host/status?api-version=2022-03-01" \
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

for app in "${analyzer_name}" "${embed_name}" "${disposition_name}"; do
  verify_no_forbidden_settings "${app}"
  verify_managed_identity_configuration "${app}"
done

wait_for_function_host "${analyzer_name}" intake_blob analyzer_queue
wait_for_function_host "${embed_name}" case_embed_queue
if [[ "${disposition_sync_enabled,,}" == 'true' ]]; then
  wait_for_function_host "${disposition_name}" disposition_sync_timer operations_monitor_timer
else
  wait_for_function_host "${disposition_name}" operations_monitor_timer
fi

wait_for_queue_depth_telemetry() {
  local expected actual query
  expected="$(printf '%s\n' \
    webjobs-blobtrigger-poison \
    notable-analysis-jobs \
    notable-analysis-jobs-poison \
    case-embed-invocations \
    case-embed-invocations-poison | LC_ALL=C sort)"
  query="AppTraces | where TimeGenerated > ago(15m) and Message startswith 'notable.queue.depth.v1 ' | extend sample=parse_json(substring(Message, strlen('notable.queue.depth.v1 '))) | where toint(sample.schema_version) == 1 | summarize arg_max(TimeGenerated, *) by QueueName=tostring(sample.queue_name) | project QueueName"
  for attempt in {1..48}; do
    actual="$(az monitor log-analytics query --workspace "${workspace_customer_id}" --analytics-query "${query}" --query 'tables[0].rows[][0]' -o tsv 2>/dev/null | sed '/^$/d' | LC_ALL=C sort || true)"
    [[ "${actual}" == "${expected}" ]] && return
    sleep 10
  done
  echo 'The operations monitor did not emit fresh structured depth telemetry for all five queues.' >&2
  exit 1
}

if [[ -n "${ALERT_ACTION_GROUP_RESOURCE_ID:-}" ]]; then
  wait_for_queue_depth_telemetry
fi

validate_monitoring_alerts() {
  local alert_name alert_id enabled action_group
  local expected_alerts
  expected_alerts="$(az deployment group show --name "${deployment_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query 'properties.outputs.MonitoringAlertRuleNames.value[]' -o tsv)"
  if [[ -z "${ALERT_ACTION_GROUP_RESOURCE_ID:-}" ]]; then
    [[ -z "${expected_alerts}" ]] || { echo 'Alert rules were unexpectedly returned without an action group.' >&2; exit 1; }
    return
  fi
  while IFS= read -r alert_name; do
    [[ -z "${alert_name}" ]] && continue
    alert_id="$(az resource list --resource-group "${AZURE_RESOURCE_GROUP}" --name "${alert_name}" --query '[0].id' -o tsv)"
    [[ -n "${alert_id}" ]] || { echo "Expected monitoring alert was not deployed: ${alert_name}" >&2; exit 1; }
    enabled="$(az resource show --ids "${alert_id}" --query properties.enabled -o tsv)"
    [[ "${enabled,,}" == 'true' ]] || { echo "Monitoring alert is not enabled: ${alert_name}" >&2; exit 1; }
    action_group="$(az resource show --ids "${alert_id}" --query 'properties.actions.actionGroups[0]' -o tsv 2>/dev/null || true)"
    if [[ -z "${action_group}" ]]; then
      action_group="$(az resource show --ids "${alert_id}" --query 'properties.actions[0].actionGroupId' -o tsv 2>/dev/null || true)"
    fi
    [[ "${action_group,,}" == "${ALERT_ACTION_GROUP_RESOURCE_ID,,}" ]] || { echo "Monitoring alert is not wired to the supplied action group: ${alert_name}" >&2; exit 1; }
  done <<<"${expected_alerts}"
}

validate_monitoring_alerts

approve_expected_frontdoor_connection() {
  local target_id="$1"
  local expected_description="$2"
  local origin_group="$3"
  local origin_name="$4"
  local origin_state connection_state connection_id
  local -a connection_ids=()
  origin_state="$(az afd origin show --resource-group "${AZURE_RESOURCE_GROUP}" --profile-name "${frontdoor_profile}" --origin-group-name "${origin_group}" --origin-name "${origin_name}" --query sharedPrivateLinkResource.status -o tsv)"
  [[ "${origin_state}" == 'Approved' ]] && return
  mapfile -t connection_ids < <(
    az network private-endpoint-connection list \
      --id "${target_id}" \
      --query "[?properties.privateLinkServiceConnectionState.status=='Pending' && properties.privateLinkServiceConnectionState.description=='${expected_description}'].id" \
      -o tsv
  )
  [[ ${#connection_ids[@]} -eq 1 && -n "${connection_ids[0]}" ]] || {
    echo "Expected exactly one pending Front Door request '${expected_description}' on ${target_id}." >&2
    exit 1
  }
  connection_id="${connection_ids[0]}"
  az network private-endpoint-connection approve \
    --id "${connection_id}" \
    --description 'Approved Front Door Premium managed private origin' \
    --output none
  for attempt in {1..30}; do
    connection_state="$(az network private-endpoint-connection show --id "${connection_id}" --query properties.privateLinkServiceConnectionState.status -o tsv)"
    [[ "${connection_state}" == 'Approved' ]] && return
    sleep 10
  done
  echo "Front Door private endpoint connection did not reach Approved on ${target_id}." >&2
  exit 1
}

expect_direct_origin_denied() {
  local url="$1"
  local status
  status="$(curl --silent --show-error --max-time 20 --output /dev/null --write-out '%{http_code}' \
    --header "Authorization: Bearer ${PORTAL_VALIDATION_BEARER_TOKEN}" "${url}" || true)"
  if [[ "${status}" =~ ^2 ]]; then
    echo "Direct portal origin unexpectedly returned success: ${url}" >&2
    exit 1
  fi
}

if [[ "${deploy_portal}" == true ]]; then
  verify_no_forbidden_settings "${portal_name}"
  verify_managed_identity_configuration "${portal_name}"
  wait_for_function_host "${portal_name}" portal_http

  upload_ready=false
  for attempt in {1..18}; do
    if az storage blob upload-batch \
      --auth-mode login \
      --account-name "${PORTAL_UI_STORAGE_ACCOUNT_NAME}" \
      --destination '$web' \
      --source frontend/analyst-portal/dist \
      --overwrite true \
      --output none; then
      upload_ready=true
      break
    fi
    sleep 10
  done
  [[ "${upload_ready}" == true ]] || { echo 'Portal UI upload failed after RBAC propagation wait.' >&2; exit 1; }

  subscription_id="$(az account show --query id -o tsv)"
  portal_storage_id="/subscriptions/${subscription_id}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/${PORTAL_UI_STORAGE_ACCOUNT_NAME}"
  portal_function_id="$(az functionapp show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${portal_name}" --query id -o tsv)"
  portal_function_host="$(az functionapp show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${portal_name}" --query defaultHostName -o tsv)"
  approve_expected_frontdoor_connection "${portal_storage_id}" 'Front Door private static website origin' portal-ui portal-web
  approve_expected_frontdoor_connection "${portal_function_id}" 'Front Door private portal Function origin' portal-api portal-function

  for origin in portal-function portal-web; do
    case "${origin}" in
      portal-function) group=portal-api ;;
      portal-web) group=portal-ui ;;
    esac
    for attempt in {1..30}; do
      state="$(az afd origin show --resource-group "${AZURE_RESOURCE_GROUP}" --profile-name "${frontdoor_profile}" --origin-group-name "${group}" --origin-name "${origin}" --query sharedPrivateLinkResource.status -o tsv 2>/dev/null || true)"
      [[ "${state}" == 'Approved' ]] && break
      sleep 10
    done
    [[ "${state}" == 'Approved' ]] || { echo "Front Door origin ${origin} was not approved." >&2; exit 1; }
  done

  [[ "$(az storage account show --ids "${portal_storage_id}" --query publicNetworkAccess -o tsv)" == 'Disabled' ]] || exit 1
  [[ "$(az functionapp show --ids "${portal_function_id}" --query publicNetworkAccess -o tsv)" == 'Disabled' ]] || exit 1

  expect_direct_origin_denied "https://${portal_function_host}/ready"
  curl --fail --silent --show-error --max-time 240 \
    --header "Authorization: Bearer ${PORTAL_VALIDATION_BEARER_TOKEN}" \
    "https://${frontdoor_host}/ready" >/dev/null

  if [[ "${deployment_environment}" == 'production' ]]; then
    synthetic_name_b64="$(printf '%s' "${PORTAL_SYNTHETIC_CHECK_NAME}" | base64 | tr -d '\n')"
    synthetic_query="let checkName=base64_decode_tostring('${synthetic_name_b64}'); AppAvailabilityResults | where TimeGenerated > ago(15m) and Name == checkName | summarize Results=count(), Successes=countif(Success == true)"
    synthetic_ready=false
    for attempt in {1..30}; do
      synthetic_row="$(az monitor log-analytics query --workspace "${workspace_customer_id}" --analytics-query "${synthetic_query}" --query 'tables[0].rows[0]' -o tsv 2>/dev/null || true)"
      read -r synthetic_results synthetic_successes <<<"${synthetic_row}"
      if [[ "${synthetic_results:-0}" =~ ^[0-9]+$ && "${synthetic_successes:-0}" =~ ^[0-9]+$ && ${synthetic_results} -gt 0 && ${synthetic_successes} -gt 0 ]]; then
        synthetic_ready=true
        break
      fi
      sleep 10
    done
    [[ "${synthetic_ready}" == true ]] || {
      echo 'Production requires a fresh successful AppAvailabilityResults row from the named customer authenticated /ready monitor.' >&2
      exit 1
    }
  fi
fi

deployment_report_path="${DEPLOYMENT_REPORT_PATH:-deployment-results/${deployment_name}.json}"
mkdir -p "$(dirname -- "${deployment_report_path}")"
az deployment group show \
  --name "${deployment_name}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --query "{schema_version:'1',cloud:properties.parameters.cloudEnvironment.value,deployment_name:name,resource_group:resourceGroup,location:properties.parameters.Location.value,image_digest:properties.parameters.ContainerImageUri.value,capability_profiles:properties.parameters.CapabilityProfiles.value,provisioning_state:properties.provisioningState,completed_at:properties.timestamp,outputs:properties.outputs,verification:{source_and_image_preflight:'passed',template_validation:'passed',runtime_and_security_checks:'passed'}}" \
  --output json >"${deployment_report_path}"

echo "Deployment ${deployment_name} completed: ${analyzer_name}, ${embed_name}, ${disposition_name}${portal_name:+, ${portal_name}}."
echo "Deployment report: ${deployment_report_path}"
