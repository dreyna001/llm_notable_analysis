targetScope = 'resourceGroup'

param location string
param functionsHostStorageAccountName string
param analyzerHostStorageAccountName string = ''
param embedHostStorageAccountName string = ''
param dispositionHostStorageAccountName string = ''
param portalHostStorageAccountName string = ''
param isolateFunctionsHostStorage bool = false
param inputStorageAccountName string
param outputStorageAccountName string
param portalUiStorageAccountName string = ''
param portalUiDeployerPrincipalId string = ''

@allowed(['Standard_LRS', 'Standard_ZRS'])
param storageSkuName string = 'Standard_LRS'

param blobDataProtectionEnabled bool = false

@minValue(1)
@maxValue(365)
param blobSoftDeleteRetentionDays int = 30

@minValue(1)
@maxValue(365)
param containerSoftDeleteRetentionDays int = 30

@minValue(1)
param previousVersionRetentionDays int = 30

@minValue(1)
param inputRetentionDays int = 2

@minValue(1)
param outputRetentionDays int = 30

@minValue(1)
param caseRetentionDays int = 30

var commonProperties = {
  accessTier: 'Hot'
  allowBlobPublicAccess: false
  allowCrossTenantReplication: false
  allowSharedKeyAccess: false
  defaultToOAuthAuthentication: true
  minimumTlsVersion: 'TLS1_2'
  publicNetworkAccess: 'Disabled'
  supportsHttpsTrafficOnly: true
  networkAcls: {
    bypass: 'None'
    defaultAction: 'Deny'
  }
  encryption: {
    keySource: 'Microsoft.Storage'
    requireInfrastructureEncryption: false
    services: {
      blob: { enabled: true }
      file: { enabled: true }
    }
  }
}

var hostStorageAccountNames = isolateFunctionsHostStorage
  ? [
      analyzerHostStorageAccountName
      embedHostStorageAccountName
      dispositionHostStorageAccountName
      portalHostStorageAccountName
    ]
  : [functionsHostStorageAccountName]

resource hostStorages 'Microsoft.Storage/storageAccounts@2023-05-01' = [for accountName in hostStorageAccountNames: {
  name: accountName
  location: location
  kind: 'StorageV2'
  sku: { name: storageSkuName }
  properties: commonProperties
}]

resource inputStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: inputStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: storageSkuName }
  properties: commonProperties
}

resource outputStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: outputStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: storageSkuName }
  properties: commonProperties
}

resource portalStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = if (!empty(portalUiStorageAccountName)) {
  name: portalUiStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: storageSkuName }
  properties: commonProperties
}

resource portalBlobService 'Microsoft.Storage/storageAccounts/blobServices@2025-08-01' = if (!empty(portalUiStorageAccountName)) {
  parent: portalStorage
  name: 'default'
  properties: {
    staticWebsite: {
      enabled: true
      indexDocument: 'index.html'
      errorDocument404Path: 'index.html'
    }
  }
}

var blobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
resource portalUiDeployerBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(portalUiStorageAccountName) && !empty(portalUiDeployerPrincipalId)) {
  name: guid(portalStorage.id, portalUiDeployerPrincipalId, blobContributorRoleId)
  scope: portalStorage
  properties: {
    principalId: portalUiDeployerPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
  }
}

resource inputBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: inputStorage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: blobDataProtectionEnabled
      days: blobDataProtectionEnabled ? blobSoftDeleteRetentionDays : null
    }
    containerDeleteRetentionPolicy: {
      enabled: blobDataProtectionEnabled
      days: blobDataProtectionEnabled ? containerSoftDeleteRetentionDays : null
    }
    isVersioningEnabled: blobDataProtectionEnabled
  }
}

resource inputContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: inputBlobService
  name: 'input'
  properties: { publicAccess: 'None' }
}

resource inputQueueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: inputStorage
  name: 'default'
}

resource outputBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: outputStorage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: blobDataProtectionEnabled
      days: blobDataProtectionEnabled ? blobSoftDeleteRetentionDays : null
    }
    containerDeleteRetentionPolicy: {
      enabled: blobDataProtectionEnabled
      days: blobDataProtectionEnabled ? containerSoftDeleteRetentionDays : null
    }
    isVersioningEnabled: blobDataProtectionEnabled
  }
}

resource outputContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: outputBlobService
  name: 'output'
  properties: { publicAccess: 'None' }
}

resource outputQueueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: outputStorage
  name: 'default'
}

resource analyzerQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: outputQueueService
  name: 'notable-analysis-jobs'
}

resource embedQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: outputQueueService
  name: 'case-embed-invocations'
}

resource hostBlobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = [for (accountName, i) in hostStorageAccountNames: {
  parent: hostStorages[i]
  name: 'default'
}]

resource hostQueueServices 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = [for (accountName, i) in hostStorageAccountNames: {
  parent: hostStorages[i]
  name: 'default'
}]

resource hostTableServices 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = [for (accountName, i) in hostStorageAccountNames: {
  parent: hostStorages[i]
  name: 'default'
}]

resource inputLifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: inputStorage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-incoming'
          enabled: true
          type: 'Lifecycle'
          definition: {
            actions: union(
              { baseBlob: { delete: { daysAfterModificationGreaterThan: inputRetentionDays } } },
              blobDataProtectionEnabled
                ? { version: { delete: { daysAfterCreationGreaterThan: previousVersionRetentionDays } } }
                : {}
            )
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['input/incoming/'] }
          }
        }
      ]
    }
  }
}

resource outputLifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: outputStorage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-reports'
          enabled: true
          type: 'Lifecycle'
          definition: {
            actions: union(
              { baseBlob: { delete: { daysAfterModificationGreaterThan: outputRetentionDays } } },
              blobDataProtectionEnabled
                ? { version: { delete: { daysAfterCreationGreaterThan: previousVersionRetentionDays } } }
                : {}
            )
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['output/reports/'] }
          }
        }
        {
          name: 'expire-cases'
          enabled: true
          type: 'Lifecycle'
          definition: {
            actions: union(
              { baseBlob: { delete: { daysAfterModificationGreaterThan: caseRetentionDays } } },
              blobDataProtectionEnabled
                ? { version: { delete: { daysAfterCreationGreaterThan: previousVersionRetentionDays } } }
                : {}
            )
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['output/cases/', 'output/case_chunks/'] }
          }
        }
      ]
    }
  }
}

output hostStorageIds array = [for (accountName, i) in hostStorageAccountNames: hostStorages[i].id]
output inputStorageId string = inputStorage.id
output inputContainerId string = inputContainer.id
output inputQueueServiceId string = inputQueueService.id
output outputStorageId string = outputStorage.id
output outputContainerId string = outputContainer.id
output outputQueueServiceId string = outputQueueService.id
output analyzerQueueId string = analyzerQueue.id
output embedQueueId string = embedQueue.id
output analyzerQueueAccountName string = outputStorageAccountName
output analyzerQueueName string = analyzerQueue.name
output embedQueueAccountName string = outputStorageAccountName
output embedQueueName string = embedQueue.name
output portalStorageId string = empty(portalUiStorageAccountName) ? '' : portalStorage.id
output portalWebHostName string = empty(portalUiStorageAccountName) ? '' : replace(replace(portalStorage!.properties.primaryEndpoints.web, 'https://', ''), '/', '')
output inputBlobServiceUri string = 'https://${inputStorage.name}.blob.${environment().suffixes.storage}'
output inputQueueServiceUri string = 'https://${inputStorage.name}.queue.${environment().suffixes.storage}'
output outputBlobServiceUri string = 'https://${outputStorage.name}.blob.${environment().suffixes.storage}'
output outputQueueServiceUri string = 'https://${outputStorage.name}.queue.${environment().suffixes.storage}'
output analyzerHostBlobServiceUri string = 'https://${isolateFunctionsHostStorage ? analyzerHostStorageAccountName : functionsHostStorageAccountName}.blob.${environment().suffixes.storage}'
output analyzerHostQueueServiceUri string = 'https://${isolateFunctionsHostStorage ? analyzerHostStorageAccountName : functionsHostStorageAccountName}.queue.${environment().suffixes.storage}'
output analyzerHostTableServiceUri string = 'https://${isolateFunctionsHostStorage ? analyzerHostStorageAccountName : functionsHostStorageAccountName}.table.${environment().suffixes.storage}'
output embedHostBlobServiceUri string = 'https://${isolateFunctionsHostStorage ? embedHostStorageAccountName : functionsHostStorageAccountName}.blob.${environment().suffixes.storage}'
output embedHostQueueServiceUri string = 'https://${isolateFunctionsHostStorage ? embedHostStorageAccountName : functionsHostStorageAccountName}.queue.${environment().suffixes.storage}'
output embedHostTableServiceUri string = 'https://${isolateFunctionsHostStorage ? embedHostStorageAccountName : functionsHostStorageAccountName}.table.${environment().suffixes.storage}'
output dispositionHostBlobServiceUri string = 'https://${isolateFunctionsHostStorage ? dispositionHostStorageAccountName : functionsHostStorageAccountName}.blob.${environment().suffixes.storage}'
output dispositionHostQueueServiceUri string = 'https://${isolateFunctionsHostStorage ? dispositionHostStorageAccountName : functionsHostStorageAccountName}.queue.${environment().suffixes.storage}'
output dispositionHostTableServiceUri string = 'https://${isolateFunctionsHostStorage ? dispositionHostStorageAccountName : functionsHostStorageAccountName}.table.${environment().suffixes.storage}'
output portalHostBlobServiceUri string = 'https://${isolateFunctionsHostStorage ? portalHostStorageAccountName : functionsHostStorageAccountName}.blob.${environment().suffixes.storage}'
output portalHostQueueServiceUri string = 'https://${isolateFunctionsHostStorage ? portalHostStorageAccountName : functionsHostStorageAccountName}.queue.${environment().suffixes.storage}'
output portalHostTableServiceUri string = 'https://${isolateFunctionsHostStorage ? portalHostStorageAccountName : functionsHostStorageAccountName}.table.${environment().suffixes.storage}'
