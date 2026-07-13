targetScope = 'resourceGroup'

param foundryAccountName string
param analyzerPrincipalId string

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryAccountName
}

var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
resource analyzerFoundryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, analyzerPrincipalId, cognitiveServicesUserRoleId)
  scope: foundry
  properties: {
    principalId: analyzerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
  }
}

output foundryId string = foundry.id
