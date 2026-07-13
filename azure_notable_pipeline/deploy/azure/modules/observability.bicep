targetScope = 'resourceGroup'

param location string
param namePrefix string
param retentionDays int = 30
param deployCoreResources bool = true
param deployAlertRules bool = false
param alertActionGroupResourceId string = ''
param inputQueueServiceResourceId string = ''
param outputQueueServiceResourceId string = ''
param foundryResourceId string = ''
param azureOpenAiResourceId string = ''
param cosmosResourceId string = ''
param frontDoorProfileResourceId string = ''
param dispositionSyncEnabled bool = false
param analystPortalEnabled bool = false
param syntheticCheckName string = ''
param queueDepthTracePrefix string = 'notable.queue.depth.v1 '

@minValue(0)
param poisonQueueDepthThreshold int = 0
@minValue(1)
param analyzerQueueBacklogThreshold int = 100
@minValue(1)
param embedQueueBacklogThreshold int = 100
@minValue(1)
param modelErrorThreshold int = 5
@minValue(1)
param modelThrottleThreshold int = 5
@minValue(1)
param cosmosThrottleThreshold int = 10
@minValue(0)
@maxValue(100)
param frontDoor5xxPercentageThreshold int = 5
@minValue(24)
param dispositionCompletionGraceHours int = 26
@minValue(5)
param queueTelemetryMaxAgeMinutes int = 10

var createAlerts = deployAlertRules && !empty(alertActionGroupResourceId)
var workspaceName = '${namePrefix}-logs'
var insightsName = '${namePrefix}-insights'
var workspaceId = resourceId('Microsoft.OperationalInsights/workspaces', workspaceName)
var insightsId = resourceId('Microsoft.Insights/components', insightsName)
var alertActions = {
  actionGroups: [alertActionGroupResourceId]
}
var metricAlertActions = [{ actionGroupId: alertActionGroupResourceId }]

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (deployCoreResources) {
  name: workspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionDays
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = if (deployCoreResources) {
  name: insightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    Flow_Type: 'Bluefield'
    IngestionMode: 'LogAnalytics'
    WorkspaceResourceId: workspace!.id
  }
}

// Azure Storage exposes QueueMessageCount only at queue-service scope and without a
// QueueName dimension. The in-stack operations_monitor_timer emits one structured
// AppTrace per queue. These rules fail closed when that telemetry is absent or stale.
var poisonQueues = [
  { queueName: 'webjobs-blobtrigger-poison', storageScope: inputQueueServiceResourceId }
  { queueName: 'notable-analysis-jobs-poison', storageScope: outputQueueServiceResourceId }
  { queueName: 'case-embed-invocations-poison', storageScope: outputQueueServiceResourceId }
]
resource poisonQueueAlerts 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for queue in poisonQueues: if (createAlerts) {
  name: '${namePrefix}-${queue.queueName}-nonempty'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: '${namePrefix} ${queue.queueName} nonempty'
    description: 'Poison queue is nonempty, or its keyless depth telemetry is missing/stale. Storage scope: ${queue.storageScope}'
    enabled: true
    severity: 1
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [workspaceId]
    criteria: {
      allOf: [{
        query: format('let samples=AppTraces | where Message startswith "{0}" | extend sample=parse_json(substring(Message, strlen("{0}"))) | where toint(sample.schema_version) == 1 and tostring(sample.queue_name) == "{1}" | extend Depth=toint(sample.depth); let latest=toscalar(samples | summarize max(TimeGenerated)); let depth=toscalar(samples | where TimeGenerated == latest | summarize max(Depth)); print AlertCount=iff(isnull(latest) or latest < ago({2}m) or depth > {3}, 1, 0)', queueDepthTracePrefix, queue.queueName, queueTelemetryMaxAgeMinutes, poisonQueueDepthThreshold)
        timeAggregation: 'Maximum'
        metricMeasureColumn: 'AlertCount'
        operator: 'GreaterThan'
        threshold: 0
        failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
      }]
    }
    actions: alertActions
    autoMitigate: false
    skipQueryValidation: false
  }
}]

var backlogQueues = [
  { queueName: 'notable-analysis-jobs', threshold: analyzerQueueBacklogThreshold }
  { queueName: 'case-embed-invocations', threshold: embedQueueBacklogThreshold }
]
var poisonAlertNames = [for queue in poisonQueues: '${namePrefix}-${queue.queueName}-nonempty']
var backlogAlertNames = [for queue in backlogQueues: '${namePrefix}-${queue.queueName}-backlog']
resource backlogAlerts 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for queue in backlogQueues: if (createAlerts) {
  name: '${namePrefix}-${queue.queueName}-backlog'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: '${namePrefix} ${queue.queueName} backlog'
    description: 'Queue depth exceeded its deployment threshold continuously for 15 minutes, or queue-depth telemetry is missing/stale.'
    enabled: true
    severity: 2
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [workspaceId]
    criteria: {
      allOf: [{
        query: format('let samples=AppTraces | where Message startswith "{0}" | extend sample=parse_json(substring(Message, strlen("{0}"))) | where toint(sample.schema_version) == 1 and tostring(sample.queue_name) == "{1}" | extend Depth=toint(sample.depth); let latest=toscalar(samples | summarize max(TimeGenerated)); let sustained=toscalar(samples | where TimeGenerated > ago(16m) | summarize SampleCount=count(), Oldest=min(TimeGenerated), MinimumDepth=min(Depth) | project iff(SampleCount >= 3 and Oldest <= ago(14m) and MinimumDepth > {2}, 1, 0)); print AlertCount=iff(isnull(latest) or latest < ago({3}m) or sustained == 1, 1, 0)', queueDepthTracePrefix, queue.queueName, queue.threshold, queueTelemetryMaxAgeMinutes)
        timeAggregation: 'Maximum'
        metricMeasureColumn: 'AlertCount'
        operator: 'GreaterThan'
        threshold: 0
        failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
      }]
    }
    actions: alertActions
    autoMitigate: false
    skipQueryValidation: false
  }
}]

resource functionFailureAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (createAlerts) {
  name: '${namePrefix}-function-failures'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: '${namePrefix} Function execution failures'
    description: 'Unhandled exceptions or failed requests in any of the four isolated Function Apps.'
    enabled: true
    severity: 1
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [workspaceId]
    criteria: { allOf: [{
      query: 'union (AppExceptions | project TimeGenerated), (AppRequests | where Success == false | project TimeGenerated)'
      timeAggregation: 'Count'
      operator: 'GreaterThan'
      threshold: 0
      failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
    }] }
    actions: alertActions
    autoMitigate: false
    skipQueryValidation: false
  }
}

resource functionTimeoutAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (createAlerts) {
  name: '${namePrefix}-function-timeouts'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: '${namePrefix} Function execution timeouts'
    description: 'Function host timeout exceptions or traces were observed.'
    enabled: true
    severity: 1
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [workspaceId]
    criteria: { allOf: [{
      query: 'union (AppExceptions | project TimeGenerated, Text=OuterMessage), (AppTraces | project TimeGenerated, Text=Message) | where Text has_any ("Timeout value of", "functionTimeout", "timed out")'
      timeAggregation: 'Count'
      operator: 'GreaterThan'
      threshold: 0
      failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
    }] }
    actions: alertActions
    autoMitigate: false
    skipQueryValidation: false
  }
}

resource foundryErrorAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (createAlerts && !empty(foundryResourceId)) {
  name: '${namePrefix}-foundry-errors'
  location: 'global'
  properties: {
    description: 'Sustained Foundry model service errors.'
    severity: 1
    enabled: true
    scopes: [foundryResourceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'FoundryModelErrors'
        metricNamespace: 'Microsoft.CognitiveServices/accounts'
        metricName: 'ModelRequests'
        dimensions: [{ name: 'StatusCode', operator: 'Include', values: ['servererrors'] }]
        operator: 'GreaterThan'
        timeAggregation: 'Total'
        threshold: modelErrorThreshold
        criterionType: 'StaticThresholdCriterion'
      }]
    }
    actions: metricAlertActions
    autoMitigate: true
  }
}

resource foundryThrottleAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (createAlerts && !empty(foundryResourceId)) {
  name: '${namePrefix}-foundry-throttling'
  location: 'global'
  properties: {
    description: 'Sustained Foundry model throttling (HTTP 429).'
    severity: 2
    enabled: true
    scopes: [foundryResourceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'FoundryModelThrottling'
        metricNamespace: 'Microsoft.CognitiveServices/accounts'
        metricName: 'ModelRequests'
        dimensions: [{ name: 'StatusCode', operator: 'Include', values: ['429'] }]
        operator: 'GreaterThan'
        timeAggregation: 'Total'
        threshold: modelThrottleThreshold
        criterionType: 'StaticThresholdCriterion'
      }]
    }
    actions: metricAlertActions
    autoMitigate: true
  }
}

resource openAiErrorAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (createAlerts && !empty(azureOpenAiResourceId)) {
  name: '${namePrefix}-openai-errors'
  location: 'global'
  properties: {
    description: 'Sustained Azure OpenAI service errors.'
    severity: 1
    enabled: true
    scopes: [azureOpenAiResourceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'AzureOpenAiErrors'
        metricNamespace: 'Microsoft.CognitiveServices/accounts'
        metricName: 'AzureOpenAIRequests'
        dimensions: [{ name: 'StatusCode', operator: 'Include', values: ['servererrors'] }]
        operator: 'GreaterThan'
        timeAggregation: 'Total'
        threshold: modelErrorThreshold
        criterionType: 'StaticThresholdCriterion'
      }]
    }
    actions: metricAlertActions
    autoMitigate: true
  }
}

resource openAiThrottleAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (createAlerts && !empty(azureOpenAiResourceId)) {
  name: '${namePrefix}-openai-throttling'
  location: 'global'
  properties: {
    description: 'Sustained Azure OpenAI throttling (HTTP 429).'
    severity: 2
    enabled: true
    scopes: [azureOpenAiResourceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'AzureOpenAiThrottling'
        metricNamespace: 'Microsoft.CognitiveServices/accounts'
        metricName: 'AzureOpenAIRequests'
        dimensions: [{ name: 'StatusCode', operator: 'Include', values: ['429'] }]
        operator: 'GreaterThan'
        timeAggregation: 'Total'
        threshold: modelThrottleThreshold
        criterionType: 'StaticThresholdCriterion'
      }]
    }
    actions: metricAlertActions
    autoMitigate: true
  }
}

resource cosmosThrottleAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (createAlerts && !empty(cosmosResourceId)) {
  name: '${namePrefix}-cosmos-throttling'
  location: 'global'
  properties: {
    description: 'Sustained Cosmos DB HTTP 429 throttling.'
    severity: 2
    enabled: true
    scopes: [cosmosResourceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'CosmosThrottling'
        metricNamespace: 'Microsoft.DocumentDB/databaseAccounts'
        metricName: 'TotalRequests'
        dimensions: [{ name: 'StatusCode', operator: 'Include', values: ['429'] }]
        operator: 'GreaterThan'
        timeAggregation: 'Count'
        threshold: cosmosThrottleThreshold
        criterionType: 'StaticThresholdCriterion'
      }]
    }
    actions: metricAlertActions
    autoMitigate: true
  }
}

resource frontDoor5xxAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (createAlerts && analystPortalEnabled && !empty(frontDoorProfileResourceId)) {
  name: '${namePrefix}-frontdoor-5xx'
  location: 'global'
  properties: {
    description: 'Front Door 5XX percentage exceeded the deployment threshold.'
    severity: 1
    enabled: true
    scopes: [frontDoorProfileResourceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'FrontDoor5xx'
        metricNamespace: 'Microsoft.Cdn/profiles'
        metricName: 'Percentage5XX'
        dimensions: []
        operator: 'GreaterThan'
        timeAggregation: 'Average'
        threshold: frontDoor5xxPercentageThreshold
        criterionType: 'StaticThresholdCriterion'
      }]
    }
    actions: metricAlertActions
    autoMitigate: true
  }
}

resource syntheticFailureAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (createAlerts && analystPortalEnabled && !empty(syntheticCheckName)) {
  name: '${namePrefix}-authenticated-synthetic-failure'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: '${namePrefix} authenticated portal synthetic failure'
    description: 'The customer-supplied authenticated /ready monitor reported failure or stopped reporting. No token or IdP credential is stored by this stack.'
    enabled: true
    severity: 1
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [workspaceId]
    criteria: { allOf: [{
      query: format('let checkName=base64_decode_tostring("{0}"); let results=AppAvailabilityResults | where Name == checkName and TimeGenerated > ago(15m); print AlertCount=iff(toscalar(results | count) == 0 or toscalar(results | summarize countif(Success == false)) > 0, 1, 0)', base64(syntheticCheckName))
      timeAggregation: 'Maximum'
      metricMeasureColumn: 'AlertCount'
      operator: 'GreaterThan'
      threshold: 0
      failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
    }] }
    actions: alertActions
    autoMitigate: false
    skipQueryValidation: false
  }
}

resource dispositionMissedAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (createAlerts && dispositionSyncEnabled) {
  name: '${namePrefix}-disposition-completion-missed'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: '${namePrefix} disposition completion missed'
    description: 'No successful daily disposition-sync completion was observed within the configured grace period.'
    enabled: true
    severity: 1
    evaluationFrequency: 'PT1H'
    windowSize: 'P1D'
    scopes: [workspaceId]
    criteria: { allOf: [{
      query: format('let monitorStarted=toscalar(AppTraces | where Message startswith "{0}" | summarize min(TimeGenerated)); let completions=AppTraces | where Message startswith "ServiceNow disposition sync finished:" and Message has "status" and Message has "success" and TimeGenerated > ago({1}h); print MissingCompletion=iff(isnotnull(monitorStarted) and monitorStarted < ago({1}h) and toscalar(completions | count) == 0, 1, 0)', queueDepthTracePrefix, dispositionCompletionGraceHours)
      timeAggregation: 'Maximum'
      metricMeasureColumn: 'MissingCompletion'
      operator: 'GreaterThan'
      threshold: 0
      failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
    }] }
    actions: alertActions
    autoMitigate: false
    skipQueryValidation: false
  }
}

output workspaceId string = workspaceId
output workspaceCustomerId string = deployCoreResources ? workspace!.properties.customerId : ''
output applicationInsightsId string = insightsId
output applicationInsightsConnectionString string = deployCoreResources ? insights!.properties.ConnectionString : ''
output alertRuleNames array = createAlerts ? concat(
  poisonAlertNames,
  backlogAlertNames,
  [
    '${namePrefix}-function-failures'
    '${namePrefix}-function-timeouts'
    '${namePrefix}-foundry-errors'
    '${namePrefix}-foundry-throttling'
    '${namePrefix}-cosmos-throttling'
  ],
  empty(azureOpenAiResourceId) ? [] : ['${namePrefix}-openai-errors', '${namePrefix}-openai-throttling'],
  analystPortalEnabled ? concat(
    ['${namePrefix}-frontdoor-5xx'],
    empty(syntheticCheckName) ? [] : ['${namePrefix}-authenticated-synthetic-failure']
  ) : [],
  dispositionSyncEnabled ? ['${namePrefix}-disposition-completion-missed'] : []
) : []
