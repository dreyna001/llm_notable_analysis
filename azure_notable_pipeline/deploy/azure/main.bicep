targetScope = 'resourceGroup'

@description('Lowercase deployment prefix used for Azure resource names.')
@minLength(3)
@maxLength(24)
param DeploymentPrefix string

@description('Azure deployment region. Customer-managed model resources must use this region in v1.')
param Location string = 'eastus'

@allowed(['AzureCloud', 'AzureUSGovernment'])
param cloudEnvironment string = 'AzureCloud'

@description('Full immutable ACR image URI. Production deploys must use @sha256:<digest>.')
param ContainerImageUri string

@description('Resource ID of the ACR that owns ContainerImageUri.')
param ContainerRegistryResourceId string

@minLength(1)
param AzureAiFoundryAnthropicBaseUrl string

@description('Resource ID of the existing customer Foundry account that exposes Claude.')
@minLength(1)
param AzureAiFoundryResourceId string

param AzureAiFoundryAnalysisDeployment string = 'claude-sonnet-4-6'

param AzureOpenAiEndpoint string = ''
param AzureOpenAiResourceId string = ''
param AzureOpenAiApiVersion string = '2024-10-21'
param AzureOpenAiResourceRegion string = Location
param AzureOpenAiEmbeddingsDeployment string = ''
param AzureOpenAiPortalChatDeployment string = ''
param AzureSearchEndpoint string = ''
param AzureSearchResourceId string = ''
param RagAzureSearchIndex string = ''
param KeyVaultName string = ''
@minLength(3)
param CosmosAccountName string
@minLength(1)
param CosmosDatabaseName string

param SideEffectIdempotencyContainerName string = 'notable-side-effect-idempotency'
param CaseIndexContainerName string = '${DeploymentPrefix}-case-index'
param DispositionContainerName string = '${DeploymentPrefix}-servicenow-dispositions'
param DispositionSyncStateContainerName string = '${DeploymentPrefix}-disposition-sync-state'
param ChatSessionsContainerName string = '${DeploymentPrefix}-chat-sessions'
param ChatMessagesContainerName string = '${DeploymentPrefix}-chat-messages'

@description('Provision disposition persistence and grants for the future timer app.')
param ServiceNowDispositionSyncEnabled bool = false

@description('Provision chat-history persistence only with the analyst_portal profile.')
param CaseQaChatHistoryEnabled bool = false

param FunctionsHostStorageAccountName string
param StorageAccountNameInput string
param StorageAccountNameOutput string
param StorageAccountNamePortalUi string = ''
param PortalUiDeployerPrincipalId string = ''

@allowed(['jwt', 'iam'])
param PortalAuthMode string = 'jwt'
param PortalJwtIssuer string = ''
param PortalJwtAudience string = ''
param PortalEntraRequiredAppRole string = ''
param ApiManagementPublisherEmail string = ''
param ApiManagementPublisherName string = 'Notable Analysis'

@allowed(['blob', 'notable_rest'])
param ReportSinkMode string = 'blob'

param CapabilityProfiles string = 'core'

@minValue(30)
@maxValue(1800)
param AnalyzerTimeoutSeconds int = 360

@minValue(1)
param AnalyzerMaxInstanceCount int = 5

@minValue(1)
param EmbedMaxInstanceCount int = 5

@minValue(30)
@maxValue(225)
param PortalChatTimeoutSec int = 225

@allowed(['EP1', 'EP2', 'EP3'])
param FunctionPlanSkuName string = 'EP1'

@allowed(['StandardV2'])
param ApiManagementSkuName string = 'StandardV2'

param AlertActionGroupResourceId string = ''

@minValue(1)
param InputRetentionDays int = 2
@minValue(1)
param OutputRetentionDays int = 30
@minValue(1)
param CaseRetentionDays int = 30

var acrIdSegments = split(ContainerRegistryResourceId, '/')
var acrSubscriptionId = acrIdSegments[2]
var acrResourceGroupName = acrIdSegments[4]
var acrName = acrIdSegments[8]
var foundryIdSegments = split(AzureAiFoundryResourceId, '/')
var foundrySubscriptionId = foundryIdSegments[2]
var foundryResourceGroupName = foundryIdSegments[4]
var foundryName = foundryIdSegments[8]
var openAiIdSegments = split(
  empty(AzureOpenAiResourceId)
    ? '/subscriptions/none/resourceGroups/none/providers/Microsoft.CognitiveServices/accounts/none'
    : AzureOpenAiResourceId,
  '/'
)
var searchIdSegments = split(
  empty(AzureSearchResourceId)
    ? '/subscriptions/none/resourceGroups/none/providers/Microsoft.Search/searchServices/none'
    : AzureSearchResourceId,
  '/'
)
var normalizedCapabilityProfiles = split(toLower(replace(CapabilityProfiles, ' ', '')), ',')
var hasAnalystPortalProfile = contains(normalizedCapabilityProfiles, 'analyst_portal')
var deployPortal = hasAnalystPortalProfile && !empty(StorageAccountNamePortalUi)
var deployChatHistoryContainers = hasAnalystPortalProfile && CaseQaChatHistoryEnabled

module storage 'modules/storage.bicep' = {
  name: '${DeploymentPrefix}-storage'
  params: {
    location: Location
    functionsHostStorageAccountName: FunctionsHostStorageAccountName
    inputStorageAccountName: StorageAccountNameInput
    outputStorageAccountName: StorageAccountNameOutput
    portalUiStorageAccountName: StorageAccountNamePortalUi
    portalUiDeployerPrincipalId: PortalUiDeployerPrincipalId
    inputRetentionDays: InputRetentionDays
    outputRetentionDays: OutputRetentionDays
    caseRetentionDays: CaseRetentionDays
  }
}

module network 'modules/network.bicep' = {
  name: '${DeploymentPrefix}-network'
  params: {
    location: Location
    namePrefix: DeploymentPrefix
    inputStorageAccountName: StorageAccountNameInput
    outputStorageAccountName: StorageAccountNameOutput
    functionsHostStorageAccountName: FunctionsHostStorageAccountName
    portalUiStorageAccountName: StorageAccountNamePortalUi
  }
  dependsOn: [storage]
}

module identities 'modules/identities.bicep' = {
  name: '${DeploymentPrefix}-identities'
  params: {
    location: Location
    namePrefix: DeploymentPrefix
  }
  dependsOn: [storage]
}

module cosmos 'modules/cosmos.bicep' = {
  name: '${DeploymentPrefix}-cosmos'
  params: {
    location: Location
    accountName: CosmosAccountName
    databaseName: CosmosDatabaseName
    sideEffectIdempotencyContainerName: SideEffectIdempotencyContainerName
    caseIndexContainerName: CaseIndexContainerName
    dispositionContainerName: DispositionContainerName
    dispositionSyncStateContainerName: DispositionSyncStateContainerName
    chatSessionsContainerName: ChatSessionsContainerName
    chatMessagesContainerName: ChatMessagesContainerName
    deployCaseIndex: hasAnalystPortalProfile
    deployDispositionContainers: ServiceNowDispositionSyncEnabled
    deployChatHistoryContainers: deployChatHistoryContainers
    analyzerPrincipalId: identities.outputs.analyzer.principalId
    embedPrincipalId: identities.outputs.embed.principalId
    dispositionPrincipalId: identities.outputs.disposition.principalId
    portalPrincipalId: identities.outputs.portal.principalId
  }
}

module analyzerHostAccess 'modules/host-storage-access.bicep' = {
  name: '${DeploymentPrefix}-analyzer-host-storage'
  params: {
    functionsHostStorageAccountName: FunctionsHostStorageAccountName
    identityResourceId: identities.outputs.analyzer.id
    identityPrincipalId: identities.outputs.analyzer.principalId
  }
}
module embedHostAccess 'modules/host-storage-access.bicep' = {
  name: '${DeploymentPrefix}-embed-host-storage'
  params: {
    functionsHostStorageAccountName: FunctionsHostStorageAccountName
    identityResourceId: identities.outputs.embed.id
    identityPrincipalId: identities.outputs.embed.principalId
  }
}
module dispositionHostAccess 'modules/host-storage-access.bicep' = {
  name: '${DeploymentPrefix}-disposition-host-storage'
  params: {
    functionsHostStorageAccountName: FunctionsHostStorageAccountName
    identityResourceId: identities.outputs.disposition.id
    identityPrincipalId: identities.outputs.disposition.principalId
  }
}
module portalHostAccess 'modules/host-storage-access.bicep' = {
  name: '${DeploymentPrefix}-portal-host-storage'
  params: {
    functionsHostStorageAccountName: FunctionsHostStorageAccountName
    identityResourceId: identities.outputs.portal.id
    identityPrincipalId: identities.outputs.portal.principalId
  }
}

module registryAccess 'modules/container-registry-access.bicep' = {
  name: '${DeploymentPrefix}-acr-access'
  scope: resourceGroup(acrSubscriptionId, acrResourceGroupName)
  params: {
    containerRegistryName: acrName
    runtimePrincipalIds: [
      identities.outputs.analyzer.principalId
      identities.outputs.embed.principalId
      identities.outputs.disposition.principalId
      identities.outputs.portal.principalId
    ]
  }
}

module foundryAccess 'modules/foundry-access.bicep' = {
  name: '${DeploymentPrefix}-foundry-access'
  scope: resourceGroup(foundrySubscriptionId, foundryResourceGroupName)
  params: {
    foundryAccountName: foundryName
    analyzerPrincipalId: identities.outputs.analyzer.principalId
  }
}

module openAiAccess 'modules/openai-access.bicep' = if (!empty(AzureOpenAiResourceId)) {
  name: '${DeploymentPrefix}-openai-access'
  scope: resourceGroup(openAiIdSegments[2], openAiIdSegments[4])
  params: {
    openAiAccountName: openAiIdSegments[8]
    embedPrincipalId: identities.outputs.embed.principalId
    portalPrincipalId: deployPortal ? identities.outputs.portal.principalId : ''
  }
}

module searchAccess 'modules/search-access.bicep' = if (!empty(AzureSearchResourceId)) {
  name: '${DeploymentPrefix}-search-access'
  scope: resourceGroup(searchIdSegments[2], searchIdSegments[4])
  params: {
    searchServiceName: searchIdSegments[8]
    principalIds: deployPortal
      ? [identities.outputs.analyzer.principalId, identities.outputs.portal.principalId]
      : [identities.outputs.analyzer.principalId]
  }
}

module keyVaultAccess 'modules/keyvault-access.bicep' = if (!empty(KeyVaultName)) {
  name: '${DeploymentPrefix}-keyvault-access'
  params: {
    keyVaultName: KeyVaultName
    secretReaderPrincipalIds: [identities.outputs.analyzer.principalId, identities.outputs.disposition.principalId]
  }
}

module observability 'modules/observability.bicep' = {
  name: '${DeploymentPrefix}-observability'
  params: {
    location: Location
    namePrefix: DeploymentPrefix
    alertActionGroupResourceId: AlertActionGroupResourceId
  }
}

resource functionPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${DeploymentPrefix}-functions-plan'
  location: Location
  kind: 'elastic'
  sku: { name: FunctionPlanSkuName, tier: 'ElasticPremium', capacity: 1 }
  properties: {
    maximumElasticWorkerCount: max(AnalyzerMaxInstanceCount, EmbedMaxInstanceCount)
    reserved: true
    zoneRedundant: false
  }
}

module analyzerFunction 'modules/functions-analyzer.bicep' = {
  name: '${DeploymentPrefix}-analyzer-function'
  params: {
    location: Location
    functionAppName: '${DeploymentPrefix}-notable-analyzer-queue'
    serverFarmId: functionPlan.id
    functionSubnetId: network.outputs.functionSubnetId
    containerImageUri: ContainerImageUri
    analyzerIdentityResourceId: identities.outputs.analyzer.id
    analyzerIdentityClientId: identities.outputs.analyzer.clientId
    analyzerIdentityPrincipalId: identities.outputs.analyzer.principalId
    inputStorageAccountName: StorageAccountNameInput
    outputStorageAccountName: StorageAccountNameOutput
    inputBlobServiceUri: storage.outputs.inputBlobServiceUri
    inputQueueServiceUri: storage.outputs.inputQueueServiceUri
    outputBlobServiceUri: storage.outputs.outputBlobServiceUri
    outputQueueServiceUri: storage.outputs.outputQueueServiceUri
    hostBlobServiceUri: storage.outputs.hostBlobServiceUri
    hostQueueServiceUri: storage.outputs.hostQueueServiceUri
    hostTableServiceUri: storage.outputs.hostTableServiceUri
    applicationInsightsConnectionString: observability.outputs.applicationInsightsConnectionString
    keyVaultUri: empty(KeyVaultName) ? '' : keyVaultAccess!.outputs.keyVaultUri
    azureAiFoundryAnthropicBaseUrl: AzureAiFoundryAnthropicBaseUrl
    azureAiFoundryResourceId: AzureAiFoundryResourceId
    azureAiFoundryAnalysisDeployment: AzureAiFoundryAnalysisDeployment
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    sideEffectIdempotencyContainerName: cosmos.outputs.sideEffectIdempotencyContainerName
    caseIndexContainerName: cosmos.outputs.caseIndexContainerName
    reportSinkMode: ReportSinkMode
    capabilityProfiles: CapabilityProfiles
    maxInstanceCount: AnalyzerMaxInstanceCount
    timeoutSeconds: AnalyzerTimeoutSeconds
  }
  dependsOn: [registryAccess, foundryAccess, analyzerHostAccess]
}

module embedFunction 'modules/functions-embed.bicep' = {
  name: '${DeploymentPrefix}-embed-function'
  params: {
    location: Location
    functionAppName: '${DeploymentPrefix}-notable-case-embed'
    serverFarmId: functionPlan.id
    functionSubnetId: network.outputs.functionSubnetId
    containerImageUri: ContainerImageUri
    embedIdentityResourceId: identities.outputs.embed.id
    embedIdentityClientId: identities.outputs.embed.clientId
    embedIdentityPrincipalId: identities.outputs.embed.principalId
    outputStorageAccountName: StorageAccountNameOutput
    outputBlobServiceUri: storage.outputs.outputBlobServiceUri
    outputQueueServiceUri: storage.outputs.outputQueueServiceUri
    hostBlobServiceUri: storage.outputs.hostBlobServiceUri
    hostQueueServiceUri: storage.outputs.hostQueueServiceUri
    hostTableServiceUri: storage.outputs.hostTableServiceUri
    applicationInsightsConnectionString: observability.outputs.applicationInsightsConnectionString
    azureOpenAiEndpoint: AzureOpenAiEndpoint
    azureOpenAiApiVersion: AzureOpenAiApiVersion
    azureOpenAiEmbeddingsDeployment: AzureOpenAiEmbeddingsDeployment
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    caseIndexContainerName: cosmos.outputs.caseIndexContainerName
    capabilityProfiles: CapabilityProfiles
    maxInstanceCount: EmbedMaxInstanceCount
  }
  dependsOn: [registryAccess, embedHostAccess, openAiAccess]
}

module portalFunction 'modules/functions-portal.bicep' = if (deployPortal) {
  name: '${DeploymentPrefix}-portal-function'
  params: {
    location: Location
    functionAppName: '${DeploymentPrefix}-notable-portal-api'
    serverFarmId: functionPlan.id
    functionSubnetId: network.outputs.functionSubnetId
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    sitesPrivateDnsZoneId: network.outputs.sitesPrivateDnsZoneId
    containerImageUri: ContainerImageUri
    portalIdentityResourceId: identities.outputs.portal.id
    portalIdentityClientId: identities.outputs.portal.clientId
    portalIdentityPrincipalId: identities.outputs.portal.principalId
    outputStorageAccountName: StorageAccountNameOutput
    outputBlobServiceUri: storage.outputs.outputBlobServiceUri
    hostBlobServiceUri: storage.outputs.hostBlobServiceUri
    hostQueueServiceUri: storage.outputs.hostQueueServiceUri
    hostTableServiceUri: storage.outputs.hostTableServiceUri
    applicationInsightsConnectionString: observability.outputs.applicationInsightsConnectionString
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    caseIndexContainerName: cosmos.outputs.caseIndexContainerName
    chatSessionsContainerName: deployChatHistoryContainers ? cosmos.outputs.chatSessionsContainerName : ''
    chatMessagesContainerName: deployChatHistoryContainers ? cosmos.outputs.chatMessagesContainerName : ''
    azureOpenAiEndpoint: AzureOpenAiEndpoint
    azureOpenAiApiVersion: AzureOpenAiApiVersion
    azureOpenAiEmbeddingsDeployment: AzureOpenAiEmbeddingsDeployment
    azureOpenAiPortalChatDeployment: AzureOpenAiPortalChatDeployment
    azureSearchEndpoint: AzureSearchEndpoint
    ragAzureSearchIndex: RagAzureSearchIndex
    capabilityProfiles: CapabilityProfiles
    portalAuthMode: PortalAuthMode
    portalJwtIssuer: PortalJwtIssuer
    portalJwtAudience: PortalJwtAudience
    portalEntraRequiredAppRole: PortalEntraRequiredAppRole
    caseQaChatHistoryEnabled: deployChatHistoryContainers
    portalChatTimeoutSec: PortalChatTimeoutSec
  }
  dependsOn: [registryAccess, portalHostAccess, openAiAccess, searchAccess]
}

module portalApiManagement 'modules/apim-portal.bicep' = if (deployPortal) {
  name: '${DeploymentPrefix}-portal-apim'
  params: {
    location: Location
    apiManagementName: '${DeploymentPrefix}-portal-apim'
    apiManagementSkuName: ApiManagementSkuName
    publisherEmail: ApiManagementPublisherEmail
    publisherName: ApiManagementPublisherName
    apimSubnetId: network.outputs.apimSubnetId
    portalFunctionHostName: portalFunction!.outputs.defaultHostName
    portalAuthMode: PortalAuthMode
    portalJwtIssuer: PortalJwtIssuer
    portalJwtAudience: PortalJwtAudience
    portalEntraRequiredAppRole: PortalEntraRequiredAppRole
  }
}

module portalFrontDoor 'modules/frontdoor-portal.bicep' = if (deployPortal) {
  name: '${DeploymentPrefix}-portal-frontdoor'
  params: {
    location: Location
    profileName: '${DeploymentPrefix}-portal-fd'
    endpointName: '${DeploymentPrefix}-portal'
    portalUiStorageId: storage.outputs.portalStorageId
    portalUiHostName: storage.outputs.portalWebHostName
    apiManagementId: portalApiManagement!.outputs.apiManagementId
    apiManagementHostName: portalApiManagement!.outputs.gatewayHostName
    portalFunctionId: portalFunction!.outputs.functionAppId
    portalFunctionHostName: portalFunction!.outputs.defaultHostName
  }
}

output DeploymentLocation string = Location
output ConfiguredCloud string = cloudEnvironment
output AnalyzerFunctionAppName string = analyzerFunction.outputs.functionAppName
output EmbedFunctionAppName string = embedFunction.outputs.functionAppName
output PortalFunctionAppName string = deployPortal ? portalFunction!.outputs.functionAppName : ''
output PortalApiManagementName string = deployPortal ? portalApiManagement!.outputs.apiManagementName : ''
output PortalFrontDoorProfileName string = deployPortal ? portalFrontDoor!.outputs.profileName : ''
output AnalysisDeployment string = AzureAiFoundryAnalysisDeployment
output AzureOpenAiRegion string = AzureOpenAiResourceRegion
output ReportSinkMode string = ReportSinkMode
output InputStorageAccountName string = StorageAccountNameInput
output OutputStorageAccountName string = StorageAccountNameOutput
output AnalyzerQueueName string = 'notable-analysis-jobs'
output CaseEmbedQueueName string = 'case-embed-invocations'
output CosmosEndpoint string = cosmos.outputs.endpoint
output CosmosDatabaseName string = cosmos.outputs.databaseName
output SideEffectIdempotencyContainerName string = cosmos.outputs.sideEffectIdempotencyContainerName
output CaseIndexContainerName string = cosmos.outputs.caseIndexContainerName
output DispositionContainerName string = cosmos.outputs.dispositionContainerName
output DispositionSyncStateContainerName string = cosmos.outputs.dispositionSyncStateContainerName
output ChatSessionsContainerName string = cosmos.outputs.chatSessionsContainerName
output ChatMessagesContainerName string = cosmos.outputs.chatMessagesContainerName
output PortalApiUrl string = deployPortal ? 'https://${portalFrontDoor!.outputs.endpointHostName}/api' : ''
output PortalChatUrl string = deployPortal ? 'https://${portalFrontDoor!.outputs.endpointHostName}/api/chat' : ''
output PortalBrowserApiBaseUrl string = deployPortal ? 'https://${portalFrontDoor!.outputs.endpointHostName}' : ''
output PortalFrontDoorHostName string = deployPortal ? portalFrontDoor!.outputs.endpointHostName : ''
output PortalUiStorageAccountName string = StorageAccountNamePortalUi
