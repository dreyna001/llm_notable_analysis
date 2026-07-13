targetScope = 'resourceGroup'

param searchServiceName string
param principalIds array

resource search 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: searchServiceName
}

var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
resource indexReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in principalIds: {
  name: guid(search.id, principalId, searchIndexDataReaderRoleId)
  scope: search
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
  }
}]
