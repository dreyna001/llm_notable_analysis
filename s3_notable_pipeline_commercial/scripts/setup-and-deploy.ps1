param(
    [switch]$Apply,
    [switch]$BootstrapEcr,
    [string]$VarFile = "terraform.tfvars",
    [string]$BackendConfig = "backend.hcl"
)

$ErrorActionPreference = "Stop"
# Commercial AWS Path B. Path A and Path C continue to use the legacy SAM runbooks.

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Resolve-Path (Join-Path $scriptDir "..")
$terraformRoot = "deploy/terraform/customer_default"
Set-Location $projectDir

foreach ($commandName in @("aws", "terraform")) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "$commandName is required"
    }
}

$region = "us-east-1"
if (
    -not [string]::IsNullOrWhiteSpace($env:AWS_REGION) -and
    -not [string]::IsNullOrWhiteSpace($env:AWS_DEFAULT_REGION) -and
    $env:AWS_REGION -ne $env:AWS_DEFAULT_REGION
) {
    throw "AWS_REGION and AWS_DEFAULT_REGION disagree; both must be $region."
}
$configuredRegion = $env:AWS_REGION
if ([string]::IsNullOrWhiteSpace($configuredRegion)) { $configuredRegion = $env:AWS_DEFAULT_REGION }
if ([string]::IsNullOrWhiteSpace($configuredRegion)) {
    $configuredRegion = (aws configure get region 2>$null | Out-String).Trim()
}
if ($configuredRegion -ne $region) {
    throw "Configured AWS region must be $region; found: $configuredRegion"
}

$expectedAccountId = $env:COMMERCIAL_AWS_ACCOUNT_ID
if ($expectedAccountId -notmatch '^[0-9]{12}$') {
    throw "Set COMMERCIAL_AWS_ACCOUNT_ID to the approved 12-digit commercial AWS account."
}
$callerAccount = (aws sts get-caller-identity --region $region --query Account --output text 2>$null | Out-String).Trim()
$callerArn = (aws sts get-caller-identity --region $region --query Arn --output text 2>$null | Out-String).Trim()
if ($callerAccount -ne $expectedAccountId) {
    throw "AWS caller account $callerAccount does not match approved account $expectedAccountId."
}
if (-not $callerArn.StartsWith("arn:aws:", [System.StringComparison]::Ordinal)) {
    throw "AWS caller ARN is not in the commercial aws partition: $callerArn"
}

$varFilePath = Join-Path $terraformRoot $VarFile
if (-not (Test-Path $varFilePath -PathType Leaf)) {
    throw "Missing $varFilePath; run python scripts/configure_path_b.py first."
}
$backendConfigPath = Join-Path $terraformRoot $BackendConfig
if (-not (Test-Path $backendConfigPath -PathType Leaf)) {
    throw "Missing $backendConfigPath; copy backend.hcl.example and set the approved remote state location."
}

Write-Host "Account: $callerAccount"
Write-Host "Region: $region"
Write-Host "Terraform root: $terraformRoot"
terraform "-chdir=$terraformRoot" fmt -check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
terraform "-chdir=$terraformRoot" init "-backend-config=$BackendConfig"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
terraform "-chdir=$terraformRoot" validate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$planName = if ($BootstrapEcr) { "bootstrap-ecr.tfplan" } else { "customer-default.tfplan" }
if (-not $Apply) {
    $planArgs = @("-chdir=$terraformRoot", "plan", "-var-file=$VarFile")
    if ($BootstrapEcr) {
        $planArgs += "-var=deploy_application=false"
        $planArgs += "-target=module.ecr[0]"
    }
    $planArgs += "-out=$planName"
    terraform @planArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    terraform "-chdir=$terraformRoot" show $planName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Plan saved at $terraformRoot/$planName. Review it, then rerun with -Apply."
    exit 0
}

$planPath = Join-Path $terraformRoot $planName
if (-not (Test-Path $planPath -PathType Leaf)) {
    throw "Missing reviewed plan $planPath; run the matching plan-only command first."
}
terraform "-chdir=$terraformRoot" show $planName
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
terraform "-chdir=$terraformRoot" apply $planName
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
terraform "-chdir=$terraformRoot" output -json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Terraform apply complete. Follow the validation steps in docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md."
