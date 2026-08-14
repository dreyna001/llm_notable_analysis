targetScope = 'resourceGroup'

param location string
param functionAppName string
param serverFarmId string
param functionSubnetId string
param containerImageUri string
param dispositionIdentityResourceId string
param dispositionIdentityClientId string
param dispositionIdentityPrincipalId string
param inputStorageAccountName string
param inputQueueServiceUri string
param outputStorageAccountName string
param outputBlobServiceUri string
param outputQueueServiceUri string
param hostBlobServiceUri string
param hostQueueServiceUri string
param hostTableServiceUri string
param applicationInsightsConnectionString string
param keyVaultUri string = ''
param cosmosEndpoint string
param cosmosDatabaseName string
param caseIndexContainerName string = ''
param dispositionContainerName string
param dispositionSyncStateContainerName string
param serviceNowBaseUrl string
param serviceNowDispositionSyncEnabled bool = false
param serviceNowTimeoutSeconds int = 15
param serviceNowDispositionSyncTokenSecretName string
param serviceNowDispositionFieldMap string = '/home/site/wwwroot/deploy/servicenow/disposition_field_map.example.json'
param serviceNowDispositionCodeMap string = '/home/site/wwwroot/deploy/servicenow/disposition_code_map.example.json'
param serviceNowDispositionBackfillDays int = 90
param dispositionRetentionDays int = 365
param allowPrivateOutboundEndpoints bool = false
param serviceNowClosedTicketSyncEnabled bool = false
param closedTicketRagEnabled bool = false
param closedTicketVisionEnabled bool = false
param serviceNowClosedTicketTokenSecretName string = ''
param serviceNowClosedTicketQuery string = ''
param closedTicketRetentionDays int = 30
param closedTicketContainerName string = ''
param closedTicketSyncStateContainerName string = ''
param closedTicketAzureSearchIndex string = 'closed_tickets'
param azureOpenAiEndpoint string = ''
param azureOpenAiApiVersion string = '2024-10-21'
param azureOpenAiEmbeddingsDeployment string = ''
param azureSearchEndpoint string = ''
param ragTenantId string = ''
param zoneRedundant bool = false

var applicationSettings = [
  { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
  { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
  { name: 'AzureFunctionsJobHost__functionTimeout', value: '00:15:00' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: applicationInsightsConnectionString }
  { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
  { name: 'WEBSITES_PORT', value: '8080' }
  { name: 'WEBSITE_VNET_ROUTE_ALL', value: '1' }
  { name: 'AZURE_CLIENT_ID', value: dispositionIdentityClientId }
  { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
  { name: 'AzureWebJobsStorage__clientId', value: dispositionIdentityClientId }
  { name: 'AzureWebJobsStorage__blobServiceUri', value: hostBlobServiceUri }
  { name: 'AzureWebJobsStorage__queueServiceUri', value: hostQueueServiceUri }
  { name: 'AzureWebJobsStorage__tableServiceUri', value: hostTableServiceUri }
  { name: 'OUTPUT_STORAGE_ACCOUNT_URL', value: outputBlobServiceUri }
  { name: 'INPUT_QUEUE_SERVICE_URI', value: inputQueueServiceUri }
  { name: 'OUTPUT_QUEUE_SERVICE_URI', value: outputQueueServiceUri }
  { name: 'OUTPUT_CONTAINER_NAME', value: 'output' }
  { name: 'CASE_ARCHIVE_CONTAINER', value: 'output' }
  { name: 'CASE_ARCHIVE_PREFIX', value: 'cases/' }
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOS_DATABASE_NAME', value: cosmosDatabaseName }
  { name: 'CASE_INDEX_CONTAINER', value: caseIndexContainerName }
  { name: 'DISPOSITION_CONTAINER', value: dispositionContainerName }
  { name: 'DISPOSITION_SYNC_STATE_CONTAINER', value: dispositionSyncStateContainerName }
  { name: 'CAPABILITY_PROFILES', value: 'core' }
  { name: 'KEY_VAULT_URI', value: keyVaultUri }
  { name: 'ALLOW_PRIVATE_OUTBOUND_ENDPOINTS', value: string(allowPrivateOutboundEndpoints) }
  { name: 'SERVICENOW_BASE_URL', value: serviceNowBaseUrl }
  { name: 'SERVICENOW_TIMEOUT_SECONDS', value: string(serviceNowTimeoutSeconds) }
  { name: 'SERVICENOW_DISPOSITION_SYNC_ENABLED', value: string(serviceNowDispositionSyncEnabled) }
  { name: 'SERVICENOW_DISPOSITION_SYNC_TOKEN_SECRET_NAME', value: serviceNowDispositionSyncTokenSecretName }
  { name: 'SERVICENOW_DISPOSITION_FIELD_MAP', value: serviceNowDispositionFieldMap }
  { name: 'SERVICENOW_DISPOSITION_CODE_MAP', value: serviceNowDispositionCodeMap }
  { name: 'SERVICENOW_DISPOSITION_BACKFILL_DAYS', value: string(serviceNowDispositionBackfillDays) }
  { name: 'DISPOSITION_RETENTION_DAYS', value: string(dispositionRetentionDays) }
  { name: 'DISPOSITION_SYNC_SCHEDULE', value: '0 0 0 * * *' }
  { name: 'SERVICENOW_CLOSED_TICKET_SYNC_ENABLED', value: string(serviceNowClosedTicketSyncEnabled) }
  { name: 'SERVICENOW_CLOSED_TICKET_TOKEN_SECRET_NAME', value: serviceNowClosedTicketTokenSecretName }
  { name: 'SERVICENOW_CLOSED_TICKET_QUERY', value: serviceNowClosedTicketQuery }
  { name: 'CLOSED_TICKET_RETENTION_DAYS', value: string(closedTicketRetentionDays) }
  { name: 'CLOSED_TICKET_CONTAINER', value: closedTicketContainerName }
  { name: 'CLOSED_TICKET_SYNC_STATE_CONTAINER', value: closedTicketSyncStateContainerName }
  { name: 'CLOSED_TICKET_ARCHIVE_CONTAINER', value: 'output' }
  { name: 'CLOSED_TICKET_ARCHIVE_PREFIX', value: 'closed_tickets' }
  { name: 'CLOSED_TICKET_RAG_ENABLED', value: string(closedTicketRagEnabled) }
  { name: 'CLOSED_TICKET_AZURE_SEARCH_INDEX', value: closedTicketAzureSearchIndex }
  { name: 'CLOSED_TICKET_VISION_ENABLED', value: string(closedTicketVisionEnabled) }
  { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
  { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenAiApiVersion }
  { name: 'AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT', value: azureOpenAiEmbeddingsDeployment }
  { name: 'AZURE_SEARCH_ENDPOINT', value: azureSearchEndpoint }
  { name: 'RAG_TENANT_ID', value: ragTenantId }
  { name: 'OPERATIONS_MONITOR_SCHEDULE', value: '0 */5 * * * *' }
  { name: 'AzureWebJobs.intake_blob.Disabled', value: 'true' }
  { name: 'AzureWebJobs.analyzer_queue.Disabled', value: 'true' }
  { name: 'AzureWebJobs.case_embed_queue.Disabled', value: 'true' }
  { name: 'AzureWebJobs.rag_ingest_queue.Disabled', value: 'true' }
  { name: 'AzureWebJobs.disposition_sync_timer.Disabled', value: string(!serviceNowDispositionSyncEnabled) }
  { name: 'AzureWebJobs.closed_ticket_sync_timer.Disabled', value: string(!serviceNowClosedTicketSyncEnabled) }
  { name: 'AzureWebJobs.closed_ticket_embed_timer.Disabled', value: string(!closedTicketRagEnabled) }
  { name: 'AzureWebJobs.operations_monitor_timer.Disabled', value: 'false' }
  { name: 'AzureWebJobs.portal_http.Disabled', value: 'true' }
]

resource plan 'Microsoft.Web/serverfarms@2023-12-01' existing = {
  name: last(split(serverFarmId, '/'))
}
resource inputStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: inputStorageAccountName
}
resource inputQueueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' existing = {
  parent: inputStorage
  name: 'default'
}
resource outputStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: outputStorageAccountName
}
resource outputQueueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' existing = {
  parent: outputStorage
  name: 'default'
}
resource outputBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: outputStorage
  name: 'default'
}
resource outputContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: outputBlobService
  name: 'output'
}

var blobReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var blobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var queueReaderRoleId = '19e7f393-937e-4f77-808e-94535e297925'
resource outputBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (serviceNowDispositionSyncEnabled) {
  name: guid(outputContainer.id, dispositionIdentityResourceId, blobReaderRoleId)
  scope: outputContainer
  properties: {
    principalId: dispositionIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobReaderRoleId)
  }
}
resource outputBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (serviceNowClosedTicketSyncEnabled || closedTicketRagEnabled) {
  name: guid(outputContainer.id, dispositionIdentityResourceId, blobContributorRoleId)
  scope: outputContainer
  properties: {
    principalId: dispositionIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
  }
}
resource inputQueueReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(inputQueueService.id, dispositionIdentityResourceId, queueReaderRoleId)
  scope: inputQueueService
  properties: {
    principalId: dispositionIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueReaderRoleId)
  }
}
resource outputQueueReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(outputQueueService.id, dispositionIdentityResourceId, queueReaderRoleId)
  scope: outputQueueService
  properties: {
    principalId: dispositionIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueReaderRoleId)
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux,container'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${dispositionIdentityResourceId}': {} }
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
      acrUserManagedIdentityID: dispositionIdentityClientId
      ftpsState: 'Disabled'
      functionAppScaleLimit: 1
      http20Enabled: true
      linuxFxVersion: 'DOCKER|${containerImageUri}'
      minTlsVersion: '1.2'
      minimumElasticInstanceCount: zoneRedundant ? 2 : 1
      use32BitWorkerProcess: false
      vnetRouteAllEnabled: true
      appSettings: applicationSettings
    }
  }
  dependsOn: [outputBlobReader, outputBlobContributor, inputQueueReader, outputQueueReader]
}

output functionAppId string = functionApp.id
output functionAppName string = functionApp.name
output defaultHostName string = functionApp.properties.defaultHostName
