# Run the portal API preview using the shared repo .venv.
$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    throw "Missing $PythonExe. Run scripts\bootstrap_dev_venv.ps1 first."
}

& $PythonExe (Join-Path $RepoRoot "llm_notable_analysis_onprem_systemd\scripts\preview_portal_ui.py") @args
