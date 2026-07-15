targetScope = 'resourceGroup'

param location string
param functionAppName string
param serverFarmId string
param functionSubnetId string
param containerImageUri string
param embedIdentityResourceId string
param embedIdentityClientId string
param embedIdentityPrincipalId string
param outputStorageAccountName string
param outputBlobServiceUri string
param outputQueueServiceUri string
param hostBlobServiceUri string
param hostQueueServiceUri string
param hostTableServiceUri string
param applicationInsightsConnectionString string
param azureOpenAiEndpoint string = ''
param azureOpenAiApiVersion string = '2024-10-21'
param azureOpenAiEmbeddingsDeployment string = ''
@minValue(1)
param caseEmbedQueueTtlSeconds int = 86400
param cosmosEndpoint string
param cosmosDatabaseName string
param caseIndexContainerName string = ''
param caseQaAzureSearchIndex string = ''
param capabilityProfiles string = 'core'
param zoneRedundant bool = false

@minValue(1)
param maxInstanceCount int = 5

var applicationSettings = [
  { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
  { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
  { name: 'AzureFunctionsJobHost__functionTimeout', value: '00:15:00' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: applicationInsightsConnectionString }
  { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
  { name: 'WEBSITES_PORT', value: '8080' }
  { name: 'WEBSITE_VNET_ROUTE_ALL', value: '1' }
  { name: 'AZURE_CLIENT_ID', value: embedIdentityClientId }
  { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
  { name: 'AzureWebJobsStorage__clientId', value: embedIdentityClientId }
  { name: 'AzureWebJobsStorage__blobServiceUri', value: hostBlobServiceUri }
  { name: 'AzureWebJobsStorage__queueServiceUri', value: hostQueueServiceUri }
  { name: 'AzureWebJobsStorage__tableServiceUri', value: hostTableServiceUri }
  { name: 'OUTPUT_STORAGE_ACCOUNT_URL', value: outputBlobServiceUri }
  { name: 'OUTPUT_CONTAINER_NAME', value: 'output' }
  { name: 'CASE_ARCHIVE_CONTAINER', value: 'output' }
  { name: 'CASE_EMBED_QUEUE_NAME', value: 'case-embed-invocations' }
  { name: 'OutputStorage__queueServiceUri', value: outputQueueServiceUri }
  { name: 'OutputStorage__credential', value: 'managedidentity' }
  { name: 'OutputStorage__clientId', value: embedIdentityClientId }
  { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
  { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenAiApiVersion }
  { name: 'AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT', value: azureOpenAiEmbeddingsDeployment }
  { name: 'CASE_EMBED_QUEUE_TTL_SECONDS', value: string(caseEmbedQueueTtlSeconds) }
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOS_DATABASE_NAME', value: cosmosDatabaseName }
  { name: 'CASE_INDEX_CONTAINER', value: caseIndexContainerName }
  { name: 'CASE_QA_RETRIEVAL_BACKEND', value: 'azure_search' }
  { name: 'CASE_QA_AZURE_SEARCH_INDEX', value: caseQaAzureSearchIndex }
  { name: 'CAPABILITY_PROFILES', value: capabilityProfiles }
  { name: 'AzureWebJobs.intake_blob.Disabled', value: 'true' }
  { name: 'AzureWebJobs.analyzer_queue.Disabled', value: 'true' }
  { name: 'AzureWebJobs.case_embed_queue.Disabled', value: 'false' }
  { name: 'AzureWebJobs.disposition_sync_timer.Disabled', value: 'true' }
  { name: 'AzureWebJobs.operations_monitor_timer.Disabled', value: 'true' }
  { name: 'AzureWebJobs.portal_http.Disabled', value: 'true' }
]

resource plan 'Microsoft.Web/serverfarms@2023-12-01' existing = {
  name: last(split(serverFarmId, '/'))
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
resource embedQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' existing = {
  parent: outputQueueService
  name: 'case-embed-invocations'
}

var blobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var queueProcessorRoleId = '8a0f0c08-91a1-4084-bc3d-661d67233fed'
resource outputBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(outputContainer.id, embedIdentityResourceId, blobContributorRoleId)
  scope: outputContainer
  properties: {
    principalId: embedIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
  }
}
resource embedQueueProcessor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(embedQueue.id, embedIdentityResourceId, queueProcessorRoleId)
  scope: embedQueue
  properties: {
    principalId: embedIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueProcessorRoleId)
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux,container'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${embedIdentityResourceId}': {} }
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
      acrUserManagedIdentityID: embedIdentityClientId
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
  dependsOn: [outputBlobContributor, embedQueueProcessor]
}

output functionAppId string = functionApp.id
output functionAppName string = functionApp.name
output defaultHostName string = functionApp.properties.defaultHostName
