$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run ./setup.ps1 first.' }
    & ./.venv/Scripts/python.exe -m streamlit run integration/app.py
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard did not start successfully.' }
} finally {
    Pop-Location
}
