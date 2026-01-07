# Test Script for Notable Analyzer Pipeline
# Uploads test file and checks output

Write-Host "=== Testing Notable Analyzer Pipeline ===" -ForegroundColor Cyan

# Get stack name (default or from user)
$stackName = "notable-analyzer-stack"
if ($args.Count -gt 0) {
    $stackName = $args[0]
}

Write-Host "`nUsing stack name: $stackName" -ForegroundColor Yellow

# Get bucket names from stack outputs
Write-Host "`nGetting bucket names from stack..." -ForegroundColor Yellow
try {
    $inputBucket = aws cloudformation describe-stacks `
        --stack-name $stackName `
        --query 'Stacks[0].Outputs[?OutputKey==`InputBucketName`].OutputValue' `
        --output text 2>&1
    
    $outputBucket = aws cloudformation describe-stacks `
        --stack-name $stackName `
        --query 'Stacks[0].Outputs[?OutputKey==`OutputBucketName`].OutputValue' `
        --output text 2>&1
    
    if ($LASTEXITCODE -ne 0 -or -not $inputBucket -or -not $outputBucket) {
        Write-Host "❌ Could not get bucket names from stack" -ForegroundColor Red
        Write-Host "  Make sure the stack is deployed and outputs are available" -ForegroundColor Yellow
        exit 1
    }
    
    Write-Host "  ✅ Input bucket: $inputBucket" -ForegroundColor Green
    Write-Host "  ✅ Output bucket: $outputBucket" -ForegroundColor Green
} catch {
    Write-Host "❌ Error getting stack outputs: $_" -ForegroundColor Red
    exit 1
}

# Upload test file
Write-Host "`nUploading test file..." -ForegroundColor Yellow
$testFile = "test-notable.txt"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$s3Key = "incoming/test-notable-$timestamp.txt"

if (-not (Test-Path $testFile)) {
    Write-Host "❌ Test file not found: $testFile" -ForegroundColor Red
    exit 1
}

Write-Host "  Uploading $testFile to s3://$inputBucket/$s3Key" -ForegroundColor Gray
aws s3 cp $testFile "s3://$inputBucket/$s3Key"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Upload failed" -ForegroundColor Red
    exit 1
}

Write-Host "  ✅ Upload successful" -ForegroundColor Green

# Wait for processing
Write-Host "`nWaiting 60 seconds for Lambda to process..." -ForegroundColor Yellow
Start-Sleep -Seconds 60

# Check output
Write-Host "`nChecking output bucket..." -ForegroundColor Yellow
$outputKey = "reports/test-notable-$timestamp.md"

Write-Host "  Looking for: s3://$outputBucket/$outputKey" -ForegroundColor Gray
$exists = aws s3 ls "s3://$outputBucket/$outputKey" 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✅ Report found!" -ForegroundColor Green
    
    # Download report
    Write-Host "`nDownloading report..." -ForegroundColor Yellow
    $localReport = "test-notable-$timestamp.md"
    aws s3 cp "s3://$outputBucket/$outputKey" $localReport
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ Report downloaded to: $localReport" -ForegroundColor Green
        Write-Host "`n=== Report Preview (first 50 lines) ===" -ForegroundColor Cyan
        Get-Content $localReport -Head 50
        Write-Host "`n... (full report saved to $localReport)" -ForegroundColor Gray
    }
} else {
    Write-Host "  ⚠️  Report not found yet" -ForegroundColor Yellow
    Write-Host "  Listing all reports in output bucket:" -ForegroundColor Gray
    aws s3 ls "s3://$outputBucket/reports/" --recursive | Select-Object -Last 5
    Write-Host "`n  You may need to wait a bit longer or check CloudWatch logs" -ForegroundColor Yellow
}

Write-Host "`n=== Test Complete ===" -ForegroundColor Cyan
