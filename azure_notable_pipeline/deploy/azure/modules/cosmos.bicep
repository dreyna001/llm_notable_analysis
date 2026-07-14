targetScope = 'resourceGroup'

@description('Azure region for the single-region Cosmos account.')
param location string

@description('Enable availability-zone placement in the write region. The selected region must support Cosmos availability zones.')
param zoneRedundant bool = false

@description('Use continuous seven-day backup. False preserves the account default periodic backup contract.')
param continuousBackupEnabled bool = false

@description('Globally unique Cosmos DB account name.')
param accountName string

@description('Cosmos DB for NoSQL database name.')
param databaseName string

param sideEffectIdempotencyContainerName string = 'notable-side-effect-idempotency'
param caseIndexContainerName string
param dispositionContainerName string
param dispositionSyncStateContainerName string
param chatSessionsContainerName string
param chatMessagesContainerName string
param chatQuotaContainerName string

@description('Create the case-index aggregate for the analyst_portal profile.')
param deployCaseIndex bool = false

@description('Create ServiceNow disposition aggregates when disposition sync is enabled.')
param deployDispositionContainers bool = false

@description('Create chat-history aggregates only for analyst_portal deployments with history enabled.')
param deployChatHistoryContainers bool = false

@description('Create the per-user distributed chat admission-control aggregate for analyst portal deployments.')
param deployChatQuota bool = false

param analyzerPrincipalId string
param embedPrincipalId string
param dispositionPrincipalId string
param portalPrincipalId string

var dataReaderRoleDefinitionId = '00000000-0000-0000-0000-000000000001'
var dataContributorRoleDefinitionId = '00000000-0000-0000-0000-000000000002'

var defaultIndexingPolicy = {
  indexingMode: 'consistent'
  automatic: true
  includedPaths: [
    { path: '/*' }
  ]
  excludedPaths: [
    { path: '/"_etag"/?' }
  ]
}

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: accountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: union({
    databaseAccountOfferType: 'Standard'
    capabilities: [
      { name: 'EnableServerless' }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Strong'
    }
    disableKeyBasedMetadataWriteAccess: true
    disableLocalAuth: true
    enableAutomaticFailover: false
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: zoneRedundant
      }
    ]
  }, continuousBackupEnabled ? {
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
  } : {})
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource sideEffectIdempotency 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: sideEffectIdempotencyContainerName
  properties: {
    resource: {
      id: sideEffectIdempotencyContainerName
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: defaultIndexingPolicy
    }
  }
}

resource caseIndex 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = if (deployCaseIndex) {
  parent: database
  name: caseIndexContainerName
  properties: {
    resource: {
      id: caseIndexContainerName
      partitionKey: {
        paths: ['/case_id']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: union(defaultIndexingPolicy, {
        compositeIndexes: [
          [
            { path: '/processed_at', order: 'descending' }
            { path: '/case_id', order: 'descending' }
          ]
          [
            { path: '/correlation_id', order: 'ascending' }
            { path: '/processed_at', order: 'descending' }
            { path: '/case_id', order: 'descending' }
          ]
        ]
      })
    }
  }
}

resource disposition 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = if (deployDispositionContainers) {
  parent: database
  name: dispositionContainerName
  properties: {
    resource: {
      id: dispositionContainerName
      partitionKey: {
        paths: ['/snow_sys_id']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: union(defaultIndexingPolicy, {
        compositeIndexes: [
          [
            { path: '/correlation_id', order: 'ascending' }
            { path: '/sys_updated_on', order: 'descending' }
            { path: '/snow_sys_id', order: 'ascending' }
          ]
          [
            { path: '/case_id', order: 'ascending' }
            { path: '/sys_updated_on', order: 'descending' }
            { path: '/snow_sys_id', order: 'ascending' }
          ]
          [
            { path: '/status', order: 'ascending' }
            { path: '/sys_updated_on', order: 'descending' }
            { path: '/snow_sys_id', order: 'ascending' }
          ]
        ]
      })
    }
  }
}

resource dispositionSyncState 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = if (deployDispositionContainers) {
  parent: database
  name: dispositionSyncStateContainerName
  properties: {
    resource: {
      id: dispositionSyncStateContainerName
      partitionKey: {
        paths: ['/job_name']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: defaultIndexingPolicy
    }
  }
}

resource chatSessions 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = if (deployChatHistoryContainers) {
  parent: database
  name: chatSessionsContainerName
  properties: {
    resource: {
      id: chatSessionsContainerName
      partitionKey: {
        paths: ['/user_id']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: union(defaultIndexingPolicy, {
        compositeIndexes: [
          [
            { path: '/user_id', order: 'ascending' }
            { path: '/updated_at', order: 'descending' }
            { path: '/session_id', order: 'descending' }
          ]
        ]
      })
    }
  }
}

resource chatMessages 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = if (deployChatHistoryContainers) {
  parent: database
  name: chatMessagesContainerName
  properties: {
    resource: {
      id: chatMessagesContainerName
      partitionKey: {
        paths: ['/session_id']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: union(defaultIndexingPolicy, {
        compositeIndexes: [
          [
            { path: '/created_at', order: 'ascending' }
            { path: '/message_id', order: 'ascending' }
          ]
        ]
      })
    }
  }
}

resource chatQuota 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = if (deployChatQuota) {
  parent: database
  name: chatQuotaContainerName
  properties: {
    resource: {
      id: chatQuotaContainerName
      partitionKey: {
        paths: ['/user_id']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: defaultIndexingPolicy
    }
  }
}

resource analyzerSideEffectContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: account
  name: guid(sideEffectIdempotency.id, analyzerPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    principalId: analyzerPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'
    scope: sideEffectIdempotency.id
  }
}

resource analyzerCaseContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployCaseIndex) {
  parent: account
  name: guid(caseIndex.id, analyzerPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    principalId: analyzerPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'
    scope: caseIndex.id
  }
}

resource embedCaseContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployCaseIndex) {
  parent: account
  name: guid(caseIndex.id, embedPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    principalId: embedPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'
    scope: caseIndex.id
  }
}

resource portalCaseReader 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployCaseIndex) {
  parent: account
  name: guid(caseIndex.id, portalPrincipalId, dataReaderRoleDefinitionId)
  properties: {
    principalId: portalPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataReaderRoleDefinitionId}'
    scope: caseIndex.id
  }
}

resource dispositionCaseReader 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployDispositionContainers && deployCaseIndex) {
  parent: account
  name: guid(caseIndex.id, dispositionPrincipalId, dataReaderRoleDefinitionId)
  properties: {
    principalId: dispositionPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataReaderRoleDefinitionId}'
    scope: caseIndex.id
  }
}

resource dispositionDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployDispositionContainers) {
  parent: account
  name: guid(disposition.id, dispositionPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    principalId: dispositionPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'
    scope: disposition.id
  }
}

resource dispositionSyncStateContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployDispositionContainers) {
  parent: account
  name: guid(dispositionSyncState.id, dispositionPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    principalId: dispositionPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'
    scope: dispositionSyncState.id
  }
}

resource portalChatSessionsContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployChatHistoryContainers) {
  parent: account
  name: guid(chatSessions.id, portalPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    principalId: portalPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'
    scope: chatSessions.id
  }
}

resource portalChatMessagesContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployChatHistoryContainers) {
  parent: account
  name: guid(chatMessages.id, portalPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    principalId: portalPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'
    scope: chatMessages.id
  }
}

resource portalChatQuotaContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (deployChatQuota) {
  parent: account
  name: guid(chatQuota.id, portalPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    principalId: portalPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'
    scope: chatQuota.id
  }
}

output accountId string = account.id
output endpoint string = account.properties.documentEndpoint
output databaseName string = database.name
output sideEffectIdempotencyContainerName string = sideEffectIdempotency.name
output caseIndexContainerName string = deployCaseIndex ? caseIndex.name : ''
output dispositionContainerName string = deployDispositionContainers ? disposition.name : ''
output dispositionSyncStateContainerName string = deployDispositionContainers ? dispositionSyncState.name : ''
output chatSessionsContainerName string = deployChatHistoryContainers ? chatSessions.name : ''
output chatMessagesContainerName string = deployChatHistoryContainers ? chatMessages.name : ''
output chatQuotaContainerName string = deployChatQuota ? chatQuota.name : ''
