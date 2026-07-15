[CmdletBinding()]
param(
    [switch]$StagingGate,
    [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
    [string]$DeploymentName = $env:AZURE_DEPLOYMENT_NAME
)

$ErrorActionPreference = "Stop"
$projectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $projectDir
try {
    Write-Host "Running offline Azure staging contracts"
    $pythonTest = if ($env:PYTHON) { $env:PYTHON } else { "python" }
    & $pythonTest -m pytest -q `
        tests/test_private_intake_contract.py `
        tests/test_portal_openapi_contract.py `
        tests/test_portal_jwt.py `
        tests/test_portal_handler.py `
        tests/test_portal_api_contract.py `
        tests/test_azure_openai_gateway.py `
        tests/test_cosmos_store.py `
        tests/test_disposition_sync_handler.py `
        tests/test_servicenow_disposition_sync.py
    if ($LASTEXITCODE -ne 0) { throw "Offline staging contracts failed" }
    if (-not $StagingGate) {
        Write-Host "Offline gate passed. Use -StagingGate only from the isolated Azure staging runner."
        return
    }

    if (-not $ResourceGroup -or -not $DeploymentName) { throw "ResourceGroup and DeploymentName are required" }
    if ($env:STAGING_CHAOS_CONFIRMATION -ne "isolated-nonproduction") {
        throw "Set STAGING_CHAOS_CONFIRMATION=isolated-nonproduction after verifying the dedicated staging subscription"
    }
    $activeSubscription = (& az account show --query id -o tsv).Trim()
    if (-not $env:STAGING_SUBSCRIPTION_ID -or $activeSubscription -ne $env:STAGING_SUBSCRIPTION_ID) {
        throw "Active subscription does not match STAGING_SUBSCRIPTION_ID; refusing live mutation"
    }

    $outputs = & az deployment group show -g $ResourceGroup -n $DeploymentName --query properties.outputs -o json | ConvertFrom-Json
    function Output-Value([string]$Name) { return [string]$outputs.$Name.value }
    $inputAccount = Output-Value "InputStorageAccountName"
    $outputAccount = Output-Value "OutputStorageAccountName"
    $analyzerApp = Output-Value "AnalyzerFunctionAppName"
    $embedApp = Output-Value "EmbedFunctionAppName"
    $portalHost = Output-Value "PortalFrontDoorHostName"
    $portalApp = Output-Value "PortalFunctionAppName"
    $analyzerQueue = Output-Value "AnalyzerQueueName"
    $embedQueue = Output-Value "CaseEmbedQueueName"

    foreach ($account in @($inputAccount, $outputAccount)) {
        $publicAccess = (& az storage account show -g $ResourceGroup -n $account --query publicNetworkAccess -o tsv).Trim()
        if ($publicAccess -ne "Disabled") { throw "Storage public network access is not disabled for $account" }
    }
    if ($portalApp) {
        $publicAccess = (& az functionapp show -g $ResourceGroup -n $portalApp --query publicNetworkAccess -o tsv).Trim()
        if ($publicAccess -ne "Disabled") { throw "Portal Function public network access is not disabled" }
    }

    function Get-Setting([string]$App, [string]$Name) {
        return (& az functionapp config appsettings list -g $ResourceGroup -n $App --query "[?name=='$Name'].value | [0]" -o tsv).Trim()
    }
    foreach ($app in @($analyzerApp, $embedApp)) {
        if ((Get-Setting $app "SPLUNK_SINK_ENABLED") -eq "true") { throw "Consequential Splunk sink is enabled on $app" }
        if ((Get-Setting $app "SERVICENOW_CREATE_ENABLED") -eq "true") { throw "Consequential ServiceNow create is enabled on $app" }
    }

    $tempDir = Join-Path ([IO.Path]::GetTempPath()) ("azure-notable-staging-" + [guid]::NewGuid())
    New-Item -ItemType Directory $tempDir | Out-Null
    $queueWasChanged = $false
    try {
        function New-Fixture([string]$Id) {
            $path = Join-Path $tempDir "$Id.json"
            @{ finding_id=$Id; event_time="2026-01-01T00:00:00Z"; rule_name="synthetic staging fixture"; description="Non-production benign pipeline acceptance event" } |
                ConvertTo-Json -Compress | Set-Content -Encoding utf8NoBOM $path
            return $path
        }
        function Send-Fixture([string]$Id) {
            $path = New-Fixture $Id
            & az storage blob upload --auth-mode login --account-name $inputAccount --container-name input --name "incoming/$Id.json" --file $path --overwrite true --output none
            if ($LASTEXITCODE -ne 0) { throw "Private upload failed for $Id" }
        }
        function Wait-Blob([string]$Name, [int]$LimitSeconds = 900) {
            for ($elapsed = 0; $elapsed -lt $LimitSeconds; $elapsed += 10) {
                $exists = (& az storage blob exists --auth-mode login --account-name $outputAccount --container-name output --name $Name --query exists -o tsv).Trim()
                if ($exists -eq "true") { return }
                Start-Sleep 10
            }
            throw "Timed out waiting for $Name"
        }
        function Wait-Queue([string]$Account, [string]$Queue, [string]$Marker, [int]$LimitSeconds = 1800) {
            for ($elapsed = 0; $elapsed -lt $LimitSeconds; $elapsed += 10) {
                $messages = & az storage message peek --auth-mode login --account-name $Account --queue-name $Queue --num-messages 32 -o json 2>$null
                if ($LASTEXITCODE -eq 0 -and ($messages -join "`n").Contains($Marker)) { return }
                Start-Sleep 10
            }
            throw "Timed out waiting for poison queue $Queue"
        }

        $runId = "staging-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
        Send-Fixture $runId
        Wait-Blob "reports/$runId.json"

        $maxInstancesText = Get-Setting $analyzerApp "WEBSITE_MAX_DYNAMIC_APPLICATION_SCALE_OUT"
        $maxInstances = 5
        if ($maxInstancesText -match '^[1-9][0-9]*$') { $maxInstances = [int]$maxInstancesText }
        $burstCount = 3 * $maxInstances
        Write-Host "Publishing $burstCount synthetic intake objects (3x analyzer cap $maxInstances)"
        1..$burstCount | ForEach-Object { Send-Fixture "$runId-burst-$_" }
        1..$burstCount | ForEach-Object { Wait-Blob "reports/$runId-burst-$_.json" 1800 }

        Send-Fixture $runId
        Wait-Blob "reports/$runId.json"

        $analyzerMessage = @{ schema_version=1; container_name="input"; blob_name="incoming/$runId-missing.json"; etag='"staging-missing-etag"'; size_bytes=1; last_modified="2026-01-01T00:00:00Z" } | ConvertTo-Json -Compress
        $embedMessage = @{ schema_version=1; case_envelope_container="output"; case_envelope_blob_name="cases/2026/01/01/$runId-missing.json" } | ConvertTo-Json -Compress
        & az storage message put --auth-mode login --account-name $outputAccount --queue-name $analyzerQueue --content $analyzerMessage --output none
        & az storage message put --auth-mode login --account-name $outputAccount --queue-name $embedQueue --content $embedMessage --output none
        Wait-Queue $outputAccount "$analyzerQueue-poison" $runId
        Wait-Queue $outputAccount "$embedQueue-poison" $runId

        $failureQueue = "$runId-does-not-exist"
        & az functionapp config appsettings set -g $ResourceGroup -n $analyzerApp --settings "ANALYZER_QUEUE_NAME=$failureQueue" --output none
        $queueWasChanged = $true
        Send-Fixture "$runId-publication-failure"
        Wait-Queue $inputAccount "webjobs-blobtrigger-poison" "$runId-publication-failure"
        & az functionapp config appsettings set -g $ResourceGroup -n $analyzerApp --settings "ANALYZER_QUEUE_NAME=$analyzerQueue" --output none
        $queueWasChanged = $false

        $alertNames = @(& az monitor scheduled-query list -g $ResourceGroup --query '[].name' -o tsv) + @(& az monitor metrics alert list -g $ResourceGroup --query '[].name' -o tsv)
        foreach ($suffix in @("webjobs-blobtrigger-poison-nonempty", "notable-analysis-jobs-poison-nonempty", "case-embed-invocations-poison-nonempty", "function-failures", "function-timeouts")) {
            if (-not ($alertNames | Where-Object { $_.Trim().EndsWith($suffix) })) { throw "Required enabled alert rule ending in $suffix was not found" }
        }

        if ($portalHost) {
            if (-not $env:PORTAL_TEST_BEARER_TOKEN) { throw "PORTAL_TEST_BEARER_TOKEN is required for portal staging" }
            $headers = @{ Authorization = "Bearer $($env:PORTAL_TEST_BEARER_TOKEN)" }
            $response = Invoke-WebRequest -Uri "https://$portalHost/ready" -Headers $headers -TimeoutSec 30
            if ($response.StatusCode -ne 200) { throw "Authenticated /ready failed" }
        }

        $dispositionApp = (& az functionapp list -g $ResourceGroup --query "[?contains(name, 'disposition')].name | [0]" -o tsv).Trim()
        if ($dispositionApp -and (Get-Setting $dispositionApp "SERVICENOW_DISPOSITION_SYNC_ENABLED") -eq "true") {
            throw "Disposition sync must remain disabled during the staging dry run"
        }
        Write-Host "Azure staging gate passed. Poison messages are retained for recovery evidence."
    }
    finally {
        if ($queueWasChanged) {
            & az functionapp config appsettings set -g $ResourceGroup -n $analyzerApp --settings "ANALYZER_QUEUE_NAME=$analyzerQueue" --output none | Out-Null
        }
        Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
