targetScope = 'resourceGroup'

param location string
param namePrefix string
param retentionDays int = 30
param alertActionGroupResourceId string = ''

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionDays
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    Flow_Type: 'Bluefield'
    IngestionMode: 'LogAnalytics'
    WorkspaceResourceId: workspace.id
  }
}

resource functionFailureAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (!empty(alertActionGroupResourceId)) {
  name: '${namePrefix}-function-failures'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: '${namePrefix} Function failures'
    description: 'Alerts on unhandled Function exceptions. Poison-queue and backlog alerts are added with the staging monitor configuration.'
    enabled: true
    severity: 1
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [
      workspace.id
    ]
    criteria: {
      allOf: [
        {
          query: 'AppExceptions | summarize FailureCount=count()'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [
        alertActionGroupResourceId
      ]
    }
    autoMitigate: false
    skipQueryValidation: false
  }
}

output workspaceId string = workspace.id
output applicationInsightsId string = insights.id
output applicationInsightsConnectionString string = insights.properties.ConnectionString
