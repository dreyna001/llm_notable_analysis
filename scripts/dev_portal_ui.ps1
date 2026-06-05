# Run the analyst portal React dev server using npm from the shared repo .venv.
$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$NpmExe = Join-Path $RepoRoot ".venv\Scripts\npm.cmd"
$FrontendDir = Join-Path $RepoRoot "llm_notable_analysis_onprem_systemd\frontend\analyst-portal"

if (-not (Test-Path $NpmExe)) {
    throw "Missing $NpmExe. Run scripts\bootstrap_dev_venv.ps1 first."
}

Push-Location $FrontendDir
try {
    & $NpmExe run dev @args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
