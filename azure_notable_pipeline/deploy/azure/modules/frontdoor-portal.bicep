targetScope = 'resourceGroup'

param location string
param profileName string
param endpointName string
param portalUiStorageId string
param portalUiHostName string
param portalFunctionId string
param portalFunctionHostName string

resource profile 'Microsoft.Cdn/profiles@2024-09-01' = {
  name: profileName
  location: 'global'
  sku: { name: 'Premium_AzureFrontDoor' }
  properties: {
    originResponseTimeoutSeconds: 240
  }
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-09-01' = {
  parent: profile
  name: endpointName
  location: 'global'
  properties: { enabledState: 'Enabled' }
}

// Every origin group is intentionally single-origin and has no healthProbeSettings.
// Portal availability is monitored by an authenticated synthetic /ready request.
resource apiOriginGroup 'Microsoft.Cdn/profiles/originGroups@2024-09-01' = {
  parent: profile
  name: 'portal-api'
  properties: {
    sessionAffinityState: 'Disabled'
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
      additionalLatencyInMilliseconds: 50
    }
  }
}
resource apiOrigin 'Microsoft.Cdn/profiles/originGroups/origins@2024-09-01' = {
  parent: apiOriginGroup
  name: 'portal-function'
  properties: {
    enabledState: 'Enabled'
    hostName: portalFunctionHostName
    originHostHeader: portalFunctionHostName
    httpPort: 80
    httpsPort: 443
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: true
    sharedPrivateLinkResource: {
      privateLink: { id: portalFunctionId }
      privateLinkLocation: location
      groupId: 'sites'
      requestMessage: 'Front Door private portal Function origin'
    }
  }
}

resource uiOriginGroup 'Microsoft.Cdn/profiles/originGroups@2024-09-01' = {
  parent: profile
  name: 'portal-ui'
  properties: {
    sessionAffinityState: 'Disabled'
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
      additionalLatencyInMilliseconds: 50
    }
  }
}
resource uiOrigin 'Microsoft.Cdn/profiles/originGroups/origins@2024-09-01' = {
  parent: uiOriginGroup
  name: 'portal-web'
  properties: {
    enabledState: 'Enabled'
    hostName: portalUiHostName
    originHostHeader: portalUiHostName
    httpPort: 80
    httpsPort: 443
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: true
    sharedPrivateLinkResource: {
      privateLink: { id: portalUiStorageId }
      privateLinkLocation: location
      groupId: 'web'
      requestMessage: 'Front Door private static website origin'
    }
  }
}

resource apiRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  parent: endpoint
  name: 'api'
  properties: {
    originGroup: { id: apiOriginGroup.id }
    supportedProtocols: ['Http', 'Https']
    patternsToMatch: ['/api/*']
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    httpsRedirect: 'Enabled'
  }
  dependsOn: [apiOrigin]
}
resource healthRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  parent: endpoint
  name: 'health'
  properties: {
    originGroup: { id: apiOriginGroup.id }
    supportedProtocols: ['Http', 'Https']
    patternsToMatch: ['/health']
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    httpsRedirect: 'Enabled'
  }
  dependsOn: [apiOrigin]
}
resource readyRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  parent: endpoint
  name: 'ready'
  properties: {
    originGroup: { id: apiOriginGroup.id }
    supportedProtocols: ['Http', 'Https']
    patternsToMatch: ['/ready']
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    httpsRedirect: 'Enabled'
  }
  dependsOn: [apiOrigin]
}
// Keep the SPA shell uncached; hashed/static assets use the cached wildcard route.
resource spaShellRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  parent: endpoint
  name: 'spa-shell'
  properties: {
    originGroup: { id: uiOriginGroup.id }
    supportedProtocols: ['Http', 'Https']
    patternsToMatch: ['/', '/index.html']
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    httpsRedirect: 'Enabled'
  }
  dependsOn: [uiOrigin]
}
resource uiRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  parent: endpoint
  name: 'ui'
  properties: {
    originGroup: { id: uiOriginGroup.id }
    supportedProtocols: ['Http', 'Https']
    patternsToMatch: ['/*']
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    httpsRedirect: 'Enabled'
    cacheConfiguration: {
      queryStringCachingBehavior: 'IgnoreQueryString'
      compressionSettings: {
        contentTypesToCompress: ['text/html', 'text/css', 'application/javascript', 'application/json', 'image/svg+xml']
        isCompressionEnabled: true
      }
    }
  }
  dependsOn: [uiOrigin, apiRoute, healthRoute, readyRoute, spaShellRoute]
}

output profileName string = profile.name
output profileId string = profile.id
output endpointName string = endpoint.name
output endpointHostName string = endpoint.properties.hostName
output apiOriginId string = apiOrigin.id
output uiOriginId string = uiOrigin.id
