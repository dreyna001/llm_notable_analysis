targetScope = 'resourceGroup'

param keyVaultName string
param secretReaderPrincipalIds array
param customerManagedKeyEnabled bool = false
param customerManagedKeyIdentityResourceId string = ''

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

var keyVaultCryptoUserRoleId = 'e147488a-f6f5-4113-8e2d-b22465e65bf6'
resource customerManagedKeyAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (customerManagedKeyEnabled) {
  name: guid(keyVault.id, customerManagedKeyIdentityResourceId, keyVaultCryptoUserRoleId)
  scope: keyVault
  properties: {
    principalId: reference(customerManagedKeyIdentityResourceId, '2018-11-30').principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultCryptoUserRoleId)
  }
}

output keyVaultUri string = keyVault.properties.vaultUri
