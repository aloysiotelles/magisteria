param(
    [string]$Mode = "",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

switch ($Mode.ToUpperInvariant()) {
    "ISTO" {
        & $python "$PSScriptRoot\SUBA_ISTO.py" @RemainingArgs
        exit $LASTEXITCODE
    }
    default {
        & $python "$PSScriptRoot\suba_deploy.py" @RemainingArgs
        exit $LASTEXITCODE
    }
}
