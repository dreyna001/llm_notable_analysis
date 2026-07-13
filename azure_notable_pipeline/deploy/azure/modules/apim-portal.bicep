targetScope = 'resourceGroup'

param location string
param apiManagementName string
param apiManagementSkuName string = 'StandardV2'
param publisherEmail string
param publisherName string = 'Notable Analysis'
param apimSubnetId string
param portalFunctionHostName string

@allowed(['jwt', 'iam'])
param portalAuthMode string = 'jwt'
param portalJwtIssuer string
param portalJwtAudience string
param portalEntraRequiredAppRole string = ''

var portalOpenIdConfigurationUrl = endsWith(portalJwtIssuer, '/')
  ? '${portalJwtIssuer}.well-known/openid-configuration'
  : '${portalJwtIssuer}/.well-known/openid-configuration'
var requiredRoleClaim = portalAuthMode == 'iam'
  ? '<claim name="roles" match="any"><value>${portalEntraRequiredAppRole}</value></claim>'
  : ''
var apiPolicy = '<policies><inbound><base /><validate-jwt header-name="Authorization" require-scheme="Bearer" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized" require-expiration-time="true" require-signed-tokens="true"><openid-config url="${portalOpenIdConfigurationUrl}" /><audiences><audience>${portalJwtAudience}</audience></audiences><issuers><issuer>${portalJwtIssuer}</issuer></issuers><required-claims><claim name="sub" match="any" />${requiredRoleClaim}</required-claims></validate-jwt></inbound><backend><forward-request timeout="30" /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'

resource apiManagement 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apiManagementName
  location: location
  sku: {
    name: apiManagementSkuName
    capacity: 1
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    publicNetworkAccess: 'Enabled'
    virtualNetworkType: 'External'
    virtualNetworkConfiguration: {
      subnetResourceId: apimSubnetId
    }
    disableGateway: false
  }
}

resource portalApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apiManagement
  name: 'portal'
  properties: {
    displayName: 'Notable Analyst Portal'
    path: ''
    protocols: ['https']
    serviceUrl: 'https://${portalFunctionHostName}'
    subscriptionRequired: false
    format: 'openapi+json'
    value: loadTextContent('../../../docs/contracts/portal.openapi.json')
  }
}

resource portalApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: portalApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: apiPolicy
  }
}

output apiManagementId string = apiManagement.id
output apiManagementName string = apiManagement.name
output gatewayHostName string = '${apiManagement.name}.azure-api.net'
output gatewayUrl string = 'https://${apiManagement.name}.azure-api.net'
