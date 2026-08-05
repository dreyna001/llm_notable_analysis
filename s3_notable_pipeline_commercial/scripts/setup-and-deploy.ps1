# Setup and Deploy Script for Notable Analyzer Pipeline
# Prerequisites: AWS CLI, SAM CLI, Docker must be installed
#
# Readiness: publish the image to commercial us-east-1 ECR and capture its immutable digest first.

Write-Host "=== Notable Analyzer Pipeline - Setup and Deploy ===" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Resolve-Path (Join-Path $scriptDir "..")
$samTemplate = "deploy/aws/template-sam.yaml"
$samBuiltTemplate = ".aws-sam/build/template.yaml"
Set-Location $projectDir

# Check prerequisites
Write-Host "`nChecking prerequisites..." -ForegroundColor Yellow

$missing = @()

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "  AWS CLI not found" -ForegroundColor Red
    $missing += "AWS CLI (https://aws.amazon.com/cli/)"
} else {
    Write-Host "  AWS CLI found" -ForegroundColor Green
    aws --version
}

if (-not (Get-Command sam -ErrorAction SilentlyContinue)) {
    Write-Host "  SAM CLI not found" -ForegroundColor Red
    $missing += "SAM CLI (https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)"
} else {
    Write-Host "  SAM CLI found" -ForegroundColor Green
    sam --version
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "  Docker not found" -ForegroundColor Red
    $missing += "Docker (https://www.docker.com/products/docker-desktop)"
} else {
    Write-Host "  Docker found" -ForegroundColor Green
    docker --version
}

if ($missing.Count -gt 0) {
    Write-Host "`nMissing prerequisites:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "`nPlease install the missing tools and run this script again." -ForegroundColor Yellow
    exit 1
}

$region = "us-east-1"

# Check the commercial AWS deployment boundary
Write-Host "`nChecking commercial AWS deployment boundary..." -ForegroundColor Yellow
if (
    -not [string]::IsNullOrWhiteSpace($env:AWS_REGION) -and
    -not [string]::IsNullOrWhiteSpace($env:AWS_DEFAULT_REGION) -and
    $env:AWS_REGION -ne $env:AWS_DEFAULT_REGION
) {
    Write-Host "  AWS_REGION and AWS_DEFAULT_REGION disagree; both must be $region." -ForegroundColor Red
    exit 1
}

$configuredRegion = $env:AWS_REGION
if ([string]::IsNullOrWhiteSpace($configuredRegion)) {
    $configuredRegion = $env:AWS_DEFAULT_REGION
}
if ([string]::IsNullOrWhiteSpace($configuredRegion)) {
    $configuredRegionOutput = aws configure get region 2>$null
    if ($LASTEXITCODE -eq 0) {
        $configuredRegion = ($configuredRegionOutput | Out-String).Trim()
    }
}
if ($configuredRegion -ne $region) {
    $reportedRegion = if ([string]::IsNullOrWhiteSpace($configuredRegion)) { "<unset>" } else { $configuredRegion }
    Write-Host "  Configured AWS region must be $region; found: $reportedRegion" -ForegroundColor Red
    exit 1
}

$expectedAccountId = $env:COMMERCIAL_AWS_ACCOUNT_ID
if ($expectedAccountId -notmatch '^[0-9]{12}$') {
    Write-Host "  Set COMMERCIAL_AWS_ACCOUNT_ID to the approved 12-digit commercial AWS account." -ForegroundColor Red
    exit 1
}

$callerAccountOutput = aws sts get-caller-identity --region $region --query Account --output text 2>$null
$callerAccountExitCode = $LASTEXITCODE
$callerAccount = ($callerAccountOutput | Out-String).Trim()
if ($callerAccountExitCode -ne 0 -or $callerAccount -notmatch '^[0-9]{12}$') {
    Write-Host "  AWS credentials are unavailable or STS returned an invalid account ID." -ForegroundColor Red
    exit 1
}
$callerArnOutput = aws sts get-caller-identity --region $region --query Arn --output text 2>$null
$callerArnExitCode = $LASTEXITCODE
$callerArn = ($callerArnOutput | Out-String).Trim()
if ($callerArnExitCode -ne 0 -or -not $callerArn.StartsWith("arn:aws:", [System.StringComparison]::Ordinal)) {
    Write-Host "  AWS caller ARN is not in the commercial aws partition: $callerArn" -ForegroundColor Red
    exit 1
}
if ($callerAccount -ne $expectedAccountId) {
    Write-Host "  AWS caller account $callerAccount does not match approved account $expectedAccountId." -ForegroundColor Red
    exit 1
}

$credentialSource = if ([string]::IsNullOrWhiteSpace($env:AWS_PROFILE)) { "default credential chain" } else { $env:AWS_PROFILE }
Write-Host "  Account: $callerAccount" -ForegroundColor Green
Write-Host "  Caller: $callerArn" -ForegroundColor Green
Write-Host "  Partition: aws" -ForegroundColor Green
Write-Host "  Region: $region" -ForegroundColor Green
Write-Host "  Credential source: $credentialSource" -ForegroundColor Green

# Check Bedrock access
Write-Host "`nChecking Bedrock access..." -ForegroundColor Yellow
try {
    $novaModels = aws bedrock list-foundation-models --region $region --query "modelSummaries[?contains(modelId, 'nova-pro')].modelId" --output text 2>$null
    $novaAvailable = $LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($novaModels) -and $novaModels -ne "None"

    $claudeProfiles = aws bedrock list-inference-profiles --region $region --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude-sonnet-4-6')].inferenceProfileId" --output text 2>$null
    $claudeAvailable = $LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($claudeProfiles) -and $claudeProfiles -ne "None"

    if ($novaAvailable -or $claudeAvailable) {
        Write-Host "  Bedrock access confirmed" -ForegroundColor Green
        if ($novaAvailable) {
            Write-Host "  Available Nova Pro models: $novaModels" -ForegroundColor Gray
        }
        if ($claudeAvailable) {
            Write-Host "  Available Claude Sonnet 4.6 inference profiles: $claudeProfiles" -ForegroundColor Gray
        }
        Write-Host "  Validate deploy-time values still match template parameters (AwsAccountId, model/profile, region)." -ForegroundColor Gray
    } else {
        Write-Host "  Could not verify Nova Pro models or Claude Sonnet 4.6 inference profiles (may need model/profile access request)." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Could not check Bedrock access for Nova Pro or Claude Sonnet 4.6 profile" -ForegroundColor Yellow
}

# Build
Write-Host "`nBefore deploy: ensure EcrRepositoryUri and ImageDigest identify the approved image in us-east-1." -ForegroundColor Yellow
Write-Host "`n=== Step 1: Building application ===" -ForegroundColor Cyan
Write-Host "Running: sam build -t $samTemplate" -ForegroundColor Gray
sam build -t $samTemplate
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed" -ForegroundColor Red
    exit 1
}

# Wave 1 parity parameters (safe defaults stay core-first)
Write-Host "`n=== Wave 1 Parity Parameters (reference) ===" -ForegroundColor Cyan
Write-Host "Defaults are core-only and safe for first deploy. Enable parity profiles only in dev/staging after prerequisites are ready." -ForegroundColor Gray
Write-Host "See docs/operations/CAPABILITY_PROFILES.md and config.env.example for full contracts." -ForegroundColor Gray
Write-Host ""
Write-Host "  CapabilityProfiles (default: core)" -ForegroundColor Yellow
Write-Host "    core                          - required base analysis path" -ForegroundColor Gray
Write-Host "    core,html_reports             - add escaped HTML companion reports" -ForegroundColor Gray
Write-Host "    core,rag                      - private OpenSearch advisory context (set RagEnabled=true)" -ForegroundColor Gray
Write-Host "    core,rag,spl_readonly         - SPL generation + read-only Splunk investigation (SplunkBaseUrl, token secret)" -ForegroundColor Gray
Write-Host "    core,rag,elastic_readonly     - Elasticsearch read-only investigation (mutually exclusive with spl_readonly)" -ForegroundColor Gray
Write-Host "    core,ticket_draft             - ServiceNow draft payloads in JSON reports" -ForegroundColor Gray
Write-Host "    core,action_gated             - Splunk writeback / ServiceNow create + DynamoDB idempotency" -ForegroundColor Gray
Write-Host ""
Write-Host "  OpenSearch grounding" -ForegroundColor Yellow
Write-Host "    OpenSearchEndpoint, OpenSearchDomainArn, RagTenantId, private VPC IDs" -ForegroundColor Gray
Write-Host "    SplQueryRagEnabled / ElasticsearchGroundingEnabled enable dictionary lanes" -ForegroundColor Gray
Write-Host ""
Write-Host "  Investigation backend (choose one read-only profile)" -ForegroundColor Yellow
Write-Host "    spl_readonly: SplunkBaseUrl, SplunkApiTokenSecretArn, InvestigationQueryExecutor (rest|mcp)" -ForegroundColor Gray
Write-Host "    elastic_readonly: ElasticsearchBaseUrl, ElasticsearchApiKeySecretArn, ElasticsearchIndexAllowlist" -ForegroundColor Gray
Write-Host ""
Write-Host "  ServiceNow / idempotency (action_gated or ticket_draft)" -ForegroundColor Yellow
Write-Host "    ServiceNowBaseUrl, ServiceNowApiTokenSecretArn, ServiceNowApprovalHmacSecretArn" -ForegroundColor Gray
Write-Host "    ServiceNowAssignmentGroup (required for ticket_draft drafts)" -ForegroundColor Gray
Write-Host "    SideEffectIdempotencyTableName (default: notable-side-effect-idempotency)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Safe first deploy: CapabilityProfiles=core, SplunkSinkMode=s3, HtmlReportEnabled=false, RagEnabled=false" -ForegroundColor Green

# Deploy
Write-Host "`n=== Step 2: Deploying to AWS ===" -ForegroundColor Cyan
if (Test-Path "samconfig.toml") {
    Write-Host "Found samconfig.toml - using existing configuration" -ForegroundColor Gray
    Write-Host "Review parameter_overrides for Wave 1 settings before deploy (see reference above)." -ForegroundColor Gray
    Write-Host "Running: sam deploy --region $region --template-file $samBuiltTemplate" -ForegroundColor Gray
    sam deploy --region $region --template-file $samBuiltTemplate
} else {
    Write-Host "No samconfig.toml found - running guided deployment" -ForegroundColor Gray
    Write-Host "Running: sam deploy --guided --region $region --template-file $samBuiltTemplate" -ForegroundColor Gray
    Write-Host "`nYou'll be prompted for:" -ForegroundColor Yellow
    Write-Host "  - Stack name (e.g., notable-analyzer-stack)" -ForegroundColor Gray
    Write-Host "  - AWS Region (us-east-1)" -ForegroundColor Gray
    Write-Host "  - Input bucket name (must be globally unique)" -ForegroundColor Gray
    Write-Host "  - Output bucket name (must be globally unique)" -ForegroundColor Gray
    Write-Host "  - SplunkSinkMode ('s3' or 'notable_rest'; use 's3' for testing)" -ForegroundColor Gray
    Write-Host "  - CapabilityProfiles (default 'core'; see Wave 1 reference above)" -ForegroundColor Gray
    Write-Host "  - HtmlReportEnabled (default 'false')" -ForegroundColor Gray
    Write-Host "  - RagEnabled, SplQueryRagEnabled, or ElasticsearchGroundingEnabled (default off)" -ForegroundColor Gray
    Write-Host "  - OpenSearchEndpoint, OpenSearchDomainArn, RagTenantId, and private VPC IDs when enabled" -ForegroundColor Gray
    Write-Host "  - ElasticsearchBaseUrl / ElasticsearchApiKeySecretArn (elastic_readonly)" -ForegroundColor Gray
    Write-Host "  - ServiceNowBaseUrl, ServiceNowApiTokenSecretArn, ServiceNowApprovalHmacSecretArn, ServiceNowAssignmentGroup" -ForegroundColor Gray
    Write-Host "  - SideEffectIdempotencyTableName (action_gated; default notable-side-effect-idempotency)" -ForegroundColor Gray
    Write-Host "  - AwsAccountId, EcrRepositoryUri, ImageDigest, and BedrockAnalysisModelId" -ForegroundColor Gray
    Write-Host "  - If notable_rest: SplunkBaseUrl + SplunkApiTokenSecretArn (Secrets Manager ARN)" -ForegroundColor Gray
    Write-Host "  - Optional: SplunkApiTokenSecretField (default 'token') and SplunkNotableUpdatePath" -ForegroundColor Gray
    sam deploy --guided --region $region --template-file $samBuiltTemplate
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed" -ForegroundColor Red
    exit 1
}

Write-Host "`nDeployment complete!" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Core smoke: .\scripts\test-pipeline.ps1" -ForegroundColor Yellow
Write-Host "  2. Wave 1 staging smoke (live AWS): .\scripts\test-pipeline.ps1 -Wave1Smoke" -ForegroundColor Yellow
Write-Host "     Add -ExpectCapabilityProfiles `"core,rag`" when validating a specific profile bundle." -ForegroundColor Gray
