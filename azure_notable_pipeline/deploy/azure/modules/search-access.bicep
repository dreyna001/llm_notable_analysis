targetScope = 'resourceGroup'

param searchServiceName string
param analyzerPrincipalId string
param portalPrincipalId string = ''
param dispositionPrincipalId string = ''

resource search 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: searchServiceName
}

var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
resource analyzerIndexContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, analyzerPrincipalId, searchIndexDataContributorRoleId)
  scope: search
  properties: {
    principalId: analyzerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
  }
}

resource portalIndexReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(portalPrincipalId)) {
  name: guid(search.id, portalPrincipalId, searchIndexDataReaderRoleId)
  scope: search
  properties: {
    principalId: portalPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
  }
}

resource dispositionIndexContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(dispositionPrincipalId)) {
  name: guid(search.id, dispositionPrincipalId, searchIndexDataContributorRoleId)
  scope: search
  properties: {
    principalId: dispositionPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
  }
}
