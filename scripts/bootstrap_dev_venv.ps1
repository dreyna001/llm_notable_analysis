# Create one project-wide .venv for Python backend tools and Node/npm (via nodeenv).
param(
    [string]$Python = "python",
    [switch]$SkipNode,
    [switch]$SkipFrontendInstall,
    [switch]$SkipPlaywrightInstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvDir = Join-Path $RepoRoot ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$NpmExe = Join-Path $VenvDir "Scripts\npm.cmd"
$FrontendDir = Join-Path $RepoRoot "llm_notable_analysis_onprem_systemd\frontend\analyst-portal"

function Invoke-VenvPython {
    param([string[]]$PythonArgs)
    & $PythonExe @PythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: python $($PythonArgs -join ' ')"
    }
}

function Invoke-VenvPip {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PipArgs)
    $allArgs = @("-m", "pip") + $PipArgs
    & $PythonExe @allArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: python -m pip $($PipArgs -join ' ')"
    }
}

Write-Host "Repo root: $RepoRoot"
Write-Host "Virtual env: $VenvDir"

if (-not (Test-Path $PythonExe)) {
    & $Python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment with: $Python"
    }
}

Invoke-VenvPip install --upgrade pip wheel
$editableInstall = @(
    "install",
    "-e", (Join-Path $RepoRoot "onprem-llm-sdk"),
    "-e", (Join-Path $RepoRoot "onprem_rag_notable_analysis"),
    "-e", (Join-Path $RepoRoot "llm_notable_analysis_onprem_systemd"),
    "pytest",
    "nodeenv"
)
Invoke-VenvPip @editableInstall

if (-not $SkipNode) {
    $NodeExe = Join-Path $VenvDir "Scripts\node.exe"
    if (-not (Test-Path $NodeExe)) {
        Write-Host "Installing Node.js into .venv via nodeenv..."
        $env:VIRTUAL_ENV = $VenvDir
        $env:PATH = "$(Join-Path $VenvDir 'Scripts');$env:PATH"
        Invoke-VenvPython @("-m", "nodeenv", "-p", "--node", "22.14.0")
    }
}

if (-not $SkipFrontendInstall) {
    if (-not (Test-Path $NpmExe)) {
        throw "npm not found in venv. Re-run without -SkipNode or install Node manually into .venv."
    }
    Write-Host "Installing analyst portal frontend dependencies..."
    $env:VIRTUAL_ENV = $VenvDir
    $env:PATH = "$(Join-Path $VenvDir 'Scripts');$env:PATH"
    Push-Location $FrontendDir
    try {
        & $NpmExe install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed in $FrontendDir"
        }
        if (-not $SkipPlaywrightInstall) {
            Write-Host "Installing Playwright Chromium for portal E2E tests..."
            & $NpmExe run install:e2e-browsers
            if ($LASTEXITCODE -ne 0) {
                throw "playwright install chromium failed in $FrontendDir"
            }
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Done. Activate the shared dev environment:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Then run, for example:"
Write-Host "  python llm_notable_analysis_onprem_systemd\scripts\preview_portal_ui.py"
Write-Host "  .\scripts\dev_portal_ui.ps1"
Write-Host "  .\scripts\dev_portal_e2e.ps1"
