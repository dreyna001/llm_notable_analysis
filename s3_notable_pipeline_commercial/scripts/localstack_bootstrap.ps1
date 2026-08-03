$ErrorActionPreference = "Continue"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$endpoint = if ($env:AWS_ENDPOINT_URL) { $env:AWS_ENDPOINT_URL } else { "http://localhost:4566" }
$env:AWS_ENDPOINT_URL = $endpoint
$env:AWS_ACCESS_KEY_ID = if ($env:AWS_ACCESS_KEY_ID) { $env:AWS_ACCESS_KEY_ID } else { "test" }
$env:AWS_SECRET_ACCESS_KEY = if ($env:AWS_SECRET_ACCESS_KEY) { $env:AWS_SECRET_ACCESS_KEY } else { "test" }
$env:AWS_REGION = if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-1" }
$env:AWS_DEFAULT_REGION = if ($env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION } else { $env:AWS_REGION }

$inputBucket = if ($env:INPUT_BUCKET_NAME) { $env:INPUT_BUCKET_NAME } else { "notable-local-input" }
$outputBucket = if ($env:OUTPUT_BUCKET_NAME) { $env:OUTPUT_BUCKET_NAME } else { "notable-local-output" }
$tableName = if ($env:SIDE_EFFECT_IDEMPOTENCY_TABLE) { $env:SIDE_EFFECT_IDEMPOTENCY_TABLE } else { "notable-local-side-effects" }
$analyzerQueue = if ($env:ANALYZER_QUEUE_NAME) { $env:ANALYZER_QUEUE_NAME } else { "notable-local-analyzer" }
$analyzerDlq = if ($env:ANALYZER_DLQ_NAME) { $env:ANALYZER_DLQ_NAME } else { "notable-local-analyzer-dlq" }
$embedQueue = if ($env:CASE_EMBED_QUEUE_NAME) { $env:CASE_EMBED_QUEUE_NAME } else { "notable-local-case-embed" }
$embedDlq = if ($env:CASE_EMBED_DLQ_NAME) { $env:CASE_EMBED_DLQ_NAME } else { "notable-local-case-embed-dlq" }
$ragQueue = if ($env:RAG_INGEST_QUEUE_NAME) { $env:RAG_INGEST_QUEUE_NAME } else { "notable-local-rag-ingest" }
$ragDlq = if ($env:RAG_INGEST_DLQ_NAME) { $env:RAG_INGEST_DLQ_NAME } else { "notable-local-rag-ingest-dlq" }

function Invoke-AwsLocal {
    aws --endpoint-url $endpoint @args
}

function Ensure-Bucket {
    param([string]$BucketName)
    Invoke-AwsLocal s3api head-bucket --bucket $BucketName *> $null
    if ($LASTEXITCODE -ne 0) {
        Invoke-AwsLocal s3 mb "s3://$BucketName" | Out-Null
    }
}

function Ensure-Secret {
    param(
        [string]$Name,
        [string]$Value
    )
    Invoke-AwsLocal secretsmanager describe-secret --secret-id $Name *> $null
    if ($LASTEXITCODE -eq 0) {
        Invoke-AwsLocal secretsmanager put-secret-value --secret-id $Name --secret-string $Value | Out-Null
    } else {
        Invoke-AwsLocal secretsmanager create-secret --name $Name --secret-string $Value | Out-Null
    }
}

function Ensure-QueuePair {
    param(
        [string]$QueueName,
        [string]$DlqName
    )
    $dlqUrl = Invoke-AwsLocal sqs create-queue --queue-name $DlqName --query QueueUrl --output text
    $dlqArn = Invoke-AwsLocal sqs get-queue-attributes `
        --queue-url $dlqUrl `
        --attribute-names QueueArn `
        --query Attributes.QueueArn `
        --output text
    $redrive = "{`"deadLetterTargetArn`":`"$dlqArn`",`"maxReceiveCount`":`"5`"}"
    Invoke-AwsLocal sqs create-queue `
        --queue-name $QueueName `
        --attributes "RedrivePolicy=$redrive,VisibilityTimeout=900" | Out-Null
}

Ensure-Bucket $inputBucket
Ensure-Bucket $outputBucket

Invoke-AwsLocal dynamodb describe-table --table-name $tableName *> $null
if ($LASTEXITCODE -ne 0) {
    Invoke-AwsLocal dynamodb create-table `
        --table-name $tableName `
        --attribute-definitions "AttributeName=id,AttributeType=S" `
        --key-schema "AttributeName=id,KeyType=HASH" `
        --billing-mode PAY_PER_REQUEST | Out-Null
    Invoke-AwsLocal dynamodb wait table-exists --table-name $tableName
    Invoke-AwsLocal dynamodb update-time-to-live `
        --table-name $tableName `
        --time-to-live-specification "Enabled=true,AttributeName=expires_at" | Out-Null
}

Ensure-QueuePair $analyzerQueue $analyzerDlq
Ensure-QueuePair $embedQueue $embedDlq
Ensure-QueuePair $ragQueue $ragDlq

Ensure-Secret "local/splunk/api-token" '{"token":"local-splunk-token"}'
Ensure-Secret "local/servicenow/api-token" '{"token":"local-servicenow-token"}'
Ensure-Secret "local/servicenow/approval-hmac" '{"hmac_key":"local-approval-hmac"}'
Ensure-Secret "local/elasticsearch/api-key" '{"api_key":"local-elasticsearch-key"}'

Write-Host "LocalStack bootstrap complete at $endpoint"
