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
param ChatQuotaContainerName string = '${DeploymentPrefix}-chat-quota'

@description('Provision disposition persistence and grants for the future timer app.')
param ServiceNowDispositionSyncEnabled bool = false

@description('Provision chat-history persistence only with the analyst_portal profile.')
param CaseQaChatHistoryEnabled bool = false

param FunctionsHostStorageAccountName string
@description('Opt in to one Functions host storage account per app. This changes host state placement and requires four globally unique account names; deploy through staging before production.')
param IsolateFunctionsHostStorage bool = false
param AnalyzerHostStorageAccountName string = ''
param EmbedHostStorageAccountName string = ''
param DispositionHostStorageAccountName string = ''
param PortalHostStorageAccountName string = ''

@allowed(['Standard_LRS', 'Standard_ZRS'])
param StorageSkuName string = 'Standard_LRS'

@description('Enable blob and container soft delete plus blob versioning on input/output data accounts.')
param BlobDataProtectionEnabled bool = false
@minValue(1)
@maxValue(365)
param BlobSoftDeleteRetentionDays int = 30
@minValue(1)
@maxValue(365)
param ContainerSoftDeleteRetentionDays int = 30
@minValue(1)
param PreviousVersionRetentionDays int = 30
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
param MaxCompressedInputBytes int = 1048576

@minValue(1)
param EmbedMaxInstanceCount int = 5

@minValue(30)
@maxValue(225)
param PortalChatTimeoutSec int = 225

@description('Use Cosmos-backed per-user chat admission control. Keep enabled for live analyst deployments.')
param PortalChatDistributedQuotaEnabled bool = true
@minValue(1)
@maxValue(16)
param PortalChatPerUserMaxConcurrency int = 2
@minValue(60)
@maxValue(86400)
param PortalChatQuotaWindowSeconds int = 3600
@minValue(1)
@maxValue(2048)
param PortalChatMaxRequestsPerWindow int = 30
@minValue(1)
param PortalChatMaxBudgetUnitsPerWindow int = 100000
@minValue(1)
param PortalChatBudgetUnitsPerRequest int = 5000
@minValue(226)
@maxValue(3600)
param PortalChatLeaseSeconds int = 300
@minValue(60)
@maxValue(86400)
param PortalChatRequestDedupeSeconds int = 3600

@allowed(['EP1', 'EP2', 'EP3'])
param FunctionPlanSkuName string = 'EP1'

@description('Enable zone redundancy on the Elastic Premium Functions plan. Confirm regional support and capacity before enabling.')
param FunctionPlanZoneRedundant bool = false

@description('Enable zone redundancy for a newly created serverless Cosmos account. Existing non-zonal serverless accounts require migration to a new account.')
param CosmosZoneRedundant bool = false

@description('Use Cosmos continuous seven-day backup instead of periodic backup.')
param CosmosContinuousBackupEnabled bool = false

@allowed(['StandardV2'])
param ApiManagementSkuName string = 'StandardV2'

param AlertActionGroupResourceId string = ''

@allowed(['development', 'staging', 'production'])
param DeploymentEnvironment string = 'development'

@description('Application Insights availability result name emitted by the customer authenticated /ready monitor. The stack stores no token.')
param PortalSyntheticCheckName string = ''

@minValue(0)
param PoisonQueueDepthThreshold int = 0
@minValue(1)
param AnalyzerQueueBacklogThreshold int = 100
@minValue(1)
param EmbedQueueBacklogThreshold int = 100
@minValue(1)
param ModelErrorThreshold int = 5
@minValue(1)
param ModelThrottleThreshold int = 5
@minValue(1)
param CosmosThrottleThreshold int = 10
@minValue(0)
@maxValue(100)
param FrontDoor5xxPercentageThreshold int = 5
@minValue(24)
param DispositionCompletionGraceHours int = 26
@minValue(5)
param QueueTelemetryMaxAgeMinutes int = 10

param ServiceNowBaseUrl string = 'https://your-instance.service-now.com'
@minValue(1)
@maxValue(300)
param ServiceNowTimeoutSeconds int = 15
param ServiceNowDispositionSyncTokenSecretName string = ''
param ServiceNowDispositionFieldMap string = '/home/site/wwwroot/deploy/servicenow/disposition_field_map.example.json'
param ServiceNowDispositionCodeMap string = '/home/site/wwwroot/deploy/servicenow/disposition_code_map.example.json'
@minValue(1)
@maxValue(3650)
param ServiceNowDispositionBackfillDays int = 90
@minValue(1)
@maxValue(3650)
param DispositionRetentionDays int = 365
param AllowPrivateOutboundEndpoints bool = false

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
var queueDepthTracePrefix = 'notable.queue.depth.v1 '
var isProduction = DeploymentEnvironment == 'production'
var validatedAlertActionGroupResourceId = isProduction && empty(AlertActionGroupResourceId)
  ? fail('AlertActionGroupResourceId is required when DeploymentEnvironment=production.')
  : AlertActionGroupResourceId
var validatedSyntheticCheckName = isProduction && deployPortal && empty(PortalSyntheticCheckName)
  ? fail('PortalSyntheticCheckName is required for a production analyst portal.')
  : PortalSyntheticCheckName
var validatedKeyVaultName = ServiceNowDispositionSyncEnabled && empty(KeyVaultName)
  ? fail('KeyVaultName is required when ServiceNowDispositionSyncEnabled=true.')
  : KeyVaultName
var validatedDispositionTokenSecretName = ServiceNowDispositionSyncEnabled && empty(ServiceNowDispositionSyncTokenSecretName)
  ? fail('ServiceNowDispositionSyncTokenSecretName is required when ServiceNowDispositionSyncEnabled=true.')
  : ServiceNowDispositionSyncTokenSecretName
var validatedBlobDataProtection = isProduction && !BlobDataProtectionEnabled
  ? fail('BlobDataProtectionEnabled must be true when DeploymentEnvironment=production.')
  : BlobDataProtectionEnabled
var validatedCosmosContinuousBackup = isProduction && !CosmosContinuousBackupEnabled
  ? fail('CosmosContinuousBackupEnabled must be true when DeploymentEnvironment=production.')
  : CosmosContinuousBackupEnabled
var validatedStorageSkuName = FunctionPlanZoneRedundant && StorageSkuName != 'Standard_ZRS'
  ? fail('StorageSkuName must be Standard_ZRS when FunctionPlanZoneRedundant=true.')
  : StorageSkuName
var portalChatQuotaOverlapWindows = ((PortalChatRequestDedupeSeconds + PortalChatQuotaWindowSeconds - 1) / PortalChatQuotaWindowSeconds) + 1
var validatedPortalChatMaxRequestsPerWindow = portalChatQuotaOverlapWindows * PortalChatMaxRequestsPerWindow > 4096
  ? fail('Portal chat quota settings can retain at most 4096 recent request IDs; reduce the request rate or dedupe interval.')
  : PortalChatMaxRequestsPerWindow
var validatedAnalyzerHostStorageAccountName = IsolateFunctionsHostStorage && empty(AnalyzerHostStorageAccountName)
  ? fail('AnalyzerHostStorageAccountName is required when IsolateFunctionsHostStorage=true.')
  : AnalyzerHostStorageAccountName
var validatedEmbedHostStorageAccountName = IsolateFunctionsHostStorage && empty(EmbedHostStorageAccountName)
  ? fail('EmbedHostStorageAccountName is required when IsolateFunctionsHostStorage=true.')
  : EmbedHostStorageAccountName
var validatedDispositionHostStorageAccountName = IsolateFunctionsHostStorage && empty(DispositionHostStorageAccountName)
  ? fail('DispositionHostStorageAccountName is required when IsolateFunctionsHostStorage=true.')
  : DispositionHostStorageAccountName
var validatedPortalHostStorageAccountName = IsolateFunctionsHostStorage && empty(PortalHostStorageAccountName)
  ? fail('PortalHostStorageAccountName is required when IsolateFunctionsHostStorage=true.')
  : PortalHostStorageAccountName
var functionHostStorageAccountNames = IsolateFunctionsHostStorage
  ? [
      validatedAnalyzerHostStorageAccountName
      validatedEmbedHostStorageAccountName
      validatedDispositionHostStorageAccountName
      validatedPortalHostStorageAccountName
    ]
  : [FunctionsHostStorageAccountName]

module storage 'modules/storage.bicep' = {
  name: '${DeploymentPrefix}-storage'
  params: {
    location: Location
    functionsHostStorageAccountName: FunctionsHostStorageAccountName
    isolateFunctionsHostStorage: IsolateFunctionsHostStorage
    analyzerHostStorageAccountName: validatedAnalyzerHostStorageAccountName
    embedHostStorageAccountName: validatedEmbedHostStorageAccountName
    dispositionHostStorageAccountName: validatedDispositionHostStorageAccountName
    portalHostStorageAccountName: validatedPortalHostStorageAccountName
    storageSkuName: validatedStorageSkuName
    blobDataProtectionEnabled: validatedBlobDataProtection
    blobSoftDeleteRetentionDays: BlobSoftDeleteRetentionDays
    containerSoftDeleteRetentionDays: ContainerSoftDeleteRetentionDays
    previousVersionRetentionDays: PreviousVersionRetentionDays
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
    functionsHostStorageAccountNames: functionHostStorageAccountNames
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
    chatQuotaContainerName: ChatQuotaContainerName
    deployCaseIndex: hasAnalystPortalProfile
    deployDispositionContainers: ServiceNowDispositionSyncEnabled
    deployChatHistoryContainers: deployChatHistoryContainers
    deployChatQuota: deployPortal && PortalChatDistributedQuotaEnabled
    analyzerPrincipalId: identities.outputs.analyzer.principalId
    embedPrincipalId: identities.outputs.embed.principalId
    dispositionPrincipalId: identities.outputs.disposition.principalId
    portalPrincipalId: identities.outputs.portal.principalId
    zoneRedundant: CosmosZoneRedundant
    continuousBackupEnabled: validatedCosmosContinuousBackup
  }
}

module analyzerHostAccess 'modules/host-storage-access.bicep' = {
  name: '${DeploymentPrefix}-analyzer-host-storage'
  params: {
    functionsHostStorageAccountName: IsolateFunctionsHostStorage ? validatedAnalyzerHostStorageAccountName : FunctionsHostStorageAccountName
    identityResourceId: identities.outputs.analyzer.id
    identityPrincipalId: identities.outputs.analyzer.principalId
  }
}
module embedHostAccess 'modules/host-storage-access.bicep' = {
  name: '${DeploymentPrefix}-embed-host-storage'
  params: {
    functionsHostStorageAccountName: IsolateFunctionsHostStorage ? validatedEmbedHostStorageAccountName : FunctionsHostStorageAccountName
    identityResourceId: identities.outputs.embed.id
    identityPrincipalId: identities.outputs.embed.principalId
  }
}
module dispositionHostAccess 'modules/host-storage-access.bicep' = {
  name: '${DeploymentPrefix}-disposition-host-storage'
  params: {
    functionsHostStorageAccountName: IsolateFunctionsHostStorage ? validatedDispositionHostStorageAccountName : FunctionsHostStorageAccountName
    identityResourceId: identities.outputs.disposition.id
    identityPrincipalId: identities.outputs.disposition.principalId
  }
}
module portalHostAccess 'modules/host-storage-access.bicep' = {
  name: '${DeploymentPrefix}-portal-host-storage'
  params: {
    functionsHostStorageAccountName: IsolateFunctionsHostStorage ? validatedPortalHostStorageAccountName : FunctionsHostStorageAccountName
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

module keyVaultAccess 'modules/keyvault-access.bicep' = if (!empty(validatedKeyVaultName)) {
  name: '${DeploymentPrefix}-keyvault-access'
  params: {
    keyVaultName: validatedKeyVaultName
    secretReaderPrincipalIds: concat(
      [identities.outputs.analyzer.principalId],
      ServiceNowDispositionSyncEnabled ? [identities.outputs.disposition.principalId] : []
    )
  }
}

module observabilityBase 'modules/observability.bicep' = {
  name: '${DeploymentPrefix}-observability'
  params: {
    location: Location
    namePrefix: DeploymentPrefix
    deployCoreResources: true
    deployAlertRules: false
  }
}

resource functionPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${DeploymentPrefix}-functions-plan'
  location: Location
  kind: 'elastic'
  sku: { name: FunctionPlanSkuName, tier: 'ElasticPremium', capacity: FunctionPlanZoneRedundant ? 3 : 1 }
  properties: {
    maximumElasticWorkerCount: max(AnalyzerMaxInstanceCount, EmbedMaxInstanceCount)
    reserved: true
    zoneRedundant: FunctionPlanZoneRedundant
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
    hostBlobServiceUri: storage.outputs.analyzerHostBlobServiceUri
    hostQueueServiceUri: storage.outputs.analyzerHostQueueServiceUri
    hostTableServiceUri: storage.outputs.analyzerHostTableServiceUri
    applicationInsightsConnectionString: observabilityBase.outputs.applicationInsightsConnectionString
    keyVaultUri: empty(validatedKeyVaultName) ? '' : keyVaultAccess!.outputs.keyVaultUri
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
    maxCompressedInputBytes: MaxCompressedInputBytes
    timeoutSeconds: AnalyzerTimeoutSeconds
    zoneRedundant: FunctionPlanZoneRedundant
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
    hostBlobServiceUri: storage.outputs.embedHostBlobServiceUri
    hostQueueServiceUri: storage.outputs.embedHostQueueServiceUri
    hostTableServiceUri: storage.outputs.embedHostTableServiceUri
    applicationInsightsConnectionString: observabilityBase.outputs.applicationInsightsConnectionString
    azureOpenAiEndpoint: AzureOpenAiEndpoint
    azureOpenAiApiVersion: AzureOpenAiApiVersion
    azureOpenAiEmbeddingsDeployment: AzureOpenAiEmbeddingsDeployment
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    caseIndexContainerName: cosmos.outputs.caseIndexContainerName
    capabilityProfiles: CapabilityProfiles
    maxInstanceCount: EmbedMaxInstanceCount
    zoneRedundant: FunctionPlanZoneRedundant
  }
  dependsOn: [registryAccess, embedHostAccess, openAiAccess]
}

module dispositionFunction 'modules/functions-disposition.bicep' = {
  name: '${DeploymentPrefix}-disposition-function'
  params: {
    location: Location
    functionAppName: '${DeploymentPrefix}-notable-disposition-sync'
    serverFarmId: functionPlan.id
    functionSubnetId: network.outputs.functionSubnetId
    containerImageUri: ContainerImageUri
    dispositionIdentityResourceId: identities.outputs.disposition.id
    dispositionIdentityClientId: identities.outputs.disposition.clientId
    dispositionIdentityPrincipalId: identities.outputs.disposition.principalId
    inputStorageAccountName: StorageAccountNameInput
    inputQueueServiceUri: storage.outputs.inputQueueServiceUri
    outputStorageAccountName: StorageAccountNameOutput
    outputBlobServiceUri: storage.outputs.outputBlobServiceUri
    outputQueueServiceUri: storage.outputs.outputQueueServiceUri
    hostBlobServiceUri: storage.outputs.dispositionHostBlobServiceUri
    hostQueueServiceUri: storage.outputs.dispositionHostQueueServiceUri
    hostTableServiceUri: storage.outputs.dispositionHostTableServiceUri
    applicationInsightsConnectionString: observabilityBase.outputs.applicationInsightsConnectionString
    keyVaultUri: empty(validatedKeyVaultName) ? '' : keyVaultAccess!.outputs.keyVaultUri
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    caseIndexContainerName: cosmos.outputs.caseIndexContainerName
    dispositionContainerName: cosmos.outputs.dispositionContainerName
    dispositionSyncStateContainerName: cosmos.outputs.dispositionSyncStateContainerName
    serviceNowBaseUrl: ServiceNowBaseUrl
    serviceNowDispositionSyncEnabled: ServiceNowDispositionSyncEnabled
    serviceNowTimeoutSeconds: ServiceNowTimeoutSeconds
    serviceNowDispositionSyncTokenSecretName: validatedDispositionTokenSecretName
    serviceNowDispositionFieldMap: ServiceNowDispositionFieldMap
    serviceNowDispositionCodeMap: ServiceNowDispositionCodeMap
    serviceNowDispositionBackfillDays: ServiceNowDispositionBackfillDays
    dispositionRetentionDays: DispositionRetentionDays
    allowPrivateOutboundEndpoints: AllowPrivateOutboundEndpoints
    zoneRedundant: FunctionPlanZoneRedundant
  }
  dependsOn: [registryAccess, dispositionHostAccess]
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
    hostBlobServiceUri: storage.outputs.portalHostBlobServiceUri
    hostQueueServiceUri: storage.outputs.portalHostQueueServiceUri
    hostTableServiceUri: storage.outputs.portalHostTableServiceUri
    applicationInsightsConnectionString: observabilityBase.outputs.applicationInsightsConnectionString
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    caseIndexContainerName: cosmos.outputs.caseIndexContainerName
    chatSessionsContainerName: deployChatHistoryContainers ? cosmos.outputs.chatSessionsContainerName : ''
    chatMessagesContainerName: deployChatHistoryContainers ? cosmos.outputs.chatMessagesContainerName : ''
    chatQuotaContainerName: cosmos.outputs.chatQuotaContainerName
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
    portalChatDistributedQuotaEnabled: PortalChatDistributedQuotaEnabled
    portalChatPerUserMaxConcurrency: PortalChatPerUserMaxConcurrency
    portalChatQuotaWindowSeconds: PortalChatQuotaWindowSeconds
    portalChatMaxRequestsPerWindow: validatedPortalChatMaxRequestsPerWindow
    portalChatMaxBudgetUnitsPerWindow: PortalChatMaxBudgetUnitsPerWindow
    portalChatBudgetUnitsPerRequest: PortalChatBudgetUnitsPerRequest
    portalChatLeaseSeconds: PortalChatLeaseSeconds
    portalChatRequestDedupeSeconds: PortalChatRequestDedupeSeconds
    caseQaChatHistoryEnabled: deployChatHistoryContainers
    portalChatTimeoutSec: PortalChatTimeoutSec
    zoneRedundant: FunctionPlanZoneRedundant
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
  }
}

module observabilityAlerts 'modules/observability.bicep' = if (!empty(validatedAlertActionGroupResourceId)) {
  name: '${DeploymentPrefix}-monitor-alerts'
  params: {
    location: Location
    namePrefix: DeploymentPrefix
    deployCoreResources: false
    deployAlertRules: true
    alertActionGroupResourceId: validatedAlertActionGroupResourceId
    inputQueueServiceResourceId: storage.outputs.inputQueueServiceId
    outputQueueServiceResourceId: storage.outputs.outputQueueServiceId
    foundryResourceId: AzureAiFoundryResourceId
    azureOpenAiResourceId: AzureOpenAiResourceId
    cosmosResourceId: cosmos.outputs.accountId
    frontDoorProfileResourceId: deployPortal ? portalFrontDoor!.outputs.profileId : ''
    dispositionSyncEnabled: ServiceNowDispositionSyncEnabled
    analystPortalEnabled: deployPortal
    syntheticCheckName: validatedSyntheticCheckName
    queueDepthTracePrefix: queueDepthTracePrefix
    poisonQueueDepthThreshold: PoisonQueueDepthThreshold
    analyzerQueueBacklogThreshold: AnalyzerQueueBacklogThreshold
    embedQueueBacklogThreshold: EmbedQueueBacklogThreshold
    modelErrorThreshold: ModelErrorThreshold
    modelThrottleThreshold: ModelThrottleThreshold
    cosmosThrottleThreshold: CosmosThrottleThreshold
    frontDoor5xxPercentageThreshold: FrontDoor5xxPercentageThreshold
    dispositionCompletionGraceHours: DispositionCompletionGraceHours
    queueTelemetryMaxAgeMinutes: QueueTelemetryMaxAgeMinutes
  }
  dependsOn: [analyzerFunction, embedFunction, dispositionFunction]
}

output DeploymentLocation string = Location
output ConfiguredCloud string = cloudEnvironment
output AnalyzerFunctionAppName string = analyzerFunction.outputs.functionAppName
output EmbedFunctionAppName string = embedFunction.outputs.functionAppName
output DispositionFunctionAppName string = dispositionFunction.outputs.functionAppName
output PortalFunctionAppName string = deployPortal ? portalFunction!.outputs.functionAppName : ''
output PortalApiManagementName string = deployPortal ? portalApiManagement!.outputs.apiManagementName : ''
output PortalFrontDoorProfileName string = deployPortal ? portalFrontDoor!.outputs.profileName : ''
output MonitoringAlertRuleNames array = empty(validatedAlertActionGroupResourceId) ? [] : observabilityAlerts!.outputs.alertRuleNames
output ApplicationInsightsName string = '${DeploymentPrefix}-insights'
output LogAnalyticsWorkspaceCustomerId string = observabilityBase.outputs.workspaceCustomerId
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
output ChatQuotaContainerName string = cosmos.outputs.chatQuotaContainerName
output PortalApiUrl string = deployPortal ? 'https://${portalFrontDoor!.outputs.endpointHostName}/api' : ''
output PortalChatUrl string = deployPortal ? 'https://${portalFrontDoor!.outputs.endpointHostName}/api/chat' : ''
output PortalBrowserApiBaseUrl string = deployPortal ? 'https://${portalFrontDoor!.outputs.endpointHostName}' : ''
output PortalFrontDoorHostName string = deployPortal ? portalFrontDoor!.outputs.endpointHostName : ''
output PortalUiStorageAccountName string = StorageAccountNamePortalUi
