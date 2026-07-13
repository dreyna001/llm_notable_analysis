targetScope = 'resourceGroup'

param location string
param namePrefix string

resource analyzer 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-analyzer-mi'
  location: location
}
resource embed 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-embed-mi'
  location: location
}
resource disposition 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-disposition-mi'
  location: location
}
resource portal 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-portal-mi'
  location: location
}

output analyzer object = {
  id: analyzer.id
  clientId: analyzer.properties.clientId
  principalId: analyzer.properties.principalId
}
output embed object = { id: embed.id, clientId: embed.properties.clientId, principalId: embed.properties.principalId }
output disposition object = {
  id: disposition.id
  clientId: disposition.properties.clientId
  principalId: disposition.properties.principalId
}
output portal object = {
  id: portal.id
  clientId: portal.properties.clientId
  principalId: portal.properties.principalId
}
