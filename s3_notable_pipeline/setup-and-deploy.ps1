# Setup and Deploy Script for Notable Analyzer Pipeline
# Prerequisites: AWS CLI, SAM CLI, Docker must be installed

Write-Host "=== Notable Analyzer Pipeline - Setup and Deploy ===" -ForegroundColor Cyan

# Check prerequisites
Write-Host "`nChecking prerequisites..." -ForegroundColor Yellow

$missing = @()

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "  ❌ AWS CLI not found" -ForegroundColor Red
    $missing += "AWS CLI (https://aws.amazon.com/cli/)"
} else {
    Write-Host "  ✅ AWS CLI found" -ForegroundColor Green
    aws --version
}

if (-not (Get-Command sam -ErrorAction SilentlyContinue)) {
    Write-Host "  ❌ SAM CLI not found" -ForegroundColor Red
    $missing += "SAM CLI (https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)"
} else {
    Write-Host "  ✅ SAM CLI found" -ForegroundColor Green
    sam --version
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "  ❌ Docker not found" -ForegroundColor Red
    $missing += "Docker (https://www.docker.com/products/docker-desktop)"
} else {
    Write-Host "  ✅ Docker found" -ForegroundColor Green
    docker --version
}

if ($missing.Count -gt 0) {
    Write-Host "`n❌ Missing prerequisites:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "`nPlease install the missing tools and run this script again." -ForegroundColor Yellow
    exit 1
}

# Check AWS credentials
Write-Host "`nChecking AWS credentials..." -ForegroundColor Yellow
try {
    $identity = aws sts get-caller-identity 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ AWS credentials configured" -ForegroundColor Green
        Write-Host $identity
    } else {
        Write-Host "  ❌ AWS credentials not configured" -ForegroundColor Red
        Write-Host "  Run: aws configure" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "  ❌ Error checking AWS credentials" -ForegroundColor Red
    exit 1
}

# Check Bedrock access
Write-Host "`nChecking Bedrock access..." -ForegroundColor Yellow
try {
    $models = aws bedrock list-foundation-models --region us-east-1 --query 'modelSummaries[?contains(modelId, `nova-pro`)].modelId' --output text 2>&1
    if ($LASTEXITCODE -eq 0 -and $models) {
        Write-Host "  ✅ Bedrock access confirmed" -ForegroundColor Green
        Write-Host "  Available Nova Pro models: $models" -ForegroundColor Gray
    } else {
        Write-Host "  ⚠️  Could not verify Bedrock access (may need model access request)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ⚠️  Could not check Bedrock access" -ForegroundColor Yellow
}

# Build
Write-Host "`n=== Step 1: Building application ===" -ForegroundColor Cyan
Write-Host "Running: sam build -t template-sam.yaml" -ForegroundColor Gray
sam build -t template-sam.yaml
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Build failed" -ForegroundColor Red
    exit 1
}

# Deploy
Write-Host "`n=== Step 2: Deploying to AWS ===" -ForegroundColor Cyan
if (Test-Path "samconfig.toml") {
    Write-Host "Found samconfig.toml - using existing configuration" -ForegroundColor Gray
    Write-Host "Running: sam deploy" -ForegroundColor Gray
    sam deploy
} else {
    Write-Host "No samconfig.toml found - running guided deployment" -ForegroundColor Gray
    Write-Host "Running: sam deploy --guided" -ForegroundColor Gray
    Write-Host "`nYou'll be prompted for:" -ForegroundColor Yellow
    Write-Host "  - Stack name (e.g., notable-analyzer-stack)" -ForegroundColor Gray
    Write-Host "  - AWS Region (e.g., us-east-1)" -ForegroundColor Gray
    Write-Host "  - Input bucket name (must be globally unique)" -ForegroundColor Gray
    Write-Host "  - Output bucket name (must be globally unique)" -ForegroundColor Gray
    Write-Host "  - Splunk sink mode (use 's3' for testing)" -ForegroundColor Gray
    sam deploy --guided
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Deployment failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ Deployment complete!" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Run test-pipeline.ps1 to test the deployment" -ForegroundColor Yellow
