targetScope = 'resourceGroup'

param location string
param functionsHostStorageAccountName string
param inputStorageAccountName string
param outputStorageAccountName string
param portalUiStorageAccountName string = ''

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

resource hostStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: functionsHostStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: commonProperties
}

resource inputStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: inputStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: commonProperties
}

resource outputStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: outputStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: commonProperties
}

resource portalStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = if (!empty(portalUiStorageAccountName)) {
  name: portalUiStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: commonProperties
}

resource inputBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: inputStorage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: false }
    isVersioningEnabled: false
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
    deleteRetentionPolicy: { enabled: false }
    isVersioningEnabled: false
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

resource hostBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: hostStorage
  name: 'default'
}

resource hostQueueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: hostStorage
  name: 'default'
}

resource hostTableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: hostStorage
  name: 'default'
}

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
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: inputRetentionDays } } }
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
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: outputRetentionDays } } }
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['output/reports/'] }
          }
        }
        {
          name: 'expire-cases'
          enabled: true
          type: 'Lifecycle'
          definition: {
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: caseRetentionDays } } }
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['output/cases/', 'output/case_chunks/'] }
          }
        }
      ]
    }
  }
}

output hostStorageId string = hostStorage.id
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
output inputBlobServiceUri string = 'https://${inputStorage.name}.blob.${environment().suffixes.storage}'
output inputQueueServiceUri string = 'https://${inputStorage.name}.queue.${environment().suffixes.storage}'
output outputBlobServiceUri string = 'https://${outputStorage.name}.blob.${environment().suffixes.storage}'
output outputQueueServiceUri string = 'https://${outputStorage.name}.queue.${environment().suffixes.storage}'
output hostBlobServiceUri string = 'https://${hostStorage.name}.blob.${environment().suffixes.storage}'
output hostQueueServiceUri string = 'https://${hostStorage.name}.queue.${environment().suffixes.storage}'
output hostTableServiceUri string = 'https://${hostStorage.name}.table.${environment().suffixes.storage}'
