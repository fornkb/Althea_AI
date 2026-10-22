param([switch]$Check)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run ./setup.ps1 first.' }
    # Include tools installed since this terminal was opened (for example FFmpeg).
    $taskUserPath = [Environment]::GetEnvironmentVariable('Path','User')
    if ($taskUserPath) { $env:Path += ';' + $taskUserPath }
    if ($Check) {
        & ./.venv/Scripts/python.exe -m pip check
        if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed. Run setup.ps1.' }
        & ./.venv/Scripts/python.exe -m althea_app --mode live --provider gemini --preflight
        if ($LASTEXITCODE -ne 0) { throw 'Preflight failed.' }
        return
    }
    & ./.venv/Scripts/python.exe -c "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(p) for p in ('flask','waitress')) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing web application dependencies...'
        & ./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
        if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies. Run setup.ps1.' }
    }
    & ./.venv/Scripts/python.exe -m althea_app.web
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard did not start successfully.' }
} finally {
    Pop-Location
}
