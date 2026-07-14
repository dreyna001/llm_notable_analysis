targetScope = 'resourceGroup'

param location string
param functionAppName string
param serverFarmId string
param functionSubnetId string
param privateEndpointSubnetId string
param sitesPrivateDnsZoneId string
param containerImageUri string
param portalIdentityResourceId string
param portalIdentityClientId string
param portalIdentityPrincipalId string
param outputStorageAccountName string
param outputBlobServiceUri string
param hostBlobServiceUri string
param hostQueueServiceUri string
param hostTableServiceUri string
param applicationInsightsConnectionString string
param cosmosEndpoint string
param cosmosDatabaseName string
param caseIndexContainerName string
param chatSessionsContainerName string = ''
param chatMessagesContainerName string = ''
param chatQuotaContainerName string = ''
param azureOpenAiEndpoint string
param azureOpenAiApiVersion string = '2024-10-21'
param azureOpenAiEmbeddingsDeployment string
param azureOpenAiPortalChatDeployment string
param azureSearchEndpoint string = ''
param ragAzureSearchIndex string = ''
param capabilityProfiles string = 'core,analyst_portal'
param zoneRedundant bool = false

@allowed(['jwt', 'iam'])
param portalAuthMode string = 'jwt'
param portalJwtIssuer string
param portalJwtAudience string
param portalEntraRequiredAppRole string = ''
param caseQaChatHistoryEnabled bool = false
param portalChatDistributedQuotaEnabled bool = true
@minValue(1)
@maxValue(16)
param portalChatPerUserMaxConcurrency int = 2
@minValue(60)
@maxValue(86400)
param portalChatQuotaWindowSeconds int = 3600
@minValue(1)
@maxValue(2048)
param portalChatMaxRequestsPerWindow int = 30
@minValue(1)
param portalChatMaxBudgetUnitsPerWindow int = 100000
@minValue(1)
param portalChatBudgetUnitsPerRequest int = 5000
@minValue(226)
@maxValue(3600)
param portalChatLeaseSeconds int = 300
@minValue(60)
@maxValue(86400)
param portalChatRequestDedupeSeconds int = 3600

@minValue(30)
@maxValue(225)
param portalChatTimeoutSec int = 225

var applicationSettings = [
  { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
  { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
  { name: 'AzureFunctionsJobHost__functionTimeout', value: '00:03:45' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: applicationInsightsConnectionString }
  { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
  { name: 'WEBSITES_PORT', value: '8080' }
  { name: 'WEBSITE_VNET_ROUTE_ALL', value: '1' }
  { name: 'AZURE_CLIENT_ID', value: portalIdentityClientId }
  { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
  { name: 'AzureWebJobsStorage__clientId', value: portalIdentityClientId }
  { name: 'AzureWebJobsStorage__blobServiceUri', value: hostBlobServiceUri }
  { name: 'AzureWebJobsStorage__queueServiceUri', value: hostQueueServiceUri }
  { name: 'AzureWebJobsStorage__tableServiceUri', value: hostTableServiceUri }
  { name: 'OUTPUT_STORAGE_ACCOUNT_URL', value: outputBlobServiceUri }
  { name: 'OUTPUT_CONTAINER_NAME', value: 'output' }
  { name: 'CASE_ARCHIVE_CONTAINER', value: 'output' }
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOS_DATABASE_NAME', value: cosmosDatabaseName }
  { name: 'CASE_INDEX_CONTAINER', value: caseIndexContainerName }
  { name: 'CHAT_SESSIONS_CONTAINER', value: chatSessionsContainerName }
  { name: 'CHAT_MESSAGES_CONTAINER', value: chatMessagesContainerName }
  { name: 'PORTAL_CHAT_QUOTA_CONTAINER', value: chatQuotaContainerName }
  { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
  { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenAiApiVersion }
  { name: 'AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT', value: azureOpenAiEmbeddingsDeployment }
  { name: 'AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT', value: azureOpenAiPortalChatDeployment }
  { name: 'AZURE_SEARCH_ENDPOINT', value: azureSearchEndpoint }
  { name: 'RAG_AZURE_SEARCH_INDEX', value: ragAzureSearchIndex }
  { name: 'CAPABILITY_PROFILES', value: capabilityProfiles }
  { name: 'PORTAL_AUTH_MODE', value: portalAuthMode }
  { name: 'PORTAL_JWT_ISSUER', value: portalJwtIssuer }
  { name: 'PORTAL_JWT_AUDIENCE', value: portalJwtAudience }
  { name: 'PORTAL_ENTRA_REQUIRED_APP_ROLE', value: portalEntraRequiredAppRole }
  { name: 'PORTAL_CORS_ALLOWED_ORIGINS', value: '' }
  { name: 'PORTAL_CHAT_TIMEOUT_SEC', value: string(portalChatTimeoutSec) }
  { name: 'PORTAL_CHAT_DISTRIBUTED_QUOTA_ENABLED', value: string(portalChatDistributedQuotaEnabled) }
  { name: 'PORTAL_CHAT_PER_USER_MAX_CONCURRENCY', value: string(portalChatPerUserMaxConcurrency) }
  { name: 'PORTAL_CHAT_QUOTA_WINDOW_SECONDS', value: string(portalChatQuotaWindowSeconds) }
  { name: 'PORTAL_CHAT_MAX_REQUESTS_PER_WINDOW', value: string(portalChatMaxRequestsPerWindow) }
  { name: 'PORTAL_CHAT_MAX_BUDGET_UNITS_PER_WINDOW', value: string(portalChatMaxBudgetUnitsPerWindow) }
  { name: 'PORTAL_CHAT_BUDGET_UNITS_PER_REQUEST', value: string(portalChatBudgetUnitsPerRequest) }
  { name: 'PORTAL_CHAT_LEASE_SECONDS', value: string(portalChatLeaseSeconds) }
  { name: 'PORTAL_CHAT_REQUEST_DEDUPE_SECONDS', value: string(portalChatRequestDedupeSeconds) }
  { name: 'CASE_QA_CHAT_HISTORY_ENABLED', value: string(caseQaChatHistoryEnabled) }
  { name: 'AzureWebJobs.intake_blob.Disabled', value: 'true' }
  { name: 'AzureWebJobs.analyzer_queue.Disabled', value: 'true' }
  { name: 'AzureWebJobs.case_embed_queue.Disabled', value: 'true' }
  { name: 'AzureWebJobs.disposition_sync_timer.Disabled', value: 'true' }
  { name: 'AzureWebJobs.operations_monitor_timer.Disabled', value: 'true' }
  { name: 'AzureWebJobs.portal_http.Disabled', value: 'false' }
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

var blobReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
resource outputBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(outputContainer.id, portalIdentityResourceId, blobReaderRoleId)
  scope: outputContainer
  properties: {
    principalId: portalIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobReaderRoleId)
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux,container'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${portalIdentityResourceId}': {} }
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
      acrUserManagedIdentityID: portalIdentityClientId
      ftpsState: 'Disabled'
      http20Enabled: true
      linuxFxVersion: 'DOCKER|${containerImageUri}'
      minTlsVersion: '1.2'
      minimumElasticInstanceCount: zoneRedundant ? 2 : 1
      use32BitWorkerProcess: false
      vnetRouteAllEnabled: true
      appSettings: applicationSettings
    }
  }
  dependsOn: [outputBlobReader]
}

resource entraAuthentication 'Microsoft.Web/sites/config@2023-12-01' = if (portalAuthMode == 'iam') {
  parent: functionApp
  name: 'authsettingsV2'
  properties: {
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'
    }
    httpSettings: {
      requireHttps: true
      routes: { apiPrefix: '/.auth' }
      forwardProxy: { convention: 'Standard' }
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: portalJwtAudience
          openIdIssuer: portalJwtIssuer
        }
        validation: {
          allowedAudiences: [portalJwtAudience]
        }
      }
    }
    login: { tokenStore: { enabled: false } }
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
  }
}

resource portalPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: '${functionAppName}-pe'
  location: location
  properties: {
    subnet: { id: privateEndpointSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'portal-sites-connection'
        properties: {
          privateLinkServiceId: functionApp.id
          groupIds: ['sites']
        }
      }
    ]
  }
}
resource portalPrivateEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: portalPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      { name: 'sites', properties: { privateDnsZoneId: sitesPrivateDnsZoneId } }
    ]
  }
}

output functionAppId string = functionApp.id
output functionAppName string = functionApp.name
output defaultHostName string = functionApp.properties.defaultHostName
