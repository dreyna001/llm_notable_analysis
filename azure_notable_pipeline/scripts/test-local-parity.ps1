$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

if (-not $env:RUN_LOCAL_AZURE_PARITY) {
    $env:RUN_LOCAL_AZURE_PARITY = "1"
}
if (-not $env:AZURITE_CONNECTION_STRING) {
    $env:AZURITE_CONNECTION_STRING = "UseDevelopmentStorage=true"
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

& $PythonCommand @PythonArgs -m pytest -m integration tests/integration/test_local_azure_parity.py @args
