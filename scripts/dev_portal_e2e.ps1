# Run analyst portal Playwright E2E tests using npm from the shared repo .venv.
param(
    [switch]$InstallBrowsers
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvDir = Join-Path $RepoRoot ".venv"
$NpmExe = Join-Path $VenvDir "Scripts\npm.cmd"
$NodeExe = Join-Path $VenvDir "Scripts\node.exe"
$FrontendDir = Join-Path $RepoRoot "llm_notable_analysis_onprem_systemd\frontend\analyst-portal"
$PlaywrightPkg = Join-Path $FrontendDir "node_modules\@playwright\test\package.json"

if (-not (Test-Path $NpmExe)) {
    throw "Missing $NpmExe. Run scripts\bootstrap_dev_venv.ps1 first."
}
if (-not (Test-Path $NodeExe)) {
    throw "Missing $NodeExe. Re-run scripts\bootstrap_dev_venv.ps1 without -SkipNode."
}
if (-not (Test-Path $PlaywrightPkg)) {
    throw "@playwright/test is not installed. Run scripts\bootstrap_dev_venv.ps1 (or npm install in $FrontendDir)."
}

$env:VIRTUAL_ENV = $VenvDir
$env:PATH = "$(Join-Path $VenvDir 'Scripts');$env:PATH"

Push-Location $FrontendDir
try {
    if ($InstallBrowsers) {
        Write-Host "Installing Playwright Chromium via repo .venv npm..."
        & $NpmExe run install:e2e-browsers
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }

    Write-Host "Using npm: $NpmExe"
    Write-Host "Using node: $NodeExe"
    if ($args.Count -gt 0) {
        & $NpmExe exec playwright test @args
    }
    else {
        & $NpmExe run test:e2e
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
