targetScope = 'resourceGroup'

param location string
param apiManagementName string
param apiManagementSkuName string = 'StandardV2'
param publisherEmail string
param publisherName string = 'Notable Analysis'
param apimSubnetId string
param portalFunctionHostName string

param portalJwtIssuer string
param portalJwtAudience string
param portalEntraRequiredAppRole string = ''

var portalOpenIdConfigurationUrl = endsWith(portalJwtIssuer, '/')
  ? '${portalJwtIssuer}.well-known/openid-configuration'
  : '${portalJwtIssuer}/.well-known/openid-configuration'
var apiPolicy = '<policies><inbound><base /><validate-jwt header-name="Authorization" require-scheme="Bearer" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized" require-expiration-time="true" require-signed-tokens="true" output-token-variable-name="portalJwt"><openid-config url="${portalOpenIdConfigurationUrl}" /><audiences><audience>${portalJwtAudience}</audience></audiences><issuers><issuer>${portalJwtIssuer}</issuer></issuers><required-claims><claim name="sub" match="any" /></required-claims></validate-jwt><choose><when condition="@{ var jwt = (Jwt)context.Variables[&quot;portalJwt&quot;]; var required = &quot;${portalEntraRequiredAppRole}&quot;; var roles = jwt.Claims.GetValueOrDefault(&quot;roles&quot;, new string[0]); var scopes = jwt.Claims.GetValueOrDefault(&quot;scp&quot;, new string[0]).SelectMany(value => value.Split(&apos; &apos;)); return !roles.Concat(scopes).Contains(required); }"><return-response><set-status code="403" reason="Forbidden" /><set-body>{&quot;error&quot;:&quot;Forbidden&quot;}</set-body></return-response></when></choose></inbound><backend><forward-request timeout="30" /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'
// The browser stops waiting at 220 seconds and the Function host at 225 seconds.
// This operation-only budget gives APIM time to receive and forward the Function response
// while keeping every other portal operation on the API-level 30-second timeout.
var chatOperationPolicy = '<policies><inbound><base /></inbound><backend><forward-request timeout="230" /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'

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

resource portalChatOperation 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' existing = {
  parent: portalApi
  name: 'api_chat_api_chat_post'
}

resource portalChatOperationPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-05-01' = {
  parent: portalChatOperation
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: chatOperationPolicy
  }
}

output apiManagementId string = apiManagement.id
output apiManagementName string = apiManagement.name
output gatewayHostName string = '${apiManagement.name}.azure-api.net'
output gatewayUrl string = 'https://${apiManagement.name}.azure-api.net'
