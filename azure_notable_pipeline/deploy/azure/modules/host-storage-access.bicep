targetScope = 'resourceGroup'

param functionsHostStorageAccountName string
param identityResourceId string
param identityPrincipalId string

resource hostStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: functionsHostStorageAccountName
}

var blobOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var queueContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var tableContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource hostBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(hostStorage.id, identityResourceId, blobOwnerRoleId)
  scope: hostStorage
  properties: {
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobOwnerRoleId)
  }
}
resource hostQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(hostStorage.id, identityResourceId, queueContributorRoleId)
  scope: hostStorage
  properties: {
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueContributorRoleId)
  }
}
resource hostTable 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(hostStorage.id, identityResourceId, tableContributorRoleId)
  scope: hostStorage
  properties: {
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', tableContributorRoleId)
  }
}
