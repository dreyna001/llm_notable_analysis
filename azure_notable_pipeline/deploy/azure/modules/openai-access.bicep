targetScope = 'resourceGroup'

param openAiAccountName string
param embedPrincipalId string
param portalPrincipalId string = ''

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAiAccountName
}

var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
resource embedOpenAiAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAi.id, embedPrincipalId, openAiUserRoleId)
  scope: openAi
  properties: {
    principalId: embedPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
  }
}

resource portalOpenAiAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(portalPrincipalId)) {
  name: guid(openAi.id, portalPrincipalId, openAiUserRoleId)
  scope: openAi
  properties: {
    principalId: portalPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
  }
}
