targetScope = 'resourceGroup'

param location string
param functionAppName string
param serverFarmId string
param functionSubnetId string
param containerImageUri string
param analyzerIdentityResourceId string
param analyzerIdentityClientId string
param analyzerIdentityPrincipalId string
param inputStorageAccountName string
param outputStorageAccountName string
param inputBlobServiceUri string
param inputQueueServiceUri string
param outputBlobServiceUri string
param outputQueueServiceUri string
param hostBlobServiceUri string
param hostQueueServiceUri string
param hostTableServiceUri string
param applicationInsightsConnectionString string
param keyVaultUri string = ''
param azureAiFoundryAnthropicBaseUrl string
param azureAiFoundryResourceId string
param azureAiFoundryAnalysisDeployment string = 'claude-sonnet-4-6'
param cosmosEndpoint string
param cosmosDatabaseName string
param sideEffectIdempotencyContainerName string
param caseIndexContainerName string = ''
param reportSinkMode string = 'blob'
param capabilityProfiles string = 'core'
param zoneRedundant bool = false

@minValue(1)
param maxCompressedInputBytes int = 1048576

@minValue(1)
param maxInstanceCount int = 5

@minValue(30)
@maxValue(1800)
param timeoutSeconds int = 360

var timeout = format(
  '00:{0}:{1}',
  padLeft(string(timeoutSeconds / 60), 2, '0'),
  padLeft(string(timeoutSeconds % 60), 2, '0')
)
var azureWebJobsStorage = [
  { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
  { name: 'AzureWebJobsStorage__clientId', value: analyzerIdentityClientId }
  { name: 'AzureWebJobsStorage__blobServiceUri', value: hostBlobServiceUri }
  { name: 'AzureWebJobsStorage__queueServiceUri', value: hostQueueServiceUri }
  { name: 'AzureWebJobsStorage__tableServiceUri', value: hostTableServiceUri }
]
var applicationSettings = concat(azureWebJobsStorage, [
  { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
  { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
  { name: 'AzureFunctionsJobHost__functionTimeout', value: timeout }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: applicationInsightsConnectionString }
  { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
  { name: 'WEBSITES_PORT', value: '8080' }
  { name: 'WEBSITE_VNET_ROUTE_ALL', value: '1' }
  { name: 'AZURE_CLIENT_ID', value: analyzerIdentityClientId }
  { name: 'INPUT_STORAGE_ACCOUNT_URL', value: inputBlobServiceUri }
  { name: 'INPUT_CONTAINER_NAME', value: 'input' }
  { name: 'OUTPUT_STORAGE_ACCOUNT_URL', value: outputBlobServiceUri }
  { name: 'OUTPUT_CONTAINER_NAME', value: 'output' }
  { name: 'ANALYZER_QUEUE_NAME', value: 'notable-analysis-jobs' }
  { name: 'CASE_EMBED_QUEUE_NAME', value: 'case-embed-invocations' }
  { name: 'InputStorage__blobServiceUri', value: inputBlobServiceUri }
  { name: 'InputStorage__queueServiceUri', value: inputQueueServiceUri }
  { name: 'InputStorage__credential', value: 'managedidentity' }
  { name: 'InputStorage__clientId', value: analyzerIdentityClientId }
  { name: 'OutputStorage__queueServiceUri', value: outputQueueServiceUri }
  { name: 'OutputStorage__credential', value: 'managedidentity' }
  { name: 'OutputStorage__clientId', value: analyzerIdentityClientId }
  { name: 'AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL', value: azureAiFoundryAnthropicBaseUrl }
  { name: 'AZURE_AI_FOUNDRY_RESOURCE_ID', value: azureAiFoundryResourceId }
  { name: 'AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT', value: azureAiFoundryAnalysisDeployment }
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOS_DATABASE_NAME', value: cosmosDatabaseName }
  { name: 'SIDE_EFFECT_IDEMPOTENCY_CONTAINER', value: sideEffectIdempotencyContainerName }
  { name: 'CASE_INDEX_CONTAINER', value: caseIndexContainerName }
  { name: 'REPORT_SINK_MODE', value: reportSinkMode }
  { name: 'CAPABILITY_PROFILES', value: capabilityProfiles }
  { name: 'MAX_COMPRESSED_INPUT_BYTES', value: string(maxCompressedInputBytes) }
  { name: 'KEY_VAULT_URI', value: keyVaultUri }
  { name: 'AzureWebJobs.intake_blob.Disabled', value: 'false' }
  { name: 'AzureWebJobs.analyzer_queue.Disabled', value: 'false' }
  { name: 'AzureWebJobs.case_embed_queue.Disabled', value: 'true' }
  { name: 'AzureWebJobs.disposition_sync_timer.Disabled', value: 'true' }
  { name: 'AzureWebJobs.operations_monitor_timer.Disabled', value: 'true' }
  { name: 'AzureWebJobs.portal_http.Disabled', value: 'true' }
])

resource plan 'Microsoft.Web/serverfarms@2023-12-01' existing = {
  name: last(split(serverFarmId, '/'))
}
resource inputStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: inputStorageAccountName
}
resource outputStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: outputStorageAccountName
}
resource outputBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: outputStorage
  name: 'default'
}
resource outputContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: outputBlobService
  name: 'output'
}
resource outputQueueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' existing = {
  parent: outputStorage
  name: 'default'
}
resource analyzerQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' existing = {
  parent: outputQueueService
  name: 'notable-analysis-jobs'
}
resource embedQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' existing = {
  parent: outputQueueService
  name: 'case-embed-invocations'
}

var blobOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var blobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var queueContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

// Storage Queue Data Contributor, scope: 'output-notable-analysis-jobs'.
// The same role at input account scope supports Blob-trigger receipts/poison.

resource inputBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(inputStorage.id, analyzerIdentityResourceId, blobOwnerRoleId)
  scope: inputStorage
  properties: {
    principalId: analyzerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobOwnerRoleId)
  }
}
resource inputQueueContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(inputStorage.id, analyzerIdentityResourceId, queueContributorRoleId)
  scope: inputStorage
  properties: {
    principalId: analyzerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueContributorRoleId)
  }
}
resource outputBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(outputContainer.id, analyzerIdentityResourceId, blobContributorRoleId)
  scope: outputContainer
  properties: {
    principalId: analyzerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
  }
}
resource analyzerQueueContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(analyzerQueue.id, analyzerIdentityResourceId, queueContributorRoleId)
  scope: analyzerQueue
  properties: {
    principalId: analyzerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueContributorRoleId)
  }
}
resource embedQueueContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(embedQueue.id, analyzerIdentityResourceId, queueContributorRoleId)
  scope: embedQueue
  properties: {
    principalId: analyzerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueContributorRoleId)
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux,container'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${analyzerIdentityResourceId}': {} }
  }
  properties: {
    serverFarmId: plan.id
    virtualNetworkSubnetId: functionSubnetId
    httpsOnly: true
    publicNetworkAccess: 'Disabled'
    clientAffinityEnabled: false
    siteConfig: {
      alwaysOn: true
      acrUseManagedIdentityCreds: true
      acrUserManagedIdentityID: analyzerIdentityClientId
      ftpsState: 'Disabled'
      functionAppScaleLimit: maxInstanceCount
      http20Enabled: true
      linuxFxVersion: 'DOCKER|${containerImageUri}'
      minTlsVersion: '1.2'
      minimumElasticInstanceCount: zoneRedundant ? 2 : 1
      use32BitWorkerProcess: false
      vnetRouteAllEnabled: true
      appSettings: applicationSettings
    }
  }
  dependsOn: [
    inputBlobOwner
    inputQueueContributor
    outputBlobContributor
    analyzerQueueContributor
    embedQueueContributor
  ]
}

output functionAppId string = functionApp.id
output functionAppName string = functionApp.name
output defaultHostName string = functionApp.properties.defaultHostName
