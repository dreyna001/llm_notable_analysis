Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$required = @(
    'AZURE_SUBSCRIPTION_ID', 'AZURE_RESOURCE_GROUP', 'AZURE_DEPLOYMENT_PREFIX',
    'CONTAINER_REGISTRY_RESOURCE_ID', 'CONTAINER_IMAGE_URI',
    'AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL', 'AZURE_AI_FOUNDRY_RESOURCE_ID',
    'FUNCTIONS_HOST_STORAGE_ACCOUNT_NAME', 'INPUT_STORAGE_ACCOUNT_NAME',
    'OUTPUT_STORAGE_ACCOUNT_NAME', 'COSMOS_ACCOUNT_NAME', 'COSMOS_DATABASE_NAME'
)
foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Required environment variable is unset: $name"
    }
}
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required.'
}
if ($env:CONTAINER_IMAGE_URI -notmatch '@sha256:[0-9a-fA-F]{64}$') {
    throw 'CONTAINER_IMAGE_URI must be pinned to an immutable @sha256 digest.'
}

$location = if ($env:AZURE_LOCATION) { $env:AZURE_LOCATION } else { 'eastus' }
$capabilityProfiles = if ($env:CAPABILITY_PROFILES) { $env:CAPABILITY_PROFILES } else { 'core' }
$capabilityProfiles = $capabilityProfiles -replace '\s', ''
$deployPortal = ",${capabilityProfiles},".ToLowerInvariant().Contains(',analyst_portal,')
if ($deployPortal) {
    $portalRequired = @(
        'PORTAL_UI_STORAGE_ACCOUNT_NAME', 'PORTAL_UI_DEPLOYER_PRINCIPAL_ID',
        'PORTAL_JWT_ISSUER', 'PORTAL_JWT_AUDIENCE', 'APIM_PUBLISHER_EMAIL',
        'AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_RESOURCE_ID',
        'AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT', 'AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT',
        'PORTAL_VALIDATION_BEARER_TOKEN'
    )
    foreach ($name in $portalRequired) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
            throw "Required analyst-portal environment variable is unset: $name"
        }
    }
    if (
        $env:PORTAL_AUTH_MODE -ieq 'iam' -and
        [string]::IsNullOrWhiteSpace($env:PORTAL_ENTRA_REQUIRED_APP_ROLE)
    ) {
        throw 'PORTAL_ENTRA_REQUIRED_APP_ROLE is required when PORTAL_AUTH_MODE=iam.'
    }
}
az account set --subscription $env:AZURE_SUBSCRIPTION_ID
$acrLoginServer = az resource show --ids $env:CONTAINER_REGISTRY_RESOURCE_ID --query properties.loginServer -o tsv
if (-not $env:CONTAINER_IMAGE_URI.StartsWith("$acrLoginServer/", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Container image registry does not match CONTAINER_REGISTRY_RESOURCE_ID.'
}

az group create --name $env:AZURE_RESOURCE_GROUP --location $location --output none
$deploymentName = "$($env:AZURE_DEPLOYMENT_PREFIX)-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
$parameters = @(
    "DeploymentPrefix=$($env:AZURE_DEPLOYMENT_PREFIX)",
    "Location=$location",
    "ContainerRegistryResourceId=$($env:CONTAINER_REGISTRY_RESOURCE_ID)",
    "ContainerImageUri=$($env:CONTAINER_IMAGE_URI)",
    "AzureAiFoundryAnthropicBaseUrl=$($env:AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL)",
    "AzureAiFoundryResourceId=$($env:AZURE_AI_FOUNDRY_RESOURCE_ID)",
    "AzureAiFoundryAnalysisDeployment=$(if ($env:AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT) { $env:AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT } else { 'claude-sonnet-4-6' })",
    "AzureOpenAiEndpoint=$($env:AZURE_OPENAI_ENDPOINT)",
    "AzureOpenAiResourceId=$($env:AZURE_OPENAI_RESOURCE_ID)",
    "AzureOpenAiEmbeddingsDeployment=$($env:AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT)",
    "AzureOpenAiPortalChatDeployment=$($env:AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT)",
    "AzureSearchEndpoint=$($env:AZURE_SEARCH_ENDPOINT)",
    "AzureSearchResourceId=$($env:AZURE_SEARCH_RESOURCE_ID)",
    "RagAzureSearchIndex=$($env:RAG_AZURE_SEARCH_INDEX)",
    "KeyVaultName=$($env:KEY_VAULT_NAME)",
    "CosmosAccountName=$($env:COSMOS_ACCOUNT_NAME)",
    "CosmosDatabaseName=$($env:COSMOS_DATABASE_NAME)",
    "CapabilityProfiles=$capabilityProfiles",
    "ServiceNowDispositionSyncEnabled=$(if ($env:SERVICENOW_DISPOSITION_SYNC_ENABLED) { $env:SERVICENOW_DISPOSITION_SYNC_ENABLED } else { 'false' })",
    "CaseQaChatHistoryEnabled=$(if ($env:CASE_QA_CHAT_HISTORY_ENABLED) { $env:CASE_QA_CHAT_HISTORY_ENABLED } else { 'false' })",
    "FunctionsHostStorageAccountName=$($env:FUNCTIONS_HOST_STORAGE_ACCOUNT_NAME)",
    "StorageAccountNameInput=$($env:INPUT_STORAGE_ACCOUNT_NAME)",
    "StorageAccountNameOutput=$($env:OUTPUT_STORAGE_ACCOUNT_NAME)",
    "StorageAccountNamePortalUi=$($env:PORTAL_UI_STORAGE_ACCOUNT_NAME)",
    "PortalUiDeployerPrincipalId=$($env:PORTAL_UI_DEPLOYER_PRINCIPAL_ID)",
    "PortalAuthMode=$(if ($env:PORTAL_AUTH_MODE) { $env:PORTAL_AUTH_MODE } else { 'jwt' })",
    "PortalJwtIssuer=$($env:PORTAL_JWT_ISSUER)",
    "PortalJwtAudience=$($env:PORTAL_JWT_AUDIENCE)",
    "PortalEntraRequiredAppRole=$($env:PORTAL_ENTRA_REQUIRED_APP_ROLE)",
    "ApiManagementPublisherEmail=$($env:APIM_PUBLISHER_EMAIL)",
    "ApiManagementPublisherName=$(if ($env:APIM_PUBLISHER_NAME) { $env:APIM_PUBLISHER_NAME } else { 'Notable Analysis' })",
    "PortalChatTimeoutSec=$(if ($env:PORTAL_CHAT_TIMEOUT_SEC) { $env:PORTAL_CHAT_TIMEOUT_SEC } else { '225' })"
)
az deployment group create --name $deploymentName --resource-group $env:AZURE_RESOURCE_GROUP --template-file deploy/azure/main.bicep --parameters $parameters --output none

$analyzer = az deployment group show --name $deploymentName --resource-group $env:AZURE_RESOURCE_GROUP --query properties.outputs.AnalyzerFunctionAppName.value -o tsv
$embed = az deployment group show --name $deploymentName --resource-group $env:AZURE_RESOURCE_GROUP --query properties.outputs.EmbedFunctionAppName.value -o tsv
$portal = "$(az deployment group show --name $deploymentName --resource-group $env:AZURE_RESOURCE_GROUP --query properties.outputs.PortalFunctionAppName.value -o tsv)".Trim()
$apim = "$(az deployment group show --name $deploymentName --resource-group $env:AZURE_RESOURCE_GROUP --query properties.outputs.PortalApiManagementName.value -o tsv)".Trim()
$frontDoorProfile = "$(az deployment group show --name $deploymentName --resource-group $env:AZURE_RESOURCE_GROUP --query properties.outputs.PortalFrontDoorProfileName.value -o tsv)".Trim()
$frontDoorHost = "$(az deployment group show --name $deploymentName --resource-group $env:AZURE_RESOURCE_GROUP --query properties.outputs.PortalFrontDoorHostName.value -o tsv)".Trim()

$forbiddenSettingPattern = '^(AZUREWEBJOBSSTORAGE|AZUREWEBJOBSDASHBOARD|WEBSITE_CONTENTAZUREFILECONNECTIONSTRING|WEBSITE_CONTENTSHARE)$|(^|_)(DOCKER_REGISTRY_SERVER|ACR|AZURE_CONTAINER_REGISTRY|CONTAINER_REGISTRY)(_|$).*(USERNAME|PASSWORD|API_?KEY|ACCESS_?KEY|KEY|TOKEN|SECRET|CREDENTIAL|CONNECTION_?STRING)|(^|_)(AZURE_)?(STORAGE|BLOB|QUEUE|TABLE|FILE|FILES)(_|$).*(ACCOUNT_?KEY|ACCESS_?KEY|API_?KEY|KEY|CONNECTION_?STRING|SAS(_TOKEN)?|PASSWORD|SECRET)|(^|_)(AZURE_AI_FOUNDRY|AI_FOUNDRY|FOUNDRY|ANTHROPIC|AZURE_OPENAI|OPENAI|AZURE_SEARCH|COGNITIVE_SEARCH|SEARCH_SERVICE|SEARCH|COSMOSDB|COSMOS|AZURE_COSMOS)(_|$).*(API_?KEY|ACCOUNT_?KEY|ACCESS_?KEY|PRIMARY_?KEY|SECONDARY_?KEY|MASTER_?KEY|KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|CONNECTION_?STRING)'

function Assert-AzSucceeded {
    param([Parameter(Mandatory = $true)][string]$Operation)
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed while $Operation."
    }
}

function Get-AppSettingValue {
    param(
        [Parameter(Mandatory = $true)][string]$App,
        [Parameter(Mandatory = $true)][string]$SettingName
    )
    $value = az functionapp config appsettings list `
        --resource-group $env:AZURE_RESOURCE_GROUP `
        --name $App `
        --query "[?name=='$SettingName'].value | [0]" `
        -o tsv
    Assert-AzSucceeded -Operation "reading a required setting from $App"
    return "$value".Trim()
}

function Assert-NoForbiddenSettings {
    param([Parameter(Mandatory = $true)][string]$App)
    $settingNames = @(
        az functionapp config appsettings list `
            --resource-group $env:AZURE_RESOURCE_GROUP `
            --name $App `
            --query '[].name' `
            -o tsv
    )
    Assert-AzSucceeded -Operation "auditing app-setting names on $App"
    foreach ($settingName in $settingNames) {
        $normalizedName = "$settingName".Trim().ToUpperInvariant()
        if ($normalizedName -and $normalizedName -match $forbiddenSettingPattern) {
            throw "Forbidden credential, key, secret, connection-string, or Azure Files setting found on ${App}: $settingName."
        }
    }
}

function Assert-ManagedIdentityConfiguration {
    param([Parameter(Mandatory = $true)][string]$App)

    $identityIds = @(
        az functionapp identity show `
            --resource-group $env:AZURE_RESOURCE_GROUP `
            --name $App `
            --query 'keys(userAssignedIdentities)' `
            -o tsv
    ) | ForEach-Object { "$_".Trim() } | Where-Object { $_ }
    Assert-AzSucceeded -Operation "reading the managed identity attached to $App"
    if ($identityIds.Count -ne 1) {
        throw "$App must have exactly one user-assigned managed identity."
    }

    $identityClientId = "$(az identity show --ids $identityIds[0] --query clientId -o tsv)".Trim()
    Assert-AzSucceeded -Operation "resolving the managed identity attached to $App"
    $imageSetting = "$(az functionapp config show --resource-group $env:AZURE_RESOURCE_GROUP --name $App --query linuxFxVersion -o tsv)".Trim()
    Assert-AzSucceeded -Operation "reading the configured image from $App"
    $acrManagedIdentity = "$(az functionapp config show --resource-group $env:AZURE_RESOURCE_GROUP --name $App --query acrUseManagedIdentityCreds -o tsv)".Trim()
    Assert-AzSucceeded -Operation "reading the ACR authentication mode from $App"
    $acrManagedIdentityClientId = "$(az functionapp config show --resource-group $env:AZURE_RESOURCE_GROUP --name $App --query acrUserManagedIdentityID -o tsv)".Trim()
    Assert-AzSucceeded -Operation "reading the ACR managed identity from $App"
    if (
        $imageSetting -cne "DOCKER|$($env:CONTAINER_IMAGE_URI)" -or
        $acrManagedIdentity -ine 'true' -or
        $acrManagedIdentityClientId -ine $identityClientId
    ) {
        throw "Managed-identity image-pull configuration is not ready on $App."
    }

    $hostCredential = Get-AppSettingValue -App $App -SettingName 'AzureWebJobsStorage__credential'
    $hostClientId = Get-AppSettingValue -App $App -SettingName 'AzureWebJobsStorage__clientId'
    if ($hostCredential -ine 'managedidentity' -or $hostClientId -ine $identityClientId) {
        throw "Identity-based Functions host storage is not configured for the app identity on $App."
    }
    foreach ($service in @('blob', 'queue', 'table')) {
        $hostServiceUri = Get-AppSettingValue -App $App -SettingName "AzureWebJobsStorage__${service}ServiceUri"
        if ($hostServiceUri -notmatch '^https://' -or $hostServiceUri -match '(AccountKey|SharedAccessSignature|sig=)') {
            throw "Identity-based Functions host $service service configuration is not ready on $App."
        }
    }
}

function Wait-FunctionHost {
    param(
        [Parameter(Mandatory = $true)][string]$App,
        [Parameter(Mandatory = $true)][string[]]$ExpectedFunctions
    )

    $appId = "$(az functionapp show --resource-group $env:AZURE_RESOURCE_GROUP --name $App --query id -o tsv)".Trim()
    Assert-AzSucceeded -Operation "resolving the resource ID for $App"
    $expected = @($ExpectedFunctions | Sort-Object)
    foreach ($attempt in 1..18) {
        $appState = "$(az functionapp show --resource-group $env:AZURE_RESOURCE_GROUP --name $App --query state -o tsv 2>$null)".Trim()
        $hostState = "$(az rest --method get --url "https://management.azure.com${appId}/hostruntime/admin/host/status?api-version=2022-03-01" --query state -o tsv 2>$null)".Trim()
        $functionOutput = @(az functionapp function list --resource-group $env:AZURE_RESOURCE_GROUP --name $App --query '[].name' -o tsv 2>$null)
        $functionCommandSucceeded = $LASTEXITCODE -eq 0
        $actual = @(
            $functionOutput |
                ForEach-Object { ("$_".Trim() -split '/')[-1] } |
                Where-Object { $_ } |
                Sort-Object
        )
        $functionSetMatches = $functionCommandSucceeded -and (($actual -join "`n") -ceq ($expected -join "`n"))
        if ($appState -eq 'Running' -and $hostState -eq 'Running' -and $functionSetMatches) {
            return
        }
        Start-Sleep -Seconds 10
    }
    throw "$App did not reach a healthy Functions host with the exact expected enabled function set after managed-identity image-pull and host-storage propagation."
}

foreach ($app in @($analyzer, $embed)) {
    Assert-NoForbiddenSettings -App $app
    Assert-ManagedIdentityConfiguration -App $app
}

Wait-FunctionHost -App $analyzer -ExpectedFunctions @('intake_blob', 'analyzer_queue')
Wait-FunctionHost -App $embed -ExpectedFunctions @('case_embed_queue')

function Approve-PendingPrivateConnections {
    param([Parameter(Mandatory = $true)][string]$TargetResourceId)
    $connectionIds = @(
        az network private-endpoint-connection list `
            --id $TargetResourceId `
            --query "[?properties.privateLinkServiceConnectionState.status=='Pending'].id" `
            -o tsv
    ) | ForEach-Object { "$_".Trim() } | Where-Object { $_ }
    Assert-AzSucceeded -Operation "discovering pending Front Door connections on $TargetResourceId"
    foreach ($connectionId in $connectionIds) {
        az network private-endpoint-connection approve `
            --id $connectionId `
            --description 'Approved Front Door Premium managed private origin' `
            --output none
        Assert-AzSucceeded -Operation "approving a Front Door connection on $TargetResourceId"
    }
}

function Wait-PrivateConnectionsApproved {
    param([Parameter(Mandatory = $true)][string]$TargetResourceId)
    foreach ($attempt in 1..30) {
        $states = @(
            az network private-endpoint-connection list `
                --id $TargetResourceId `
                --query '[].properties.privateLinkServiceConnectionState.status' `
                -o tsv
        ) | ForEach-Object { "$_".Trim() } | Where-Object { $_ }
        if ($LASTEXITCODE -eq 0 -and $states.Count -gt 0 -and @($states | Where-Object { $_ -ne 'Approved' }).Count -eq 0) {
            return
        }
        Start-Sleep -Seconds 10
    }
    throw "Private endpoint connections did not all reach Approved on $TargetResourceId."
}

function Assert-DirectOriginDenied {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $response = Invoke-WebRequest `
            -Uri $Url `
            -Headers @{ Authorization = "Bearer $($env:PORTAL_VALIDATION_BEARER_TOKEN)" } `
            -TimeoutSec 20 `
            -UseBasicParsing
        $statusCode = [int]$response.StatusCode
    }
    catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        else {
            return
        }
    }
    if ($statusCode -ge 200 -and $statusCode -lt 300) {
        throw "Direct portal origin unexpectedly returned success: $Url"
    }
}

if ($deployPortal) {
    Assert-NoForbiddenSettings -App $portal
    Assert-ManagedIdentityConfiguration -App $portal
    Wait-FunctionHost -App $portal -ExpectedFunctions @('portal_http')

    Remove-Item Env:VITE_PORTAL_API_BASE_URL -ErrorAction SilentlyContinue
    npm --prefix frontend/analyst-portal ci
    if ($LASTEXITCODE -ne 0) { throw 'Portal npm install failed.' }
    npm --prefix frontend/analyst-portal test
    if ($LASTEXITCODE -ne 0) { throw 'Portal unit tests failed.' }
    npm --prefix frontend/analyst-portal run build
    if ($LASTEXITCODE -ne 0) { throw 'Portal production build failed.' }
    $uploadReady = $false
    foreach ($attempt in 1..18) {
        az storage blob upload-batch `
            --auth-mode login `
            --account-name $env:PORTAL_UI_STORAGE_ACCOUNT_NAME `
            --destination '$web' `
            --source frontend/analyst-portal/dist `
            --overwrite true `
            --output none
        if ($LASTEXITCODE -eq 0) {
            $uploadReady = $true
            break
        }
        Start-Sleep -Seconds 10
    }
    if (-not $uploadReady) { throw 'Portal UI upload failed after RBAC propagation wait.' }

    $subscriptionId = "$(az account show --query id -o tsv)".Trim()
    $portalStorageId = "/subscriptions/$subscriptionId/resourceGroups/$($env:AZURE_RESOURCE_GROUP)/providers/Microsoft.Storage/storageAccounts/$($env:PORTAL_UI_STORAGE_ACCOUNT_NAME)"
    $portalFunctionId = "$(az functionapp show --resource-group $env:AZURE_RESOURCE_GROUP --name $portal --query id -o tsv)".Trim()
    $apimId = "$(az apim show --resource-group $env:AZURE_RESOURCE_GROUP --name $apim --query id -o tsv)".Trim()
    foreach ($targetId in @($portalStorageId, $portalFunctionId, $apimId)) {
        Approve-PendingPrivateConnections -TargetResourceId $targetId
        Wait-PrivateConnectionsApproved -TargetResourceId $targetId
    }

    $origins = @(
        @{ Group = 'portal-chat'; Name = 'portal-function' },
        @{ Group = 'portal-api'; Name = 'portal-apim' },
        @{ Group = 'portal-ui'; Name = 'portal-web' }
    )
    foreach ($origin in $origins) {
        $state = ''
        foreach ($attempt in 1..30) {
            $state = "$(az afd origin show --resource-group $env:AZURE_RESOURCE_GROUP --profile-name $frontDoorProfile --origin-group-name $origin.Group --origin-name $origin.Name --query sharedPrivateLinkResource.status -o tsv 2>$null)".Trim()
            if ($state -eq 'Approved') { break }
            Start-Sleep -Seconds 10
        }
        if ($state -ne 'Approved') { throw "Front Door origin $($origin.Name) was not approved." }
    }

    # Never disable APIM public access until every Front Door managed endpoint is approved.
    az resource update --ids $apimId --set properties.publicNetworkAccess=Disabled --output none
    Assert-AzSucceeded -Operation 'disabling APIM public network access after origin approval'
    if ("$(az resource show --ids $apimId --query properties.publicNetworkAccess -o tsv)".Trim() -ne 'Disabled') { throw 'APIM public access is not disabled.' }
    if ("$(az storage account show --ids $portalStorageId --query publicNetworkAccess -o tsv)".Trim() -ne 'Disabled') { throw 'Portal UI storage public access is not disabled.' }
    if ("$(az functionapp show --ids $portalFunctionId --query publicNetworkAccess -o tsv)".Trim() -ne 'Disabled') { throw 'Portal Function public access is not disabled.' }

    Assert-DirectOriginDenied -Url "https://${apim}.azure-api.net/ready"
    Invoke-RestMethod `
        -Uri "https://${frontDoorHost}/ready" `
        -Headers @{ Authorization = "Bearer $($env:PORTAL_VALIDATION_BEARER_TOKEN)" } `
        -TimeoutSec 240 | Out-Null
}

Write-Host "Deployment $deploymentName completed: $analyzer, $embed$(if ($portal) { ", $portal" })."
