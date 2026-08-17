# Test Script for Notable Analyzer Pipeline
# Uploads test file and checks output.
#
# Requires PowerShell 5.1+ or pwsh, AWS CLI, and COMMERCIAL_AWS_ACCOUNT_ID set to the
# approved 12-digit commercial account. Fails closed outside aws/us-east-1.
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

$region = "us-east-1"

function Assert-CommercialAwsBoundary {
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
}

Assert-CommercialAwsBoundary

Write-Host "`nUsing stack name: $StackName" -ForegroundColor Yellow

function Get-LambdaEnvironmentVariables {
    param(
        [string]$Stack,
        [string]$FunctionName = "notable-analyzer-s3"
    )

    $functionArn = aws cloudformation describe-stacks `
        --region $region `
        --stack-name $Stack `
        --query 'Stacks[0].Outputs[?OutputKey==`FunctionArn`].OutputValue' `
        --output text 2>$null

    if ($LASTEXITCODE -eq 0 -and $functionArn -and $functionArn -ne "None") {
        $FunctionName = ($functionArn -split ':')[-1]
    }

    $envJson = aws lambda get-function-configuration `
        --region $region `
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

    aws s3 ls "s3://$Bucket/$Key" --region $region 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Wait-ForS3ObjectExists {
    param(
        [string]$Bucket,
        [string]$Key,
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(1, $TimeoutSeconds))
    do {
        if (Test-S3ObjectExists -Bucket $Bucket -Key $Key) {
            return $true
        }
        if ([DateTime]::UtcNow -ge $deadline) {
            break
        }
        Start-Sleep -Seconds 5
    } while ($true)
    return $false
}

function Get-S3ReportObjectKey {
    param(
        [string]$Bucket,
        [string]$ReportStem,
        [ValidateSet("md", "json", "html")]
        [string]$Extension
    )

    if (
        $ReportStem -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or
        @($ReportStem.Split('/') | Where-Object { $_ -in @("", ".", "..") }).Count -gt 0
    ) {
        throw "ReportStem is not a normalized S3 key stem"
    }

    $prefix = "reports/$ReportStem--"
    $keysOutput = aws s3api list-objects-v2 `
        --region $region `
        --bucket $Bucket `
        --prefix $prefix `
        --query 'Contents[].Key' `
        --output text 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($keysOutput) -or $keysOutput -eq "None") {
        return $null
    }

    $escapedStem = [Regex]::Escape($ReportStem)
    $pattern = "^reports/$escapedStem--[a-f0-9]{32}\.$([Regex]::Escape($Extension))$"
    $matches = @(
        ($keysOutput -split '\s+') |
            Where-Object { $_ -and $_ -match $pattern } |
            Sort-Object -Unique
    )
    if ($matches.Count -gt 1) {
        throw "Multiple report artifacts matched s3://$Bucket/$prefix*.$Extension"
    }
    if ($matches.Count -eq 1) {
        return $matches[0]
    }
    return $null
}

function Wait-ForS3ReportObjectKey {
    param(
        [string]$Bucket,
        [string]$ReportStem,
        [ValidateSet("md", "json", "html")]
        [string]$Extension,
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(1, $TimeoutSeconds))
    do {
        $key = Get-S3ReportObjectKey -Bucket $Bucket -ReportStem $ReportStem -Extension $Extension
        if ($key) {
            return $key
        }
        if ([DateTime]::UtcNow -ge $deadline) {
            break
        }
        Start-Sleep -Seconds 5
    } while ($true)
    return $null
}

function Invoke-Wave1SmokeChecks {
    param(
        [string]$OutputBucketName,
        [string]$ReportObjectStem,
        [string]$LocalReportBaseName,
        [hashtable]$LambdaEnv,
        [string]$LambdaFunctionName,
        [int]$ArtifactTimeoutSeconds
    )

    Write-Host "`n=== Wave 1 Smoke Checks (optional) ===" -ForegroundColor Cyan
    Write-Host "Lambda function: $LambdaFunctionName" -ForegroundColor Gray
    $wave1Failed = $false

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

    $jsonKey = "$ReportObjectStem.json"
    $htmlKey = "$ReportObjectStem.html"
    $localJson = "$LocalReportBaseName.json"

    if (
        -not (
            Wait-ForS3ObjectExists `
                -Bucket $OutputBucketName `
                -Key $jsonKey `
                -TimeoutSeconds $ArtifactTimeoutSeconds
        )
    ) {
        Write-Host "  JSON report missing: s3://$OutputBucketName/$jsonKey" -ForegroundColor Red
        $wave1Failed = $true
    } else {
        Write-Host "  JSON report found" -ForegroundColor Green
        aws s3 cp "s3://$OutputBucketName/$jsonKey" $localJson --region $region | Out-Null
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
                if (
                    Wait-ForS3ObjectExists `
                        -Bucket $OutputBucketName `
                        -Key $htmlKey `
                        -TimeoutSeconds $ArtifactTimeoutSeconds
                ) {
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
                    Write-Host "  rag: unexpected rag_status='$ragStatus' (check RagEnabled/OpenSearch configuration)" -ForegroundColor Red
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
                    aws dynamodb describe-table --region $region --table-name $tableName 2>$null | Out-Null
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
        --region $region `
        --stack-name $StackName `
        --query 'Stacks[0].Outputs[?OutputKey==`InputBucketName`].OutputValue' `
        --output text 2>&1

    $outputBucket = aws cloudformation describe-stacks `
        --region $region `
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
aws s3 cp $testFile "s3://$inputBucket/$s3Key" --region $region
if ($LASTEXITCODE -ne 0) {
    Write-Host "Upload failed" -ForegroundColor Red
    exit 1
}

Write-Host "  Upload successful" -ForegroundColor Green

# Check output
Write-Host "`nChecking output bucket..." -ForegroundColor Yellow
$reportStem = "incoming/$reportBaseName"
Write-Host "  Waiting up to $WaitSeconds seconds for the versioned report artifact" -ForegroundColor Gray
try {
    $outputKey = Wait-ForS3ReportObjectKey `
        -Bucket $outputBucket `
        -ReportStem $reportStem `
        -Extension "md" `
        -TimeoutSeconds $WaitSeconds
} catch {
    Write-Host "  Report discovery failed: $_" -ForegroundColor Red
    exit 1
}

if ($outputKey) {
    Write-Host "  Found: s3://$outputBucket/$outputKey" -ForegroundColor Gray
    Write-Host "  Report found!" -ForegroundColor Green

    # Download report
    Write-Host "`nDownloading report..." -ForegroundColor Yellow
    $localReport = "$reportBaseName.md"
    aws s3 cp "s3://$outputBucket/$outputKey" $localReport --region $region

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Report downloaded to: $localReport" -ForegroundColor Green
        Write-Host "`n=== Report Preview (first 50 lines) ===" -ForegroundColor Cyan
        Get-Content $localReport -Head 50
        Write-Host "`n... (full report saved to $localReport)" -ForegroundColor Gray
    } else {
        Write-Host "  Report download failed" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  Report not found within $WaitSeconds seconds" -ForegroundColor Red
    Write-Host "  Expected one key matching reports/$reportStem--<processing-id>.md" -ForegroundColor Gray
    Write-Host "  Check the analyzer queue, DLQ, and CloudWatch logs." -ForegroundColor Yellow
    exit 1
}

if ($Wave1Smoke) {
    $lambdaEnv, $lambdaFunctionName = Get-LambdaEnvironmentVariables -Stack $StackName
    if (-not $lambdaEnv) {
        Write-Host "`nWave 1 smoke checks skipped: could not read Lambda environment" -ForegroundColor Red
        $script:Wave1SmokeFailed = $true
    } else {
        Invoke-Wave1SmokeChecks `
            -OutputBucketName $outputBucket `
            -ReportObjectStem ($outputKey.Substring(0, $outputKey.Length - 3)) `
            -LocalReportBaseName $reportBaseName `
            -LambdaEnv $lambdaEnv `
            -LambdaFunctionName $lambdaFunctionName `
            -ArtifactTimeoutSeconds $WaitSeconds
    }
}

if ($Wave1Smoke -and $script:Wave1SmokeFailed) {
    Write-Host "`n=== Test Failed ===" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Test Complete ===" -ForegroundColor Cyan
