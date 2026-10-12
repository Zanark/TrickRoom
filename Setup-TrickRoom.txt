param([switch]$SkipModels)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 for Windows, then rerun setup.' }
    }
    & $Python -m pip install --quiet -c requirements-lock.txt -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See the pip error above.' }
    if (-not $SkipModels) {
        & $Python -m trickroom --download-models
        if ($LASTEXITCODE -ne 0) { throw 'Model download/checksum verification failed.' }
    }
    Write-Host 'TrickRoom is ready. Run .\Start-TrickRoom.ps1 (no camera opens in demo).'
} finally {
    Pop-Location
}
