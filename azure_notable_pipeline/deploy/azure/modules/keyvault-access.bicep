targetScope = 'resourceGroup'

param keyVaultName string
param secretReaderPrincipalIds array

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
resource secretReaderAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in secretReaderPrincipalIds: {
    name: guid(keyVault.id, principalId, secretsUserRoleId)
    scope: keyVault
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
    }
  }
]

output keyVaultUri string = keyVault.properties.vaultUri
