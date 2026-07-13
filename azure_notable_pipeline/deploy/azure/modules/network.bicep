targetScope = 'resourceGroup'

param location string
param namePrefix string
param inputStorageAccountName string
param outputStorageAccountName string
param functionsHostStorageAccountName string
param portalUiStorageAccountName string = ''

@description('CIDR for the regional application VNet.')
param vnetAddressPrefix string = '10.42.0.0/16'
param functionSubnetPrefix string = '10.42.0.0/24'
param privateEndpointSubnetPrefix string = '10.42.1.0/24'

resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: '${namePrefix}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: [vnetAddressPrefix] }
    subnets: [
      {
        name: 'functions-integration'
        properties: {
          addressPrefix: functionSubnetPrefix
          delegations: [
            {
              name: 'web-serverfarms'
              properties: { serviceName: 'Microsoft.Web/serverFarms' }
            }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource functionSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-01-01' existing = {
  parent: vnet
  name: 'functions-integration'
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-01-01' existing = {
  parent: vnet
  name: 'private-endpoints'
}

var storageSuffix = environment().suffixes.storage
resource blobDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.blob.${storageSuffix}'
  location: 'global'
}
resource queueDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.queue.${storageSuffix}'
  location: 'global'
}
resource tableDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.table.${storageSuffix}'
  location: 'global'
}
resource webDns 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!empty(portalUiStorageAccountName)) {
  name: 'privatelink.web.${storageSuffix}'
  location: 'global'
}

resource blobDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: blobDns
  name: '${namePrefix}-blob-vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}
resource queueDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: queueDns
  name: '${namePrefix}-queue-vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}
resource tableDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: tableDns
  name: '${namePrefix}-table-vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}
resource webDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (!empty(portalUiStorageAccountName)) {
  parent: webDns
  name: '${namePrefix}-web-vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

var endpointSpecs = [
  {
    name: 'input-blob'
    accountName: inputStorageAccountName
    subresource: 'blob'
    zoneId: blobDns.id
  }
  {
    name: 'input-queue'
    accountName: inputStorageAccountName
    subresource: 'queue'
    zoneId: queueDns.id
  }
  { name: 'output-blob', accountName: outputStorageAccountName, subresource: 'blob', zoneId: blobDns.id }
  { name: 'output-queue', accountName: outputStorageAccountName, subresource: 'queue', zoneId: queueDns.id }
  { name: 'host-blob', accountName: functionsHostStorageAccountName, subresource: 'blob', zoneId: blobDns.id }
  { name: 'host-queue', accountName: functionsHostStorageAccountName, subresource: 'queue', zoneId: queueDns.id }
  { name: 'host-table', accountName: functionsHostStorageAccountName, subresource: 'table', zoneId: tableDns.id }
]

resource storagePrivateEndpoints 'Microsoft.Network/privateEndpoints@2024-01-01' = [
  for spec in endpointSpecs: {
    name: '${namePrefix}-${spec.name}-pe'
    location: location
    properties: {
      subnet: { id: privateEndpointSubnet.id }
      privateLinkServiceConnections: [
        {
          name: '${spec.name}-connection'
          properties: {
          privateLinkServiceId: resourceId('Microsoft.Storage/storageAccounts', spec.accountName)
          groupIds: [spec.subresource]
          }
        }
      ]
    }
  }
]

resource storagePrivateEndpointDnsZoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = [
  for (spec, i) in endpointSpecs: {
    parent: storagePrivateEndpoints[i]
    name: 'default'
    properties: {
      privateDnsZoneConfigs: [
        {
        name: spec.subresource
          properties: { privateDnsZoneId: spec.zoneId }
        }
      ]
    }
  }
]

resource portalWebPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-01-01' = if (!empty(portalUiStorageAccountName)) {
  name: '${namePrefix}-portal-web-pe'
  location: location
  properties: {
    subnet: { id: privateEndpointSubnet.id }
    privateLinkServiceConnections: [
      {
        name: 'portal-web-connection'
        properties: {
          privateLinkServiceId: resourceId('Microsoft.Storage/storageAccounts', portalUiStorageAccountName)
          groupIds: ['web']
        }
      }
    ]
  }
  resource dnsZoneGroup 'privateDnsZoneGroups' = {
    name: 'default'
    properties: { privateDnsZoneConfigs: [{ name: 'web', properties: { privateDnsZoneId: webDns.id } }] }
  }
}

output vnetId string = vnet.id
output functionSubnetId string = functionSubnet.id
output privateEndpointSubnetId string = privateEndpointSubnet.id
