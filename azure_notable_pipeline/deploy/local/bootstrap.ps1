[CmdletBinding()]
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot "local.env")
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    $EnvFile = Join-Path $PSScriptRoot "local.env.example"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker is required"
}
$PythonArgs = @()
if ($env:PYTHON) {
    $PythonCommand = $env:PYTHON
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
    $PythonArgs = @("-3.12")
} else {
    throw "Python 3.12 is required; set PYTHON to the interpreter path"
}

docker compose --env-file $EnvFile -f (Join-Path $PSScriptRoot "docker-compose.yml") up -d --wait azurite cosmos
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed with exit code $LASTEXITCODE"
}

& $PythonCommand @PythonArgs (Join-Path $PSScriptRoot "bootstrap_emulators.py") --env-file $EnvFile
if ($LASTEXITCODE -ne 0) {
    throw "Emulator bootstrap failed with exit code $LASTEXITCODE"
}
