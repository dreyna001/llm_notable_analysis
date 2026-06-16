# Test Script for Notable Analyzer Pipeline
# Uploads test file and checks output.
#
# Default: core smoke only (upload + markdown report check).
# Optional Wave 1 checks (require live AWS credentials and a deployed stack):
#   .\scripts\test-pipeline.ps1 -Wave1Smoke
#   .\scripts\test-pipeline.ps1 my-stack-name -Wave1Smoke
#   .\scripts\test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag"

param(
    [Parameter(Position = 0)]
    [string]$StackName = "notable-analyzer-stack",
    [switch]$Wave1Smoke,
    [string]$ExpectCapabilityProfiles = "",
    [int]$WaitSeconds = 60
)

Write-Host "=== Testing Notable Analyzer Pipeline ===" -ForegroundColor Cyan
$script:Wave1SmokeFailed = $false
if ($Wave1Smoke) {
    Write-Host "Wave 1 smoke checks: ENABLED (live AWS; not a unit test)" -ForegroundColor Yellow
} else {
    Write-Host "Core smoke only. Pass -Wave1Smoke for optional Wave 1 profile checks." -ForegroundColor Gray
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $projectDir

Write-Host "`nUsing stack name: $StackName" -ForegroundColor Yellow

function Get-LambdaEnvironmentVariables {
    param(
        [string]$Stack,
        [string]$FunctionName = "notable-analyzer-s3"
    )

    $functionArn = aws cloudformation describe-stacks `
        --stack-name $Stack `
        --query 'Stacks[0].Outputs[?OutputKey==`FunctionArn`].OutputValue' `
        --output text 2>$null

    if ($LASTEXITCODE -eq 0 -and $functionArn -and $functionArn -ne "None") {
        $FunctionName = ($functionArn -split ':')[-1]
    }

    $envJson = aws lambda get-function-configuration `
        --function-name $FunctionName `
        --query 'Environment.Variables' `
        --output json 2>$null

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($envJson) -or $envJson -eq "null") {
        return $null, $FunctionName
    }

    $vars = @{}
    ($envJson | ConvertFrom-Json).PSObject.Properties | ForEach-Object {
        $vars[$_.Name] = [string]$_.Value
    }
    return $vars, $FunctionName
}

function Test-S3ObjectExists {
    param(
        [string]$Bucket,
        [string]$Key
    )

    aws s3 ls "s3://$Bucket/$Key" 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Invoke-Wave1SmokeChecks {
    param(
        [string]$OutputBucketName,
        [string]$ReportBaseName,
        [hashtable]$LambdaEnv,
        [string]$LambdaFunctionName
    )

    Write-Host "`n=== Wave 1 Smoke Checks (optional) ===" -ForegroundColor Cyan
    Write-Host "Lambda function: $LambdaFunctionName" -ForegroundColor Gray

    $profilesRaw = if ($LambdaEnv -and $LambdaEnv.ContainsKey("CAPABILITY_PROFILES")) {
        [string]$LambdaEnv["CAPABILITY_PROFILES"]
    } else {
        ""
    }
    if ([string]::IsNullOrWhiteSpace($profilesRaw)) {
        Write-Host "  Could not read CAPABILITY_PROFILES from Lambda environment" -ForegroundColor Red
        $script:Wave1SmokeFailed = $true
        return
    }

    $profiles = @(
        $profilesRaw.Split(',') |
            ForEach-Object { $_.Trim().ToLowerInvariant() } |
            Where-Object { $_ }
    )
    Write-Host "  Deployed profiles: $profilesRaw" -ForegroundColor Green

    if ($ExpectCapabilityProfiles) {
        $expected = @(
            $ExpectCapabilityProfiles.Split(',') |
                ForEach-Object { $_.Trim().ToLowerInvariant() } |
                Where-Object { $_ }
        )
        $missing = @($expected | Where-Object { $_ -notin $profiles })
        $extra = @($profiles | Where-Object { $_ -notin $expected -and $_ -ne "core" })
        if ($missing.Count -gt 0) {
            Write-Host "  Expected profiles missing from deployment: $($missing -join ', ')" -ForegroundColor Red
            $wave1Failed = $true
        } elseif ($extra.Count -gt 0) {
            Write-Host "  Deployment has additional profiles: $($extra -join ', ')" -ForegroundColor Yellow
        } else {
            Write-Host "  Profile set matches -ExpectCapabilityProfiles" -ForegroundColor Green
        }
    }

    $jsonKey = "reports/$ReportBaseName.json"
    $htmlKey = "reports/$ReportBaseName.html"
    $localJson = "$ReportBaseName.json"
    $wave1Failed = $false

    if (-not (Test-S3ObjectExists -Bucket $OutputBucketName -Key $jsonKey)) {
        Write-Host "  JSON report missing: s3://$OutputBucketName/$jsonKey" -ForegroundColor Red
        $wave1Failed = $true
    } else {
        Write-Host "  JSON report found" -ForegroundColor Green
        aws s3 cp "s3://$OutputBucketName/$jsonKey" $localJson | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Could not download JSON report for profile checks" -ForegroundColor Red
            $wave1Failed = $true
        } else {
            $report = Get-Content $localJson -Raw | ConvertFrom-Json
            $metadata = $report.metadata
            if (-not $metadata) {
                Write-Host "  JSON report has no metadata block" -ForegroundColor Yellow
            }

            if ("html_reports" -in $profiles) {
                if (Test-S3ObjectExists -Bucket $OutputBucketName -Key $htmlKey) {
                    Write-Host "  html_reports: HTML companion report found" -ForegroundColor Green
                } else {
                    Write-Host "  html_reports: HTML report missing at s3://$OutputBucketName/$htmlKey" -ForegroundColor Red
                    $wave1Failed = $true
                }
            }

            if ("rag" -in $profiles) {
                $ragStatus = if ($metadata) { [string]$metadata.rag_status } else { "" }
                if ($ragStatus -in @("success", "no_match")) {
                    Write-Host "  rag: metadata.rag_status=$ragStatus" -ForegroundColor Green
                } elseif ($ragStatus -eq "skipped") {
                    Write-Host "  rag: profile enabled but RAG appears disabled (rag_status=skipped)" -ForegroundColor Yellow
                } else {
                    Write-Host "  rag: unexpected rag_status='$ragStatus' (check RagEnabled/RagBedrockKbId)" -ForegroundColor Red
                    $wave1Failed = $true
                }
            }

            if ("spl_readonly" -in $profiles) {
                $backend = if ($metadata) { [string]$metadata.investigation_query_backend } else { "" }
                $genStatus = if ($metadata) { [string]$metadata.spl_query_generation_status } else { "" }
                $hasResults = $null -ne $report.investigation_query_results
                if ($genStatus -eq "success" -or $hasResults) {
                    Write-Host "  spl_readonly: SPL generation/investigation artifacts present (backend=$backend)" -ForegroundColor Green
                } else {
                    Write-Host "  spl_readonly: no SPL generation success or investigation_query_results (status=$genStatus)" -ForegroundColor Yellow
                    Write-Host "    Confirm Splunk credentials, allowlists, and CloudWatch logs in staging." -ForegroundColor Gray
                }
            }

            if ("elastic_readonly" -in $profiles) {
                $backend = if ($metadata) { [string]$metadata.investigation_query_backend } else { "" }
                $hasResults = $null -ne $report.investigation_query_results
                if ($backend -eq "elasticsearch" -and $hasResults) {
                    Write-Host "  elastic_readonly: investigation_query_results present (backend=$backend)" -ForegroundColor Green
                } else {
                    Write-Host "  elastic_readonly: expected elasticsearch investigation results (backend=$backend)" -ForegroundColor Yellow
                    Write-Host "    Confirm Elasticsearch URL, API key secret, and index allowlist in staging." -ForegroundColor Gray
                }
            }

            if ("ticket_draft" -in $profiles) {
                $draft = $report.servicenow_section.draft
                if ($draft) {
                    Write-Host "  ticket_draft: servicenow_section.draft present" -ForegroundColor Green
                } else {
                    Write-Host "  ticket_draft: servicenow_section.draft missing from JSON report" -ForegroundColor Red
                    $wave1Failed = $true
                }
            }

            if ("action_gated" -in $profiles) {
                $tableName = if ($LambdaEnv.ContainsKey("SIDE_EFFECT_IDEMPOTENCY_TABLE")) {
                    [string]$LambdaEnv["SIDE_EFFECT_IDEMPOTENCY_TABLE"]
                } else {
                    ""
                }
                if ([string]::IsNullOrWhiteSpace($tableName)) {
                    Write-Host "  action_gated: SIDE_EFFECT_IDEMPOTENCY_TABLE not set on Lambda" -ForegroundColor Red
                    $wave1Failed = $true
                } else {
                    aws dynamodb describe-table --table-name $tableName 2>$null | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "  action_gated: idempotency table exists ($tableName)" -ForegroundColor Green
                    } else {
                        Write-Host "  action_gated: idempotency table not found ($tableName)" -ForegroundColor Red
                        $wave1Failed = $true
                    }
                }
                Write-Host "  action_gated: replay/idempotency behavior requires manual staging validation" -ForegroundColor Gray
                Write-Host "    Re-upload the same notable or replay side-effect keys; confirm no duplicate writes." -ForegroundColor Gray
            }
        }
    }

    if ($wave1Failed) {
        Write-Host "`nWave 1 smoke checks reported failures (see above)." -ForegroundColor Red
        $script:Wave1SmokeFailed = $true
    } else {
        Write-Host "`nWave 1 smoke checks completed (review warnings above if any)." -ForegroundColor Green
    }
}

# Get bucket names from stack outputs
Write-Host "`nGetting bucket names from stack..." -ForegroundColor Yellow
try {
    $inputBucket = aws cloudformation describe-stacks `
        --stack-name $StackName `
        --query 'Stacks[0].Outputs[?OutputKey==`InputBucketName`].OutputValue' `
        --output text 2>&1

    $outputBucket = aws cloudformation describe-stacks `
        --stack-name $StackName `
        --query 'Stacks[0].Outputs[?OutputKey==`OutputBucketName`].OutputValue' `
        --output text 2>&1

    if ($LASTEXITCODE -ne 0 -or -not $inputBucket -or -not $outputBucket) {
        Write-Host "Could not get bucket names from stack" -ForegroundColor Red
        Write-Host "  Make sure the stack is deployed and outputs are available" -ForegroundColor Yellow
        exit 1
    }

    Write-Host "  Input bucket: $inputBucket" -ForegroundColor Green
    Write-Host "  Output bucket: $outputBucket" -ForegroundColor Green
} catch {
    Write-Host "Error getting stack outputs: $_" -ForegroundColor Red
    exit 1
}

# Upload test file
Write-Host "`nUploading test file..." -ForegroundColor Yellow
$testFile = "data/test-notable.txt"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportBaseName = "test-notable-$timestamp"
$s3Key = "incoming/$reportBaseName.txt"

if (-not (Test-Path $testFile)) {
    Write-Host "Test file not found: $testFile" -ForegroundColor Red
    exit 1
}

Write-Host "  Uploading $testFile to s3://$inputBucket/$s3Key" -ForegroundColor Gray
aws s3 cp $testFile "s3://$inputBucket/$s3Key"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Upload failed" -ForegroundColor Red
    exit 1
}

Write-Host "  Upload successful" -ForegroundColor Green

# Wait for processing
Write-Host "`nWaiting $WaitSeconds seconds for Lambda to process..." -ForegroundColor Yellow
Start-Sleep -Seconds $WaitSeconds

# Check output
Write-Host "`nChecking output bucket..." -ForegroundColor Yellow
$outputKey = "reports/$reportBaseName.md"

Write-Host "  Looking for: s3://$outputBucket/$outputKey" -ForegroundColor Gray
$null = aws s3 ls "s3://$outputBucket/$outputKey" 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  Report found!" -ForegroundColor Green

    # Download report
    Write-Host "`nDownloading report..." -ForegroundColor Yellow
    $localReport = "$reportBaseName.md"
    aws s3 cp "s3://$outputBucket/$outputKey" $localReport

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Report downloaded to: $localReport" -ForegroundColor Green
        Write-Host "`n=== Report Preview (first 50 lines) ===" -ForegroundColor Cyan
        Get-Content $localReport -Head 50
        Write-Host "`n... (full report saved to $localReport)" -ForegroundColor Gray
    }
} else {
    Write-Host "  Report not found yet" -ForegroundColor Yellow
    Write-Host "  Listing all reports in output bucket:" -ForegroundColor Gray
    aws s3 ls "s3://$outputBucket/reports/" --recursive | Select-Object -Last 5
    Write-Host "`n  You may need to wait a bit longer or check CloudWatch logs" -ForegroundColor Yellow
}

if ($Wave1Smoke) {
    $lambdaEnv, $lambdaFunctionName = Get-LambdaEnvironmentVariables -Stack $StackName
    if (-not $lambdaEnv) {
        Write-Host "`nWave 1 smoke checks skipped: could not read Lambda environment" -ForegroundColor Red
        $script:Wave1SmokeFailed = $true
    } else {
        Invoke-Wave1SmokeChecks `
            -OutputBucketName $outputBucket `
            -ReportBaseName $reportBaseName `
            -LambdaEnv $lambdaEnv `
            -LambdaFunctionName $lambdaFunctionName
    }
}

if ($Wave1Smoke -and $script:Wave1SmokeFailed) {
    Write-Host "`n=== Test Failed ===" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Test Complete ===" -ForegroundColor Cyan
